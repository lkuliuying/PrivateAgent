"""本机项目与会话管理使用临时数据库，不访问真实项目或模型。"""
import asyncio
import sqlite3

import pytest
import pytest_asyncio
from test_local_executor import close, setup

from private_agent_local.store import Store


@pytest_asyncio.fixture
async def local(tmp_path):
    fixture = await setup(tmp_path)
    try:
        yield fixture
    finally:
        await close(fixture[0], fixture[1])


@pytest.mark.asyncio
async def test_project_rename_pin_persistence_and_existing_routes(local, tmp_path):
    app, client, server, root, body = local
    project_id = body["project_id"]
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = (await client.post("/projects", json={"name": "另一个项目", "root_path": str(other_root)})).json()
    renamed = await client.patch(f"/projects/{project_id}", json={"name": "  修改后的名称  "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "修改后的名称"
    assert renamed.json()["root_path"] == str(root.resolve())
    pinned = await client.post(f"/projects/{project_id}/pin")
    assert pinned.status_code == 200 and pinned.json()["pinned_at"]
    assert (await client.post(f"/projects/{project_id}/pin")).json() == pinned.json()
    assert [item["id"] for item in (await client.get("/projects")).json()] == [project_id, other["id"]]
    assert (await client.post(f"/projects/{project_id}/instruction-trust", json={"trusted": True})).status_code == 200
    assert (await client.post(f"/projects/{project_id}/authorize-scope")).status_code == 200
    store_path = app.state.desktop.runtime.store.path
    await app.state.desktop.clear()
    reopened = Store(store_path)
    try:
        project = reopened.get("project", project_id)
        assert project["pinned_at"] == pinned.json()["pinned_at"]
        assert project["name"] == "修改后的名称"
    finally:
        reopened.db.close()
    await app.state.desktop.activate("account-a", app.state.desktop.cloud.origin, 1)
    assert (await client.post(f"/projects/{project_id}/unpin")).json()["pinned_at"] is None
    assert [item["id"] for item in (await client.get("/projects")).json()] == [other["id"], project_id]
    assert server.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"name": "  "}, {"name": None}, {"name": "x" * 256}, {"name": "名称", "root_path": "/changed"}])
async def test_project_edit_validates_name_and_does_not_change_scope(local, payload):
    app, client, _, _, body = local
    store = app.state.desktop.runtime.store
    original = store.get("project", body["project_id"])
    result = await client.patch(f"/projects/{body['project_id']}", json=payload)
    assert result.status_code == 422
    assert store.get("project", body["project_id"]) == original


def seed_completed_run(owner, body):
    created = owner.create({**body, "permission_mode": "readonly"}, launch=False)
    store = owner.store
    run = store.run(created["id"])
    run["status"] = "completed"
    store.save_run(run)
    run_id, session_id = run["id"], body["session_id"]
    store.context.import_legacy(session_id)
    store.context.begin(session_id, "test-checkpoint")
    store.grant(session_id, body["project_id"], "2099-01-01T00:00:00+00:00")
    with store.transaction():
        store.db.execute("INSERT INTO managed_executions VALUES (?,?,?,?,?,?)", ("execution", run_id, session_id, body["workspace_id"], "completed", "{}"))
        store.db.execute("INSERT INTO execution_chunks VALUES (?,?,?,?,?,?)", ("execution", 1, "stdout", "test", 4, 1))
        store.db.execute("INSERT INTO file_snapshots VALUES (?,?,?,?,?)", ("snapshot", run_id, "main.py", "digest", "{}"))
        store.db.execute("INSERT INTO patch_sets VALUES (?,?,?,?,?)", ("patch", run_id, "operation", "applied", "{}"))
        store.db.execute("INSERT INTO patch_journal VALUES (?,?,?)", ("patch", 1, "{}"))
        store.db.execute("INSERT INTO run_checkpoints VALUES (?,?,?,?,?)", ("checkpoint", run_id, 1, "digest", "{}"))
        store.db.execute("INSERT INTO run_control_requests VALUES (?,?,?,?,?)", (run_id, "request", "pause", "fingerprint", "{}"))
        store.db.execute("INSERT INTO workspace_leases VALUES (?,?,?,?,?,?)", ("workspace", run_id, "owner", 1, "released", "now"))
    return run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["project", "session"])
async def test_delete_cascades_atomically_preserves_files_and_other_project(local, tmp_path, kind):
    app, client, _, root, body = local
    owner = app.state.desktop.runtime
    retained = root / "keep.txt"
    retained.write_text("保留项目文件", encoding="utf-8")
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = (await client.post("/projects", json={"name": "保留项目", "root_path": str(other_root)})).json()
    other_workspace = (await client.get(f"/projects/{other['id']}/workspaces")).json()[0]
    other_session = (await client.post("/sessions", json={"project_id": other["id"], "workspace_id": other_workspace["id"]})).json()
    seed_completed_run(owner, body)
    await owner.activate_project(body["project_id"])
    target = f"/{kind}s/{body[kind + '_id']}"
    result = await client.delete(target)
    assert result.status_code == 200 and result.json() == {"deleted": True}
    assert (await client.delete(target)).status_code == 404
    assert (await client.get(f"/sessions/{body['session_id']}/messages")).status_code == 404
    assert [item["id"] for item in (await client.get("/sessions")).json()] == [other_session["id"]]
    assert retained.read_text(encoding="utf-8") == "保留项目文件"
    store = owner.store
    for table in ("runs", "events", "approvals", "executions", "context_items", "context_checkpoints", "messages", "grants",
                  "managed_executions", "execution_chunks", "file_snapshots", "patch_sets", "patch_journal", "run_checkpoints",
                  "run_control_requests", "workspace_leases"):
        assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert store.get("project", other["id"])["name"] == "保留项目"
    if kind == "project":
        assert owner.active_project_id is None
        assert (await client.get(f"/projects/{body['project_id']}/workspaces")).status_code == 404
        recreated = (await client.post("/projects", json={"name": "重新添加", "root_path": str(root)})).json()
        assert recreated["id"] != body["project_id"]
    else:
        assert store.get("project", body["project_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["created", "queued", "running", "waiting_approval", "paused"])
async def test_delete_rejects_active_run_without_partial_changes(local, status):
    app, client, _, _, body = local
    owner = app.state.desktop.runtime
    run_id = seed_completed_run(owner, body)
    run = owner.store.run(run_id)
    run["status"] = status
    owner.store.save_run(run)
    for kind in ("session", "project"):
        result = await client.delete(f"/{kind}s/{body[kind + '_id']}")
        assert result.status_code == 409 and result.json()["error_code"] == "record_in_use"
        assert owner.store.get(kind, body[kind + "_id"])
    run["status"] = "completed"
    owner.store.save_run(run)


@pytest.mark.asyncio
async def test_delete_rejects_background_process_and_pending_task_cleanup(local):
    app, client, _, _, body = local
    owner = app.state.desktop.runtime
    run_id = seed_completed_run(owner, body)
    with owner.store.transaction():
        owner.store.db.execute("UPDATE managed_executions SET status='running'")
    assert (await client.delete(f"/sessions/{body['session_id']}")).status_code == 409
    with owner.store.transaction():
        owner.store.db.execute("UPDATE managed_executions SET status='completed'")
    pending = asyncio.create_task(asyncio.Event().wait())
    owner.tasks[run_id] = pending
    try:
        assert (await client.delete(f"/projects/{body['project_id']}")).status_code == 409
    finally:
        owner.tasks.pop(run_id)
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    owner.execution_sessions.slots["cleanup"] = {"record": {**body}}
    try:
        assert (await client.delete(f"/sessions/{body['session_id']}")).status_code == 409
    finally:
        owner.execution_sessions.slots.clear()


@pytest.mark.asyncio
async def test_delete_rolls_back_all_children_on_database_failure(local):
    app, _, _, _, body = local
    owner = app.state.desktop.runtime
    seed_completed_run(owner, body)
    store = owner.store
    before = "\n".join(store.db.iterdump())
    store.db.execute("CREATE TEMP TRIGGER reject_delete BEFORE DELETE ON projects BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        store.delete_project(body["project_id"])
    assert "\n".join(store.db.iterdump()) == before
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.asyncio
async def test_archived_sessions_are_hidden_until_explicit_restore(local):
    app, client, _, _, body = local
    owner = app.state.desktop.runtime
    session_id = body["session_id"]
    owner.store.update("session", session_id, archived_at="2026-01-01T00:00:00Z")
    for path in ("/sessions", "/sessions/recent", "/sessions/search?q=test"):
        assert [item["id"] for item in (await client.get(path)).json()] == []
    for action in ("archive", "unarchive"):
        assert (await client.post(f"/sessions/{session_id}/{action}")).status_code == 200
    assert [item["id"] for item in (await client.get("/sessions/recent")).json()] == [session_id]
    assert (await client.post(f"/sessions/{session_id}/pin")).json()["pinned_at"]
    created = owner.create({**body, "permission_mode": "readonly"}, launch=False)
    run = owner.store.run(created["id"])
    owner.execution_sessions._check(run, owner.root(body["project_id"], body["workspace_id"]))
    run["status"] = "completed"
    owner.store.save_run(run)
    assert (await client.delete(f"/sessions/{session_id}")).status_code == 200


@pytest.mark.asyncio
async def test_unknown_records_return_not_found(local):
    _, client, _, _, _ = local
    assert (await client.patch("/projects/999999", json={"name": "项目"})).status_code == 404
    for path in ("/projects/999999/pin", "/projects/999999/unpin"):
        assert (await client.post(path)).status_code == 404
    for path in ("/projects/999999", "/sessions/999999"):
        assert (await client.delete(path)).status_code == 404


@pytest.mark.asyncio
async def test_directory_edit_updates_root_binding_revokes_old_grants_and_keeps_files(local, tmp_path):
    app, client, server, root, body = local
    owner = app.state.desktop.runtime
    store = owner.store
    project_id = body["project_id"]
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    retained = root / "keep.txt"
    retained.write_text("原始文件", encoding="utf-8")
    store.update("project", project_id, trust_instructions=True)
    grant = store.grant(body["session_id"], project_id, "2099-01-01T00:00:00+00:00")
    worktree = store.create("workspace", {"project_id": project_id, "kind": "git_worktree", "root_path": str(root), "status": "active"})
    before = store.get("session", body["session_id"])
    result = await client.patch(f"/projects/{project_id}", json={"name": "新名称", "root_path": str(new_root), "authorize_scope": True})
    assert result.status_code == 200, result.text
    assert result.json()["name"] == "新名称" and result.json()["root_path"] == str(new_root)
    assert result.json()["authorized"] and not result.json()["trust_instructions"]
    assert store.get("session", body["session_id"]) == before
    assert owner.root(project_id, body["workspace_id"]) == new_root
    assert store.get("workspace", worktree["id"]) == worktree
    ensured = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    assert ensured.status_code == 201 and ensured.json()["id"] == body["workspace_id"]
    assert store.active_grant(body["session_id"]) is None
    revoked = store._unpack(store.db.execute("SELECT data FROM grants WHERE id=?", (grant["id"],)).fetchone()[0])
    assert revoked["revoke_reason"] == "project_directory_changed"
    assert retained.read_text(encoding="utf-8") == "原始文件" and list(new_root.iterdir()) == []
    assert (await client.get(f"/projects/{project_id}")).json()["root_path"] == str(new_root)
    assert server.calls == []


@pytest.mark.asyncio
async def test_directory_edit_requires_confirmation_and_rejects_missing_or_duplicate_paths(local, tmp_path):
    app, client, _, _, body = local
    store = app.state.desktop.runtime.store
    original = store.get("project", body["project_id"])
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    target = f"/projects/{body['project_id']}"
    payload = {"name": "修改", "root_path": str(new_root)}
    assert (await client.patch(target, json=payload)).status_code == 403
    assert (await client.patch(target, json={**payload, "root_path": str(tmp_path / "missing"), "authorize_scope": True})).status_code == 422
    assert (await client.post("/projects", json={"name": "占用目录", "root_path": str(new_root)})).status_code == 201
    assert (await client.patch(target, json={**payload, "authorize_scope": True})).status_code == 409
    assert store.get("project", body["project_id"]) == original


@pytest.mark.asyncio
async def test_directory_edit_is_blocked_during_run_and_rolls_back_on_workspace_failure(local, tmp_path):
    app, client, _, root, body = local
    owner = app.state.desktop.runtime
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    run_id = seed_completed_run(owner, body)
    run = owner.store.run(run_id)
    run["status"] = "paused"
    owner.store.save_run(run)
    payload = {"name": "修改", "root_path": str(new_root), "authorize_scope": True}
    assert (await client.patch(f"/projects/{body['project_id']}", json=payload)).status_code == 409
    run["status"] = "completed"
    owner.store.save_run(run)
    before = "\n".join(owner.store.db.iterdump())
    owner.store.db.execute("CREATE TEMP TRIGGER reject_workspace_update BEFORE UPDATE ON workspaces BEGIN SELECT RAISE(ABORT, 'workspace failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="workspace failure"):
        await client.patch(f"/projects/{body['project_id']}", json=payload)
    assert "\n".join(owner.store.db.iterdump()) == before
    assert owner.root(body["project_id"], body["workspace_id"]) == root


@pytest.mark.asyncio
async def test_unresolved_execution_lease_cannot_be_deleted(local):
    app, client, _, _, body = local
    owner = app.state.desktop.runtime
    seed_completed_run(owner, body)
    with owner.store.transaction():
        owner.store.db.execute("UPDATE workspace_leases SET state='reconcile'")
    for kind in ("project", "session"):
        assert (await client.delete(f"/{kind}s/{body[kind + '_id']}")).status_code == 409
