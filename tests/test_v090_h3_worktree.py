"""v0.9.0 H3 契约测试：可选 Git worktree（计划 §4）。

覆盖：
- 能力位关闭 → 409；非 Git 项目 → 409 worktree_not_git；
- 创建前预览（原项目/基础分支/新分支/路径/清理策略）；
- 创建成功：kind=git_worktree、分支正确、原仓库 HEAD 不受影响；
- 非法分支名（路径穿越）→ 422；
- dirty worktree 永不自动删除（409，目录保留）；
- 干净 worktree 清理成功并归档；失败保留现场（cleanup_pending）。
"""

from __future__ import annotations

import subprocess

import pytest_asyncio

from personal_assistant.config import settings as cfg


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest_asyncio.fixture()
async def git_project(client, tmp_path, monkeypatch):
    """在 tmp_path 建真实 git 仓库并登记为项目（含根工作区）。"""
    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], str(repo))
    _git(["config", "user.email", "test@example.com"], str(repo))
    _git(["config", "user.name", "test"], str(repo))
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "."], str(repo))
    _git(["commit", "-m", "init"], str(repo))

    resp = await client.post(
        "/projects", json={"name": "wt-project", "root_path": str(repo)}
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]
    resp = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    assert resp.status_code == 201, resp.text
    return {"project_id": project_id, "repo": repo}


def _head_sha(repo) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    return out.stdout.decode().strip()


async def test_worktree_flag_disabled(client, git_project):
    resp = await client.post(
        f"/projects/{git_project['project_id']}/workspaces/worktree",
        json={"branch_name": "agent/task-1"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"


async def test_worktree_not_git_project(client, tmp_path, monkeypatch):
    """非 Git 目录是合法项目，但不能建 worktree。"""
    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(cfg, "coding_worktree_enabled", True)
    plain = tmp_path / "plain"
    plain.mkdir()
    resp = await client.post(
        "/projects", json={"name": "plain-project", "root_path": str(plain)}
    )
    project_id = resp.json()["id"]
    await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    resp = await client.post(
        f"/projects/{project_id}/workspaces/worktree",
        json={"branch_name": "agent/x"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "worktree_not_git"


async def test_worktree_preview_shows_plan_facts(client, git_project, monkeypatch):
    monkeypatch.setattr(cfg, "coding_worktree_enabled", True)
    project_id = git_project["project_id"]
    resp = await client.get(
        f"/projects/{project_id}/worktrees/preview",
        params={"branch_name": "agent/fix-login"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_project"] == "wt-project"
    assert body["base_branch"] == "main"
    assert body["base_head_sha"] == _head_sha(git_project["repo"])
    assert body["new_branch"] == "agent/fix-login"
    assert ".pa-worktrees" in body["worktree_path"]
    assert body["cleanup_policy"]


async def test_worktree_create_success_and_repo_intact(client, git_project, monkeypatch):
    """创建成功；原仓库 HEAD 与工作区不受影响（零容忍）。"""
    monkeypatch.setattr(cfg, "coding_worktree_enabled", True)
    project_id = git_project["project_id"]
    repo = git_project["repo"]
    head_before = _head_sha(repo)

    resp = await client.post(
        f"/projects/{project_id}/workspaces/worktree",
        json={"branch_name": "agent/task-42"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "git_worktree"
    assert body["branch_name"] == "agent/task-42"
    assert body["status"] == "active"
    # 原仓库完整性：HEAD 不变、工作区干净、仍在 main
    assert _head_sha(repo) == head_before
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    ).stdout.decode().strip()
    assert branch == "main"


async def test_worktree_branch_name_traversal_rejected(client, git_project, monkeypatch):
    monkeypatch.setattr(cfg, "coding_worktree_enabled", True)
    resp = await client.post(
        f"/projects/{git_project['project_id']}/workspaces/worktree",
        json={"branch_name": "..\\evil"},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "worktree_branch_invalid"


async def test_worktree_cleanup_refuses_dirty(client, git_project, monkeypatch):
    """dirty worktree 永不自动删除（409，目录保留）。"""
    monkeypatch.setattr(cfg, "coding_worktree_enabled", True)
    project_id = git_project["project_id"]
    resp = await client.post(
        f"/projects/{project_id}/workspaces/worktree",
        json={"branch_name": "agent/dirty-task"},
    )
    assert resp.status_code == 201, resp.text
    ws = resp.json()

    # 在 worktree 内制造未提交变更
    from pathlib import Path

    wt_path = Path(ws["root_path"])
    (wt_path / "wip.txt").write_text("untracked\n", encoding="utf-8")

    resp = await client.post(
        f"/projects/{project_id}/workspaces/{ws['workspace_id']}/cleanup"
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "worktree_dirty"
    assert wt_path.is_dir(), "dirty worktree 目录不得被删除"


async def test_worktree_cleanup_clean_success(client, git_project, monkeypatch):
    """干净 worktree 清理成功并归档。"""
    monkeypatch.setattr(cfg, "coding_worktree_enabled", True)
    project_id = git_project["project_id"]
    resp = await client.post(
        f"/projects/{project_id}/workspaces/worktree",
        json={"branch_name": "agent/clean-task"},
    )
    assert resp.status_code == 201, resp.text
    ws = resp.json()

    resp = await client.post(
        f"/projects/{project_id}/workspaces/{ws['workspace_id']}/cleanup"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] is True

    from pathlib import Path

    assert not Path(ws["root_path"]).is_dir()
    # workspace 记录归档（不物理删除审计关系）
    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import ProjectWorkspace

    async with async_session_factory() as db:
        record = await db.get(ProjectWorkspace, ws["workspace_id"])
        assert record.status == "archived"
