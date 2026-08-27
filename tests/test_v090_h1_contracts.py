"""v0.9.0 H1 契约测试：升级契约、项目/对话拆分、Asia/Shanghai 时间。

覆盖：
- sessions/messages/workspaces/runs 时间统一带 Z 的 RFC 3339 UTC（H0 §5）；
- legacy/unbound 会话显式绑定（无批量/猜测绑定，H0 §4.2）；
- 「当前用户目录」候选不自动扩大 trusted path（H0 §4.2 第 3 条）；
- 项目创建失败不留半绑定（workspace 补建幂等）。
"""

from __future__ import annotations

from sqlalchemy import select

from personal_assistant.core.compatibility import compatibility_telemetry


async def _enable(monkeypatch) -> None:
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)


async def _make_project_with_workspace(client, name: str, root: str):
    resp = await client.post("/projects", json={"name": name, "root_path": root})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]
    resp = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    assert resp.status_code == 201, resp.text
    return project_id, resp.json()["id"]


# ===========================================================================
# §5 时间序列化：带 Z 的 RFC 3339 UTC
# ===========================================================================


async def test_session_times_serialize_rfc3339_utc(client, monkeypatch):
    """会话/消息时间统一带 Z；客户端可按 Asia/Shanghai 无歧义转换。"""
    await _enable(monkeypatch)
    resp = await client.post("/sessions", json={"title": "v090-time"})
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["id"]
    body = resp.json()
    for key in ("created_at", "updated_at"):
        assert body[key].endswith("Z"), f"{key} 缺少 Z 后缀: {body[key]}"
        assert "+" not in body[key]

    resp = await client.get(f"/sessions/{session_id}")
    assert resp.json()["created_at"].endswith("Z")

    resp = await client.get(f"/sessions/{session_id}/messages")
    assert resp.status_code == 200


async def test_workspace_times_serialize_rfc3339_utc(
    client, monkeypatch, tmp_path
):
    await _enable(monkeypatch)
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "v090-ws", root)
    resp = await client.get(f"/projects/{project_id}/workspaces/{ws_id}")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("created_at", "updated_at"):
        assert body[key].endswith("Z")


# ===========================================================================
# §4.2 legacy/unbound 会话显式绑定
# ===========================================================================


async def test_bind_project_migrates_unbound_session(client, monkeypatch, tmp_path):
    """未绑定会话显式选择项目后才迁移：kind 升为 coding + 审计行。"""
    await _enable(monkeypatch)
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "v090-bind", root)

    resp = await client.post("/sessions", json={"title": "legacy-unbound"})
    assert resp.status_code == 201
    session_id = resp.json()["id"]
    assert resp.json()["kind"] == "legacy"
    assert resp.json()["project_id"] is None

    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        f"/sessions/{session_id}/bind-project",
        json={"project_id": project_id, "workspace_id": ws_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "coding"
    assert body["project_id"] == project_id
    assert body["workspace_id"] == ws_id
    after = compatibility_telemetry.snapshot()
    delta = after["paths"]["legacy_session_bind"]["outcomes"][
        "bound"
    ] - before["paths"]["legacy_session_bind"]["outcomes"]["bound"]
    assert delta == 1

    # 重复绑定拒绝（不静默改绑）
    resp = await client.post(
        f"/sessions/{session_id}/bind-project",
        json={"project_id": project_id, "workspace_id": ws_id},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "session_bind_conflict"


async def test_bind_project_rejects_workspace_mismatch(client, monkeypatch, tmp_path):
    """workspace 不属于请求项目 → 403（与创建链同语义）。"""
    await _enable(monkeypatch)
    root_a = str((tmp_path / "a").resolve())
    root_b = str((tmp_path / "b").resolve())
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    project_a, _ = await _make_project_with_workspace(client, "v090-a", root_a)
    _project_b, ws_b = await _make_project_with_workspace(client, "v090-b", root_b)

    resp = await client.post("/sessions", json={"title": "unbound"})
    session_id = resp.json()["id"]
    resp = await client.post(
        f"/sessions/{session_id}/bind-project",
        json={"project_id": project_a, "workspace_id": ws_b},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "workspace_outside_trust"


async def test_bind_project_flag_disabled(client):
    """flag 关闭时绑定入口失败关闭。"""
    resp = await client.post("/sessions", json={"title": "legacy"})
    session_id = resp.json()["id"]
    resp = await client.post(
        f"/sessions/{session_id}/bind-project",
        json={"project_id": 1, "workspace_id": 1},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"


async def test_no_batch_binding_endpoint_exists():
    """契约红线：不存在批量绑定端点（防猜测绑定回归）。"""
    from personal_assistant.main_api import app

    paths = set(app.openapi()["paths"])
    assert not any("bind-all" in p or "bulk" in p for p in paths)
    assert "/sessions/{session_id}/bind-project" in paths


# ===========================================================================
# §4.2 「当前用户目录」候选：不自动扩大授权
# ===========================================================================


async def _cleanup_home_state(session) -> None:
    """清理上一轮残留：home 项目/工作区与 trusted path（保证用例可重入）。"""
    from pathlib import Path

    from sqlalchemy import delete

    from personal_assistant.core.models import (
        Project,
        ProjectWorkspace,
        TrustedPath,
    )

    home = str(Path.home().resolve())
    result = await session.execute(
        select(Project.id).where(Project.root_path == home)
    )
    ids = [row[0] for row in result.all()]
    if ids:
        await session.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.project_id.in_(ids))
        )
        await session.execute(delete(Project).where(Project.id.in_(ids)))
    await session.execute(delete(TrustedPath).where(TrustedPath.path == home))
    await session.commit()


async def test_user_home_candidate_does_not_auto_trust(
    client, monkeypatch, fresh_session
):
    """候选创建不写 trusted_paths；显式 authorize-scope 后才建立信任。"""
    from pathlib import Path

    from personal_assistant.core.repo_tools import TrustedPathRepository

    await _enable(monkeypatch)
    await _cleanup_home_state(fresh_session)
    home = str(Path.home().resolve())

    resp = await client.get("/projects/user-home-candidate")
    assert resp.status_code == 200
    assert resp.json()["available"] is True

    resp = await client.post("/projects/user-home")
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["exists"] is True
    assert body["authorized"] is False, "候选创建不得自动授权用户目录"
    assert body["project_id"] is not None
    assert body["workspace_id"] is not None
    # 响应不泄露绝对路径（脱敏契约）
    assert home not in resp.text

    # 幂等：再次创建返回同一项目
    resp = await client.post("/projects/user-home")
    assert resp.json()["project_id"] == body["project_id"]
    assert resp.json()["created"] is False

    # trusted_paths 确实没有 home（跨 session 读，避免事务快照干扰）
    trusted = await TrustedPathRepository(fresh_session).get_by_path(home)
    assert trusted is None

    # 显式确认后才授权
    project_id = body["project_id"]
    resp = await client.post(f"/projects/{project_id}/authorize-scope")
    assert resp.status_code == 200, resp.text
    resp = await client.get("/projects/user-home-candidate")
    assert resp.json()["authorized"] is True

    # 收尾清理，避免污染后续轮次/真实开发库观察
    await _cleanup_home_state(fresh_session)


async def test_user_home_candidate_flag_disabled(client):
    """flag 关闭时候选不可用（不创建）。"""
    resp = await client.get("/projects/user-home-candidate")
    assert resp.json()["available"] is False
    resp = await client.post("/projects/user-home")
    assert resp.status_code == 409


# ===========================================================================
# 升级契约：旧项目幂等补建 root workspace
# ===========================================================================


async def test_upgrade_reconcile_ensures_root_workspaces(db, monkeypatch):
    """v0.9.0 启动 reconcile：无 workspace 的旧项目补建（幂等）。"""
    from personal_assistant.config import settings
    from personal_assistant.core.models import Project
    from personal_assistant.core.repo_workspaces import ProjectWorkspaceRepository
    from personal_assistant.core.v090_upgrade import (
        ensure_root_workspaces_for_projects,
    )

    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    project = Project(name="v090-upgrade", root_path="C:/v090-upgrade-probe")
    db.add(project)
    await db.commit()
    await db.refresh(project)

    repo = ProjectWorkspaceRepository(db)
    assert await repo.list_by_project(project.id) == []

    count = await ensure_root_workspaces_for_projects(db)
    assert count >= 1
    workspaces = await repo.list_by_project(project.id)
    assert len(workspaces) == 1
    assert workspaces[0].kind == "root"

    # 幂等：再次运行不新增
    before = len(await repo.list_by_project(project.id))
    await ensure_root_workspaces_for_projects(db)
    assert len(await repo.list_by_project(project.id)) == before

    # 清理
    from sqlalchemy import delete

    from personal_assistant.core.models import ProjectWorkspace

    await db.execute(
        delete(ProjectWorkspace).where(ProjectWorkspace.project_id == project.id)
    )
    await db.execute(delete(Project).where(Project.id == project.id))
    await db.commit()
