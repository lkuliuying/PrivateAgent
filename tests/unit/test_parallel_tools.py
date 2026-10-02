"""只读批次的并发上限、串行屏障、顺序和取消边界。"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from private_agent_core.contracts import (
    ModelMessage,
    ModelResponse,
    ModelToolDefinition,
    ToolCall,
    ToolResult,
)
from private_agent_core.runtime import AgentRuntime, CancellationToken


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,readonly,receipt,prior_success,expected", [
    ("acknowledged", False, True, True, "acknowledged"),
    ("acknowledged", False, True, False, "acknowledged"),
    ("acknowledged", True, True, True, "steering_superseded"),
    ("dispatched", False, True, False, "execution_unknown"),
    ("prepared", False, False, False, "steering_superseded"),
    ("acknowledged", False, False, False, "steering_superseded"),
])
async def test_mcp_write_receipts_survive_steering_without_promoting_unconfirmed_results(phase, readonly, receipt, prior_success, expected):
    from private_agent_local.core_adapter import LocalRunAdapter
    from private_agent_local.tool_registry import REGISTRY

    call = ToolCall(id="current-call", name="call_mcp_tool", arguments={})
    confirmed = {"result": {"content": [{"type": "text", "text": "已完成一项写入"}]}, "untrusted": True}
    execution = {"tool_call_id": call.id, "tool_name": call.name,
                 "mcp_call": {"phase": phase, "readonly": readonly}, "output": confirmed if receipt else None}
    run = {"generation": 1, "recovery_contract_version": "1.0", "executions": [execution]}

    async def boundary(current):
        assert current is run

    adapter = object.__new__(LocalRunAdapter)
    adapter.run = run
    adapter.response_generation = 0
    adapter.response_execution_offset = 0
    adapter.owner = SimpleNamespace(registry=REGISTRY, controls=SimpleNamespace(boundary=boundary))
    prior = ToolResult(tool_call_id=call.id, name=call.name, success=prior_success,
                       output={"from_model": "不能作为确认回执"} if prior_success else None,
                       error=None if prior_success else "旧结果", error_code=None if prior_success else "steering_superseded")
    result = await adapter._finalize_result(call, prior)
    if expected == "acknowledged":
        assert result.success and result.error_code is None
        assert result.output["result"] == confirmed["result"]
        assert result.output["goal_changed"] is True and "重复执行" in result.output["notice"]
        assert "from_model" not in result.output
    else:
        assert not result.success and result.error_code == expected and result.output is None
    assert execution["output"] == (confirmed if receipt else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("reused_id", [False, True])
async def test_mcp_receipt_for_another_call_or_response_cannot_authorize_current_success(reused_id):
    from private_agent_local.core_adapter import LocalRunAdapter
    from private_agent_local.tool_registry import REGISTRY

    async def boundary(run):
        pass

    call = ToolCall(id="new-call", name="call_mcp_tool", arguments={})
    adapter = object.__new__(LocalRunAdapter)
    adapter.run = {"generation": 1, "recovery_contract_version": "1.0", "executions": [
        {"tool_call_id": call.id if reused_id else "old-call", "tool_name": call.name,
         "mcp_call": {"phase": "acknowledged", "readonly": False}, "output": {"result": "old"}}]}
    adapter.response_generation = 0
    adapter.response_execution_offset = 1 if reused_id else 0
    adapter.owner = SimpleNamespace(registry=REGISTRY, controls=SimpleNamespace(boundary=boundary))
    result = await adapter._finalize_result(call, ToolResult(tool_call_id=call.id, name=call.name, success=False, error="已取消"))
    assert not result.success and result.error_code == "steering_superseded" and result.output is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,readonly", [("acknowledged", False), ("dispatched", False), ("acknowledged", True)])
async def test_mcp_steering_finalization_reaches_next_model_context(phase, readonly):
    from private_agent_local.core_adapter import LocalRunAdapter
    from private_agent_local.tool_registry import REGISTRY

    call = ToolCall(id="external-call", name="call_mcp_tool", arguments={})
    run = {"generation": 0, "recovery_contract_version": "1.0", "executions": []}
    receipt = {"result": {"structured_content": {"completed_count": 1}}, "untrusted": True}
    recorded = []

    async def boundary(current):
        assert current is run

    async def dispatch(current, **kwargs):
        assert current.id == call.id
        run["executions"].append({"tool_call_id": call.id, "tool_name": call.name,
                                  "mcp_call": {"phase": phase, "readonly": readonly}, "output": receipt})
        run["generation"] += 1
        return ToolResult(tool_call_id=call.id, name=call.name, success=False, error="追加约束中断了连接回收", error_code="steering_superseded")

    async def record(message):
        recorded.append(message)

    adapter = object.__new__(LocalRunAdapter)
    adapter.run, adapter.response_generation = run, 0
    adapter.response_execution_offset = 0
    adapter.owner = SimpleNamespace(registry=REGISTRY, controls=SimpleNamespace(boundary=boundary))
    dispatcher = SimpleNamespace(execute=dispatch, finalize_result=adapter._finalize_result)
    model = Model((call,))
    result = await AgentRuntime(model, dispatcher, context_sink=record).run(
        [ModelMessage(role="user", content="执行一次外部操作")],
        tool_definitions=[ModelToolDefinition(name=call.name, description="受控外部工具", input_schema={"type": "object", "properties": {}})])
    assert result.status.value == "completed" and len(run["executions"]) == 1
    next_result = next(message for message in model.requests[1].messages if message.role == "tool")
    committed = next(message for message in recorded if message.role == "tool")
    assert committed == next_result
    body = json.loads(next_result.content)
    if phase == "acknowledged" and not readonly:
        assert body["success"] is True and body["output"]["result"] == receipt["result"]
        assert body["output"]["goal_changed"] is True
    else:
        assert body["success"] is False
        assert body["error_code"] == ("execution_unknown" if phase == "dispatched" else "steering_superseded")


class Model:
    def __init__(self, calls):
        self.calls, self.requests = calls, []

    async def complete(self, request, **kwargs):
        self.requests.append(request)
        return ModelResponse(tool_calls=self.calls) if len(self.requests) == 1 else ModelResponse(text="done")


def definitions():
    return [ModelToolDefinition(name=name, description=name, input_schema={"type": "object", "properties": {}})
            for name in ("read", "write")]


@pytest.mark.asyncio
async def test_read_batches_overlap_cap_two_and_writes_form_a_barrier():
    active, peak, history = set(), 0, []
    first_pair = asyncio.Event()

    class Dispatcher:
        async def execute(self, call, **kwargs):
            nonlocal peak
            if call.name == "write":
                assert not active
            active.add(call.id)
            peak = max(peak, len(active))
            history.append(("start", call.id))
            try:
                if call.id in {"a", "b"}:
                    if {"a", "b"} <= active:
                        first_pair.set()
                    await asyncio.wait_for(first_pair.wait(), 1)
                    if call.id == "a":
                        await asyncio.sleep(0.01)
                if call.id == "c":
                    raise ValueError("单项读取失败")
                return ToolResult(tool_call_id=call.id, name=call.name, success=True, output={"id": call.id})
            finally:
                history.append(("end", call.id))
                active.remove(call.id)

    calls = tuple(ToolCall(id=key, name=name, arguments={}) for key, name in
                  [("a", "read"), ("b", "read"), ("c", "read"), ("d", "write"), ("e", "read")])
    model = Model(calls)
    result = await AgentRuntime(model, Dispatcher(), parallel_tool_names=frozenset({"read"})).run(
        [ModelMessage(role="user", content="test")], tool_definitions=definitions())
    assert result.status.value == "completed" and peak == 2
    assert history.index(("end", "a")) < history.index(("start", "d")) < history.index(("start", "e"))
    messages = [item for item in model.requests[1].messages if item.role == "tool"]
    assert [item.tool_call_id for item in messages] == ["a", "b", "c", "d", "e"]
    assert "单项读取失败" in messages[2].content
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))


@pytest.mark.asyncio
async def test_cancel_reclaims_all_reads_and_never_starts_following_write():
    active, closed = set(), set()
    entered = asyncio.Event()
    token = CancellationToken()

    class Dispatcher:
        async def execute(self, call, **kwargs):
            assert call.name == "read"
            active.add(call.id)
            if len(active) == 2:
                entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.add(call.id)
                active.remove(call.id)

    calls = tuple(ToolCall(id=key, name=name, arguments={}) for key, name in
                  [("a", "read"), ("b", "read"), ("c", "write")])
    task = asyncio.create_task(AgentRuntime(Model(calls), Dispatcher(), parallel_tool_names=frozenset({"read"})).run(
        [ModelMessage(role="user", content="test")], tool_definitions=definitions(), cancellation=token))
    await asyncio.wait_for(entered.wait(), 1)
    token.cancel()
    result = await asyncio.wait_for(task, 1)
    assert result.status.value == "cancelled" and not active and closed == {"a", "b"}
    assert not any(step.status.value == "running" for step in result.steps)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_finished", [False, True])
async def test_local_steer_cancels_both_reads_without_retaining_old_results(tmp_path, monkeypatch, first_finished):
    from test_local_executor import close, response, setup, until
    from test_local_recovery import control

    from private_agent_local.runtime import TERMINAL

    api = await setup(tmp_path)
    app, client, server, root, body = api
    active, closed = set(), set()
    entered = asyncio.Event()
    owner = app.state.desktop.runtime
    original = owner.tool

    async def controlled(run, path, call):
        if call["name"] != "read_code_file":
            return await original(run, path, call)
        active.add(call["id"])
        if len(active) == 2:
            entered.set()
        try:
            if first_finished and call["id"] == "a":
                await entered.wait()
                return {"content": "不得进入新目标上下文的旧结果"}
            await asyncio.Event().wait()
        finally:
            active.remove(call["id"])
            closed.add(call["id"])

    monkeypatch.setattr(owner, "tool", controlled)
    server.responses = [response(*[{"id": key, "name": "read_code_file", "arguments": {"rel_path": "a.txt"}}
                                  for key in ("a", "b")]), response(text="已根据新的约束重新规划")]
    try:
        created = await client.post("/agent-runs", json={**body, "recovery_contract_version": "1.0"})
        run_id = created.json()["id"]
        await asyncio.wait_for(entered.wait(), 2)
        expected = 1 if first_finished else 2
        for _ in range(20):
            if len(owner.controls.tool_tasks[run_id]) == expected:
                break
            await asyncio.sleep(0)
        assert len(owner.controls.tool_tasks[run_id]) == expected
        await control(api, run_id, "steer", message="停止读取，仅解释")
        run = await until(client, run_id, TERMINAL)
        assert run["status"] == "completed" and closed == {"a", "b"} and not active
        assert run_id not in owner.controls.tool_tasks
        messages = owner.store.context.messages(body["session_id"])
        results = [message for message in messages if message.role == "tool"]
        assert len(results) == 2 and all("steering_superseded" in item.content for item in results)
        assert not owner.store.run(run_id)["pending_response"]["tool_calls"]
    finally:
        await close(app, client)
