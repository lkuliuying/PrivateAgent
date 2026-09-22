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


def test_compaction_uses_eighty_percent_capacity_and_not_message_count():
    request = ModelRequest(messages=tuple(ModelMessage(role="user", content="短消息") for _ in range(120)))
    budget = request_budget(request, 1_000_000, 2048)
    assert not budget["should_compact"] and not budget["exceeded"]
    size = budget["request_bytes"]
    assert not request_budget(request, 1_000_000, 2048, previous_usage=(size, 799999))["should_compact"]
    assert request_budget(request, 1_000_000, 2048, previous_usage=(size, 800000))["should_compact"]
    assert budget["auto_compact_threshold_tokens"] == 800000


def test_provider_usage_counts_cached_prefix_and_estimates_new_growth():
    request = ModelRequest(messages=(ModelMessage(role="user", content="x" * 3000),))
    size = request_budget(request, 32000, 2048)["request_bytes"]
    budget = request_budget(request, 32000, 2048, previous_usage=(size - 100, 1000))
    assert budget["estimated_input_tokens"] == 1125
    assert budget["measurement_source"] == "provider_usage_with_growth"


def test_large_context_wire_budget_scales_with_capacity_but_remains_bounded():
    request = ModelRequest(messages=tuple(ModelMessage(role="user", content="x" * 400000) for _ in range(8)))
    size = len(request.model_dump_json().encode("utf-8"))
    below = request_budget(request, 1_000_000, 2048, previous_usage=(size, 799999))
    assert below["request_bytes"] > 1_500_000 and below["max_request_bytes"] == 8_000_000
    assert not below["should_compact"] and not below["exceeded"]
    assert request_budget(request, 1_000_000, 2048, previous_usage=(size, 800000))["should_compact"]
    assert request_budget(request, 8192, 2048, previous_usage=(size, 100))["exceeded"]
    assert request_budget(request, 1_000_000_000, 2048)["max_request_bytes"] == 64 * 1024 * 1024


@pytest.mark.asyncio
async def test_many_short_messages_below_threshold_do_not_compact_or_fail(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        server.profiles[0]["context_tokens"] = 1_000_000
        history = app.state.desktop.runtime.store.context
        history.import_legacy(body["session_id"])
        for index in range(120):
            history.append(body["session_id"], "prior", ModelMessage(role="user" if index % 2 == 0 else "assistant", content="短对话"), key=str(index), source="user" if index % 2 == 0 else "model")
        server.responses = [response(text="已回答")]
        run = (await client.post("/agent-runs", json=body)).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "completed", final.get("error_message")
        events = app.state.desktop.runtime.store.run(run["id"])["events"]
        assert not [event for event in events if event["type"].startswith("context.compaction_")]
        assert len(history.items(body["session_id"])) >= 122
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_manual_compaction_recovers_failed_badge_without_deleting_history(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    try:
        server.responses = [response(text="完成")]
        created = (await client.post("/agent-runs", json=body)).json()
        await until(client, created["id"], TERMINAL)
        runtime = app.state.desktop.runtime
        seed(runtime.store, body["session_id"])
        before = runtime.store.context.items(body["session_id"])
        run = runtime.store.run(created["id"])
        run.update(compaction_state="failed", compaction_error="先前压缩失败")
        runtime.store.save_run(run)
        result = await client.post(f"/sessions/{body['session_id']}/context/compact", json={"client_request_id": "retry"})
        assert result.json()["state"] == "completed"
        refreshed = runtime.store.run(run["id"])
        assert refreshed["compaction_state"] == "idle" and refreshed["compaction_error"] is None
        assert runtime.store.context.items(body["session_id"]) == before
    finally:
        await close(app, client)


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
        # 本用例验证缺少供应商计量时的连续压缩，不使用固定 3 token 伪装长上下文实测。
        for result in server.responses:
            result["usage"] = {"input_tokens": 0, "output_tokens": 2}
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
