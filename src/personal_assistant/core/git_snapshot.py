"""v0.6.0 C2: run 创建时的只读 Git 快照（C0-D06）。

C0-D06：Git HEAD/branch/dirty 是 run 创建时只读快照，不自动 checkout、
建分支或清理工作区。非 git 目录返回 ``None`` 快照；git 读取失败抛
``GitSnapshotError``（路由映射为 ``git_snapshot_failed`` 409）。

错误消息不得包含本地绝对路径（C0 §9）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

GIT_TIMEOUT_SECONDS = 8.0


class GitSnapshotError(RuntimeError):
    """无法获得要求的 Git 快照（git 命令失败或超时）。"""


@dataclass(frozen=True)
class GitSnapshot:
    """run 创建时刻的 Git 只读快照。"""

    head_sha: str | None
    branch: str | None
    dirty: bool


async def _run_git(root_path: str, args: list[str]) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            root_path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise GitSnapshotError("git 不可用") from None
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(), timeout=GIT_TIMEOUT_SECONDS
        )
    except TimeoutError:
        proc.kill()
        raise GitSnapshotError("git 快照读取超时") from None
    return proc.returncode or 0, (out + err).decode("utf-8", errors="replace")


async def read_git_snapshot(root_path: str) -> GitSnapshot | None:
    """读取工作区 Git 快照；非 git 目录返回 None。只读，不修改工作区。"""
    rc, _ = await _run_git(root_path, ["rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        return None

    rc, out = await _run_git(root_path, ["rev-parse", "HEAD"])
    if rc != 0:
        raise GitSnapshotError("无法读取 git HEAD")
    head_sha = out.strip().splitlines()[0] if out.strip() else None

    branch: str | None = None
    rc, out = await _run_git(root_path, ["symbolic-ref", "--short", "HEAD"])
    if rc == 0 and out.strip():
        branch = out.strip().splitlines()[0]

    rc, out = await _run_git(root_path, ["status", "--porcelain"])
    if rc != 0:
        raise GitSnapshotError("无法读取 git 工作区状态")
    dirty = bool(out.strip())

    return GitSnapshot(head_sha=head_sha, branch=branch, dirty=dirty)
