"""v0.6.0 C1: ProjectWorkspace + session 绑定 集成测试。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.config import settings
from personal_assistant.core.history import SessionRepository
from personal_assistant.core.models import Project, ProjectWorkspace
from personal_assistant.core.repo_workspaces import ProjectWorkspaceRepository
from personal_assistant.core.workspaces import ProjectWorkspaceService


class TestWorkspaceEnsureRoot:
    """幂等补建 root workspace。"""

    async def test_create_root_workspace_for_new_project(self, db: AsyncSession):
        """新建 project 时自动创建 root workspace。"""
        project = Project(name="ws-test-1", root_path="/tmp/ws-test-1")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        svc = ProjectWorkspaceService(db)
        ws = await svc.ensure_root_workspace(project)
        assert ws is not None
        assert ws.project_id == project.id
        assert ws.kind == "root"
        assert ws.root_path == "/tmp/ws-test-1"
        assert ws.status == "active"

    async def test_ensure_root_workspace_is_idempotent(self, db: AsyncSession):
        """重复调用 ensure_root_workspace 不创建重复 workspace。"""
        project = Project(name="ws-test-2", root_path="/tmp/ws-test-2")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        svc = ProjectWorkspaceService(db)
        ws1 = await svc.ensure_root_workspace(project)
        ws2 = await svc.ensure_root_workspace(project)
        assert ws1.id == ws2.id

        repo = ProjectWorkspaceRepository(db)
        all_ws = await repo.list_by_project(project.id)
        assert len(all_ws) == 1

    async def test_touch_last_used(self, db: AsyncSession):
        """touch_last_used 更新 last_used_at。"""
        project = Project(name="ws-test-3", root_path="/tmp/ws-test-3")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        svc = ProjectWorkspaceService(db)
        ws = await svc.ensure_root_workspace(project)
        assert ws.last_used_at is None

        await svc.touch_last_used(ws.id)
        await db.refresh(ws)
        assert ws.last_used_at is not None

    async def test_update_status(self, db: AsyncSession):
        """update_status 更新工作区状态。"""
        project = Project(name="ws-test-4", root_path="/tmp/ws-test-4")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        svc = ProjectWorkspaceService(db)
        ws = await svc.ensure_root_workspace(project)
        assert ws.status == "active"

        await svc.update_status(ws.id, "missing")
        await db.refresh(ws)
        assert ws.status == "missing"


class TestSessionBinding:
    """session 绑定 project/workspace。"""

    async def test_create_session_with_project_binding(self, db: AsyncSession):
        """创建带 project 绑定的 session。"""
        project = Project(name="sess-test-1", root_path="/tmp/sess-test-1")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        ws = await ProjectWorkspaceService(db).ensure_root_workspace(project)

        session = await SessionRepository(db).create(
            title="coding-session",
            project_id=project.id,
            workspace_id=ws.id,
            kind="coding",
        )
        assert session.project_id == project.id
        assert session.workspace_id == ws.id
        assert session.kind == "coding"

    async def test_legacy_session_has_no_binding(self, db: AsyncSession):
        """旧 session 不设置绑定字段为 None，kind 默认 legacy。"""
        session = await SessionRepository(db).create(title="legacy")
        assert session.project_id is None
        assert session.workspace_id is None
        assert session.kind == "legacy"

    async def test_list_sessions_by_project(self, db: AsyncSession):
        """按 project 过滤 session 列表。"""
        project = Project(name="sess-test-2", root_path="/tmp/sess-test-2")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        ws = await ProjectWorkspaceService(db).ensure_root_workspace(project)

        await SessionRepository(db).create(
            title="coding-1", project_id=project.id, workspace_id=ws.id, kind="coding"
        )
        await SessionRepository(db).create(
            title="coding-2", project_id=project.id, workspace_id=ws.id, kind="coding"
        )
        await SessionRepository(db).create(title="legacy")

        sessions = await SessionRepository(db).list(project_id=project.id)
        assert len(sessions) == 2
        for s in sessions:
            assert s.project_id == project.id

    async def test_list_sessions_by_kind(self, db: AsyncSession):
        """按 kind 过滤 session 列表。"""
        project = Project(name="sess-test-3", root_path="/tmp/sess-test-3")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        ws = await ProjectWorkspaceService(db).ensure_root_workspace(project)

        await SessionRepository(db).create(
            title="coding", project_id=project.id, workspace_id=ws.id, kind="coding"
        )
        await SessionRepository(db).create(
            title="legacy", project_id=project.id, workspace_id=ws.id, kind=None
        )

        # 只查本项目
        coding_sessions = await SessionRepository(db).list(
            project_id=project.id, kind="coding"
        )
        assert len(coding_sessions) == 1
        assert coding_sessions[0].kind == "coding"


class TestWorkspaceAPI:
    """workspace API 路由测试。"""

    async def test_workspace_api_hidden_when_flag_disabled(self, client):
        """flag 关闭时 workspace API 返回 404。"""
        resp = await client.get("/projects/1/workspaces")
        assert resp.status_code == 404

    async def test_ensure_root_workspace_via_api(self, client, monkeypatch, tmp_path):
        """通过 API 幂等确保 root workspace。"""
        monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

        root = str(tmp_path.resolve())

        # 创建 project
        resp = await client.post(
            "/projects",
            json={"name": "api-ws-test", "root_path": root},
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        # 确保 root workspace
        resp = await client.post(
            f"/projects/{project_id}/workspaces/root/ensure"
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["project_id"] == project_id
        assert data["kind"] == "root"
        assert data["status"] == "active"

        # 再调用一次：幂等
        resp = await client.post(
            f"/projects/{project_id}/workspaces/root/ensure"
        )
        assert resp.status_code == 201
        data2 = resp.json()
        assert data2["id"] == data["id"]

    async def test_list_workspaces(self, client, monkeypatch, tmp_path):
        """列出项目的所有 workspace。"""
        monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

        root = str(tmp_path.resolve())

        resp = await client.post(
            "/projects",
            json={"name": "api-ws-list", "root_path": root},
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        resp = await client.post(
            f"/projects/{project_id}/workspaces/root/ensure"
        )

        resp = await client.get(f"/projects/{project_id}/workspaces")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["kind"] == "root"

    async def test_session_create_with_project(self, client, monkeypatch, tmp_path):
        """创建带 project 绑定的 session。"""
        monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

        root = str(tmp_path.resolve())

        resp = await client.post(
            "/projects",
            json={"name": "api-sess-test", "root_path": root},
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        resp = await client.post(
            f"/projects/{project_id}/workspaces/root/ensure"
        )
        ws_id = resp.json()["id"]

        resp = await client.post(
            "/sessions",
            json={
                "title": "coding-session",
                "project_id": project_id,
                "workspace_id": ws_id,
                "kind": "coding",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["project_id"] == project_id
        assert data["workspace_id"] == ws_id
        assert data["kind"] == "coding"