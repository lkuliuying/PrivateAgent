"""作用域模型引用、继承与禁用边界，不调用真实模型。"""
import pytest
from test_direct_models import configuration, configure, desktop

from private_agent_local.model_catalog import ProviderInput
from private_agent_local.model_preferences import (
    ModelRestoreConfirmationRequired,
    resolve,
)


@pytest.mark.asyncio
async def test_scopes_inherit_persist_and_reject_provider_overrides(tmp_path):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        first = await configure(client)
        models.catalog.upsert("second", ProviderInput.model_validate(configuration()))
        second = next(item["id"] for item in models.catalog.profiles() if item["provider_id"] == "second")
        root = tmp_path / "project"
        root.mkdir()
        project = (await client.post("/projects", json={"name": "项目", "root_path": str(root)})).json()
        workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
        session = (await client.post("/sessions", json={"project_id": project["id"], "workspace_id": workspace["id"], "title": "会话", "kind": "coding"})).json()
        binding = {"project_id": project["id"], "session_id": session["id"]}
        assert (await client.get("/model-preferences", params=binding)).json()["source"] == "global"
        value = {**binding, "scope": "project", "profile_id": second}
        assert (await client.put("/model-preferences", json=value)).json()["source"] == "project"
        value.update(scope="session", profile_id=first)
        assert (await client.put("/model-preferences", json=value)).json()["profile_id"] == first
        value["profile_id"] = None
        inherited = (await client.put("/model-preferences", json=value)).json()
        assert (inherited["source"], inherited["profile_id"]) == ("project", second)
        invalid = await client.put("/model-preferences", json={**value, "base_url": "https://other.example.test"})
        assert invalid.status_code == 422
        invalid = await client.get("/model-preferences", params={**binding, "project_id": 9999})
        assert invalid.status_code >= 400
        models.catalog.delete("second")
        unavailable = (await client.get("/model-preferences", params=binding)).json()
        assert unavailable["profile_id"] == second and unavailable["available"] is False
        result = await client.post("/agent-runs", json={**binding, "workspace_id": workspace["id"], "message": "不能静默回退"})
        assert result.status_code == 409
        assert calls == []


async def bound_session(client, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = (await client.post("/projects", json={"name": "恢复确认", "root_path": str(root)})).json()
    workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
    session = (await client.post("/sessions", json={"project_id": project["id"], "workspace_id": workspace["id"], "kind": "coding", "title": "恢复会话"})).json()
    return {"project_id": project["id"], "workspace_id": workspace["id"], "session_id": session["id"]}


def pending_source(identifier):
    return {"profile_id": identifier, "source_scope": "project", "reason": "服务地址不同，需确认模型",
            "source_identity": {"provider_id": "provider", "protocol": "openai", "api_format": "chat_completions",
                                "base_url": "https://old.example.test/v1", "model_id": "fixture-model"}}


@pytest.mark.asyncio
async def test_pending_model_precedence_and_explicit_scope_confirmation(tmp_path):
    async with desktop(tmp_path) as (models, app, client, _, calls):
        identifier = await configure(client)
        binding = await bound_session(client, tmp_path)
        store = app.state.desktop.runtime.store
        pending = pending_source(identifier)
        store.update("project", binding["project_id"], model_profile_id=None, model_restore_pending=pending)
        params = {key: binding[key] for key in ("project_id", "session_id")}
        restored = (await client.get("/model-preferences", params=params)).json()
        assert restored["source"] == "project" and restored["profile_id"] is None
        assert restored["requires_confirmation"] is True and restored["available"] is False
        assert restored["restore_source"]["source_identity"] == pending["source_identity"]

        changed = await client.put("/model-preferences", json={**params, "scope": "global", "profile_id": identifier})
        assert changed.json()["requires_confirmation"] is True
        invalid = await client.put("/model-preferences", json={**params, "scope": "project", "profile_id": "missing"})
        assert invalid.status_code == 409
        assert store.get("project", binding["project_id"])["model_restore_pending"] == pending

        chosen = await client.put("/model-preferences", json={**params, "scope": "session", "profile_id": identifier})
        assert chosen.json()["source"] == "session" and chosen.json()["available"] is True
        assert chosen.json()["requires_confirmation"] is False
        assert store.get("project", binding["project_id"])["model_restore_pending"] == pending
        inherited = await client.put("/model-preferences", json={**params, "scope": "session", "profile_id": None})
        assert inherited.json()["requires_confirmation"] is True

        store.update("session", binding["session_id"], model_restore_pending=pending)
        chosen = await client.put("/model-preferences", json={**params, "scope": "project", "profile_id": identifier})
        assert chosen.json()["source"] == "session" and chosen.json()["requires_confirmation"] is True
        inherited = await client.put("/model-preferences", json={**params, "scope": "session", "profile_id": None})
        assert inherited.json()["available"] is True and inherited.json()["requires_confirmation"] is False
        assert calls == []


@pytest.mark.asyncio
async def test_pending_model_blocks_explicit_api_and_internal_creation(tmp_path):
    async with desktop(tmp_path) as (_, app, client, _, calls):
        identifier = await configure(client)
        binding = await bound_session(client, tmp_path)
        runtime = app.state.desktop.runtime
        runtime.store.update("project", binding["project_id"], model_restore_pending=pending_source(identifier))
        body = {**binding, "message": "不允许切换到错误的服务", "permission_mode": "readonly"}
        for fields in ({}, {"model_profile_id": identifier}):
            response = await client.post("/agent-runs", json={**body, **fields})
            assert response.status_code == 409
            assert response.json()["error_code"] == "model_restore_confirmation_required"
        with pytest.raises(ModelRestoreConfirmationRequired):
            runtime.create({**body, "model_profile_id": identifier}, launch=False)
        assert runtime.store.runs() == []
        assert runtime.store.list("message", session_id=binding["session_id"]) == []
        assert calls == []


@pytest.mark.asyncio
async def test_pending_model_preserves_idempotent_receipt_but_blocks_queued_turn(tmp_path):
    async with desktop(tmp_path) as (_, app, client, _, calls):
        identifier = await configure(client)
        binding = await bound_session(client, tmp_path)
        runtime = app.state.desktop.runtime
        body = {**binding, "message": "已存在请求", "client_request_id": "existing-request", "model_profile_id": identifier,
                "permission_mode": "readonly", "recovery_contract_version": "1.0"}
        created = runtime.create(body, launch=False)
        runtime.turn_queue.enqueue(binding["session_id"], created["id"], "queued-confirmation", "等待确认后再发送")
        run = runtime.store.run(created["id"])
        run.update(status="completed", active_in_process=False)
        runtime.store.save_run(run)
        runtime.store.update("project", binding["project_id"], model_restore_pending=pending_source(identifier))

        assert runtime.create(body, launch=False)["id"] == created["id"]
        response = await client.post("/agent-runs", json=body)
        assert response.status_code == 201 and response.json()["id"] == created["id"]
        runtime.turn_queue.advance(binding["session_id"], created["id"])
        item = runtime.turn_queue.get(binding["session_id"])
        assert item["state"] == "blocked" and item["message"] == "等待确认后再发送"
        assert len(runtime.store.runs()) == 1 and not runtime.tasks
        assert calls == []


def test_pending_model_survives_database_reopen(tmp_path):
    from test_local_attachments import fixture_store

    from private_agent_local.store import Store

    store, project, _, session = fixture_store(tmp_path)
    pending = pending_source("source-profile")
    store.update("project", project, model_profile_id=None, model_restore_pending=pending)
    path = store.path
    store.db.close()
    restored = Store(path)
    try:
        result = resolve(restored, [{"id": "source-profile", "is_default": True, "enabled": True}], project, session["id"])
        assert result["profile_id"] is None and result["available"] is False
        assert result["requires_confirmation"] is True
        assert result["restore_source"]["source_identity"] == pending["source_identity"]
    finally:
        restored.db.close()
