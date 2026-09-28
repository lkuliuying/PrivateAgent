"""直连供应商的产品调用链验证，所有网络均使用隔离替身。"""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager

import httpx
import pytest

from private_agent_local.app import create_app
from private_agent_local.connections import ModelConfig
from private_agent_local.direct_models import ConfiguredModels
from private_agent_local.local_models import model_service
from private_agent_local.model_catalog import ProviderInput
from private_agent_local.model_errors import CloudError

NONCE = "direct-fixture-nonce-" * 4
HEADERS = {"X-PrivateAgent-Local": NONCE, "Authorization": "Bearer fixture-account-a"}
REQUEST = {"messages": [{"role": "user", "content": "固定测试输入"}]}


async def enter_local(client):
    result = await client.post("/identity/local")
    assert result.status_code == 200, result.text
    token = result.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return token


def configuration(protocol="openai", **overrides):
    return {"name": "测试供应商", "protocol": protocol,
            "base_url": "http://127.0.0.1:11434" if protocol == "ollama" else "https://provider.example.test/v1",
            "api_format": {"openai": "chat_completions", "claude": "anthropic_messages", "ollama": "ollama_chat"}[protocol],
            "models": [{"model_id": "fixture-model", "context_tokens": 32000}], **overrides}


def provider_response(protocol, streaming=False):
    if protocol == "ollama":
        data = {"model": "fixture-model", "message": {"role": "assistant", "content": "直连完成"},
                "prompt_eval_count": 123, "eval_count": 8, "done": True}
        if streaming:
            return httpx.Response(200, headers={"Content-Type": "application/x-ndjson"}, content=json.dumps(data) + "\n")
    elif protocol == "claude":
        data = {"id": "fixture", "model": "fixture-model", "role": "assistant", "type": "message",
                "content": [{"type": "text", "text": "直连完成"}], "stop_reason": "end_turn", "usage": {"input_tokens": 123, "output_tokens": 8}}
        if streaming:
            events = [("message_start", {"type": "message_start", "message": {**data, "content": []}}),
                      ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                      ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "直连完成"}}),
                      ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                      ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 8}}),
                      ("message_stop", {"type": "message_stop"})]
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content="".join(f"event: {name}\ndata: {json.dumps(body)}\n\n" for name, body in events))
    else:
        data = {"id": "fixture", "model": "fixture-model", "choices": [{"message": {"role": "assistant", "content": "直连完成"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 8}}
        if streaming:
            data["choices"] = [{"delta": {"content": "直连完成"}, "finish_reason": "stop"}]
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=f"data: {json.dumps(data)}\n\ndata: [DONE]\n\n")
    return httpx.Response(200, json=data)


@asynccontextmanager
async def desktop(tmp_path, protocol="openai", handle=None, secrets=None):
    account_calls, provider_calls = [], []

    async def upstream(request):
        provider_calls.append(request)
        assert "fixture-account" not in str(request.headers)
        if protocol == "claude":
            assert request.headers["x-api-key"] == "fixture-provider-secret"
        elif protocol != "ollama":
            assert request.headers["Authorization"] == "Bearer fixture-provider-secret"
        if handle:
            value = handle(request)
            return await value if hasattr(value, "__await__") else value
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "fixture-model", "context_length": 32000}]})
        body = json.loads(request.content)
        return provider_response(protocol, body.get("stream", False))

    network_guard = pytest.MonkeyPatch()

    async def reject_unconfigured_network(_transport, request):
        account_calls.append(request.url.path)
        raise AssertionError("本机测试不得访问未配置的外部服务")

    network_guard.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_unconfigured_network)
    models = ConfiguredModels(model_transport=httpx.MockTransport(upstream), secrets=secrets)
    app = create_app(data_dir=tmp_path / "data", cloud=models, nonce=NONCE)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=HEADERS) as client:
        try:
            await enter_local(client)
            yield models, app, client, account_calls, provider_calls
        finally:
            await app.state.desktop.clear()
            await models.close()
            network_guard.undo()


async def configure(client, protocol="openai"):
    result = await client.put("/model-providers/provider", json=configuration(protocol))
    assert result.status_code == 200, result.text
    identifier = result.json()["models"][0]["profile_id"]
    if protocol != "ollama":
        assert (await client.put("/model-providers/provider/runtime-secret", json={"secret": "fixture-provider-secret"})).status_code == 200
    return identifier


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "claude", "ollama"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_all_protocols_direct_only(tmp_path, protocol, streaming):
    async with desktop(tmp_path, protocol) as (models, _, client, accounts, calls):
        identifier = await configure(client, protocol)
        deltas = []

        async def receive(delta):
            deltas.append(delta)

        result = await models.complete_stream(models.token, identifier, REQUEST, on_delta=receive) if streaming else await models.complete(models.token, identifier, REQUEST)
        assert result["text"] == "直连完成"
        assert result["model_profile_id"] == identifier
        assert result["usage"]["input_tokens"] == 123
        assert result["transport_metrics"]["provider_requests"] == 1
        assert len(calls) == 1
        assert accounts == []
        if streaming:
            assert "".join(deltas) == result["text"]


@pytest.mark.asyncio
async def test_project_agent_uses_direct_profile_for_all_tool_rounds(tmp_path):
    count = 0

    def provider(request):
        nonlocal count
        count += 1
        body = json.loads(request.content)
        assert body["model"] == "fixture-model"
        if count == 1:
            return httpx.Response(200, json={"model": "fixture-model", "choices": [{"message": {"content": "", "tool_calls": [{"id": "call-fixture", "type": "function", "function": {"name": "list_project_directory", "arguments": '{"rel_path":"."}'}}]}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 123, "completion_tokens": 8}})
        assert any(message["role"] == "tool" for message in body["messages"])
        return provider_response("openai")

    async with desktop(tmp_path, handle=provider) as (models, _, client, accounts, calls):
        identifier = await configure(client)
        models.catalog.data["profiles"][identifier]["supports_streaming"] = False
        models.catalog.save()
        root = tmp_path / "project"
        root.mkdir()
        (root / "fixture.txt").write_text("fixture", encoding="utf-8")
        project = (await client.post("/projects", json={"name": "测试项目", "root_path": str(root)})).json()
        workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
        binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
        session = (await client.post("/sessions", json={**binding, "title": "直连测试", "kind": "coding"})).json()
        result = await client.post("/agent-runs", json={**binding, "session_id": session["id"], "message": "列出目录", "permission_mode": "readonly"})
        assert result.status_code == 201, result.text
        from test_local_executor import TERMINAL, until
        final = await until(client, result.json()["id"], TERMINAL)
        assert final["status"] == "completed", final
        assert final["output"] == "直连完成"
        assert final["model_profile_id"] == identifier
        assert len(calls) == 2 and accounts == []


@pytest.mark.asyncio
async def test_secrets_account_and_endpoint_isolation_and_restart(tmp_path):
    async with desktop(tmp_path) as (models, _, client, accounts, calls):
        identifier = await configure(client)
        reference = (await client.get("/model-providers/provider/secret-reference")).json()
        assert len(reference["alias"]) == 64
        assert (await client.get("/model-providers")).json()[0]["api_key_configured"]
        bag = dict(models.secrets)
        current_token = models.token
        client.headers["Authorization"] = "Bearer obsolete-platform-session"
        denied = await client.get("/model-providers")
        assert denied.status_code == 401
        assert denied.headers["X-PrivateAgent-Session"] == "expired"
        assert (await client.post("/identity")).status_code == 404
        with pytest.raises(CloudError, match="重新连接"):
            await models.complete("obsolete-platform-session", identifier, REQUEST)
        client.headers["Authorization"] = f"Bearer {current_token}"
        assert (await client.get("/model-providers/provider/secret-reference")).json() == reference
        assert not calls
    for path in (tmp_path / "data").rglob("*.sqlite3*"):
        assert b"fixture-provider-secret" not in path.read_bytes()
        assert b"fixture-account-a" not in path.read_bytes()
    async with desktop(tmp_path, secrets=bag) as (models, _, client, accounts, calls):
        assert (await client.get("/model-providers")).json()[0]["api_key_configured"]
        assert (await models.complete(models.token, identifier, REQUEST))["text"] == "直连完成"
        changed = configuration(base_url="https://other.example.test/v1")
        assert (await client.put("/model-providers/provider", json=changed)).status_code == 200
        assert not (await client.get("/model-providers")).json()[0]["api_key_configured"]
        with pytest.raises(CloudError) as error:
            await models.complete(models.token, identifier, REQUEST)
        assert error.value.code == "model_missing_api_key"
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_discovery_and_draft_secret_stay_local(tmp_path):
    async with desktop(tmp_path) as (_, _, client, accounts, calls):
        identifier = await configure(client)
        result = await client.post("/model-providers/discover/models", json={"provider_id": "provider", "protocol": "openai", "base_url": configuration()["base_url"]})
        assert result.status_code == 200, result.text
        assert result.json()["models"][0]["model_id"] == "fixture-model"
        probe = await client.post(f"/agent-model-profiles/{identifier}/probe")
        assert probe.json()["model_exists"] is True
        assert probe.json()["native_tool_calls"] is None
        wrong = await client.post("/model-providers/discover/models", json={"provider_id": "provider", "protocol": "openai", "base_url": "https://other.example.test/v1"})
        assert wrong.status_code == 422
        assert len(calls) == 2 and accounts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500, 302])
async def test_provider_failure_never_falls_back_or_exposes_body(tmp_path, status):
    async with desktop(tmp_path, handle=lambda request: httpx.Response(status, headers={"Location": "https://account.example.test/desktop/model/complete"}, json={"error": {"message": "fixture-provider-secret"}})) as (models, _, client, accounts, calls):
        identifier = await configure(client)
        with pytest.raises(CloudError) as error:
            await models.complete(models.token, identifier, REQUEST)
        assert "fixture-provider-secret" not in str(error.value)
        assert error.value.status != 401
        assert len(calls) == 1 and accounts == []


@pytest.mark.asyncio
async def test_cancellation_closes_request_without_proxy_or_retry(tmp_path):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def upstream(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with desktop(tmp_path, handle=upstream) as (models, _, client, accounts, calls):
        identifier = await configure(client)
        task = asyncio.create_task(models.complete(models.token, identifier, REQUEST))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and len(calls) == 1 and accounts == []


@pytest.mark.asyncio
async def test_invalid_input_and_missing_profile_do_not_use_network(tmp_path):
    async with desktop(tmp_path) as (models, _, client, accounts, calls):
        with pytest.raises(CloudError):
            await models.complete(models.token, None, REQUEST)
        for change in ({"base_url": "https://user:fixture-provider-secret@example.test"}, {"api_format": "anthropic_messages"}, {"models": []}):
            result = await client.put("/model-providers/provider", json=configuration(**change))
            assert result.status_code == 422
            assert "fixture-provider-secret" not in result.text
        identifier = await configure(client)
        result = await client.put("/model-providers/provider/runtime-secret", json={"secret": "fixture-provider-secret", "extra": True})
        assert result.status_code == 422 and "fixture-provider-secret" not in result.text
        await client.put("/model-providers/provider", json=configuration(enabled=False))
        with pytest.raises(CloudError):
            await models.complete(models.token, identifier, REQUEST)
        assert not calls and accounts == []


@pytest.mark.asyncio
async def test_probe_is_explicit_cancelled_on_logout_and_durable(tmp_path):
    started = asyncio.Event()

    async def upstream(request):
        started.set()
        await asyncio.Event().wait()

    async with desktop(tmp_path, handle=upstream) as (models, _, client, _, calls):
        identifier = await configure(client)
        assert not calls
        assert (await client.post(f"/agent-model-profiles/{identifier}/tool-probe")).status_code == 202
        await asyncio.wait_for(started.wait(), 2)
        assert (await client.post(f"/agent-model-profiles/{identifier}/tool-probe")).status_code == 409
        assert (await client.post("/identity/clear")).status_code == 200
        assert not models.probes
        await enter_local(client)
        state = (await client.get(f"/agent-model-profiles/{identifier}/tool-probe")).json()
        assert state["status"] == "failed" and state["error_code"] == "probe_interrupted"


@pytest.mark.asyncio
async def test_legacy_service_mode_always_selects_direct_runtime():
    for mode in ("auto", "service", "local"):
        model = model_service(ModelConfig(inference_mode=mode))
        try:
            assert isinstance(model, ConfiguredModels)
        finally:
            await model.close()






@pytest.mark.asyncio
async def test_ollama_context_budget_matches_actual_request(tmp_path):
    async with desktop(tmp_path, "ollama") as (models, _, client, _, calls):
        identifier = await configure(client, "ollama")
        result = await client.put("/model-settings", json={"llm_context_length": 4096, "llm_temperature": 0.4})
        assert result.status_code == 200
        assert (await client.get(f"/agent-model-profiles/{identifier}")).json()["context_tokens"] == 4096
        assert (await models.profiles(models.token))[0]["context_tokens"] == 4096
        await models.complete(models.token, identifier, REQUEST)
        assert json.loads(calls[0].content)["options"]["num_ctx"] == 4096
        assert json.loads(calls[0].content)["options"]["temperature"] == 0.4


@pytest.mark.asyncio
async def test_catalog_write_failure_restores_committed_state(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        await configure(client)
        catalog = models.catalog
        catalog.db.execute("PRAGMA query_only=ON")
        try:
            with pytest.raises(sqlite3.OperationalError):
                catalog.upsert("provider", ProviderInput.model_validate(configuration(name="未提交配置")))
            assert catalog.provider("provider")["name"] == "测试供应商"
        finally:
            catalog.db.execute("PRAGMA query_only=OFF")


@pytest.mark.asyncio
async def test_oversized_provider_response_is_closed_without_fallback(tmp_path):
    class Oversized(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"x" * (2 * 1024 * 1024 + 1)

        async def aclose(self):
            self.closed = True

    stream = Oversized()
    async with desktop(tmp_path, handle=lambda request: httpx.Response(200, stream=stream)) as (models, _, client, accounts, calls):
        identifier = await configure(client)
        with pytest.raises(CloudError) as error:
            await models.complete(models.token, identifier, REQUEST)
        assert error.value.code == "model_invalid_response"
        assert stream.closed and len(calls) == 1 and accounts == []


@pytest.mark.asyncio
async def test_probe_storage_failure_does_not_leave_running_task(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, _):
        identifier = await configure(client)
        models.start_probe(models.token, identifier)
        task = models.probes[identifier]
        models.catalog.db.execute("PRAGMA query_only=ON")
        try:
            await asyncio.wait_for(task, 2)
            assert not models.probes
            result = (await client.get(f"/agent-model-profiles/{identifier}/tool-probe")).json()
            assert result["status"] == "failed" and result["error_code"] == "probe_storage_failed"
        finally:
            models.catalog.db.execute("PRAGMA query_only=OFF")
