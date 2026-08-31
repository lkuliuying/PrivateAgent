"""自动模型路由只使用账号配置；失败不回退，所有网络由测试替身隔离。"""
import json

import httpx
import pytest
from test_local_executor import HEADERS, NONCE, TERMINAL, until

from private_agent_local.app import create_app
from private_agent_local.cloud import CloudError
from private_agent_local.connections import ModelConfig
from private_agent_local.local_models import (
    ConfiguredModels,
    LocalInference,
    model_service,
)


def configuration(protocol="ollama", endpoint="http://127.0.0.1:11434"):
    profile = {"id": "selected", "provider_id": "provider", "provider": protocol, "model_name": "fixture",
               "is_default": True, "is_local": protocol == "ollama", "enabled": True, "context_tokens": 8192}
    provider = {"id": "provider", "protocol": protocol, "base_url": endpoint, "enabled": True,
                "api_format": "ollama_chat" if protocol == "ollama" else "chat_completions",
                "api_key_configured": False, "models": [{"profile_id": "selected", "model_id": "fixture"}]}
    return profile, provider


class Services:
    def __init__(self, profile, provider):
        self.profile, self.provider = profile, provider
        self.cloud_calls = []
        self.local_calls = []

    def server(self, request):
        self.cloud_calls.append(request.url.path)
        assert request.headers["authorization"] == HEADERS["Authorization"]
        if request.url.path == "/auth/me":
            return httpx.Response(200, json={"id": 7})
        if request.url.path == "/model-providers":
            return httpx.Response(200, json=[self.provider])
        if request.url.path == "/agent-model-profiles":
            return httpx.Response(200, json=[self.profile])
        assert request.url.path == "/desktop/model/complete"
        assert json.loads(request.content)["model_profile_id"] == self.profile["id"]
        return httpx.Response(200, json={"text": "供应商完成", "provider": "openai", "model": "fixture",
                                        "usage": {"input_tokens": 200, "cached_tokens": 100}, "tool_calls": []})

    def local(self, request):
        self.local_calls.append(request.url.path)
        assert "authorization" not in request.headers
        assert request.url.host in {"127.0.0.1", "localhost", "::1"}
        if self.provider["protocol"] == "ollama":
            assert request.url.path == "/api/chat"
            assert json.loads(request.content)["options"]["num_ctx"] == 8192
            return httpx.Response(200, json={"model": "fixture", "message": {"content": "本机完成"},
                                            "prompt_eval_count": 100, "eval_count": 4, "done": True})
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"model": "fixture", "choices": [{"message": {"content": "本机完成"}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 100, "completion_tokens": 4}})

    def service(self):
        return ConfiguredModels("https://account.example.test", transport=httpx.MockTransport(self.server),
                                model_transport=httpx.MockTransport(self.local))


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol,endpoint,local", [
    ("ollama", "http://127.0.0.1:11434", True),
    ("openai", "http://localhost:9000/v1", True),
    ("openai", "http://[::1]:9000/v1", True),
    ("openai", "https://provider.example.test/v1", False),
])
async def test_selected_model_drives_actual_runtime_without_execution_switch(tmp_path, protocol, endpoint, local):
    services = Services(*configuration(protocol, endpoint))
    service = services.service()
    app = create_app(data_dir=tmp_path / "data", cloud=service, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=HEADERS) as client:
        try:
            assert (await client.post("/identity")).status_code == 200
            root = tmp_path / "project"
            root.mkdir()
            project = (await client.post("/projects", json={"name": "测试", "root_path": str(root)})).json()
            workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
            binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
            session = (await client.post("/sessions", json={**binding, "title": "测试"})).json()
            # 不传模型 ID 时使用配置中的默认模型，并把实际 ID 固定到运行记录。
            run = (await client.post("/agent-runs", json={**binding, "session_id": session["id"], "message": "测试", "permission_mode": "readonly"})).json()
            final = await until(client, run["id"], TERMINAL)
            assert final["status"] == "completed", final
            assert final["model_profile_id"] == "selected"
            assert final["output"] == ("本机完成" if local else "供应商完成")
            assert bool(services.local_calls) is local
            assert ("/desktop/model/complete" in services.cloud_calls) is not local
        finally:
            await app.state.desktop.clear()
            await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disabled", "missing", "unknown", "mismatch", "nonloopback", "credentials", "protocol", "capacity"])
async def test_invalid_local_configuration_never_sends_prompt_or_falls_back(change):
    profile, provider = configuration()
    if change == "disabled":
        provider["enabled"] = False
    elif change == "missing":
        provider["models"] = []
    elif change == "mismatch":
        provider["models"][0]["model_id"] = "different"
    elif change == "nonloopback":
        provider["base_url"] = "https://other.example.test"
    elif change == "credentials":
        provider["api_key_configured"] = True
    elif change == "protocol":
        provider["api_format"] = "anthropic_messages"
    elif change == "capacity":
        profile["context_tokens"] = None
    services = Services(profile, provider)
    service = services.service()
    try:
        with pytest.raises(CloudError):
            await service.complete("account-a", "unknown" if change == "unknown" else "selected", {"messages": [{"role": "user", "content": "测试"}]})
        assert not services.local_calls
        assert "/desktop/model/complete" not in services.cloud_calls
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_configuration_changes_take_effect_without_restarting_service():
    services = Services(*configuration())
    service = services.service()
    request = {"messages": [{"role": "user", "content": "测试"}]}
    try:
        assert (await service.complete("account-a", "selected", request))["text"] == "本机完成"
        services.profile, services.provider = configuration("openai", "https://provider.example.test/v1")
        assert (await service.complete("account-a", "selected", request))["text"] == "供应商完成"
        assert len(services.local_calls) == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_unavailable_local_service_does_not_retry_on_server():
    services = Services(*configuration())
    def unavailable(request):
        raise httpx.ConnectError("fixture", request=request)
    service = ConfiguredModels("https://account.example.test", transport=httpx.MockTransport(services.server),
                               model_transport=httpx.MockTransport(unavailable))
    try:
        with pytest.raises(CloudError):
            await service.complete("account-a", None, {"messages": [{"role": "user", "content": "测试"}]})
        assert "/desktop/model/complete" not in services.cloud_calls
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_default_factory_uses_automatic_routing():
    service = model_service("https://account.example.test", ModelConfig())
    try:
        assert isinstance(service, ConfiguredModels)
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,status", [(None, 200), ({"models": [None]}, 200), ({"models": []}, 302), ({"models": []}, 401)])
async def test_discovery_errors_are_explicit_and_do_not_follow_redirects(payload, status):
    calls = []
    def malformed(request):
        calls.append(request)
        return httpx.Response(status, json=payload, headers={"Location": "https://other.example.test"})
    models = LocalInference(ModelConfig(), transport=httpx.MockTransport(malformed))
    try:
        with pytest.raises(CloudError, match="无法读取本机模型列表"):
            await models.discover()
        assert len(calls) == 1
    finally:
        await models.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol,path,payload", [
    ("ollama", "/api/tags", {"models": [{"name": "fixture"}, {"name": "fixture"}]}),
    ("openai", "/v1/models", {"data": [{"id": "fixture"}]}),
])
async def test_discovery_is_authenticated_locally_and_does_not_invent_capacity(tmp_path, monkeypatch, protocol, path, payload):
    services = Services(*configuration())
    service = services.service()
    calls = []
    def discover(request):
        calls.append(request.url.path)
        assert request.url.path == path
        assert "authorization" not in request.headers
        return httpx.Response(200, json=payload)
    monkeypatch.setattr("private_agent_local.app.LocalInference", lambda config: LocalInference(config, transport=httpx.MockTransport(discover)))
    app = create_app(data_dir=tmp_path / "data", cloud=service, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=HEADERS) as client:
        try:
            data = {"protocol": protocol, "base_url": "http://127.0.0.1:9000" + ("/v1" if protocol == "openai" else "")}
            assert (await client.post("/local-models/discover", json=data)).status_code == 401
            assert not calls
            await client.post("/identity")
            result = await client.post("/local-models/discover", json=data)
            assert result.status_code == 200
            assert result.json() == {"models": [{"model_id": "fixture", "context_tokens": None, "max_output_tokens": None, "metadata_source": "unknown"}]}
            assert (await client.post("/local-models/discover", json={**data, "base_url": "https://other.example.test"})).status_code == 422
            assert (await client.post("/local-models/discover", json={**data, "api_key": "fixture"})).status_code == 422
            assert len(calls) == 1
        finally:
            await app.state.desktop.clear()
            await service.close()
