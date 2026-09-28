"""本机模型配置决定调用路由；无效配置和网络错误均不能回退服务器。"""
import httpx
import pytest
from test_direct_models import REQUEST, configure, desktop, enter_local
from test_direct_models import configuration as provider_configuration
from test_local_executor import HEADERS, NONCE

from private_agent_local.app import create_app
from private_agent_local.connections import ModelConfig
from private_agent_local.local_models import (
    ConfiguredModels,
    LocalInference,
    model_service,
)
from private_agent_local.model_errors import CloudError


def configuration():
    return {}, {}


class Services:
    def __init__(self, *_args):
        self.cloud_calls = []

    def server(self, request):
        self.cloud_calls.append(request.url.path)
        assert request.url.path == "/auth/me"
        assert request.headers["authorization"] == HEADERS["Authorization"]
        return httpx.Response(200, json={"id": 7})

    def service(self):
        return ConfiguredModels()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disabled", "missing", "unknown", "mismatch", "nonloopback", "protocol", "capacity"])
async def test_invalid_local_configuration_never_sends_prompt_or_falls_back(tmp_path, change):
    async with desktop(tmp_path, "ollama") as (service, _, client, accounts, calls):
        identifier = await configure(client, "ollama")
        provider = service.catalog.provider("provider")
        profile = service.catalog.data["profiles"][identifier]
        if change == "disabled":
            provider["enabled"] = False
        elif change == "missing":
            provider["models"] = []
        elif change == "mismatch":
            provider["models"][0]["model_id"] = "different"
        elif change == "nonloopback":
            provider["base_url"] = "https://other.example.test"
        elif change == "protocol":
            provider["api_format"] = "anthropic_messages"
        elif change == "capacity":
            profile["context_tokens"] = None
        with pytest.raises(CloudError):
            await service.complete(service.token, "unknown" if change == "unknown" else identifier, REQUEST)
        assert not calls and accounts == []


@pytest.mark.asyncio
async def test_configuration_changes_take_effect_without_restarting_service(tmp_path):
    async with desktop(tmp_path) as (service, _, client, accounts, calls):
        identifier = await configure(client)
        assert (await service.complete(service.token, identifier, REQUEST))["text"] == "直连完成"
        assert (await client.put("/model-providers/provider", json=provider_configuration(enabled=False))).status_code == 200
        with pytest.raises(CloudError):
            await service.complete(service.token, identifier, REQUEST)
        assert (await client.put("/model-providers/provider", json=provider_configuration())).status_code == 200
        assert (await service.complete(service.token, identifier, REQUEST))["text"] == "直连完成"
        assert len(calls) == 2 and accounts == []


@pytest.mark.asyncio
async def test_unavailable_local_service_does_not_retry_on_server(tmp_path):
    def unavailable(request):
        raise httpx.ConnectError("fixture", request=request)

    async with desktop(tmp_path, handle=unavailable) as (service, _, client, accounts, calls):
        identifier = await configure(client)
        with pytest.raises(CloudError) as error:
            await service.complete(service.token, identifier, REQUEST)
        assert error.value.code == "model_network_error"
        assert len(calls) == 1 and accounts == []


@pytest.mark.asyncio
async def test_default_factory_uses_automatic_routing():
    service = model_service(ModelConfig())
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
            await enter_local(client)
            result = await client.post("/local-models/discover", json=data)
            assert result.status_code == 200
            assert result.json() == {"models": [{"model_id": "fixture", "context_tokens": None, "max_output_tokens": None, "metadata_source": "unknown"}]}
            assert (await client.post("/local-models/discover", json={**data, "base_url": "https://other.example.test"})).status_code == 422
            assert (await client.post("/local-models/discover", json={**data, "api_key": "fixture"})).status_code == 422
            assert len(calls) == 1
        finally:
            await app.state.desktop.clear()
            await service.close()
