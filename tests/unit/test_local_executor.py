"""Desktop/cloud boundary tests using temporary projects and a fake HTTPS service."""
import asyncio
import os
import sys

import httpx
import pytest

from private_agent_local import files
from private_agent_local.app import create_app
from private_agent_local.cloud import Cloud, CloudError
from private_agent_local.entry import parent_alive
from private_agent_local.runtime import TERMINAL
from private_agent_local.store import Store

NONCE = "test-startup-nonce-" * 4
HEADERS = {"X-PrivateAgent-Local": NONCE, "Authorization": "Bearer account-a", "Origin": "http://tauri.localhost"}


class Server:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.block = asyncio.Event()

    async def handle(self, request):
        self.calls.append((request.url.path, request.content))
        if request.url.path == "/auth/me":
            token = request.headers.get("authorization")
            if token == "Bearer invalid":
                return httpx.Response(401)
            return httpx.Response(200, json={"id": 1 if token == "Bearer account-a" else 2})
        assert request.url.path == "/desktop/model/complete"
        if not self.responses:
            await self.block.wait()
        return httpx.Response(200, json=self.responses.pop(0))


def response(*calls, text=""):
    return {"text": text, "tool_calls": list(calls), "usage": {"input_tokens": 3, "output_tokens": 2}, "provider": "test", "model": "test"}


def call(name, arguments):
    return {"id": f"call-{name}", "name": name, "arguments": arguments}


async def setup(tmp_path):
    server = Server()
    cloud = Cloud("https://account.example.test", transport=httpx.MockTransport(server.handle))
    app = create_app(data_dir=tmp_path / "data", cloud=cloud, nonce=NONCE)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=HEADERS)
    assert (await client.post("/identity")).status_code == 200
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    result = await client.post("/projects", json={"name": "本机项目", "root_path": str(project_dir)})
    assert result.status_code == 201, result.text
    project = result.json()
    workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
    assert workspace["status"] == "active"
    binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
    session = (await client.post("/sessions", json={**binding, "title": "test", "kind": "coding"})).json()
    return app, client, server, project_dir, {**binding, "session_id": session["id"], "message": "Inspect and update the project"}


async def until(client, run_id, status):
    for _ in range(200):
        run = (await client.get(f"/agent-runs/{run_id}")).json()
        if run["status"] in status:
            return run
        await asyncio.sleep(0.01)
    pytest.fail(f"run did not reach {status}: {run['status']}")


async def close(app, client):
    await app.state.desktop.clear()
    await app.state.desktop.cloud.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_local_project_read_approved_write_and_cloud_boundary(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        (root / "hello.txt").write_text("before\n", encoding="utf-8")
        server.responses = [response(call("read_code_file", {"rel_path": "hello.txt"})),
                            response(call("write_project_file", {"rel_path": "hello.txt", "content": "after\n"})),
                            response(text="已修改并校验")]
        created = (await client.post("/agent-runs", json={**body, "client_request_id": "same-request"})).json()
        run_id = created["id"]
        assert (await client.post("/agent-runs", json={**body, "client_request_id": "same-request"})).json()["id"] == run_id
        await until(client, run_id, {"waiting_approval"})
        assert (root / "hello.txt").read_text() == "before\n"
        approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
        preview = (await client.get(f"/agent-runs/{run_id}/approvals/{approval['id']}/preview")).json()
        assert "-before" in preview["diff"] and "+after" in preview["diff"]
        assert (await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")).status_code == 200
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed"
        assert (root / "hello.txt").read_text() == "after\n"
        assert (await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")).status_code == 422
        assert final["input_tokens"] == 9
        messages = (await client.get(f"/sessions/{body['session_id']}/messages")).json()
        assert [m["role"] for m in messages] == ["user", "assistant"]
        wire = b"".join(data for _, data in server.calls).decode()
        assert str(root) not in wire and str(root).replace("\\", "\\\\") not in wire
        assert "root_path" not in wire and "session_id" not in wire
        assert "before" in wire  # Necessary tool context, not the project directory, is sent for inference.
        stream = await client.get(f"/agent-runs/{run_id}/events/stream")
        assert "run.terminal" in stream.text and "tool.approval_required" in stream.text
    finally:
        await close(app, client)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["reject", "stale", "cancel"])
async def test_write_denial_stale_preview_and_cancel_never_overwrite(tmp_path, decision):
    app, client, server, root, body = await setup(tmp_path)
    try:
        target = root / "test.txt"
        target.write_text("original", encoding="utf-8")
        server.responses = [response(call("write_project_file", {"rel_path": "test.txt", "content": "model edit"})), response(text="stopped")]
        run_id = (await client.post("/agent-runs", json=body)).json()["id"]
        await until(client, run_id, {"waiting_approval"})
        approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
        if decision == "cancel":
            assert (await client.post(f"/agent-runs/{run_id}/cancel")).json()["accepted"]
        else:
            if decision == "stale":
                target.write_text("user edit", encoding="utf-8")
            await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/{'approve' if decision == 'stale' else 'reject'}")
        await until(client, run_id, TERMINAL)
        assert target.read_text() == ("user edit" if decision == "stale" else "original")
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_account_switch_cancels_old_work_and_cannot_rebind_by_stale_request(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        run_id = (await client.post("/agent-runs", json=body)).json()["id"]
        await until(client, run_id, {"running"})
        client.headers["Authorization"] = "Bearer account-b"
        assert (await client.get("/projects")).status_code == 401  # Explicit bind required.
        assert (await client.post("/identity")).status_code == 200
        assert (await client.get("/projects")).json() == []
        assert (await client.get(f"/agent-runs/{run_id}")).status_code == 404
        client.headers["Authorization"] = "Bearer account-a"
        assert (await client.get("/projects")).status_code == 401
        await client.post("/identity")
        assert len((await client.get("/projects")).json()) == 1
        assert (await client.get(f"/agent-runs/{run_id}")).json()["status"] == "cancelled"
        await client.post("/identity/clear")
        assert (await client.get("/projects")).status_code == 401
        for database in (tmp_path / "data").rglob("*.sqlite3"):
            assert b"account-a" not in database.read_bytes()  # Session bearer never persisted.
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_loopback_nonce_origin_identity_and_validation(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        assert (await client.get("/projects", headers={"X-PrivateAgent-Local": "wrong"})).status_code == 403
        assert (await client.get("/projects", headers={"Origin": "https://evil.example"})).status_code == 403
        assert (await client.get("/health", headers={"Host": "evil.example"})).status_code == 403
        assert (await client.post("/identity", headers={"Authorization": "Bearer invalid"})).status_code == 401
        assert (await client.post("/agent-runs", json={**body, "permission_mode": "full_access"})).status_code == 422
        assert (await client.post("/projects", json={"name": "invalid", "root_path": "relative-folder"})).status_code == 422
        preflight = await client.options("/projects", headers={"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,x-privateagent-local"})
        assert preflight.status_code == 200
        caps = (await client.get("/capabilities")).json()
        assert caps["project_bound_runs_enabled"] and not caps["coding_full_access_supported"]
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_refresh_identity_does_not_cancel_active_task(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        run_id = (await client.post("/agent-runs", json=body)).json()["id"]
        runtime = app.state.desktop.runtime
        app.state.desktop.verified_at = 0
        await client.get("/projects")
        assert app.state.desktop.runtime is runtime
        assert (await client.get(f"/agent-runs/{run_id}")).json()["status"] in {"created", "running"}
    finally:
        await close(app, client)


def test_files_reject_traversal_credentials_links_and_stale_writes(tmp_path):
    for relative in ("../outside.txt", "C:/outside.txt", "/etc/passwd", ".env", ".ENV.local", ".ssh/id_rsa", "a\\b", "a:stream"):
        with pytest.raises(ValueError):
            files.within(tmp_path, relative, allow_missing=True)
    target = tmp_path / "file.txt"
    preview = files.patch_preview(tmp_path, "file.txt", "new")
    files.apply_patch(tmp_path, preview, "new")
    assert target.read_text() == "new"
    with pytest.raises(ValueError):
        files.apply_patch(tmp_path, preview, "new")
    assert not list(tmp_path.glob(".privateagent-write-*"))
    for command in ("python -c 'print(1)'", "npm test -- --prefix ../other", "pytest /outside", "npm test & whoami"):
        with pytest.raises(ValueError):
            files.parse_command(command)


@pytest.mark.asyncio
async def test_real_local_command_timeout_stops_child_and_does_not_forward_token(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATEAGENT_LOCAL_NONCE", "fixture-must-not-reach-child")
    result = await files.run_process(tmp_path, [sys.executable, "-c", "import os; print(os.getenv('PRIVATEAGENT_LOCAL_NONCE', 'absent'))"])
    assert result["stdout"].strip() == "absent" and result["returncode"] == 0
    pid_file = tmp_path / "pid.txt"
    script = "import os,time; from pathlib import Path; Path('pid.txt').write_text(str(os.getpid())); time.sleep(60)"
    with pytest.raises(TimeoutError):
        await files.run_process(tmp_path, [sys.executable, "-c", script], timeout=1)
    assert pid_file.exists()
    assert not parent_alive(int(pid_file.read_text()))


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows job-object lifecycle")
async def test_successful_command_does_not_leave_background_descendants(tmp_path):
    script = (
        "import subprocess,sys; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'], "
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "Path('child-pid.txt').write_text(str(child.pid))"
    )
    result = await files.run_process(tmp_path, [sys.executable, "-c", script])
    assert result["returncode"] == 0
    pid = int((tmp_path / "child-pid.txt").read_text())
    for _ in range(100):
        if not parent_alive(pid):
            break
        await asyncio.sleep(0.01)
    assert not parent_alive(pid)


def test_restart_marks_unfinished_operations_failed_without_replay(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    store.save_run({"id": "unfinished", "status": "waiting_approval", "approvals": [{"status": "pending"}]})
    store.db.close()
    restarted = Store(path)
    assert restarted.run("unfinished")["status"] == "failed"
    assert restarted.run("unfinished")["approvals"][0]["status"] == "cancelled"
    restarted.db.close()


@pytest.mark.asyncio
async def test_cloud_refuses_redirect_and_unsafe_origin():
    with pytest.raises(ValueError):
        Cloud("http://example.test")
    calls = []

    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://other.example/auth/me"})

    cloud = Cloud("https://cloud.example", transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CloudError):
            await cloud.identity("fixture")
        assert calls == ["cloud.example"]
    finally:
        await cloud.close()
