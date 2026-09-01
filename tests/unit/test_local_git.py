"""验证本机项目分支发现与目录内安全切换。"""
from __future__ import annotations

import shutil
import subprocess

import pytest
from test_local_executor import close, setup


def git(root, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.strip()


def initialize_repository(root) -> None:
    if shutil.which("git") is None:
        pytest.skip("本机未安装 Git")
    try:
        git(root, "init", "-b", "main")
    except subprocess.CalledProcessError:
        pytest.skip("本机 Git 不支持测试所需的 init -b")
    git(root, "config", "user.name", "PrivateAgent Test")
    git(root, "config", "user.email", "privateagent-test@example.invalid")
    (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "initial")
    git(root, "branch", "dev")
    git(root, "switch", "dev")


@pytest.mark.asyncio
async def test_project_lists_and_switches_only_local_root_branches(tmp_path):
    app, client, _, root, body = await setup(tmp_path)
    try:
        initialize_repository(root)
        response = await client.get(f"/projects/{body['project_id']}/git/branches")
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["is_git"] and state["current_branch"] == "dev"
        assert [branch["name"] for branch in state["branches"]] == ["dev", "main"]
        assert next(branch for branch in state["branches"] if branch["name"] == "dev")["current"]

        switched = await client.post(
            f"/projects/{body['project_id']}/git/branches/select",
            json={"branch_name": "main"},
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["current_branch"] == "main"
        assert git(root, "branch", "--show-current") == "main"
        workspace = (await client.get(f"/projects/{body['project_id']}/workspaces")).json()[0]
        assert workspace["branch_name"] == "main"
        assert workspace["head_sha"] == git(root, "rev-parse", "HEAD")
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_branch_switch_refuses_dirty_project_and_keeps_user_work(tmp_path):
    app, client, _, root, body = await setup(tmp_path)
    try:
        initialize_repository(root)
        (root / "tracked.txt").write_text("user change\n", encoding="utf-8")
        response = await client.post(
            f"/projects/{body['project_id']}/git/branches/select",
            json={"branch_name": "main"},
        )
        assert response.status_code == 422
        assert "未提交改动" in response.text
        assert git(root, "branch", "--show-current") == "dev"
        assert (root / "tracked.txt").read_text(encoding="utf-8") == "user change\n"
        workspace = (await client.get(f"/projects/{body['project_id']}/workspaces")).json()[0]
        assert workspace["status"] == "dirty"
    finally:
        await close(app, client)
