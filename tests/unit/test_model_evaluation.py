"""产品交接、直连预算和失败计量；系统凭据 API 全部替换为合成值。"""
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from test_direct_models import (
    HEADERS,
    NONCE,
    REQUEST,
    configuration,
    configure,
    desktop,
    enter_local,
    provider_response,
)
from test_local_executor import until

from private_agent_local.app import create_app
from private_agent_local.core_adapter import LocalRunAdapter
from private_agent_local.direct_models import ConfiguredModels
from private_agent_local.model_catalog import ModelParameters
from private_agent_local.model_credentials import (
    credential_target,
    read_model_credential,
)
from private_agent_local.model_errors import CloudError
from private_agent_local.runtime import TERMINAL, Runtime


@asynccontextmanager
async def evaluation_agent(path):
    def no_inference(request):
        pytest.fail("配置交接不得发起供应商请求")

    service = ConfiguredModels(model_transport=httpx.MockTransport(no_inference))
    app = create_app(data_dir=path, cloud=service, nonce=NONCE, evaluation=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=HEADERS) as client:
        try:
            await enter_local(client)
            yield service, client
        finally:
            await app.state.desktop.clear()
            await service.close()


def binding_body(root, identifier):
    return {"model_settings_directory": str(root), "credential_namespace": "candidate", "profile_id": identifier,
            "expected": {"provider": {"id": "provider", "protocol": "openai", "endpoint": configuration()["base_url"]},
                         "model": "fixture-model", "context_tokens": 32000}, "parameters": ModelParameters().model_dump()}


@pytest.mark.asyncio
async def test_handoff_is_readonly_selected_scoped_frozen_and_never_returns_secret(tmp_path, monkeypatch):
    reads = []

    def synthetic(alias, namespace):
        reads.append((alias, namespace))
        return "S6_SYNTHETIC_PROVIDER_VALUE"

    monkeypatch.setattr("private_agent_local.model_evaluation.read_model_credential", synthetic)
    async with desktop(tmp_path / "client") as (source, app, client, _, _):
        identifier = await configure(client)
        root = tmp_path / "client/data"
        database = root / source.catalog.scope / "model-settings.sqlite3"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        payload = binding_body(root, identifier)
        # 正常桌面进程没有交接授权，不因存在同名 API 而打开凭据。
        assert (await client.post("/model-evaluation/bind", json=payload)).status_code == 409
        assert not reads
        async with evaluation_agent(tmp_path / "agent") as (target, connection):
            wrong = json.loads(json.dumps(payload))
            wrong["expected"]["model"] = "different"
            assert (await connection.post("/model-evaluation/bind", json=wrong)).status_code == 409
            assert not reads
            response = await connection.post("/model-evaluation/bind", json=payload)
            assert response.status_code == 200, response.text
            assert response.json()["route"] == "direct_provider"
            assert "S6_SYNTHETIC_PROVIDER_VALUE" not in response.text
            assert reads == [(source.catalog.reference("provider")["alias"], "candidate")]
            assert hashlib.sha256(database.read_bytes()).hexdigest() == before
            assert (await connection.post("/model-evaluation/bind", json=payload)).status_code == 409
            assert len(reads) == 1
            for url in ("/model-settings", "/model-providers/provider/runtime-secret", "/agent-model-profiles/x/tool-probe"):
                assert (await connection.post(url, json={})).status_code == 409
            source.catalog.data["parameters"]["llm_temperature"] = 0.2
            source.catalog.save()
            with pytest.raises(CloudError) as failure:
                await target.complete(target.token, identifier, REQUEST)
            assert failure.value.code == "evaluation_configuration_changed"
        for path in (tmp_path / "agent").rglob("*.sqlite3*"):
            assert b"S6_SYNTHETIC_PROVIDER_VALUE" not in path.read_bytes()


@pytest.mark.asyncio
async def test_handoff_other_account_and_missing_credential_cannot_start(tmp_path, monkeypatch):
    reads = []
    monkeypatch.setattr("private_agent_local.model_evaluation.read_model_credential", lambda *args: reads.append(args))
    async with desktop(tmp_path / "client") as (source, _, client, _, _):
        identifier = await configure(client)
        payload = binding_body(tmp_path / "client/data", identifier)
        async with evaluation_agent(tmp_path / "agent") as (_, connection):
            connection.headers["Authorization"] = "Bearer fixture-account-b"
            assert (await connection.post("/identity")).status_code == 404
            assert (await connection.post("/model-evaluation/bind", json=payload)).status_code == 401
            assert not reads
            await enter_local(connection)
            result = await connection.post("/model-evaluation/bind", json=payload)
            assert result.status_code == 409 and result.json()["error_code"] == "model_missing_api_key"
            assert len(reads) == 1


def test_native_credential_target_matches_desktop_namespace_and_tests_cannot_read():
    alias = "a" * 64
    assert credential_target(alias, "candidate") == "model-provider." + alias + ".api-key.com.personal-assistant.desktop.candidate"
    assert credential_target(alias, "desktop") != credential_target(alias, "candidate")
    with pytest.raises(ValueError):
        credential_target("*", "desktop")
    with pytest.raises(CloudError, match="隔离测试"):
        read_model_credential(alias, "candidate")


def test_native_credential_decoder_frees_and_clears_synthetic_blob(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    from private_agent_local import model_credentials

    allocated, freed, observed = [], [], []

    def read(target, kind, flags, output):
        observed.append((target, kind, flags))
        pointer_type = type(output._obj)
        credential = pointer_type._type_()
        blob = ctypes.create_string_buffer("S6_SYNTHETIC".encode("utf-16-le"))
        credential.CredentialBlob = ctypes.addressof(blob)
        credential.CredentialBlobSize = len(blob.raw) - 1
        allocated.extend([credential, blob])
        ctypes.cast(output, ctypes.POINTER(pointer_type))[0] = ctypes.pointer(credential)
        return True

    def free(pointer):
        freed.append(True)

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: SimpleNamespace(CredReadW=read, CredFree=free))
    target = credential_target("b" * 64, "candidate")
    assert model_credentials._read_windows(target) == "S6_SYNTHETIC"
    assert observed == [(target, 1, 0)] and freed == [True]
    assert set(allocated[1].raw) == {0}


async def start_run(client, root, profile, limits=None):
    root.mkdir()
    (root / "file.txt").write_text("sample")
    project = (await client.post("/projects", json={"name": "合成预算测试", "root_path": str(root)})).json()
    workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
    binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
    session = (await client.post("/sessions", json={**binding, "title": "预算测试"})).json()
    payload = {**binding, "session_id": session["id"], "message": "列出目录", "permission_mode": "readonly",
               "model_profile_id": profile, "client_request_id": "same-logical-start", "context_limits": limits or {"max_total_tokens": 5000}}
    created = await client.post("/agent-runs", json=payload)
    assert created.status_code == 201, created.text
    duplicate = await client.post("/agent-runs", json=payload)
    assert duplicate.status_code in {200, 201} and duplicate.json()["id"] == created.json()["id"]
    return created.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected", [(401, "model_unauthorized"), (403, "model_unauthorized"), (404, "model_model_not_found"),
    ("json", "model_invalid_response"), ("protocol", "model_protocol_error"), ("timeout", "model_timeout"),
    ("disconnect", "model_stream_interrupted"), ("eof", "model_stream_interrupted")])
async def test_direct_failures_count_once_without_replay(tmp_path, failure, expected):
    async def upstream(request):
        if type(failure) is int:
            return httpx.Response(failure, text="S6_SYNTHETIC_PROVIDER_VALUE")
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic")
        if failure == "disconnect":
            raise httpx.RemoteProtocolError("synthetic")
        data = "bad json" if failure == "json" else 'data: []\n\n' if failure == "protocol" else 'data: {"choices":[]}\n\n'
        if failure == "json":
            data = "data: bad json\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=data)

    async with desktop(tmp_path, handle=upstream) as (_, _, client, accounts, calls):
        identifier = await configure(client)
        run = await start_run(client, tmp_path / "project", identifier)
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "failed" and final["error_code"] == expected
        assert len(calls) == 1 and accounts == []
        assert final["loop_budget"]["model_requests"] == 1 and final["usage_complete"] is False
        history = (await client.get(f"/agent-runs/{run['id']}/events")).json()["items"]
        from coding_acceptance_metrics import process_metrics

        metrics = process_metrics(history, final)
        assert metrics["provider_requests"] == 1 and metrics["provider_retries"] == 0
        assert metrics["model_seconds"] is not None
        transport = next(e["payload"] for e in history if e["type"] == "model.transport")
        assert calls[0].headers["X-Model-Call-Id"] == transport["attempt_id"] == transport["call_id"]
        assert "S6_SYNTHETIC_PROVIDER_VALUE" not in json.dumps(history)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,limits,expected", [
    ({"prompt_tokens": 3, "completion_tokens": 2}, {"max_total_tokens": 5}, "max_total_tokens"),
    ({"prompt_tokens": 3}, {"max_total_tokens": 500}, "token_usage_unknown"),
    ({}, {"max_total_tokens": 500}, "token_usage_unknown"),
    ({"prompt_tokens": 3, "completion_tokens": 2}, {"max_cost_usd": 0.1}, "cost_usage_unknown"),
    ({"prompt_tokens": 3, "completion_tokens": 2}, {"max_model_requests": 1}, "max_model_requests"),
])
async def test_direct_budget_stops_next_request_and_partial_usage_is_unknown(tmp_path, usage, limits, expected):
    def upstream(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [{"id": "read", "type": "function",
            "function": {"name": "read_code_file", "arguments": '{"rel_path":"file.txt"}'}}]}, "finish_reason": "tool_calls"}], "usage": usage})

    async with desktop(tmp_path, handle=upstream) as (models, _, client, _, calls):
        identifier = await configure(client)
        models.catalog.data["profiles"][identifier]["supports_streaming"] = False
        models.catalog.save()
        run = await start_run(client, tmp_path / "project", identifier, limits)
        final = await until(client, run["id"], TERMINAL)
        assert final["error_code"] == expected and len(calls) == 1
        assert final["status"] == ("limit_exceeded" if expected.startswith("max_") else "failed")
        assert final["cost_usd"] is None
        if "completion_tokens" not in usage:
            assert final["loop_budget"]["tokens"] is None


@pytest.mark.asyncio
async def test_direct_cancelled_inflight_request_is_counted_and_closed(tmp_path):
    entered, closed = asyncio.Event(), asyncio.Event()

    async def upstream(request):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            closed.set()

    async with desktop(tmp_path, handle=upstream) as (_, _, client, _, calls):
        identifier = await configure(client)
        run = await start_run(client, tmp_path / "project", identifier)
        await asyncio.wait_for(entered.wait(), 2)
        assert (await client.post(f"/agent-runs/{run['id']}/cancel")).json()["accepted"]
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "cancelled" and closed.is_set() and len(calls) == 1
        assert final["loop_budget"]["tokens"] is None
        history = (await client.get(f"/agent-runs/{run['id']}/events")).json()["items"]
        transports = [e["payload"] for e in history if e["type"] == "model.transport"]
        assert len(transports) == 1 and transports[0]["provider_requests"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("after_success", [False, True])
async def test_transport_event_storage_failure_releases_output_publisher(tmp_path, monkeypatch, after_success):
    original = Runtime.event
    recordings, requests = [], []

    def fail_transport(runtime, run, event_type, **payload):
        if event_type == "model.transport":
            recordings.append(event_type)
            if not after_success or len(recordings) == 2:
                raise OSError("synthetic_metric_write_failure")
        return original(runtime, run, event_type, **payload)

    def upstream(request):
        requests.append(request)
        return tool_response("openai", True) if after_success and len(requests) == 1 else provider_response("openai", True)

    monkeypatch.setattr(Runtime, "event", fail_transport)
    async with desktop(tmp_path, handle=upstream) as (_, _, client, _, calls):
        identifier = await configure(client)
        run = await start_run(client, tmp_path / "project", identifier)
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "failed" and len(calls) == (2 if after_success else 1)
        assert final.get("usage_complete") is not True and final["loop_budget"]["tokens"] is None
        publishers = [task for task in asyncio.all_tasks() if "publish_batches" in task.get_coro().__qualname__]
        assert not publishers, "计量持久化失败不能遗留流式输出任务"


@pytest.mark.asyncio
async def test_request_event_storage_failure_preserves_original_exception(tmp_path, monkeypatch):
    original_event, original_attempt = Runtime.event, LocalRunAdapter._complete_attempt
    errors = []

    def fail_request(runtime, run, event_type, **payload):
        if event_type == "model.requested":
            raise OSError("synthetic_request_event_write_failure")
        return original_event(runtime, run, event_type, **payload)

    async def capture_error(adapter, *args, **kwargs):
        try:
            return await original_attempt(adapter, *args, **kwargs)
        except Exception as error:
            errors.append(type(error))
            raise

    monkeypatch.setattr(Runtime, "event", fail_request)
    monkeypatch.setattr(LocalRunAdapter, "_complete_attempt", capture_error)
    async with desktop(tmp_path) as (_, _, client, _, calls):
        identifier = await configure(client)
        run = await start_run(client, tmp_path / "project", identifier)
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "failed" and not calls
        assert errors == [OSError], "请求事件尚未写入时，不能用未定义的清理函数掩盖原始异常"
        assert not [task for task in asyncio.all_tasks() if "publish_batches" in task.get_coro().__qualname__]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["claude", "ollama"])
async def test_unsupported_reasoning_rejected_before_request(tmp_path, protocol):
    async with desktop(tmp_path, protocol) as (models, _, client, _, calls):
        identifier = await configure(client, protocol)
        with pytest.raises(CloudError) as failure:
            await models.complete(models.token, identifier, {**REQUEST, "reasoning_effort": "high"})
        assert failure.value.code == "model_unsupported_capability" and not calls


def tool_response(protocol, stream):
    name, arguments = "list_project_directory", {"rel_path": "."}
    if protocol == "openai":
        call = {"index": 0, "id": "round-one", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        key = "delta" if stream else "message"
        value = {"choices": [{key: {"content": "", "tool_calls": [call]}, "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 123, "completion_tokens": 8}}
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=f"data: {json.dumps(value)}\n\ndata: [DONE]\n\n") if stream else httpx.Response(200, json=value)
    if protocol == "ollama":
        value = {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "round-one", "function": {"name": name, "arguments": arguments}}]},
                 "done": True, "prompt_eval_count": 123, "eval_count": 8}
        return httpx.Response(200, content=json.dumps(value) + "\n")
    block = {"type": "tool_use", "id": "round-one", "name": name, "input": arguments}
    value = {"content": [block], "stop_reason": "tool_use", "usage": {"input_tokens": 123, "output_tokens": 8}}
    if not stream:
        return httpx.Response(200, json=value)
    frames = [("message_start", {"message": {"id": "fixture", "model": "fixture-model", "usage": {"input_tokens": 123}}}),
              ("content_block_start", {"index": 0, "content_block": {**block, "input": {}}}),
              ("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta", "partial_json": json.dumps(arguments)}}),
              ("content_block_stop", {"index": 0}),
              ("message_delta", {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 8}}), ("message_stop", {})]
    return httpx.Response(200, content="".join(f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n" for kind, body in frames))


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "claude", "ollama"])
@pytest.mark.parametrize("stream", [True, False])
async def test_three_protocol_tool_roundtrip_and_pre_request_stream_selection(tmp_path, protocol, stream):
    seen = []

    def upstream(request):
        body = json.loads(request.content)
        seen.append(body)
        assert bool(body.get("stream")) is stream
        assert body.get("temperature", body.get("options", {}).get("temperature")) == 0.3
        if len(seen) == 1:
            return tool_response(protocol, stream)
        assert (any(m.get("role") == "tool" for m in body["messages"]) if protocol != "claude"
                else any(isinstance(m.get("content"), list) and any(c.get("type") == "tool_result" for c in m["content"]) for m in body["messages"]))
        return provider_response(protocol, stream)

    async with desktop(tmp_path, protocol, handle=upstream) as (models, _, client, accounts, calls):
        identifier = await configure(client, protocol)
        models.catalog.data["profiles"][identifier]["supports_streaming"] = stream
        models.catalog.data["parameters"]["llm_temperature"] = 0.3
        models.catalog.data["parameters"]["llm_context_length"] = 32000
        models.catalog.save()
        run = await start_run(client, tmp_path / "project", identifier)
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "completed", final["error_code"]
        assert final["tool_call_count"] == 1 and final["loop_budget"]["model_requests"] == 2
        assert len(calls) == 2 and accounts == []
        assert final["usage_complete"] and final["cost_usd"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "claude", "ollama"])
@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("status,expected", [(401, "model_unauthorized"), (403, "model_unauthorized"), (404, "model_model_not_found")])
async def test_three_protocol_auth_and_missing_model_never_replay(tmp_path, protocol, stream, status, expected):
    async with desktop(tmp_path, protocol, handle=lambda request: httpx.Response(status, text="synthetic")) as (models, _, client, _, calls):
        identifier = await configure(client, protocol)

        async def delta(_):
            pass

        with pytest.raises(CloudError) as failure:
            if stream:
                await models.complete_stream(models.token, identifier, REQUEST, on_delta=delta)
            else:
                await models.complete(models.token, identifier, REQUEST)
        assert failure.value.code == expected and len(calls) == 1


@pytest.mark.asyncio
async def test_rejected_capability_records_zero_dispatch_but_one_model_attempt(tmp_path):
    async with desktop(tmp_path) as (models, _, client, _, calls):
        identifier = await configure(client)
        models.catalog.data["profiles"][identifier]["native_tool_calls"] = False
        models.catalog.save()
        run = await start_run(client, tmp_path / "project", identifier)
        final = await until(client, run["id"], TERMINAL)
        assert final["error_code"] == "model_unsupported_capability"
        assert final["loop_budget"]["model_requests"] == 1 and not calls
        history = (await client.get(f"/agent-runs/{run['id']}/events")).json()["items"]
        transports = [e["payload"] for e in history if e["type"] == "model.transport"]
        assert len(transports) == 1 and transports[0]["provider_requests"] == 0
