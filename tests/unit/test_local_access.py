"""免登录工作区的身份、供应商调用和账号隔离验证。"""
import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from test_direct_models import (
    NONCE,
    REQUEST,
    configure,
    provider_response,
)
from test_local_executor import TERMINAL, until

from private_agent_local.app import create_app
from private_agent_local.direct_models import ConfiguredModels
from private_agent_local.identity import LOCAL_AUTHORITY, LOCAL_TOKEN_PREFIX
from private_agent_local.model_errors import CloudError


@asynccontextmanager
async def local_desktop(tmp_path, protocol="openai", handle=None, secrets=None, evaluation=False):
    accounts, calls = [], []

    async def provider(request):
        calls.append(request)
        assert LOCAL_TOKEN_PREFIX not in str(request.headers)
        if protocol == "claude":
            assert request.headers["x-api-key"] == "fixture-provider-secret"
        elif protocol == "openai":
            assert request.headers["Authorization"] == "Bearer fixture-provider-secret"
        if handle:
            value = handle(request)
            return await value if hasattr(value, "__await__") else value
        return provider_response(protocol, json.loads(request.content).get("stream", False))

    network_guard = pytest.MonkeyPatch()

    async def reject_unconfigured_network(_transport, request):
        accounts.append(request.url.path)
        raise AssertionError("本机测试不得访问未配置的外部服务")

    network_guard.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_unconfigured_network)
    models = ConfiguredModels(model_transport=httpx.MockTransport(provider), secrets=secrets)
    app = create_app(data_dir=tmp_path / "data", cloud=models, nonce=NONCE, evaluation=evaluation)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1",
        headers={"X-PrivateAgent-Local": NONCE}) as client:
        try:
            yield models, app, client, accounts, calls
        finally:
            await app.state.desktop.clear()
            await models.close()
            network_guard.undo()


async def enter(client):
    result = await client.post("/identity/local")
    assert result.status_code == 200, result.text
    token = result.json()["access_token"]
    assert token.startswith(LOCAL_TOKEN_PREFIX)
    client.headers["Authorization"] = f"Bearer {token}"
    return token


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "claude", "ollama"])
async def test_local_models_stream_without_any_account_request(tmp_path, protocol):
    async with local_desktop(tmp_path, protocol) as (models, app, client, accounts, calls):
        token = await enter(client)
        assert (await client.post("/identity/local")).json()["access_token"] == token
        identifier = await configure(client, protocol)
        app.state.desktop.verified_at = 0
        assert (await client.get("/model-providers")).status_code == 200
        deltas = []

        async def receive(delta):
            deltas.append(delta)

        result = await models.complete_stream(token, identifier, REQUEST, on_delta=receive)
        assert result["text"] == "直连完成" == "".join(deltas)
        assert len(calls) == 1
        assert accounts == []


@pytest.mark.asyncio
async def test_local_agent_executes_tools_and_keeps_write_approval(tmp_path):
    def provider(request):
        messages = json.loads(request.content)["messages"]
        count = sum(message["role"] == "tool" for message in messages)
        if count >= 2:
            return provider_response("openai")
        name, arguments = ("read_code_file", {"rel_path": "fixture.txt"}) if count == 0 else (
            "write_project_file", {"rel_path": "fixture.txt", "content": "after\n"})
        return httpx.Response(200, json={"model": "fixture-model", "choices": [{"message": {
            "content": "", "tool_calls": [{"id": f"call-{count}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}]}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 8}})

    async with local_desktop(tmp_path, handle=provider) as (models, _, client, accounts, calls):
        await enter(client)
        identifier = await configure(client)
        models.catalog.data["profiles"][identifier]["supports_streaming"] = False
        models.catalog.save()
        root = tmp_path / "project"
        root.mkdir()
        target = root / "fixture.txt"
        target.write_text("before\n", encoding="utf-8")
        project = (await client.post("/projects", json={"name": "本机项目", "root_path": str(root)})).json()
        workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
        binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
        session = (await client.post("/sessions", json={**binding, "title": "免登录任务", "kind": "coding"})).json()
        result = await client.post("/agent-runs", json={**binding, "session_id": session["id"],
            "message": "修改文件", "permission_mode": "confirm"})
        assert result.status_code == 201, result.text
        run_id = result.json()["id"]
        await until(client, run_id, {"waiting_approval"})
        assert target.read_text(encoding="utf-8") == "before\n"
        approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
        assert (await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")).status_code == 200
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed", final
        assert target.read_text(encoding="utf-8") == "after\n"
        assert len(calls) == 3 and accounts == []


@pytest.mark.asyncio
async def test_local_keys_history_and_restart_reject_platform_identity(tmp_path):
    async with local_desktop(tmp_path) as (models, _, client, accounts, _):
        local_token = await enter(client)
        await configure(client)
        first = (await client.get("/model-providers/provider/secret-reference")).json()
        assert (await client.get("/local-history/export")).json()["source"]["authority"] == LOCAL_AUTHORITY
        assert (await client.post("/identity")).status_code == 404
        assert accounts == []
        bag = dict(models.secrets)
        client.headers["Authorization"] = "Bearer fixture-server-account"
        assert (await client.get("/model-providers")).status_code == 401
        assert (await client.post("/identity")).status_code == 404
        assert (await client.post("/identity/clear")).status_code == 200
        with pytest.raises(CloudError):
            await models.identity(local_token)
        new_token = await enter(client)
        assert new_token != local_token
        assert (await client.get("/model-providers/provider/secret-reference")).json() == first
        assert (await client.get("/model-providers")).json()[0]["api_key_configured"]
        assert (await client.post("/identity/clear")).status_code == 200
        assert (await client.get("/projects")).status_code == 401
        with pytest.raises(CloudError):
            await models.identity(new_token)
        assert accounts == []

    async with local_desktop(tmp_path, secrets=bag) as (_, _, client, accounts, _):
        assert await enter(client) not in {local_token, new_token}
        assert (await client.get("/model-providers/provider/secret-reference")).json() == first
        assert (await client.get("/model-providers")).json()[0]["api_key_configured"]
        assert accounts == []
    for path in (tmp_path / "data").rglob("*.sqlite3*"):
        assert b"fixture-provider-secret" not in path.read_bytes()
        assert local_token.encode() not in path.read_bytes()


@pytest.mark.asyncio
async def test_untrusted_requests_are_rejected_and_evaluation_uses_local_identity(tmp_path):
    async with local_desktop(tmp_path) as (_, _, client, accounts, calls):
        for headers in ({"X-PrivateAgent-Local": "invalid"}, {"Origin": "https://untrusted.example.test"}):
            assert (await client.post("/identity/local", headers=headers)).status_code == 403
        assert (await client.get("/projects")).status_code == 401
        assert (await client.get("/admin/users")).status_code == 404
        assert accounts == calls == []
    async with local_desktop(tmp_path, evaluation=True) as (_, app, client, accounts, calls):
        await enter(client)
        assert (await client.get("/projects")).status_code == 200
        assert app.state.desktop.runtime is not None
        assert accounts == calls == []


@pytest.mark.asyncio
async def test_clearing_local_identity_cancels_probe(tmp_path):
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def provider(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with local_desktop(tmp_path, handle=provider) as (models, _, client, accounts, _):
        await enter(client)
        identifier = await configure(client)
        assert (await client.post(f"/agent-model-profiles/{identifier}/tool-probe")).status_code == 202
        await asyncio.wait_for(started.wait(), 2)
        client.headers["Authorization"] = "Bearer fixture-server-account"
        assert (await client.post("/identity/clear")).status_code == 200
        assert cancelled.is_set() and not models.probes
        assert accounts == []
