"""v0.7.0 E1：PatchSet 服务（预览 + 原子应用 + 回滚）。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §2。

复用 v0.5.0 ``patch_workflow`` 的可信写入模式：resolve_within 规范化、
最终组件链接拒绝、同目录临时文件 + ``os.replace`` 原子替换、写入后回读
核对 SHA；在此基础上实现多文件 PatchSet：

- 预览（``propose``）：只读零写入；路径/SHA/二进制/唯一性校验在预览阶段
  即完成，失败时快速关闭（T3/T5/T10）；
- 原子应用（``apply``）：预检（HEAD 漂移 T4、全部 SHA T3、rename 目标
  T11）→ 全量准备临时文件与回滚 manifest → 按冻结顺序提交（rename →
  create → update → delete）→ 回读验证（T2）→ 失败逆序回滚（T1）；
- 回滚失败即 ``partial_unknown``（T12）：终态只允许人工处置，服务层状态
  检查 + dispatcher NON_IDEMPOTENT 双重阻止自动重放（T8）。

所有错误消息只含相对路径，不含本地绝对路径（C0 §9 脱敏规则）。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .coding_errors import RUNNABLE_WORKSPACE_STATUSES
from .git_snapshot import GitSnapshotError, read_git_snapshot
from .patch_workflow import _reject_link_target
from .projects import ProjectService, resolve_within
from .repo_coding_patch_sets import (
    CodingPatchSet,
    CodingPatchSetRepository,
    PatchSetNotFound,
    PatchSetStateConflict,
)
from .workspaces import ProjectWorkspaceService

logger = get_logger(__name__)

# 单文件 diff 截断上限（字节近似，按字符截断；总输出仍受 MAX_TOTAL_DIFF_BYTES
# 硬上限约束，见 agents/patchset_contracts.py）
_MAX_SINGLE_FILE_DIFF_BYTES = 256 * 1024
_DIFF_TRUNCATION_SUFFIX = "\n…（diff 已截断）"
# 磁盘旧文件读取上限（与 patch_workflow._read_text_or_empty 一致）
_MAX_DISK_READ_BYTES = 5 * 1024 * 1024
# Windows 设备名黑名单（T5）
_WINDOWS_DEVICE_NAMES = frozenset(
    {
        "nul", "con", "prn", "aux",
        "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
        "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
        "conin$", "conout$",
    }
)
# 提交顺序（E0 §2.5 步骤 3 冻结）：rename → create → update → delete
_COMMIT_ORDER = {"rename": 0, "create": 1, "update": 2, "delete": 3}


class PatchSetError(RuntimeError):
    """带冻结错误码的 PatchSet 失败（消息只含相对路径）。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class _CommitFailed(RuntimeError):
    """提交阶段失败：携带已执行 ordinal 列表供逆序回滚。"""

    def __init__(self, executed: list[int], message: str) -> None:
        super().__init__(message)
        self.executed = executed


@dataclass
class _StagedOp:
    """一个已通过预检、准备好临时文件/备份的操作。"""

    ordinal: int
    operation: str
    rel_path: str
    new_rel_path: str | None
    full: Path
    new_full: Path | None
    old_sha256: str | None
    new_sha256: str | None
    stage: Path | None = None
    backup: Path | None = None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_disk(path: Path) -> str | None:
    """按文本语义读取文件并返回 SHA；不存在/不可读返回 None（不抛异常）。

    与 patch_workflow 的回读核对一致：read_text（universal newline）后按
    UTF-8 编码计算，避免 Windows CRLF 与预览文本（LF）SHA 不一致。
    """
    try:
        return hashlib.sha256(
            path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
    except (OSError, UnicodeDecodeError):
        return None


def _parameters_hash(operations: Sequence[dict]) -> str:
    """规范化参数哈希（T6）：sort_keys 确定性序列化后 SHA256。"""
    payload = json.dumps(
        list(operations),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ===========================================================================
# 路径与内容校验（T5：路径逃逸 / 设备名 / ADS / 链接；二进制拒绝）
# ===========================================================================


def _windows_device_name(part: str) -> str | None:
    """按 Windows 保留设备名规则提取名称：去除扩展名、尾随点与空格后 lower。

    P1-2 验收修复：`nul.txt` / `CON.md` / `com1.json` 等扩展名形态与
    `con.` / `con ` 尾随点/空格形态同样按设备名拒绝（MSDN 命名规则）。
    """
    base = part.split(".", 1)[0].rstrip(" .").lower()
    return base if base in _WINDOWS_DEVICE_NAMES else None


def _validate_rel_path(rel_path: str) -> None:
    if not rel_path:
        raise PatchSetError("patchset_invalid", "路径不能为空")
    if len(rel_path) > 2048:
        raise PatchSetError("patchset_invalid", "路径超长")
    if rel_path.startswith("/") or PurePosixPath(rel_path).is_absolute():
        raise PatchSetError("patchset_invalid", "拒绝绝对路径")
    if "\\" in rel_path:
        raise PatchSetError("patchset_invalid", "路径必须使用 / 分隔符")
    if ":" in rel_path:
        raise PatchSetError("patchset_invalid", "拒绝 Windows ADS 路径")
    if "\x00" in rel_path:
        raise PatchSetError("patchset_invalid", "路径包含 NUL 字节")
    parts = PurePosixPath(rel_path).parts
    if ".." in parts:
        raise PatchSetError("patchset_invalid", "拒绝 .. 越界路径")
    for part in parts:
        if _windows_device_name(part) is not None:
            raise PatchSetError("patchset_invalid", "拒绝设备路径")
        # P1-2 第三轮验收修复：按 Windows 规范化（去尾随点/空格）后为空或
        # 折叠为 . / .. 的组件一律拒绝——`...`、`.. `、`. ` 等形态在
        # Windows 解析时会折叠到空/上级/当前目录，形成与正常路径的别名。
        normalized = part.rstrip(" .").lower()
        if not normalized:
            raise PatchSetError("patchset_invalid", "拒绝空路径组件")
        if normalized == "..":
            raise PatchSetError("patchset_invalid", "拒绝 .. 越界路径")
        if normalized == ".":
            raise PatchSetError("patchset_invalid", "拒绝 . 路径组件")


def _check_new_content(content: str) -> None:
    if "\x00" in content:
        raise PatchSetError("patchset_invalid", "拒绝二进制内容（含 NUL 字节）")
    try:
        content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PatchSetError("patchset_invalid", "内容不是有效 UTF-8 文本") from exc


def _windows_normalize(path: str) -> str:
    """Windows 路径规范化键：逐组件去除尾随点/空格后 lower，跳过空组件。

    P1-2 第二轮验收修复：Windows 文件系统忽略路径组件尾部的点和空格
    （`README.MD.` 与 `Readme.md` 指向同一文件），仅 lower 无法覆盖；
    与设备名规则（_windows_device_name）同一规范化语义。第四轮：跳过
    空组件——`a//b` 与 `a/b` 在 Windows 解析到同一目标，唯一性键必须一致。
    """
    return "/".join(
        part.rstrip(" .").lower() for part in path.split("/") if part
    )


def _check_path_uniqueness(operations: Sequence[dict]) -> None:
    """同一 PatchSet 内路径唯一（含 rename 目标）；create 与 delete 不撞同路径。

    P1-2 验收修复：唯一性按 Windows 大小写不敏感形式归一化（lower）比较，
    `Readme.md` 与 `readme.md` 视为同一路径拒绝；第二轮按逐组件去尾随点/
    空格规范化——`README.MD.` 与 `Readme.md` 同样判重复（Windows 同一文件）。
    """
    seen: set[str] = set()
    for item in operations:
        op_type = item["operation"]
        params = item[op_type]
        if op_type == "rename":
            paths = (params["old_path"], params["new_path"])
        else:
            paths = (params["path"],)
        for path in paths:
            _validate_rel_path(path)
            key = _windows_normalize(path)
            if key in seen:
                raise PatchSetError("patchset_invalid", f"路径重复: {path}")
            seen.add(key)


def _resolve(root: str, rel_path: str) -> Path:
    """resolve_within + 最终组件链接拒绝（复用 B1 语义）。"""
    full = resolve_within(root, rel_path)
    _reject_link_target(full)
    return full


def _read_disk_utf8(full: Path, *, missing_ok: bool) -> str:
    """严格 UTF-8 读取磁盘文件；二进制/非 UTF-8 拒绝（T5 二进制拒绝）。"""
    if not full.exists():
        if missing_ok:
            return ""
        raise PatchSetError("patchset_conflict", f"文件不存在: {full.name}")
    if not full.is_file():
        raise PatchSetError("patchset_invalid", f"不是普通文件: {full.name}")
    size = full.stat().st_size
    if size > _MAX_DISK_READ_BYTES:
        raise PatchSetError(
            "patchset_invalid", f"文件过大（{size} 字节，上限 {_MAX_DISK_READ_BYTES} 字节）"
        )
    try:
        return full.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PatchSetError(
            "patchset_invalid", "目标文件不是有效 UTF-8 文本（二进制文件不支持）"
        ) from exc


def _make_diff(rel_path: str, old_content: str, new_content: str) -> tuple[str, bool]:
    """生成统一 Diff（a/ b/ 前缀）；超限截断并标记 truncated。"""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
    )
    if diff:
        diff += "\n"
    truncated = len(diff) > _MAX_SINGLE_FILE_DIFF_BYTES
    if truncated:
        diff = diff[:_MAX_SINGLE_FILE_DIFF_BYTES] + _DIFF_TRUNCATION_SUFFIX
    return diff, truncated


def _diff_stats(diff: str) -> tuple[int, int]:
    """统计 diff 的 +/− 行数（不含 +++/--- 文件头）。"""
    additions = deletions = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


# ===========================================================================
# 预览（零写入）
# ===========================================================================


def _build_preview_files(root: str, operations: Sequence[dict]) -> list[dict]:
    """校验全部操作并计算每个文件的预览（SHA/diff）；只读磁盘，零写入。"""
    _check_path_uniqueness(operations)
    files: list[dict[str, Any]] = []
    for item in operations:
        op_type = item["operation"]
        params = item[op_type]
        if op_type == "create":
            path = params["path"]
            _check_new_content(params["new_content"])
            full = _resolve(root, path)
            if full.exists():
                raise PatchSetError("patchset_conflict", f"目标文件已存在: {path}")
            old_content = ""
            new_content = params["new_content"]
        elif op_type == "update":
            path = params["path"]
            _check_new_content(params["new_content"])
            full = _resolve(root, path)
            old_content = _read_disk_utf8(full, missing_ok=False)
            new_content = params["new_content"]
        elif op_type == "delete":
            path = params["path"]
            full = _resolve(root, path)
            old_content = _read_disk_utf8(full, missing_ok=False)
            new_content = ""
        elif op_type == "rename":
            old_path = params["old_path"]
            new_path = params["new_path"]
            if "new_content" in params:
                _check_new_content(params["new_content"])
            full = _resolve(root, old_path)
            old_content = _read_disk_utf8(full, missing_ok=False)
            new_content = params.get("new_content", old_content)
            new_full = _resolve(root, new_path)
            if new_full.exists():
                raise PatchSetError("patchset_conflict", f"rename 目标已存在: {new_path}")
        else:  # pragma: no cover - schema 已约束
            raise PatchSetError("patchset_invalid", f"未知操作: {op_type}")

        old_sha = _sha256_text(old_content)
        new_sha = _sha256_text(new_content)
        expected = params.get("expected_old_sha256")
        if expected is not None and old_sha != expected:
            raise PatchSetError("patchset_conflict", f"文件内容已变化: {full.name}")

        # rename 的“当前路径”是 old_path；diff 展示目标（new）路径
        rel_path = params["old_path"] if op_type == "rename" else params["path"]
        diff_text, truncated = _make_diff(
            params.get("new_path", rel_path), old_content, new_content
        )
        entry: dict[str, Any] = {
            "operation": op_type,
            "rel_path": rel_path,
            "old_sha256": old_sha,
            "diff_text": diff_text,
            "truncated": truncated,
        }
        if op_type == "rename":
            entry["new_rel_path"] = params["new_path"]
        if op_type != "delete":
            entry["new_sha256"] = new_sha
            entry["new_content"] = new_content
        files.append(entry)
    return files


# ===========================================================================
# 原子应用（预检 → 全量准备 → 提交 → 回读验证 / 逆序回滚）
# ===========================================================================


def _stage_backup(full: Path) -> Path:
    """同目录备份旧文件（回滚 manifest），fsync 后保留。"""
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{full.name}.", suffix=".pa-bak", dir=str(full.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            with open(full, "rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        return Path(tmp_name)
    except OSError as exc:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise RuntimeError(f"备份失败: {exc}") from exc


def _stage_new_content(full: Path, content: str) -> Path:
    """同目录写新内容临时文件（提交阶段 os.replace 原子替换）。"""
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{full.name}.", suffix=".pa-stg", dir=str(full.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return Path(tmp_name)
    except OSError as exc:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise RuntimeError(f"准备失败: {exc}") from exc


def _cleanup_staged(staged: Sequence[_StagedOp]) -> None:
    """清理临时文件与备份（预检失败/成功后）。"""
    for op in staged:
        for path in (op.stage, op.backup):
            if path is not None:
                with suppress(OSError):
                    path.unlink(missing_ok=True)
        op.stage = None
        op.backup = None


def _prepare_and_stage(root: str, files: Sequence[dict]) -> list[_StagedOp]:
    """预检全部文件（T3/T5/T11）→ 全量准备临时文件与回滚 manifest。

    任一冲突/失败抛 PatchSetError/RuntimeError，零写入目标文件；
    已创建的临时文件由调用方清理。
    """
    staged: list[_StagedOp] = []
    try:
        for item in files:
            op_type = item["operation"]
            rel_path = item["rel_path"]
            full = _resolve(root, rel_path)
            old_content = _read_disk_utf8(full, missing_ok=(op_type == "create"))
            old_sha = _sha256_text(old_content)
            expected = item.get("old_sha256")
            if expected is not None and old_sha != expected:
                raise PatchSetError("patchset_conflict", f"文件内容已变化: {rel_path}")
            if op_type == "create":
                if full.exists():
                    raise PatchSetError("patchset_conflict", f"目标文件已存在: {rel_path}")
            op = _StagedOp(
                ordinal=item["ordinal"],
                operation=op_type,
                rel_path=rel_path,
                new_rel_path=item.get("new_rel_path"),
                full=full,
                new_full=(
                    _resolve(root, item["new_rel_path"])
                    if item.get("new_rel_path")
                    else None
                ),
                old_sha256=old_sha,
                new_sha256=item.get("new_sha256"),
            )
            if op_type == "create":
                op.stage = _stage_new_content(op.full, item["new_content"])
            elif op_type == "update":
                op.backup = _stage_backup(op.full)
                op.stage = _stage_new_content(op.full, item["new_content"])
            elif op_type == "delete":
                op.backup = _stage_backup(op.full)
            elif op_type == "rename":
                assert op.new_full is not None
                if op.new_full.exists():
                    raise PatchSetError(
                        "patchset_conflict", f"rename 目标已存在: {item['new_rel_path']}"
                    )
                op.backup = _stage_backup(op.full)
                op.stage = _stage_new_content(op.new_full, item["new_content"])
            staged.append(op)
    except BaseException:
        _cleanup_staged(staged)
        raise
    return staged


def _commit_all(staged: Sequence[_StagedOp]) -> list[int]:
    """按冻结顺序提交：rename → create → update → delete。返回已执行 ordinal。"""
    executed: list[int] = []
    for op in sorted(staged, key=lambda s: _COMMIT_ORDER[s.operation]):
        try:
            if op.operation == "create" or op.operation == "update":
                assert op.stage is not None and op.full is not None
                os.replace(op.stage, op.full)
                op.stage = None
            elif op.operation == "delete":
                op.full.unlink()
            elif op.operation == "rename":
                assert op.stage is not None and op.new_full is not None
                os.replace(op.stage, op.new_full)
                op.stage = None
                try:
                    op.full.unlink()
                except OSError as exc:
                    # 新路径已就位但源未删除：视同已执行，回滚将删除新文件并恢复源
                    raise _CommitFailed(
                        executed + [op.ordinal],
                        f"rename 源删除失败: {op.rel_path}",
                    ) from exc
        except OSError as exc:
            raise _CommitFailed(executed, f"{op.operation} 失败: {op.rel_path}") from exc
        executed.append(op.ordinal)
    return executed


def _verify_all(staged: Sequence[_StagedOp]) -> tuple[bool, list[str]]:
    """回读全部目标核对新 SHA / 不存在状态（T2 事实复核）。"""
    failures: list[str] = []
    for op in staged:
        if op.operation in ("create", "update"):
            disk = _sha256_disk(op.full)
            if disk != op.new_sha256:
                failures.append(f"回读 SHA 不一致: {op.rel_path}")
        elif op.operation == "delete":
            if op.full.exists():
                failures.append(f"删除后仍存在: {op.rel_path}")
        elif op.operation == "rename":
            assert op.new_full is not None
            if op.full.exists():
                failures.append(f"rename 后源仍存在: {op.rel_path}")
            if _sha256_disk(op.new_full) != op.new_sha256:
                failures.append(f"rename 目标 SHA 不一致: {op.new_rel_path}")
    return (not failures), failures


def _rollback_all(
    staged: Sequence[_StagedOp], executed: Sequence[int]
) -> tuple[bool, set[int], list[str]]:
    """逆序回滚已执行操作（T1/T12）。

    返回 (全部成功?, 回滚失败 ordinal 集合, 失败描述列表)。
    """
    failures: list[str] = []
    failed_ordinals: set[int] = set()
    for op in sorted(
        (s for s in staged if s.ordinal in executed),
        key=lambda s: s.ordinal,
        reverse=True,
    ):
        try:
            if op.operation == "create":
                op.full.unlink(missing_ok=True)
            elif op.operation == "rename":
                assert op.new_full is not None
                op.new_full.unlink(missing_ok=True)
                if op.backup is not None:
                    os.replace(op.backup, op.full)
                    op.backup = None
            else:  # update / delete
                if op.backup is not None:
                    os.replace(op.backup, op.full)
                    op.backup = None
        except OSError as exc:  # noqa: PERF203
            failed_ordinals.add(op.ordinal)
            failures.append(
                f"{op.operation} 回滚失败: {op.rel_path} ({type(exc).__name__})"
            )
    return (not failures), failed_ordinals, failures


def _verify_rollback(staged: Sequence[_StagedOp], executed: Sequence[int]) -> bool:
    """回滚后回读验证：恢复原状才算完整回滚成功（T12）。"""
    for op in staged:
        if op.ordinal not in executed:
            continue
        if op.operation == "create":
            if op.full.exists():
                return False
        elif op.operation == "rename":
            assert op.new_full is not None
            if op.new_full.exists() or _sha256_disk(op.full) != op.old_sha256:
                return False
        else:  # update / delete
            if _sha256_disk(op.full) != op.old_sha256:
                return False
    return True


# ===========================================================================
# 服务
# ===========================================================================


class PatchSetService:
    """PatchSet 预览与原子应用（绑定 run；事件与状态机见 E0 §1/§2.4）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CodingPatchSetRepository(db)

    # ---- run/workspace 校验 ----

    async def _resolve_run_context(
        self, run_id: str, *, expected_project_id: int | None = None,
        expected_workspace_id: int | None = None,
    ) -> tuple[int, int, str]:
        """解析 run 的项目/workspace 与 root；校验归属与可运行状态。"""
        from ..agents.repository import AgentRunRepository

        run = await AgentRunRepository(self.db).get_run(run_id)
        if run is None or run.project_id is None or run.workspace_id is None:
            raise PatchSetError("patchset_invalid", "run 未绑定项目/工作区")
        if expected_project_id is not None and run.project_id != expected_project_id:
            raise PatchSetError("patchset_invalid", "run 与 PatchSet 项目不匹配")
        if expected_workspace_id is not None and run.workspace_id != expected_workspace_id:
            raise PatchSetError("patchset_invalid", "run 与 PatchSet 工作区不匹配")
        workspace = await ProjectWorkspaceService(self.db).get(run.workspace_id)
        if workspace is None:
            raise PatchSetError("workspace_unavailable", "工作区不存在")
        if workspace.status not in RUNNABLE_WORKSPACE_STATUSES:
            raise PatchSetError(
                "workspace_unavailable", f"工作区状态不可用: {workspace.status}"
            )
        if not await ProjectWorkspaceService(self.db).check_path(workspace):
            raise PatchSetError("workspace_unavailable", "工作区路径缺失")
        project = await ProjectService(self.db).get(run.project_id)
        return run.project_id, run.workspace_id, project.root_path

    # ---- 预览 ----

    async def propose(self, run_id: str, operations: list[dict]) -> dict:
        """生成并持久化 PatchSet 预览；只读零写入。"""
        if not operations:
            raise PatchSetError("patchset_invalid", "operations 不能为空")
        project_id, workspace_id, root = await self._resolve_run_context(run_id)
        files = await asyncio.to_thread(_build_preview_files, root, operations)
        truncated = any(item["truncated"] for item in files)
        additions = deletions = diff_total_bytes = 0
        for item in files:
            item_add, item_del = _diff_stats(item["diff_text"])
            additions += item_add
            deletions += item_del
            diff_total_bytes += len(item["diff_text"].encode("utf-8"))
        from ..agents.patchset_contracts import MAX_TOTAL_DIFF_BYTES

        if diff_total_bytes > MAX_TOTAL_DIFF_BYTES:
            raise PatchSetError(
                "patchset_invalid",
                f"总 Diff 输出 {diff_total_bytes} 字节超过上限 {MAX_TOTAL_DIFF_BYTES}",
            )
        parameters_hash = _parameters_hash(operations)
        run = await self._run_record(run_id)
        record = await self.repo.create_preview(
            run_id=run_id,
            project_id=project_id,
            workspace_id=workspace_id,
            base_head_sha=run.base_head_sha,
            parameters_hash=parameters_hash,
            file_count=len(files),
            additions=additions,
            deletions=deletions,
            truncated=truncated,
            diff_total_bytes=diff_total_bytes,
            files=files,
        )
        await self._emit_event(
            run_id,
            "patch_set.preview_created",
            {
                "patch_set_id": record.id,
                "preview_version": record.preview_version,
                "file_count": record.file_count,
                "truncated": record.truncated,
                **({"base_head_sha": record.base_head_sha} if record.base_head_sha else {}),
            },
        )
        # E3：预览成功 → patch_preview Artifact（flag 关闭时 no-op）
        await self._project_artifact(run_id, "project_patch_preview", record.id)
        return self._preview_output(record)

    async def _run_record(self, run_id: str):
        from ..agents.repository import AgentRunRepository

        run = await AgentRunRepository(self.db).get_run(run_id)
        if run is None:
            raise PatchSetError("patchset_not_found", "run 不存在")
        return run

    @staticmethod
    def _preview_output(record) -> dict:
        files = []
        for item in record.files:
            entry = {
                "operation": item.operation,
                "path": item.rel_path,
                "old_sha256": item.old_sha256,
                "diff_text": item.diff_text,
                "truncated": item.truncated,
            }
            if item.operation == "rename":
                entry["new_path"] = item.new_rel_path
            if item.new_sha256 is not None:
                entry["new_sha256"] = item.new_sha256
            files.append(entry)
        output = {
            "patch_set_id": record.id,
            "preview_version": record.preview_version,
            "parameters_hash": record.parameters_hash,
            "truncated": record.truncated,
            "file_count": record.file_count,
            "additions": record.additions,
            "deletions": record.deletions,
            "diff_total_bytes": record.diff_total_bytes,
            "files": files,
        }
        if record.base_head_sha:
            output["base_head_sha"] = record.base_head_sha
        return output

    # ---- 原子应用 ----

    async def apply(
        self,
        run_id: str,
        patch_set_id: str,
        preview_version: int,
        expected_parameters_hash: str,
    ) -> dict:
        """审批后原子应用已预览的 PatchSet；失败回滚或 partial_unknown。"""
        try:
            patch_set = await self.repo.get_for_run(run_id, patch_set_id)
        except PatchSetNotFound as exc:
            raise PatchSetError("patchset_not_found", str(exc)) from exc

        # T6：参数/版本强校验，必须重新预览
        if (
            patch_set.preview_version != preview_version
            or patch_set.parameters_hash != expected_parameters_hash
        ):
            raise PatchSetError("patchset_preview_stale", "预览版本或参数哈希不匹配，请重新预览")
        # T7：截断预览不可应用
        if patch_set.truncated:
            raise PatchSetError("patchset_truncated", "预览被截断，不允许直接应用")
        # T8/T12：只有 previewed 可进入应用；终态（含 partial_unknown）禁止重放
        if patch_set.status != "previewed":
            raise PatchSetError(
                "patchset_partial_unknown",
                f"PatchSet 状态为 {patch_set.status}，禁止应用或自动重放",
            )

        _, _, root = await self._resolve_run_context(
            run_id,
            expected_project_id=patch_set.project_id,
            expected_workspace_id=patch_set.workspace_id,
        )

        # T4：HEAD 漂移检测（run 创建快照 vs 当前工作区）
        if patch_set.base_head_sha:
            try:
                snapshot = await read_git_snapshot(root)
            except GitSnapshotError as exc:
                raise PatchSetError("git_snapshot_failed", str(exc)) from exc
            if snapshot is None or snapshot.head_sha != patch_set.base_head_sha:
                raise PatchSetError("git_snapshot_failed", "Git HEAD 已漂移，请重新预览")

        files = [
            {
                "ordinal": item.ordinal,
                "operation": item.operation,
                "rel_path": item.rel_path,
                "new_rel_path": item.new_rel_path,
                "old_sha256": item.old_sha256,
                "new_sha256": item.new_sha256,
                "new_content": item.new_content,
            }
            for item in patch_set.files
        ]
        # 全量预检 + 准备（T3/T5/T11；零写入目标文件）
        try:
            staged = await asyncio.to_thread(_prepare_and_stage, root, files)
        except PatchSetError as exc:
            await self._mark_failed(patch_set.id, exc.error_code, str(exc))
            raise
        except Exception as exc:  # noqa: BLE001 - IO 等意外失败关闭
            await self._mark_failed(patch_set.id, "patchset_conflict", str(exc))
            raise PatchSetError("patchset_conflict", f"准备失败: {type(exc).__name__}") from exc

        try:
            executed = await asyncio.to_thread(_commit_all, staged)
        except _CommitFailed as exc:
            await self._handle_failure(
                patch_set.run_id, patch_set.id, staged, exc.executed, str(exc)
            )
            raise PatchSetError("patchset_conflict", str(exc)) from exc

        verified, verify_failures = await asyncio.to_thread(_verify_all, staged)
        if not verified:
            await self._handle_failure(
                patch_set.run_id, patch_set.id, staged, executed, "; ".join(verify_failures)
            )
            raise PatchSetError("patchset_conflict", "回读验证失败，已回滚")

        # 全部成功：先持久化终态（applied + verified，transition_status 内部
        # commit），DB 提交成功后再清理临时文件/备份（P1-1 验收修复——备份
        # 清理后置，杜绝「磁盘已修改、PatchSet 仍 previewed 且无法回滚」的
        # 幽灵状态；清理失败仅残留 .pa-bak 无害文件，不改变已持久化状态）。
        try:
            await self.repo.set_all_files_status(patch_set.id, "applied")
            record = await self.repo.transition_status(
                patch_set.id, "previewed", "applied"
            )
        except PatchSetStateConflict as exc:  # pragma: no cover - 并发终态竞争
            raise PatchSetError("patchset_partial_unknown", str(exc)) from exc
        except Exception as exc:
            # P1-1 第三轮验收修复：DB 终态写入失败（SQL 执行/commit 异常）——
            # 先经**新事务确认 durable 状态**：transition_status 内部 commit
            # 可能已成功（仅提交后查询失败），此时 DB=applied 而磁盘已改，
            # 回滚磁盘会造成反向分叉，必须按成功路径收敛；确认仍 previewed
            # 才逆序回滚磁盘（备份仍在）并尽力标记 rolled_back/partial_unknown。
            durable_outcome = await self._handle_db_terminal_failure(
                patch_set.run_id, patch_set.id, staged, executed, str(exc)
            )
            if durable_outcome == "applied":
                # commit 实际成功（仅查询失败）：终态已 durable，补发事件与投影
                await self._emit_event(
                    run_id,
                    "patch_set.applied",
                    {
                        "patch_set_id": patch_set.id,
                        "preview_version": patch_set.preview_version,
                        "verified": True,
                    },
                )
                await self._project_artifact(
                    run_id, "project_patch_applied", patch_set.id
                )
                return self._apply_output(patch_set)
            if durable_outcome == "unknown":
                # 第四轮（P1-1）：durable 状态不可判定（DB 暂不可达）——磁盘与
                # 备份保留（绝不回滚，防与已提交 applied 分叉），状态尽力落
                # partial_unknown，DB 恢复后人工处置。
                raise PatchSetError(
                    "patchset_partial_unknown",
                    "终态不可判定：磁盘与备份保留，DB 恢复后需人工处置",
                )
            raise PatchSetError(
                "patchset_conflict", f"终态持久化失败，已回滚: {type(exc).__name__}"
            ) from exc
        try:
            await asyncio.to_thread(_cleanup_staged, staged)
        except Exception:  # noqa: BLE001 - 状态已 applied，残留备份无害
            logger.warning(
                "patch set applied but cleanup failed",
                patch_set_id=patch_set.id,
            )
        await self._emit_event(
            run_id,
            "patch_set.applied",
            {
                "patch_set_id": record.id,
                "preview_version": record.preview_version,
                "verified": True,
            },
        )
        # E3：应用成功 → patch_applied Artifact（flag 关闭时 no-op）
        await self._project_artifact(run_id, "project_patch_applied", record.id)
        return self._apply_output(record)

    async def _handle_db_terminal_failure(
        self,
        run_id: str,
        patch_set_id: str,
        staged: Sequence[_StagedOp],
        executed: Sequence[int],
        reason: str,
    ) -> str:
        """DB 终态写入失败（P1-1）：先经新事务确认 durable 状态，再补偿。

        返回三态：
        - ``applied``：终态已 durable（commit 成功仅查询失败）——调用方按
          成功路径收敛（不回滚磁盘）；
        - ``unknown``：durable 状态不可判定（新事务查询也失败，DB 暂不可达）
          ——磁盘与备份保留（绝不回滚，防与可能已提交的 applied 分叉），
          尽力落 partial_unknown，DB 恢复后人工处置；
        - ``rolled_back``：确认仍 previewed——已逆序回滚磁盘并尽力标记
          rolled_back / partial_unknown，不构成「磁盘已改 + previewed」。
        """
        from .db import async_session_factory

        durable: CodingPatchSet | None = None
        durable_unknown = False
        try:
            async with async_session_factory() as s:
                durable = await self.repo.__class__(s).get_by_id(patch_set_id)
        except Exception:  # noqa: BLE001 - DB 不可达，状态不可判定
            durable_unknown = True
        if durable is not None and durable.status == "applied":
            # commit 已成功（仅提交后查询失败）：终态 durable，按成功路径
            # 清理备份（残留无害）；绝不回滚磁盘（防反向分叉）。
            try:
                await asyncio.to_thread(_cleanup_staged, staged)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "patch_set applied cleanup failed",
                    patch_set_id=patch_set_id,
                )
            return "applied"
        if durable_unknown:
            # 第四轮（P1-1）：状态不可判定——保留磁盘与备份（commit 可能已
            # 成功），尽力落 partial_unknown；DB 恢复后由人工处置。
            try:
                await self.db.rollback()
                await self.repo.transition_status(
                    patch_set_id,
                    "previewed",
                    "partial_unknown",
                    error_code="patchset_partial_unknown",
                    error_message=reason[:4000],
                )
            except Exception:  # noqa: BLE001 - DB 仍不可达
                await self.db.rollback()
                logger.error(
                    "patch_set durable-state unknown, partial_unknown not persisted",
                    patch_set_id=patch_set_id,
                    exc_info=True,
                )
            return "unknown"
        # 确认仍 previewed：逆序回滚磁盘（备份仍在），再尽力标记状态
        rollback_ok, _failed_ordinals, _rollback_failures = await asyncio.to_thread(
            _rollback_all, staged, executed
        )
        if rollback_ok:
            try:
                await self.db.rollback()  # 结束失败事务后再写状态
                await self.repo.set_all_files_status(patch_set_id, "rolled_back")
                await self.repo.transition_status(
                    patch_set_id, "previewed", "rolled_back"
                )
            except Exception:  # noqa: BLE001 - DB 仍不可用，磁盘已恢复
                await self.db.rollback()
                logger.warning(
                    "patch_set db-terminal-failure rollback state not persisted",
                    patch_set_id=patch_set_id,
                    exc_info=True,
                )
            try:
                await asyncio.to_thread(_cleanup_staged, staged)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "patch_set cleanup failed", patch_set_id=patch_set_id
                )
            return "rolled_back"
        # 回滚失败 → partial_unknown（尽力而为；DB 不可用时记录日志）
        try:
            await self.db.rollback()
            await self.repo.transition_status(
                patch_set_id,
                "previewed",
                "partial_unknown",
                error_code="patchset_partial_unknown",
                error_message=reason[:4000],
            )
        except Exception:  # noqa: BLE001 - DB 完全不可用
            await self.db.rollback()
            logger.error(
                "patch_set db-terminal-failure partial_unknown not persisted",
                patch_set_id=patch_set_id,
                exc_info=True,
            )
        return "rolled_back"

    async def _handle_failure(
        self,
        run_id: str,
        patch_set_id: str,
        staged: Sequence[_StagedOp],
        executed: Sequence[int],
        reason: str,
    ) -> None:
        """提交/验证失败：逆序回滚；回滚失败 → partial_unknown（T1/T12）。"""
        rollback_ok, failed_ordinals, rollback_failures = await asyncio.to_thread(
            _rollback_all, staged, executed
        )
        if rollback_ok:
            verified = await asyncio.to_thread(_verify_rollback, staged, executed)
        else:
            verified = False
        if rollback_ok and verified:
            try:
                await self.repo.set_all_files_status(patch_set_id, "rolled_back")
                await self.repo.transition_status(
                    patch_set_id, "previewed", "rolled_back"
                )
            except PatchSetStateConflict:  # pragma: no cover
                raise PatchSetError("patchset_partial_unknown", "状态竞争，需人工处置")
            await self._emit_event(
                run_id,
                "patch_set.rolled_back",
                {"patch_set_id": patch_set_id, "reason": reason[:512]},
            )
            await asyncio.to_thread(_cleanup_staged, staged)
            return
        # 回滚不完整 → partial_unknown：主状态先行（独立事务），文件状态尽力而为
        try:
            await self.repo.transition_status(
                patch_set_id,
                "previewed",
                "partial_unknown",
                error_code="patchset_partial_unknown",
                error_message=reason[:4000],
            )
        except PatchSetStateConflict:  # pragma: no cover
            raise PatchSetError("patchset_partial_unknown", "状态竞争，需人工处置")
        detail = "; ".join(rollback_failures) if rollback_failures else reason
        await self._emit_event(
            run_id,
            "patch_set.unknown",
            {"patch_set_id": patch_set_id, "reason": detail[:512]},
        )
        try:
            executed_set = set(executed)
            for op in staged:
                if op.ordinal not in executed_set:
                    continue
                await self.repo.set_file_status(
                    patch_set_id,
                    op.ordinal,
                    "rolled_back" if op.ordinal not in failed_ordinals else "unknown",
                )
            await self.db.commit()
        except Exception:  # noqa: BLE001 - 文件级状态是次要事实，失败只记日志
            await self.db.rollback()
            logger.warning(
                "patch_set partial_unknown file status update failed",
                patch_set_id=patch_set_id,
                exc_info=True,
            )
        await asyncio.to_thread(_cleanup_staged, staged)
        raise PatchSetError(
            "patchset_partial_unknown", "回滚不完整，已标记 partial_unknown，需人工处置"
        )

    async def _mark_failed(self, patch_set_id: str, error_code: str, message: str) -> None:
        """预检失败（零写入）：状态 → failed + patch_set.failed 事件。"""
        try:
            record = await self.repo.transition_status(
                patch_set_id,
                "previewed",
                "failed",
                error_code=error_code,
                error_message=message[:4000],
            )
        except PatchSetStateConflict as exc:  # pragma: no cover
            raise PatchSetError("patchset_partial_unknown", str(exc)) from exc
        await self._emit_event(
            record.run_id,
            "patch_set.failed",
            {
                "patch_set_id": record.id,
                "error_code": error_code,
                "error_message": message[:4000],
            },
        )

    @staticmethod
    def _apply_output(record) -> dict:
        files = []
        for item in record.files:
            entry = {
                "path": item.rel_path,
                "operation": item.operation,
                "status": item.status,
            }
            if item.old_sha256 is not None:
                entry["old_sha256"] = item.old_sha256
            if item.new_sha256 is not None:
                entry["new_sha256"] = item.new_sha256
            files.append(entry)
        return {
            "patch_set_id": record.id,
            "preview_version": record.preview_version,
            "status": record.status,
            "verified": record.status == "applied",
            "files": files,
        }

    async def _project_artifact(self, run_id: str, method: str, patch_set_id: str) -> None:
        """E3：即时投影 Artifact（独立 session；flag 关闭/失败均不影响主流程）。"""
        from ..core.artifact_projection import ArtifactProjectionService
        from ..core.db import async_session_factory

        try:
            async with async_session_factory() as session:
                service = ArtifactProjectionService(session)
                fn = getattr(service, method)
                await fn(run_id=run_id, patch_set_id=patch_set_id)
        except Exception:  # noqa: BLE001 - 投影失败不影响执行事实
            logger.warning(
                "patch_set artifact projection failed",
                run_id=run_id,
                method=method,
                exc_info=True,
            )

    # ---- durable 事件（独立 session，复用 C0 §8 模式） ----

    async def _emit_event(self, run_id: str, event_type: str, payload: dict) -> None:
        from ..agents.contracts import AgentEvent, AgentEventType
        from ..agents.repository import AgentRunRepository
        from ..core.db import async_session_factory

        try:
            async with async_session_factory() as session:
                run_repo = AgentRunRepository(session)
                run = await run_repo.get_run(run_id)
                if run is None:
                    return
                await run_repo.record_event(
                    AgentEvent(
                        run_id=run_id,
                        sequence=run.last_event_sequence + 1,
                        type=AgentEventType(event_type),
                        payload=payload,
                    )
                )
        except Exception:
            logger.warning(
                "patch_set durable event emit failed",
                run_id=run_id,
                event_type=event_type,
                exc_info=True,
            )
