"""v0.6.0 C2: Git 只读快照单元测试（C0-D06）。"""
from __future__ import annotations

import subprocess
import sys

import pytest

from personal_assistant.core.git_snapshot import read_git_snapshot


def _run_git(repo: str, *args: str) -> None:
    subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
    )


def test_non_git_directory_returns_none(tmp_path):
    """非 git 目录返回 None，不阻断 run 创建。"""
    import asyncio
    import subprocess

    target = tmp_path / "plain"
    target.mkdir()
    probe = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
    )
    if probe.returncode == 0:
        pytest.skip("临时目录位于 git 仓库内，无法构造非 git 目录")
    snapshot = asyncio.run(read_git_snapshot(str(target)))
    assert snapshot is None


@pytest.mark.skipif(
    sys.platform == "win32" and subprocess.run(
        ["git", "--version"], capture_output=True
    ).returncode != 0,
    reason="git 不可用",
)
def test_git_snapshot_reads_head_branch_dirty(tmp_path):
    """git 目录读取 HEAD/branch/dirty 只读快照，不修改工作区。"""
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(str(repo), "init", "-q")
    _run_git(str(repo), "config", "user.email", "test@example.com")
    _run_git(str(repo), "config", "user.name", "test")
    (repo / "a.txt").write_text("hello", encoding="utf-8")
    _run_git(str(repo), "add", "a.txt")
    _run_git(str(repo), "commit", "-qm", "init")

    snapshot = asyncio.run(read_git_snapshot(str(repo)))
    assert snapshot is not None
    assert len(snapshot.head_sha) == 40
    assert snapshot.branch is not None
    assert snapshot.dirty is False

    # 未提交改动 → dirty=True
    (repo / "a.txt").write_text("hello2", encoding="utf-8")
    snapshot2 = asyncio.run(read_git_snapshot(str(repo)))
    assert snapshot2 is not None
    assert snapshot2.head_sha == snapshot.head_sha
    assert snapshot2.dirty is True
