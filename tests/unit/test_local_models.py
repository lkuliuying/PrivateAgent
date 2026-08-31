"""服务器模式验证：不提供本机账号，模型推理可选本地，保留账号隔离与共享核心。"""
import subprocess
import sys

import httpx
import pytest
from test_local_executor import HEADERS, NONCE, TERMINAL, close, response, setup, until

from private_agent_local.app import create_app
from private_agent_local.cloud import Cloud
from private_agent_local.connections import ModelConfig, service_origin
from private_agent_local.local_models import ConnectedLocalModels


@pytest.mark.parametrize("url", ["", "http://cloud.example", "https://user:pass@example.test", "https://example.test/path", "https://example.test?token=fixture", "local://device"])
def test_remote_connection_rejects_insecure_or_credential_urls(url):
    with pytest.raises(ValueError):
        service_origin(url)


def test_entry_requires_server_and_rejects_removed_local_configuration(tmp_path):
    for args in ([], ["--connection-json", '{"mode":"local"}'], ["--server", "https://server.example.test", "--connection-json", '{"mode":"local"}']):
        result = subprocess.run([sys.executable, "-m", "private_agent_local.entry", "--stdio",
                                 "--data-dir", str(tmp_path / "records"), *args],
                                cwd=tmp_path, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert not (tmp_path / "records").exists()


def test_shared_core_does_not_import_full_backend_configuration(tmp_path):
    result = subprocess.run([sys.executable, "-c", "import sys; import private_agent_local.entry; assert not any(k == 'personal_assistant' or k.startswith('personal_assistant.') for k in sys.modules)"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_local_executor_never_owns_account_endpoints(tmp_path):
    calls = []

    async def server(request):
        calls.append(request.url.path)
        assert request.url.path == "/auth/me"
        if request.headers.get("authorization") == "Bearer valid-server-session":
            return httpx.Response(200, json={"id": 7})
        return httpx.Response(401)

    cloud = Cloud("https://server.example.test", transport=httpx.MockTransport(server))
    app = create_app(data_dir=tmp_path / "data", cloud=cloud, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"X-PrivateAgent-Local": NONCE}) as client:
        try:
            for method, path in [("POST", "/auth/local"), ("POST", "/auth/login"), ("POST", "/auth/register"),
                                 ("GET", "/auth/me"), ("POST", "/auth/logout")]:
                assert (await client.request(method, path)).status_code == 404
            assert not calls
            assert (await client.get("/projects")).status_code == 401
            assert (await client.post("/identity", headers={"Authorization": "Bearer invalid"})).status_code == 401
            assert not list((tmp_path / "data").glob("*/projects.sqlite3"))
            client.headers["Authorization"] = "Bearer valid-server-session"
            assert (await client.post("/identity")).status_code == 200
            assert (await client.get("/projects")).json() == []
            await client.post("/identity/clear")
            assert (await client.get("/projects")).status_code == 401
        finally:
            await app.state.desktop.clear()
            await cloud.close()


@pytest.mark.asyncio
async def test_server_account_relogin_keeps_existing_projects_messages_and_runs(tmp_path):
    first, client, server, root, body = await setup(tmp_path)
    server.responses = [response(text="服务器生成内容")]
    run = (await client.post("/agent-runs", json=body)).json()
    await until(client, run["id"], TERMINAL)
    await close(first, client)

    cloud = Cloud("https://account.example.test", transport=httpx.MockTransport(server.handle))
    second = create_app(data_dir=tmp_path / "data", cloud=cloud, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url="http://127.0.0.1", headers=HEADERS) as current:
        try:
            assert (await current.post("/identity")).status_code == 200
            assert (await current.get("/projects")).json()[0]["id"] == body["project_id"]
            assert (await current.get(f"/agent-runs/{run['id']}")).json()["output"] == "服务器生成内容"
            server.responses = [response(text="服务器续写")]
            another = (await current.post("/agent-runs", json=body)).json()
            assert (await until(current, another["id"], TERMINAL))["output"] == "服务器续写"
            messages = (await current.get(f"/sessions/{body['session_id']}/messages")).json()
            assert len(messages) == 4
            assert len(list((tmp_path / "data").glob("*/projects.sqlite3"))) == 1
            assert any(path == "/desktop/model/complete" for path, _ in server.calls)
            assert all(path in {"/auth/me", "/agent-model-profiles", "/desktop/model/complete"} for path, _ in server.calls)
        finally:
            await second.state.desktop.clear()
            await cloud.close()

@pytest.mark.parametrize("protocol", ["ollama", "openai"])
@pytest.mark.asyncio
async def test_local_models_require_server_identity_and_never_receive_account_token(tmp_path, protocol):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "127.0.0.1"
        assert "authorization" not in request.headers
        if protocol == "ollama":
            assert request.url.path == "/api/chat"
            return httpx.Response(200, json={"model": "fixture", "message": {"role": "assistant", "content": "本地完成"}, "prompt_eval_count": 123, "eval_count": 8, "done": True})
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"model": "fixture", "choices": [{"message": {"content": "本地完成"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 123, "completion_tokens": 8}})

    config = ModelConfig(inference_mode="local", model_protocol=protocol, model_endpoint="http://127.0.0.1:11434" + ("/v1" if protocol == "openai" else ""), model_name="fixture", context_tokens=8192)
    def account(request):
        assert request.url.path == "/auth/me"
        if request.headers.get("authorization") != "Bearer valid-server-session":
            return httpx.Response(401)
        return httpx.Response(200, json={"id": 7})

    service = ConnectedLocalModels("https://account.example.test", config, transport=httpx.MockTransport(account), model_transport=httpx.MockTransport(handle))
    app = create_app(data_dir=tmp_path / "data", cloud=service, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"X-PrivateAgent-Local": NONCE}) as client:
        try:
            auth = await client.post("/auth/local")
            assert auth.status_code == 404
            assert (await client.get("/agent-model-profiles")).status_code == 401
            assert (await client.post("/identity", headers={"Authorization": "Bearer invalid"})).status_code == 401
            assert not list((tmp_path / "data").glob("*/projects.sqlite3"))
            client.headers["Authorization"] = "Bearer valid-server-session"
            assert (await client.post("/identity")).status_code == 200
            assert (await client.get("/agent-model-profiles")).json()[0]["model_name"] == "fixture"
            project_root = tmp_path / "project"
            project_root.mkdir()
            project = (await client.post("/projects", json={"name": "本机项目", "root_path": str(project_root)})).json()
            workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
            binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
            session = (await client.post("/sessions", json={**binding, "title": "本机任务"})).json()
            run = (await client.post("/agent-runs", json={**binding, "session_id": session["id"], "message": "你好", "permission_mode": "readonly"})).json()
            final = await until(client, run["id"], TERMINAL)
            assert final["status"] == "completed", final
            assert final["output"] == "本地完成"
            budget = (await client.get(f"/sessions/{session['id']}/context-budget")).json()
            assert budget["used_tokens"] == 123 and budget["max_context_tokens"] == 8192
            assert len(requests) == 1
        finally:
            await app.state.desktop.clear()
            await service.close()

@pytest.mark.asyncio
async def test_switch_inference_to_local_keeps_account_projects_messages_and_runs(tmp_path):
    first, client, server, root, body = await setup(tmp_path)
    server.responses = [response(text="云端历史")]
    run = (await client.post("/agent-runs", json=body)).json()
    await until(client, run["id"], TERMINAL)
    await close(first, client)

    def infer(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"model": "fixture", "message": {"content": "本机续写"}, "prompt_eval_count": 50, "eval_count": 5})

    config = ModelConfig( inference_mode="local", model_name="fixture")
    service = ConnectedLocalModels("https://account.example.test", config, transport=httpx.MockTransport(server.handle), model_transport=httpx.MockTransport(infer))
    second = create_app(data_dir=tmp_path / "data", cloud=service, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url="http://127.0.0.1", headers=HEADERS) as current:
        try:
            assert (await current.post("/identity")).status_code == 200
            assert (await current.get("/projects")).json()[0]["id"] == body["project_id"]
            assert (await current.get(f"/agent-runs/{run['id']}")).json()["output"] == "云端历史"
            another = (await current.post("/agent-runs", json={**body, "model_profile_id": "local-model"})).json()
            assert (await until(current, another["id"], TERMINAL))["output"] == "本机续写"
            messages = (await current.get(f"/sessions/{body['session_id']}/messages")).json()
            assert len(messages) == 4
            assert len(list((tmp_path / "data").glob("*/projects.sqlite3"))) == 1
            assert (await current.post("/auth/local")).status_code == 404
        finally:
            await second.state.desktop.clear()
            await service.close()

@pytest.mark.parametrize("payload", [
    {"server_origin": "https://other.example.test"}, {"mode": "local"},
    {"model_endpoint": "http://remote.example.test"}, {"model_endpoint": "http://127.0.0.1:0"},
    {"model_endpoint": "http://127.0.0.1:70000"}, {"model_endpoint": "http://user:fixture@127.0.0.1"},
    {"context_tokens": True}, {"context_tokens": 0},
])
def test_model_config_cannot_override_identity_or_escape_loopback(payload):
    with pytest.raises(ValueError):
        ModelConfig(**payload)
