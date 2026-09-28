"""只读批次的并发上限、串行屏障、顺序和取消边界。"""
import asyncio

import pytest

from private_agent_core.contracts import (
    ModelMessage,
    ModelResponse,
    ModelToolDefinition,
    ToolCall,
    ToolResult,
)
from private_agent_core.runtime import AgentRuntime, CancellationToken


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
