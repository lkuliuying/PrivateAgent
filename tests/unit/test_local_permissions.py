"""验证权限授予、审批审计与撤销后的执行边界。"""
from datetime import datetime, timedelta, timezone

import pytest
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_local import policy


@pytest.mark.asyncio
async def test_inactive_workspace_cannot_start_a_run(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        app.state.desktop.runtime.store.update("workspace", body["workspace_id"], status="archived")
        result = await client.post("/agent-runs", json=body)
        assert result.status_code == 422
        assert not app.state.desktop.runtime.store.runs()
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_workspace_auto_writes_and_audits_but_project_scripts_still_wait(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        server.responses = [response(call("write_project_file", {"rel_path": "safe.txt", "content": "自动批准"})),
                            response(call("run_project_command", {"command": "npm test"})), response(text="停止")]
        created = (await client.post("/agent-runs", json={**body, "permission_mode": "workspace"})).json()
        await until(client, created["id"], {"waiting_approval"})
        assert (root / "safe.txt").read_text(encoding="utf-8") == "自动批准"
        events = (await client.get(f"/agent-runs/{created['id']}/events")).json()["items"]
        approved = next(e for e in events if e["type"] == "tool.auto_approved")
        assert approved["payload"]["policy_profile"] == "project-write"
        assert len(approved["payload"]["arguments_sha256"]) == 64
        assert approved["payload"]["preview"]["new_sha256"]
        approvals = (await client.get(f"/agent-runs/{created['id']}/approvals")).json()
        assert len(approvals) == 1 and approvals[0]["tool_name"] == "run_project_command"
        await client.post(f"/agent-runs/{created['id']}/approvals/{approvals[0]['id']}/reject")
        await until(client, created["id"], TERMINAL)
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_full_access_is_distinct_requires_grant_and_can_write_regular_absolute_file(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        request = {**body, "permission_mode": "full_access"}
        assert (await client.post("/agent-runs", json=request)).status_code == 422
        endpoint = f"/sessions/{body['session_id']}/full-access-grant"
        grant = (await client.post(endpoint, json={})).json()
        assert grant["active"] and grant["project_id"] == body["project_id"]
        assert (await client.post(endpoint, json={})).json()["grant_id"] == grant["grant_id"]
        target = tmp_path / "outside-project.txt"
        server.responses = [response(call("write_project_file", {"rel_path": str(target), "content": "授权范围内"})), response(text="完成")]
        created = (await client.post("/agent-runs", json=request)).json()
        final = await until(client, created["id"], TERMINAL)
        assert final["status"] == "completed"
        assert target.read_text(encoding="utf-8") == "授权范围内"
        assert (await client.get(f"/agent-runs/{created['id']}/approvals")).json() == []
        assert (await client.delete(f"/full-access-grants/{grant['grant_id']}")).json()["revoked"]
        assert not (await client.get(endpoint)).json()["active"]
        assert (await client.post("/agent-runs", json=request)).status_code == 422
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_revoke_cancels_inflight_run_and_logout_records_revocation(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        endpoint = f"/sessions/{body['session_id']}/full-access-grant"
        grant = (await client.post(endpoint, json={})).json()
        created = (await client.post("/agent-runs", json={**body, "permission_mode": "full_access"})).json()
        await until(client, created["id"], {"running"})
        assert (await client.delete(f"/full-access-grants/{grant['grant_id']}")).json()["revoked"]
        assert (await until(client, created["id"], TERMINAL))["status"] == "cancelled"
        assert not (await client.delete(f"/full-access-grants/{grant['grant_id']}")).json()["revoked"]
        await client.post(endpoint, json={})
        await client.post("/identity/clear")
        await client.post("/identity")
        assert not (await client.get(endpoint)).json()["active"]
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_expired_or_other_session_grant_cannot_authorize_tools(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        store = app.state.desktop.runtime.store
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        store.grant(body["session_id"], body["project_id"], expired)
        assert (await client.post("/agent-runs", json={**body, "permission_mode": "full_access"})).status_code == 422
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        store.grant(body["session_id"] + 1, body["project_id"], expires)
        assert (await client.post("/agent-runs", json={**body, "permission_mode": "full_access"})).status_code == 422
        assert not store.runs()
    finally:
        await close(app, client)


def test_policy_rejects_traversal_secrets_shell_and_escalation(tmp_path):
    for mode in policy.MODES:
        for path in ("../outside", ".env", ".ssh/id_rsa", ".git/config"):
            with pytest.raises(ValueError):
                policy.file_scope(tmp_path, path, mode)
    with pytest.raises(ValueError):
        policy.file_scope(tmp_path, str(tmp_path / "absolute.txt"), "workspace")
    for command in ("cmd /c whoami", "powershell -Command ls", "sudo ls", "curl https://example.test", "npm test & whoami", "python -c 'print(1)'", "git push", "git diff --ext-diff", "pytest .env"):
        with pytest.raises(ValueError):
            policy.command_plan(command, "full_access")
    assert policy.command_plan("git status --short", "workspace").automatic
    assert not policy.command_plan("npm test", "workspace").automatic
    assert policy.command_plan("pytest tests/unit -q", "full_access").automatic


@pytest.mark.asyncio
async def test_project_switch_revokes_grants_and_stops_active_full_access(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        endpoint = f"/sessions/{body['session_id']}/full-access-grant"
        await client.post("/projects/context", json={"project_id": body["project_id"]})
        await client.post(endpoint, json={})
        created = (await client.post("/agent-runs", json={**body, "permission_mode": "full_access"})).json()
        await until(client, created["id"], {"running"})
        other_root = tmp_path / "other"
        other_root.mkdir()
        other = (await client.post("/projects", json={"name": "另一个项目", "root_path": str(other_root)})).json()
        assert (await client.post("/projects/context", json={"project_id": other["id"]})).status_code == 200
        assert (await until(client, created["id"], TERMINAL))["status"] == "cancelled"
        assert not (await client.get(endpoint)).json()["active"]
        assert (await client.post(endpoint, json={})).status_code == 422
        await client.post("/projects/context", json={"project_id": body["project_id"]})
        assert not (await client.get(endpoint)).json()["active"]
    finally:
        await close(app, client)
