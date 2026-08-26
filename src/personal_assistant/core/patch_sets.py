"""编码工作流服务（第四阶段 M4）：多文件 patch set + 项目命令配置 + 命令失败诊断。

PatchSet 状态机：draft → waiting_approval → applied/rejected；applied → rolled_back。
- 创建时快照 old_content + old_sha256（created 文件 old 为 None 哨兵）。
- apply 前校验当前内容 sha256 == old_sha256，不一致拒绝（防覆盖用户新改动）。
- rollback 前校验当前 sha256 == new_sha256，不一致拒绝；created 文件回滚为删除。
项目命令配置为预授权（用户配置即授权），不经全局白名单；ad-hoc 命令仍走 run_whitelisted_command。
诊断用 LLM 从命令输出抽错误摘要/文件行/下一步建议。
"""
from __future__ import annotations

import difflib
import os
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .code_tools import _sha256_text, normalize_patch_content, parse_command
from .learning import parse_json_object
from .models import PatchSet, ProjectCommandProfile
from .projects import ProjectNotFound, ProjectService, resolve_within
from .provider import OllamaProvider, ProviderError
from .repo_patch_sets import PatchSetRepository, ProjectCommandProfileRepository
from .result_parsers import RESULT_PARSERS
from .settings import SettingsService

logger = get_logger(__name__)

PATCH_MAX_CHARS = 500000  # 单文件新内容上限（与 code_tools 一致）
MAX_READ_FILE_BYTES = 5 * 1024 * 1024

# E0 §6：命令 profile 字段约束（非法值由路由层映射 command_profile_invalid 422）
_MAX_CWD_REL_CHARS = 2048
_MAX_ENV_ALLOWLIST_ITEMS = 64
_MAX_ENV_NAME_CHARS = 64
_MAX_CAPABILITY_CHARS = 64
_MAX_DESCRIPTION_CHARS = 512
_MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MiB
RISK_LEVELS = frozenset({"safe", "confirm", "restricted"})
_ENV_REJECT_PATTERN = re.compile(
    r"(PROXY|API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)


def _validate_profile_fields(
    *,
    cwd_rel: str | None = None,
    env_allowlist: list | None = None,
    result_parser: str | None = None,
    risk_level: str | None = None,
    capability: str | None = None,
    max_output_bytes: int | None = None,
    description: str | None = None,
) -> None:
    """E0 §6 字段校验：非法即抛 ValueError（路由层映射 422）。

    - cwd_rel：workspace 内相对目录（≤2048，拒绝绝对路径/盘符/越界 ..）；
    - env_allowlist：环境变量白名单数组，拒绝代理/凭据类名称（Provider
      secret 保持在原生凭据边界，不注入命令环境）；
    - result_parser：冻结枚举（result_parsers.RESULT_PARSERS）；
    - risk_level：safe|confirm|restricted；
    - max_output_bytes：1..10MiB。
    """
    if cwd_rel is not None:
        if not isinstance(cwd_rel, str):
            raise ValueError("cwd_rel 必须为字符串")
        if len(cwd_rel) > _MAX_CWD_REL_CHARS:
            raise ValueError(f"cwd_rel 过长（上限 {_MAX_CWD_REL_CHARS} 字符）")
        if not cwd_rel.strip() or cwd_rel.strip() == ".":
            pass  # 空 = 项目根目录
        elif (
            cwd_rel.startswith(("/", "\\"))
            or re.match(r"^[A-Za-z]:[\\/]", cwd_rel)
            or os.path.isabs(cwd_rel)
        ):
            raise ValueError("cwd_rel 必须是 workspace 内相对路径，拒绝绝对路径")
        else:
            norm = os.path.normpath(cwd_rel.replace("\\", "/"))
            if norm == ".." or norm.startswith(f"..{os.sep}") or norm.startswith("../"):
                raise ValueError("cwd_rel 不得越出 workspace 根目录")
    if env_allowlist is not None:
        if not isinstance(env_allowlist, list) or not all(
            isinstance(x, str) for x in env_allowlist
        ):
            raise ValueError("env_allowlist 必须是字符串数组")
        if len(env_allowlist) > _MAX_ENV_ALLOWLIST_ITEMS:
            raise ValueError(
                f"env_allowlist 项数超限（上限 {_MAX_ENV_ALLOWLIST_ITEMS}）"
            )
        for name in env_allowlist:
            if not name or len(name) > _MAX_ENV_NAME_CHARS or "=" in name:
                raise ValueError("env_allowlist 项必须是有效环境变量名")
            if _ENV_REJECT_PATTERN.search(name):
                raise ValueError(
                    f"env_allowlist 拒绝代理/凭据类变量: {name}（Provider secret "
                    "保持在原生凭据边界）"
                )
    if result_parser is not None:
        if result_parser not in RESULT_PARSERS:
            raise ValueError(
                f"result_parser 非法: {result_parser}（可选: "
                f"{'|'.join(sorted(RESULT_PARSERS))}）"
            )
    if risk_level is not None and risk_level not in RISK_LEVELS:
        raise ValueError(
            f"risk_level 非法: {risk_level}（可选: {'|'.join(sorted(RISK_LEVELS))}）"
        )
    if capability is not None:
        if not isinstance(capability, str) or len(capability) > _MAX_CAPABILITY_CHARS:
            raise ValueError(
                f"capability 必须是 ≤{_MAX_CAPABILITY_CHARS} 的字符串"
            )
    if max_output_bytes is not None:
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or max_output_bytes < 1
            or max_output_bytes > _MAX_OUTPUT_BYTES
        ):
            raise ValueError(
                f"max_output_bytes 必须是 1..{_MAX_OUTPUT_BYTES} 的整数"
            )
    if description is not None:
        if not isinstance(description, str) or len(description) > _MAX_DESCRIPTION_CHARS:
            raise ValueError(
                f"description 必须是 ≤{_MAX_DESCRIPTION_CHARS} 的字符串"
            )


class PatchSetNotFound(LookupError):
    """补丁集不存在。"""


class CommandProfileNotFound(LookupError):
    """命令配置不存在。"""


def _read_text(full) -> str:
    size = full.stat().st_size
    if size > MAX_READ_FILE_BYTES:
        raise ValueError(f"文件过大（{size} 字节，上限 {MAX_READ_FILE_BYTES} 字节）")
    return full.read_text(encoding="utf-8", errors="ignore")


def _make_diff(rel_path: str, old: str | None, new: str) -> str:
    old_lines = (old or "").splitlines()
    new_lines = new.splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            old_lines, new_lines, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}", lineterm=""
        )
    )
    return diff + "\n" if diff else ""


class PatchSetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PatchSetRepository(db)
        self.projects = ProjectService(db)

    async def _project_root(self, project_id: int) -> Any:
        project = await self.projects.get(project_id)
        if project is None:
            raise ProjectNotFound(f"项目不存在: {project_id}")
        return project.root_path

    async def create(
        self,
        *,
        project_id: int,
        title: str,
        files: list[dict],
        task_id: int | None = None,
    ) -> PatchSet:
        """创建补丁集：为每个文件快照 old_content + sha256 + diff。

        files 每项 {rel_path, new_content, create?}。create=True 允许文件不存在
        （old_content=None 哨兵，回滚时删除）。
        """
        if not files:
            raise ValueError("补丁集至少包含一个文件")
        root = await self._project_root(project_id)
        built: list[dict] = []
        for f in files:
            rel_path = f["rel_path"]
            new_content = f["new_content"]
            if not isinstance(new_content, str):
                raise ValueError("new_content 必须为字符串")
            new_content = normalize_patch_content(rel_path, new_content)
            if len(new_content) > PATCH_MAX_CHARS:
                raise ValueError(f"{rel_path}: new_content 过大（上限 {PATCH_MAX_CHARS} 字符）")
            create = f.get("create", False)
            full = resolve_within(root, rel_path)
            if full.exists() and full.is_file():
                old_content = _read_text(full)
                old_sha = _sha256_text(old_content)
            elif create:
                old_content = None  # 哨兵：文件原本不存在，回滚时删除
                old_sha = None
            else:
                raise FileNotFoundError(f"文件不存在: {rel_path}（或传 create=True 新建）")
            built.append(
                {
                    "rel_path": rel_path,
                    "old_sha256": old_sha,
                    "new_sha256": _sha256_text(new_content),
                    "diff_text": _make_diff(rel_path, old_content, new_content),
                    "old_content": old_content,
                    "new_content": new_content,
                }
            )
        return await self.repo.create(
            project_id=project_id, title=title, files=built, task_id=task_id
        )

    async def get(self, patch_set_id: int) -> PatchSet:
        ps = await self.repo.get(patch_set_id)
        if ps is None:
            raise PatchSetNotFound(f"补丁集不存在: {patch_set_id}")
        return ps

    async def list_by_project(self, project_id: int) -> list[PatchSet]:
        return await self.repo.list_by_project(project_id)

    async def submit_for_approval(self, patch_set_id: int) -> PatchSet:
        ps = await self.get(patch_set_id)
        if ps.status != "draft":
            raise ValueError(f"仅 draft 可提交审批，当前: {ps.status}")
        await self.repo.update_status(patch_set_id, "waiting_approval")
        return await self.get(patch_set_id)

    async def apply(self, patch_set_id: int) -> dict:
        """应用补丁集：校验各文件当前 sha256 == old_sha256，一致则写入新内容。"""
        ps = await self.get(patch_set_id)
        if ps.status not in ("draft", "waiting_approval"):
            raise ValueError(f"仅 draft/waiting_approval 可应用，当前: {ps.status}")
        root = await self._project_root(ps.project_id)
        # 先全部校验，再全部写入（all-or-nothing on sha mismatch）
        for pf in ps.files:
            full = resolve_within(root, pf.rel_path)
            if full.exists() and full.is_file():
                cur_sha = _sha256_text(_read_text(full))
            else:
                cur_sha = None
            if cur_sha != pf.old_sha256:
                raise RuntimeError(
                    f"{pf.rel_path} 内容自快照后已变化，拒绝应用（防止覆盖用户新改动）"
                )
        # 全部校验通过，写入
        written: list[dict] = []
        for pf in ps.files:
            full = resolve_within(root, pf.rel_path)
            if not full.parent.exists():
                full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(pf.new_content, encoding="utf-8", newline="")
            written.append({"rel_path": pf.rel_path, "size_bytes": full.stat().st_size})
        await self.repo.update_file_statuses(patch_set_id, "applied")
        await self.repo.update_status(patch_set_id, "applied")
        return {"patch_set_id": patch_set_id, "status": "applied", "written": written}

    async def reject(self, patch_set_id: int) -> PatchSet:
        ps = await self.get(patch_set_id)
        if ps.status not in ("draft", "waiting_approval"):
            raise ValueError(f"仅 draft/waiting_approval 可拒绝，当前: {ps.status}")
        await self.repo.update_file_statuses(patch_set_id, "rejected")
        await self.repo.update_status(patch_set_id, "rejected")
        return await self.get(patch_set_id)

    async def rollback(self, patch_set_id: int) -> dict:
        """回滚补丁集：校验当前 sha256 == new_sha256，一致则恢复 old_content
       （created 文件 old_content=None → 删除）。"""
        ps = await self.get(patch_set_id)
        if ps.status != "applied":
            raise ValueError(f"仅 applied 可回滚，当前: {ps.status}")
        root = await self._project_root(ps.project_id)
        for pf in ps.files:
            full = resolve_within(root, pf.rel_path)
            if full.exists() and full.is_file():
                cur_sha = _sha256_text(_read_text(full))
            else:
                cur_sha = None
            if cur_sha != pf.new_sha256:
                raise RuntimeError(
                    f"{pf.rel_path} 应用后内容已被改动，拒绝回滚（防止覆盖用户新改动）"
                )
        restored: list[dict] = []
        for pf in ps.files:
            full = resolve_within(root, pf.rel_path)
            if pf.old_content is None:
                # created 文件回滚为删除
                if full.exists():
                    full.unlink()
                restored.append({"rel_path": pf.rel_path, "action": "deleted"})
            else:
                full.write_text(pf.old_content, encoding="utf-8", newline="")
                restored.append({"rel_path": pf.rel_path, "action": "restored"})
        await self.repo.update_file_statuses(patch_set_id, "rolled_back")
        await self.repo.update_status(patch_set_id, "rolled_back")
        return {"patch_set_id": patch_set_id, "status": "rolled_back", "restored": restored}


class CommandProfileService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectCommandProfileRepository(db)
        self.projects = ProjectService(db)

    async def create(
        self,
        *,
        project_id: int,
        name: str,
        command_json: dict,
        kind: str,
        timeout_seconds: int = 120,
        enabled: bool = True,
        cwd_rel: str | None = None,
        env_allowlist: list | None = None,
        allow_network: bool = False,
        result_parser: str | None = None,
        risk_level: str = "confirm",
        capability: str | None = None,
        max_output_bytes: int | None = None,
        description: str | None = None,
    ) -> ProjectCommandProfile:
        _validate_profile_fields(
            cwd_rel=cwd_rel,
            env_allowlist=env_allowlist,
            result_parser=result_parser,
            risk_level=risk_level,
            capability=capability,
            max_output_bytes=max_output_bytes,
            description=description,
        )
        return await self.repo.create(
            project_id=project_id,
            name=name,
            command_json=command_json,
            kind=kind,
            timeout_seconds=timeout_seconds,
            enabled=enabled,
            cwd_rel=cwd_rel,
            env_allowlist=env_allowlist,
            allow_network=allow_network,
            result_parser=result_parser,
            risk_level=risk_level,
            capability=capability,
            max_output_bytes=max_output_bytes,
            description=description,
        )

    async def list_by_project(
        self, project_id: int, kind: str | None = None
    ) -> list[ProjectCommandProfile]:
        return await self.repo.list_by_project(project_id, kind=kind)

    async def update(self, profile_id: int, **kwargs) -> ProjectCommandProfile:
        p = await self.repo.get(profile_id)
        if p is None:
            raise CommandProfileNotFound(f"命令配置不存在: {profile_id}")
        _validate_profile_fields(
            cwd_rel=kwargs.get("cwd_rel"),
            env_allowlist=kwargs.get("env_allowlist"),
            result_parser=kwargs.get("result_parser"),
            risk_level=kwargs.get("risk_level"),
            capability=kwargs.get("capability"),
            max_output_bytes=kwargs.get("max_output_bytes"),
            description=kwargs.get("description"),
        )
        # E0 §6：profile 内容变更即递增版本；历史 run 快照不受影响
        kwargs["profile_version"] = (p.profile_version or 1) + 1
        await self.repo.update(profile_id, **kwargs)
        fresh = await self.repo.get(profile_id)
        assert fresh is not None
        return fresh

    async def delete(self, profile_id: int) -> None:
        p = await self.repo.get(profile_id)
        if p is None:
            raise CommandProfileNotFound(f"命令配置不存在: {profile_id}")
        await self.repo.delete(profile_id)

    async def run(self, profile_id: int) -> dict:
        """运行项目命令配置（预授权，不经全局白名单）。

        E2：落地 cwd_rel（resolve 校验仍在 root 内）、env_allowlist 白名单
        注入（拒绝代理/凭据类）、result_parser 结构化解析与 profile_version。
        第六轮（P1-1）：统一走受审计执行路径（run_whitelisted_command_trusted）
        ——argv/schema/网络校验 + Job Object 进程树清理 + 流式有界输出；
        不再使用旧 _execute_command（无进程树清理与有界流式输出）。
        """
        p = await self.repo.get(profile_id)
        if p is None:
            raise CommandProfileNotFound(f"命令配置不存在: {profile_id}")
        if not p.enabled:
            raise ValueError(f"命令配置已禁用: {p.name}")
        project = await self.projects.get(p.project_id)
        if project is None:
            raise ProjectNotFound(f"项目不存在: {p.project_id}")
        from ..agents.runtime import CancellationToken
        from .command_workflow import run_whitelisted_command_trusted

        args = _profile_to_args(p.command_json)
        result = await run_whitelisted_command_trusted(
            self.db,
            p.project_id,
            args,
            timeout=p.timeout_seconds,
            cancellation=CancellationToken(),
            # 手动运行是用户触发：无 run 权限模式（走全局校验语义）
            permission_mode=None,
        )
        result["project_id"] = p.project_id
        result["profile_id"] = profile_id
        result["profile_name"] = p.name
        result["profile_version"] = p.profile_version or 1
        return result


def _profile_to_args(command_json: dict) -> list[str]:
    """命令配置 → args：优先 args 数组，其次 command 字符串。"""
    if "args" in command_json:
        args = [str(x) for x in command_json["args"] if str(x)]
        if not args:
            raise ValueError("命令配置 args 为空")
        return args
    cmd = command_json.get("command")
    if not cmd:
        raise ValueError("命令配置需含 command 或 args")
    return parse_command(cmd)


class DiagnosticsService:
    def __init__(self, db: AsyncSession, provider: OllamaProvider | None = None) -> None:
        self.db = db
        self._provider = provider

    async def _get_provider(self) -> OllamaProvider:
        if self._provider is not None:
            return self._provider
        s = await SettingsService(self.db).get_all()
        return OllamaProvider(
            llm_model=s["llm_model"],
            temperature=float(s["llm_temperature"]),
            context_length=int(s["llm_context_length"]),
        )

    async def diagnose(
        self, *, output: str, returncode: int, args: list[str] | None = None
    ) -> dict:
        """从命令失败输出抽取错误摘要、错误文件/行、下一步建议（LLM）。"""
        provider = await self._get_provider()
        cmd_str = " ".join(args) if args else "（未知命令）"
        prompt = (
            "你是命令诊断助手。下面是一条失败命令的输出，请抽取：错误摘要、错误文件与行号"
            "（若有）、下一步修复建议。只输出 JSON 对象："
            '{"summary":"摘要","error_files":[{"file":"路径","line":行号或0,'
            '"message":"说明"}],"suggestion":"建议"}。'
            f"\n\n命令：{cmd_str}\n返回码：{returncode}\n输出：\n{output[:6000]}"
        )
        try:
            raw = await provider.chat(
                [
                    {"role": "system", "content": "你只输出合法 JSON 对象。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except ProviderError as e:
            logger.warning("diagnose LLM failed", error=str(e))
            return {
                "summary": f"诊断生成失败: {e}",
                "error_files": [],
                "suggestion": "",
            }
        obj = parse_json_object(raw) or {}
        return {
            "summary": str(obj.get("summary", "")),
            "error_files": [
                {
                    "file": str(f.get("file", "")),
                    "line": int(f.get("line", 0) or 0),
                    "message": str(f.get("message", "")),
                }
                for f in (obj.get("error_files") or [])
                if isinstance(f, dict)
            ],
            "suggestion": str(obj.get("suggestion", "")),
        }
