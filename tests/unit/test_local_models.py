"""本机启动、供应商推理和历史兼容边界；不依赖平台账号。"""
import subprocess
import sys

import httpx
import pytest
from test_direct_models import configuration, configure, desktop, enter_local
from test_local_executor import NONCE, TERMINAL, until

from private_agent_local.app import create_app
from private_agent_local.connections import ModelConfig
from private_agent_local.direct_models import ConfiguredModels


def test_entry_rejects_platform_and_removed_connection_arguments(tmp_path):
    for args in (["--server", "https://server.example.test"], ["--connection-json", '{"mode":"local"}']):
        result = subprocess.run([sys.executable, "-m", "private_agent_local.entry", "--stdio",
                                 "--data-dir", str(tmp_path / "records"), *args],
                                cwd=tmp_path, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0 and "unrecognized arguments" in result.stderr
        assert not (tmp_path / "records").exists()


def test_shared_core_does_not_import_full_backend_configuration(tmp_path):
    result = subprocess.run([sys.executable, "-c", "import sys; import private_agent_local.entry; assert not any(k == 'personal_assistant' or k.startswith('personal_assistant.') for k in sys.modules)"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr



@pytest.mark.asyncio
async def test_platform_routes_removed_and_local_session_required(tmp_path):
    models = ConfiguredModels()
    app = create_app(data_dir=tmp_path / "data", cloud=models, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"X-PrivateAgent-Local": NONCE}) as client:
        try:
            for method, path in [("POST", "/auth/login"), ("POST", "/auth/register"), ("GET", "/auth/me"), ("POST", "/auth/logout"), ("POST", "/identity")]:
                assert (await client.request(method, path)).status_code == 404
            denied = await client.get("/projects")
            assert denied.status_code == 401 and denied.headers["X-PrivateAgent-Session"] == "expired"
            await enter_local(client)
            assert (await client.get("/projects")).json() == []
            await client.post("/identity/clear")
            assert (await client.get("/projects")).status_code == 401
        finally:
            await app.state.desktop.clear()
            await models.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["ollama", "openai"])
@pytest.mark.parametrize("capacity", [8192, 32000])
async def test_api_key_models_keep_context_limit_and_token_boundaries(tmp_path, protocol, capacity):
    async with desktop(tmp_path, protocol) as (models, _, client, accounts, calls):
        await configure(client, protocol)
        value = configuration(protocol, models=[{"model_id": "fixture-model", "context_tokens": capacity}])
        assert (await client.put("/model-providers/provider", json=value)).status_code == 200
        await client.put("/model-settings", json={"llm_temperature": 0.7, "llm_context_length": capacity, "kb_enabled_by_default": False})
        root = tmp_path / "project"
        root.mkdir()
        project = (await client.post("/projects", json={"name": "窗口测试", "root_path": str(root)})).json()
        workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
        binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
        session = (await client.post("/sessions", json={**binding, "title": "本机任务"})).json()
        run = (await client.post("/agent-runs", json={**binding, "session_id": session["id"], "message": "你好",
            "permission_mode": "readonly", "execution_contract_version": "1.0"})).json()
        final = await until(client, run["id"], TERMINAL)
        if capacity == 8192:
            assert final["status"] == "limit_exceeded" and final["error_code"] == "context_limit"
            assert not calls
        else:
            assert final["status"] == "completed", final
            assert final["output"] == "直连完成"
            assert len(calls) == 1
            budget = (await client.get(f"/sessions/{session['id']}/context-budget")).json()
            assert budget["used_tokens"] == 123 and budget["max_context_tokens"] == capacity
        assert accounts == []
        assert all("local-session:" not in str(request.headers) for request in calls)


@pytest.mark.parametrize("payload", [
    {"server_origin": "https://other.example.test"}, {"mode": "local"},
    {"model_endpoint": "http://remote.example.test"}, {"model_endpoint": "http://127.0.0.1:0"},
    {"model_endpoint": "http://127.0.0.1:70000"}, {"model_endpoint": "http://user:fixture@127.0.0.1"},
    {"context_tokens": True}, {"context_tokens": 0},
])
def test_model_config_cannot_override_identity_or_escape_loopback(payload):
    with pytest.raises(ValueError):
        ModelConfig(**payload)
