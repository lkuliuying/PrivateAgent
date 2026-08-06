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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .code_tools import _execute_command, _sha256_text, parse_command
from .learning import parse_json_object
from .models import PatchSet, ProjectCommandProfile
from .projects import ProjectNotFound, ProjectService, resolve_within
from .provider import OllamaProvider, ProviderError
from .repo_patch_sets import PatchSetRepository, ProjectCommandProfileRepository
from .settings import SettingsService

logger = get_logger(__name__)

PATCH_MAX_CHARS = 500000  # 单文件新内容上限（与 code_tools 一致）
MAX_READ_FILE_BYTES = 5 * 1024 * 1024


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
    ) -> ProjectCommandProfile:
        return await self.repo.create(
            project_id=project_id,
            name=name,
            command_json=command_json,
            kind=kind,
            timeout_seconds=timeout_seconds,
            enabled=enabled,
        )

    async def list_by_project(
        self, project_id: int, kind: str | None = None
    ) -> list[ProjectCommandProfile]:
        return await self.repo.list_by_project(project_id, kind=kind)

    async def update(self, profile_id: int, **kwargs) -> ProjectCommandProfile:
        p = await self.repo.get(profile_id)
        if p is None:
            raise CommandProfileNotFound(f"命令配置不存在: {profile_id}")
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
        """运行项目命令配置（预授权，不经全局白名单）。"""
        p = await self.repo.get(profile_id)
        if p is None:
            raise CommandProfileNotFound(f"命令配置不存在: {profile_id}")
        if not p.enabled:
            raise ValueError(f"命令配置已禁用: {p.name}")
        project = await self.projects.get(p.project_id)
        if project is None:
            raise ProjectNotFound(f"项目不存在: {p.project_id}")
        args = _profile_to_args(p.command_json)
        result = await _execute_command(
            args, project.root_path, timeout=p.timeout_seconds
        )
        result["project_id"] = p.project_id
        result["profile_id"] = profile_id
        result["profile_name"] = p.name
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
