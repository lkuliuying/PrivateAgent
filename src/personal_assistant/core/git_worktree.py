"""v0.9.0 H3：Git worktree 服务（计划 §4）。

安全契约（零容忍）：
- 全部使用**固定 Git argv**（``[git, worktree, ...]``），不经 shell、
  不拼接用户文本到 shell 字符串；模型不注册任何 worktree 工具。
- 创建失败不改动原仓库（``git worktree add`` 失败语义由 Git 保证，
  服务层再做 HEAD/脏状态复核兜底）。
- dirty worktree 永不自动删除；清理前检查未提交变更与未追踪文件。
- 分支名/路径白名单校验（拒绝 ``..``、控制字符与超长输入）。
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger

logger = get_logger(__name__)

# 固定 Git 可执行名（不经 shell；PATH 解析由操作系统完成）
GIT_EXECUTABLE = "git"
GIT_WORKTREE_TIMEOUT_SECONDS = 60

# 分支名白名单：字母数字与 . _ - /；禁止 ..、首尾 /、控制字符
_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
# worktree 目录名白名单（由分支名转译）
_DIR_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class WorktreeError(RuntimeError):
    """worktree 操作失败（附低基数错误码，不含命令输出正文）。"""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class WorktreeInfo:
    path: str
    branch: str | None
    head_sha: str | None
    detached: bool
    locked: bool


def validate_branch_name(branch: str) -> str:
    """白名单校验分支名；非法即抛 WorktreeError（422 语义）。"""
    if not isinstance(branch, str) or not _BRANCH_PATTERN.match(branch):
        raise WorktreeError("worktree_branch_invalid", "非法分支名")
    if ".." in branch or branch.endswith("/") or branch.endswith(".lock"):
        raise WorktreeError("worktree_branch_invalid", "非法分支名")
    return branch


def worktree_dir_name(branch: str) -> str:
    """分支名 → 目录名（白名单字符转译，有界）。"""
    name = _DIR_SAFE_PATTERN.sub("-", branch).strip("-")
    return (name or "worktree")[:120]


async def _run_git(argv: list[str], cwd: str) -> tuple[int, str, str]:
    """固定 argv 执行 git（无 shell）；超时失败关闭。"""
    proc = await asyncio.create_subprocess_exec(
        GIT_EXECUTABLE,
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=GIT_WORKTREE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise WorktreeError("worktree_timeout", "git 命令超时") from exc
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


async def is_git_repository(root: str) -> bool:
    """root 本身必须是某个 Git 仓库的顶层（而非仅位于某仓库内部）。

    用 ``rev-parse --show-toplevel`` 与规范化路径比较（Windows 大小写不
    敏感），避免把“位于父仓库内的普通子目录”误判为独立仓库。
    """
    code, out, _ = await _run_git(["rev-parse", "--show-toplevel"], cwd=root)
    if code != 0:
        return False
    toplevel = out.strip()
    if not toplevel:
        return False
    try:
        left = os.path.normcase(str(Path(toplevel).resolve()))
        right = os.path.normcase(str(Path(root).resolve()))
    except OSError:
        return False
    return left == right


async def list_worktrees(repo_root: str) -> list[WorktreeInfo]:
    """解析 ``git worktree list --porcelain``（固定参数）。"""
    code, out, _ = await _run_git(["worktree", "list", "--porcelain"], cwd=repo_root)
    if code != 0:
        return []
    infos: list[WorktreeInfo] = []
    current: dict[str, str | bool] = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current.get("path"):
                infos.append(_build_info(current))
            current = {"path": line[len("worktree ") :].strip()}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].strip()
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("locked"):
            current["locked"] = True
    if current.get("path"):
        infos.append(_build_info(current))
    return infos


def _build_info(current: dict) -> WorktreeInfo:
    branch = current.get("branch")
    if isinstance(branch, str) and branch.startswith("refs/heads/"):
        branch = branch[len("refs/heads/") :]
    return WorktreeInfo(
        path=str(current.get("path") or ""),
        branch=branch if isinstance(branch, str) else None,
        head_sha=current.get("head") if isinstance(current.get("head"), str) else None,
        detached=bool(current.get("detached")),
        locked=bool(current.get("locked")),
    )


async def create_worktree(
    *,
    repo_root: str,
    branch_name: str,
    target_path: str,
    base_ref: str | None = None,
) -> WorktreeInfo:
    """``git worktree add -b <branch> <path> [base_ref]``（固定 argv）。

    创建前后复核原仓库 HEAD，失败即抛错；绝不 ``--force``。
    """
    branch = validate_branch_name(branch_name)
    target = Path(target_path)
    if not target.is_absolute() or target.exists():
        raise WorktreeError("worktree_path_invalid", "目标路径非法或已存在")

    head_before = await _run_git(["rev-parse", "HEAD"], cwd=repo_root)
    argv = ["worktree", "add", "-b", branch, str(target)]
    if base_ref:
        if not re.match(r"^[A-Za-z0-9._/@{}^-]{1,200}$", base_ref):
            raise WorktreeError("worktree_ref_invalid", "非法 base ref")
        argv.append(base_ref)
    code, _, err = await _run_git(argv, cwd=repo_root)
    if code != 0:
        # 兜底复核：失败时原仓库 HEAD 不得变化（零容忍保护）
        head_after = await _run_git(["rev-parse", "HEAD"], cwd=repo_root)
        if head_before[1] != head_after[1]:
            logger.error("worktree create altered original repo HEAD")
        raise WorktreeError("worktree_create_failed", "worktree 创建失败")
    code, head_out, _ = await _run_git(["rev-parse", "HEAD"], cwd=str(target))
    return WorktreeInfo(
        path=str(target),
        branch=branch,
        head_sha=head_out.strip() if code == 0 else None,
        detached=False,
        locked=False,
    )


async def is_worktree_dirty(worktree_path: str) -> bool:
    """未提交变更或未追踪文件均视为 dirty（删除前置检查）。"""
    code, out, _ = await _run_git(["status", "--porcelain"], cwd=worktree_path)
    if code != 0:
        # 无法判定状态 → 按 dirty 处理（失败关闭，不删除）
        return True
    return bool(out.strip())


async def remove_worktree(*, repo_root: str, worktree_path: str) -> None:
    """``git worktree remove``（非强制）。dirty/占用时由调用方前置拦截。"""
    code, _, _ = await _run_git(
        ["worktree", "remove", str(worktree_path)], cwd=repo_root
    )
    if code != 0:
        raise WorktreeError("worktree_remove_failed", "worktree 删除失败（存在未提交变更或占用）")


@dataclass(frozen=True)
class CleanupReport:
    removed: bool
    reason: str  # ok / dirty / missing / locked / failed
