"""临时项目与进程内模型替身的本机执行边界回归。"""
import asyncio
import json
import os
import subprocess
import sys

import httpx
import pytest

from private_agent_local import files
from private_agent_local.app import create_app
from private_agent_local.entry import parent_alive
from private_agent_local.model_errors import CloudError
from private_agent_local.runtime import TERMINAL
from private_agent_local.store import Store

NONCE = "test-startup-nonce-" * 4
HEADERS = {"X-PrivateAgent-Local": NONCE, "Authorization": "Bearer account-a", "Origin": "http://tauri.localhost"}


class Server:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.block = asyncio.Event()
        self.profiles = [{"id": "test-profile", "model_name": "test", "context_tokens": 32000, "is_default": True, "enabled": True}]

    async def handle(self, request):
        self.calls.append((request.url.path, request.content))
        if request.url.path == "/agent-model-profiles":
            return httpx.Response(200, json=self.profiles)
        assert request.url.path == "/desktop/model/complete"
        if not self.responses:
            await self.block.wait()
        return httpx.Response(200, json=self.responses.pop(0))


def response(*calls, text=""):
    return {"text": text, "tool_calls": list(calls), "usage": {"input_tokens": 3, "output_tokens": 2}, "provider": "test", "model": "test"}


def call(name, arguments):
    return {"id": f"call-{name}", "name": name, "arguments": arguments}


class FixtureModels:
    """只调用测试对象，不建立网络连接或保留旧服务器代理实现。"""
    origin = "local-fixture://model"

    def __init__(self, server):
        self.server = server

    async def identity(self, token):
        if token not in {"account-a", "account-b"}:
            raise CloudError(401, "测试本机会话无效", code="local_session_expired")
        return {"id": 1 if token == "account-a" else 2}

    async def profiles(self, token):
        await self.identity(token)
        result = await self.server.handle(httpx.Request("GET", "https://fixture.test/agent-model-profiles"))
        return result.json()

    async def complete(self, token, profile, request):
        await self.identity(token)
        result = await self.server.handle(httpx.Request("POST", "https://fixture.test/desktop/model/complete",
            json={"model_profile_id": profile, "request": request}))
        return result.json()

    async def complete_stream(self, token, profile, request, *, on_delta):
        if hasattr(self.server, "model_stream"):
            return await self.server.model_stream(on_delta)
        return await self.complete(token, profile, request)

    async def close(self):
        pass


async def setup(tmp_path, server=None):
    server = server or Server()
    cloud = FixtureModels(server)
    app = create_app(data_dir=tmp_path / "data", cloud=cloud, nonce=NONCE)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=HEADERS)
    await app.state.desktop.activate("account-a", cloud.origin, 1)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    result = await client.post("/projects", json={"name": "本机项目", "root_path": str(project_dir)})
    assert result.status_code == 201, result.text
    project = result.json()
    workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
    assert workspace["status"] == "active"
    binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
    session = (await client.post("/sessions", json={**binding, "title": "test", "kind": "coding"})).json()
    return app, client, server, project_dir, {**binding, "session_id": session["id"], "message": "检查所选项目"}


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
@pytest.mark.parametrize("glob,received", [
    ("", '空字符串（""）'), (None, "null"), (False, "布尔值"), (123, "数值"),
    (["hidden-array-content"], "数组（1 项，内容已隐藏）"),
    ({"hidden-key": "hidden-object-content"}, "对象（内容已隐藏）"),
    ("x" * 201, "字符串（201 字符，内容已隐藏）"),
])
async def test_invalid_search_glob_exposes_safe_diagnostics_without_starting(tmp_path, glob, received):
    app, client, server, root, body = await setup(tmp_path)
    try:
        arguments = {"query": "hidden-query-content", "glob": glob, "cursor": None,
                     "unknown-field": "hidden-unknown-content"}
        server.responses = [response(call("search_project_files", arguments)), response(text="参数被拒绝")]
        created = (await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})).json()
        await until(client, created["id"], TERMINAL)
        result = await client.get(f"/agent-runs/{created['id']}/executions")
        execution, = result.json()
        assert execution["status"] == "failed" and execution["error_code"] == "invalid_tool_arguments"
        detail, = execution["output"]["parameter_errors"]
        assert detail["field"] == "glob" and detail["received"] == received
        assert '填写 "*"' in detail["hint"]
        assert "hidden-" not in result.text and "unknown-field" not in result.text
        events = (await client.get(f"/agent-runs/{created['id']}/events")).json()["items"]
        assert not any(event["type"] == "tool.started" for event in events)
        assert list(root.iterdir()) == []
    finally:
        await close(app, client)


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
        server.responses = [response(call("read_code_file", {"rel_path": "test.txt"})),
                            response(call("write_project_file", {"rel_path": "test.txt", "content": "model edit"})), response(text="stopped")]
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
        await app.state.desktop.activate("account-b", app.state.desktop.cloud.origin, 2)
        assert (await client.get("/projects")).json() == []
        assert (await client.get(f"/agent-runs/{run_id}")).status_code == 404
        client.headers["Authorization"] = "Bearer account-a"
        assert (await client.get("/projects")).status_code == 401
        await app.state.desktop.activate("account-a", app.state.desktop.cloud.origin, 1)
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
        assert (await client.get("/projects", headers={"Authorization": "Bearer invalid"})).status_code == 401
        assert (await client.post("/agent-runs", json={**body, "permission_mode": "full_access"})).status_code == 422
        assert (await client.post("/projects", json={"name": "invalid", "root_path": "relative-folder"})).status_code == 422
        preflight = await client.options("/projects", headers={"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,x-privateagent-local"})
        assert preflight.status_code == 200
        caps = (await client.get("/capabilities")).json()
        assert caps["project_bound_runs_enabled"] and caps["coding_full_access_supported"]
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
async def test_model_error_classification_is_preserved_in_local_run_and_events(tmp_path, monkeypatch):
    app, client, server, root, body = await setup(tmp_path)

    async def fail(token, profile, request):
        raise CloudError(502, "模型供应商认证失败", code="model_unauthorized")

    monkeypatch.setattr(app.state.desktop.cloud, "complete", fail)
    try:
        created = (await client.post("/agent-runs", json=body)).json()
        run = await until(client, created["id"], TERMINAL)
        assert run["status"] == "failed"
        assert run["error_code"] == "model_unauthorized"
        assert run["error_message"] == "模型供应商认证失败"
        assert run["tool_call_count"] == 0
        events = (await client.get(f"/agent-runs/{created['id']}/events")).json()
        assert events["items"][-1]["payload"]["error_code"] == "model_unauthorized"
    finally:
        await close(app, client)


@pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows 原生启动环境")
def test_prepare_process_accepts_complete_native_profile_environment(tmp_path):
    # 原生启动器将三个目录分别注入，系统默认的 AppData 子目录可以不存在。
    environment = {key: value for key, value in os.environ.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PYTHONPATH",
    }}
    for key, name in (("USERPROFILE", "profile"), ("APPDATA", "roaming"), ("LOCALAPPDATA", "local"),
                      ("TEMP", "tmp"), ("TMP", "tmp")):
        path = tmp_path / name
        path.mkdir(exist_ok=True)
        environment[key] = str(path)
    environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    code = """
import json
import os
import sys
from private_agent_local.files import prepare_process
command, environment = prepare_process([sys.executable])
print(json.dumps({"command_preserved": command == [sys.executable],
    "profile_preserved": all(environment[name] == os.environ[name]
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"))}))
"""
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"command_preserved": True, "profile_preserved": True}
    assert not (tmp_path / "profile/AppData").exists()


@pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows 目录回填")
@pytest.mark.parametrize("missing", ["USERPROFILE", "APPDATA", "LOCALAPPDATA"])
@pytest.mark.parametrize("empty", [False, True])
def test_prepare_process_fills_only_missing_or_empty_profile_values(tmp_path, monkeypatch, missing, empty):
    from private_agent_local import windows_process

    expected = {name: str(tmp_path / name) for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA")}
    for key, value in expected.items():
        monkeypatch.setenv(key, value)
    if empty:
        monkeypatch.setenv(missing, "")
    else:
        monkeypatch.delenv(missing)
    fallback = {name: str(tmp_path / ("system-" + name)) for name in expected}
    calls = []

    def profile_environment():
        calls.append(True)
        return fallback

    monkeypatch.setattr(windows_process, "profile_environment", profile_environment)
    monkeypatch.setenv("UNRELATED_FIXTURE_VALUE", "must-not-inherit")
    _, environment = files.prepare_process([sys.executable])
    assert calls == [True]
    assert {key: environment[key] for key in expected} == {**expected, missing: fallback[missing]}
    assert "UNRELATED_FIXTURE_VALUE" not in environment


@pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows 目录查询失败")
def test_prepare_process_missing_profile_lookup_failure_is_not_suppressed(monkeypatch):
    from private_agent_local import windows_process

    monkeypatch.delenv("APPDATA", raising=False)

    def unavailable():
        raise ValueError("无法定位系统应用数据目录，不能启动受限进程")

    monkeypatch.setattr(windows_process, "profile_environment", unavailable)
    with pytest.raises(ValueError, match="无法定位系统应用数据目录"):
        files.prepare_process([sys.executable])


@pytest.mark.parametrize("arguments", [[], ["bad\x00argument"], ["x" * 2001], ["x"] * 41])
def test_prepare_process_invalid_arguments_remain_rejected(arguments):
    with pytest.raises(ValueError, match="命令参数超出限制"):
        files.prepare_process(arguments)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows 原生环境和真实宿主")
async def test_native_profile_run_creation_retry_and_binding_rejection(tmp_path, monkeypatch):
    for key, name in (("USERPROFILE", "profile"), ("APPDATA", "roaming"), ("LOCALAPPDATA", "local")):
        path = tmp_path / name
        path.mkdir()
        monkeypatch.setenv(key, str(path))
    app, client, server, root, body = await setup(tmp_path)
    payload = {**body, "permission_mode": "confirm", "model_profile_id": None,
               "completion_contract_version": "1.0", "execution_contract_version": "1.0",
               "recovery_contract_version": "1.0", "client_request_id": "native-create"}
    try:
        capabilities = (await client.get(f"/sessions/{body['session_id']}/execution-capabilities")).json()
        assert capabilities["contract"]["execution"] is True
        assert capabilities["file_write_isolation"] is True
        assert capabilities["network_isolation"] is True
        assert (await client.post("/agent-runs", json={**payload, "message": ""})).status_code == 422
        assert (await client.post("/agent-runs", json={**payload, "workspace_id": body["workspace_id"] + 100})).status_code == 422
        assert (await client.post("/agent-runs", json=payload, headers={"Authorization": "Bearer different-account"})).status_code == 401
        assert app.state.desktop.runtime.store.runs() == []
        first, duplicate = await asyncio.gather(client.post("/agent-runs", json=payload), client.post("/agent-runs", json=payload))
        assert first.status_code == duplicate.status_code == 201
        run_id = first.json()["id"]
        assert duplicate.json()["id"] == run_id
        assert len(app.state.desktop.runtime.store.runs()) == 1
        assert (await client.post("/agent-runs", json={**payload, "client_request_id": "conflicting-create"})).status_code == 422
        assert (await client.post(f"/agent-runs/{run_id}/cancel")).status_code == 200
        assert (await until(client, run_id, TERMINAL))["status"] == "cancelled"
        repeated = await client.post("/agent-runs", json=payload)
        assert repeated.status_code == 201 and repeated.json()["id"] == run_id
        retry = await client.post("/agent-runs", json={**payload, "client_request_id": "explicit-new-create"})
        assert retry.status_code == 201 and retry.json()["id"] != run_id
        assert (await client.post(f"/agent-runs/{retry.json()['id']}/cancel")).status_code == 200
        assert (await until(client, retry.json()["id"], TERMINAL))["status"] == "cancelled"
        assert len(app.state.desktop.runtime.store.runs()) == 2
        assert not app.state.desktop.runtime.execution_sessions.slots
        assert not list(root.iterdir())
    finally:
        await close(app, client)
