"""S2-T05 至 T11：请求预算、连续压缩、故障、能力与循环控制。"""
import asyncio
import json
import sqlite3

import httpx
import pytest
from test_local_context_history import history_store
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_core.context import ContextLimits, request_budget
from private_agent_core.contracts import (
    ModelMessage,
    ModelRequest,
    ModelToolDefinition,
    ToolCall,
)
from private_agent_core.llm.adapters import (
    ClaudeMessagesAdapter,
    OllamaChatAdapter,
    OpenAIChatAdapter,
)
from private_agent_core.llm.contracts import ModelCapabilities, ModelGatewayError
from private_agent_core.llm.gateway import ModelGateway
from private_agent_core.runtime import CancellationToken
from private_agent_local.context_manager import LocalContext


def seed(store, session, start=0, count=16):
    if start == 0:
        store.context.append(session, "run", ModelMessage(role="user", content="原目标：检查文件，禁止写入 secrets.txt"), key="goal", source="user")
    for i in range(start, start + count):
        tool = ToolCall(id=f"call-{i}", name="read_code_file", arguments={"rel_path": f"file-{i}.txt"})
        store.context.append(session, "run", ModelMessage(role="assistant", content="助手公开文本" * 100, tool_calls=(tool,)), key=f"call-{i}", source="model")
        store.context.append(session, "run", ModelMessage(role="tool", name=tool.name, tool_call_id=tool.id,
            content=json.dumps({"success": True, "output": {"content": "x" * 5000}})), key=f"result-{i}", source="tool")


def test_request_budget_counts_schema_reserve_unknown_and_invalid_configuration():
    request = ModelRequest(messages=(ModelMessage(role="user", content="你好"),))
    base = request_budget(request, 8192, 1024)
    large = request.model_copy(update={"tools": (ModelToolDefinition(name="large", description="x" * 4000, input_schema={"type": "object"}),)})
    assert request_budget(large, 8192, 1024)["estimated_input_tokens"] > base["estimated_input_tokens"]
    assert base["input_budget_tokens"] == 8192 - 1024 - 512
    unknown = request_budget(request, None, 1024)
    assert unknown["max_context_tokens"] == 0 and unknown["capacity_source"] == "restricted_unknown"
    assert request_budget(large, 1024, 1024)["exceeded"]
    for value in [0, -1, True, 257]:
        with pytest.raises(ValueError):
            ContextLimits(max_model_requests=value)


def test_two_compactions_retain_original_sources_and_constraints(tmp_path):
    store, session = history_store(tmp_path)
    try:
        seed(store, session)
        original = store.context.items(session)
        first = store.context.compact(session, store.context.begin(session, "first"))
        store.context.save_checkpoint(session, first)
        seed(store, session, start=16, count=10)
        second = store.context.compact(session, store.context.begin(session, "second"))
        store.context.save_checkpoint(session, second)
        assert second["parent_id"] == first["id"]
        assert original[0]["item_id"] in second["summary"]["source_item_ids"]
        assert len(store.context.items(session)) == len(original) + 20
        messages = store.context.messages(session)
        assert messages[0].content == "原目标：检查文件，禁止写入 secrets.txt"
        pending = set()
        for message in messages:
            pending.update(call.id for call in message.tool_calls)
            if message.role == "tool":
                assert message.tool_call_id in pending
                pending.remove(message.tool_call_id)
        assert not pending
        assert "助手公开文本" not in json.dumps(second["summary"], ensure_ascii=False)
    finally:
        store.db.close()


def test_compaction_storage_failure_preserves_old_checkpoint(tmp_path, monkeypatch):
    store, session = history_store(tmp_path)
    try:
        seed(store, session)
        first = store.context.compact(session, store.context.begin(session, "first"))
        store.context.save_checkpoint(session, first)
        before = store.context.items(session)
        candidate = store.context.compact(session, store.context.begin(session, "failure"))
        pack = store._pack
        def fail(value):
            if value.get("id") == candidate["id"] and value.get("state") == "completed":
                raise sqlite3.OperationalError("fixture write failed")
            return pack(value)
        monkeypatch.setattr(store, "_pack", fail)
        with pytest.raises(sqlite3.OperationalError):
            store.context.save_checkpoint(session, candidate)
        assert store.context.checkpoint(session)["id"] == first["id"]
        assert store.context.items(session) == before
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_thirty_requests_and_two_compactions_continue_to_actual_write(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        server.profiles[0]["context_tokens"] = 26000
        for i in range(32):
            (root / f"input-{i}.txt").write_text(f"input {i}\n" + "x" * 3000, encoding="utf-8")
        server.responses = [response({"id": f"call-{i}", "name": "read_code_file", "arguments": {"rel_path": f"input-{i}.txt"}}) for i in range(32)]
        server.responses += [response(call("write_project_file", {"rel_path": "done.txt", "content": "verified data"})), response(text="已创建并回读")]
        run = (await client.post("/agent-runs", json={**body, "message": "检查项目后创建 done.txt；禁止联网", "permission_mode": "workspace"})).json()
        await asyncio.wait_for(app.state.desktop.runtime.tasks[run["id"]], 20)
        final = app.state.desktop.runtime.store.run(run["id"])
        assert final["status"] == "completed", (final["error_code"], final["error_message"])
        assert (root / "done.txt").read_text() == "verified data"
        assert sum(e["type"] == "context.compaction_completed" for e in final["events"]) >= 2
        requests = [json.loads(data)["request"] for path, data in server.calls if path == "/desktop/model/complete"]
        assert len(requests) == 34 and all(r["max_output_tokens"] == 2048 for r in requests)
        assert "禁止联网" in json.dumps(requests[-1], ensure_ascii=False)
        assert final["loop_budget"]["model_requests"] == 34
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_repeated_failure_stops_but_success_breaks_stagnation(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        missing = call("read_code_file", {"rel_path": "missing"})
        server.responses = [response({**missing, "id": f"failed-{i}"}) for i in range(4)]
        run = (await client.post("/agent-runs", json=body)).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["error_code"] == "no_progress" and final["status"] == "limit_exceeded"
        requests = [json.loads(data) for path, data in server.calls if path == "/desktop/model/complete"]
        assert "loop_warning" in json.dumps(requests[-1])
        server.responses = [response(missing), response(missing), response(call("list_project_directory", {})), response(missing), response(missing), response(text="已说明缺失")]
        run = (await client.post("/agent-runs", json=body)).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "completed"
        assert final["loop_budget"]["model_requests"] == 6
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_manual_compaction_is_idempotent_and_pending_at_model_boundary(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        store = app.state.desktop.runtime.store
        store.context.import_legacy(body["session_id"])
        seed(store, body["session_id"])
        server.responses = [response(call("write_project_file", {"rel_path": "x", "content": "x"})), response(text="用户拒绝，已停止")]
        run = (await client.post("/agent-runs", json=body)).json()
        await until(client, run["id"], {"waiting_approval"})
        endpoint = f"/sessions/{body['session_id']}/context/compact"
        first = (await client.post(endpoint, json={"client_request_id": "manual"})).json()
        second = (await client.post(endpoint, json={"client_request_id": "another"})).json()
        assert first["id"] == second["id"] and first["state"] == "pending"
        approval = (await client.get(f"/agent-runs/{run['id']}/approvals")).json()[0]
        await client.post(f"/agent-runs/{run['id']}/approvals/{approval['id']}/reject")
        await until(client, run["id"], TERMINAL)
        third = (await client.post(endpoint, json={"client_request_id": "manual"})).json()
        assert third["id"] == first["id"] and third["state"] == "completed"
        assert not (root / "x").exists()
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_compaction_cancel_and_hard_limit_preserve_history(tmp_path, monkeypatch):
    app, client, server, root, body = await setup(tmp_path)
    try:
        store = app.state.desktop.runtime.store
        store.context.import_legacy(body["session_id"])
        seed(store, body["session_id"])
        before = store.context.items(body["session_id"])
        def cancel(*args):
            raise asyncio.CancelledError
        monkeypatch.setattr(store.context, "compact", cancel)
        run = (await client.post("/agent-runs", json=body)).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "cancelled"
        assert store.context.items(body["session_id"])[:len(before)] == before
        assert store.context.checkpoint(body["session_id"]) is None
        assert not [p for p, _ in server.calls if p == "/desktop/model/complete"]
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_unknown_or_tiny_capacity_never_sends_oversized_request(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        server.profiles[0]["context_tokens"] = None
        run = (await client.post("/agent-runs", json={**body, "message": "用户必需信息" * 3000})).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["error_code"] == "context_limit"
        assert not [p for p, _ in server.calls if p == "/desktop/model/complete"]
        assert app.state.desktop.runtime.store.context.items(body["session_id"])[0]["message"]["content"] == "用户必需信息" * 3000
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_configuration_change_recomputes_capacity_and_usage(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        server.responses = [response(call("write_project_file", {"rel_path": "x", "content": "x"}))]
        run = (await client.post("/agent-runs", json=body)).json()
        await until(client, run["id"], {"waiting_approval"})
        server.profiles[0]["context_tokens"] = 1024
        approval = (await client.get(f"/agent-runs/{run['id']}/approvals")).json()[0]
        await client.post(f"/agent-runs/{run['id']}/approvals/{approval['id']}/reject")
        final = await until(client, run["id"], TERMINAL)
        assert final["error_code"] == "context_limit"
        assert final.get("context_usage") is None
        assert sum(p == "/desktop/model/complete" for p, _ in server.calls) == 1
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_output_limit_unsupported_capability_fails_before_provider():
    class Unsupported:
        provider_name = "fixture"
        capabilities = ModelCapabilities(False, False, False, False, False)
        async def complete(self, *args, **kwargs):
            pytest.fail("不支持输出上限时不可发起请求")
    request = ModelRequest(messages=(ModelMessage(role="user", content="x"),), max_output_tokens=512)
    with pytest.raises(ModelGatewayError, match="输出 token 上限"):
        await ModelGateway(Unsupported()).complete(request, cancellation=CancellationToken())


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,field", [("openai", "max_tokens"), ("official", "max_completion_tokens"), ("ollama", "num_predict"), ("claude", "max_tokens")])
async def test_output_limit_reaches_real_adapter_payload(provider, field):
    observed = []
    async def handle(request):
        observed.append(json.loads(request.content))
        if provider == "ollama":
            return httpx.Response(200, json={"message": {"content": "done"}, "done": True})
        if provider == "claude":
            return httpx.Response(200, json={"content": [{"type": "text", "text": "done"}], "usage": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        if provider == "ollama":
            adapter = OllamaChatAdapter(base_url="http://127.0.0.1:11434", model="fixture", client=client)
        elif provider == "claude":
            adapter = ClaudeMessagesAdapter(api_key="fixture", model="fixture", client=client)
        else:
            adapter = OpenAIChatAdapter(base_url="https://api.openai.com/v1" if provider == "official" else "https://model.example.test/v1", api_key="fixture", model="fixture", client=client)
        result = await ModelGateway(adapter).complete(ModelRequest(messages=(ModelMessage(role="user", content="x"),), max_output_tokens=512), cancellation=CancellationToken())
        assert result.text == "done"
        payload = observed[0]["options"] if provider == "ollama" else observed[0]
        assert payload[field] == 512


def test_active_and_cost_budgets_are_independent_of_approval_wait():
    from types import SimpleNamespace
    owner = SimpleNamespace(store=SimpleNamespace(context=None))
    run = {"context_limits": {"max_active_seconds": 100, "max_cost_usd": 1.0}, "tool_call_count": 3, "approval_wait_seconds": 20}
    context = LocalContext(owner, run, None)
    context.started -= 50
    assert 69 < context.remaining_seconds() <= 70
    context.cost = 1.0
    with pytest.raises(Exception, match="max_cost_usd"):
        context.check_limits()
