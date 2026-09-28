"""真实本机事件、并发调用及晚到进程输出的步骤关联回归。"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

import pytest
from test_local_execution_sessions import finished
from test_local_execution_sessions import session as session
from test_local_executor import call, close, response, setup, until
from test_local_planning import plan_call, step

from private_agent_core.contracts import AgentEvent, AgentEventType, AgentStep
from private_agent_local import observer_steps
from private_agent_local.core_adapter import LocalRunAdapter
from private_agent_local.execution_tools import ExecArgs
from private_agent_local.runtime import TERMINAL
from private_agent_local.store import Store


def core_step(identifier, ordinal=1, *, kind="tool", call_id="same", status="running"):
    return AgentStep(id=identifier, ordinal=ordinal, kind=kind, status=status,
                     tool_call_id=call_id if kind == "tool" else None,
                     name="read_code_file" if kind == "tool" else "model", started_at=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_running_model_snapshot_and_public_events_keep_the_same_step(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    try:
        run_id = (await client.post("/agent-runs", json=body)).json()["id"]
        for _ in range(100):
            run = owner.store.run(run_id)
            if any(event["type"] == "model.requested" for event in run["events"]):
                break
            await asyncio.sleep(0.01)
        model, = run["steps"]
        assert model["kind"] == "model" and model["status"] == "running"
        assert all(event["step_id"] == model["id"] for event in run["events"] if event["type"].startswith("model."))
        server.responses = [response(text="已回答当前问题。")]
        server.block.set()
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed", final
        stored = owner.store.run(run_id)
        assert stored["steps"][0]["status"] == "succeeded"
        related = [event for event in stored["events"] if event["type"].startswith(("model.", "output.validation"))
                   or event["type"] == "decision.summary"]
        assert {event["step_id"] for event in related} == {model["id"]}
        assert all(event["step_id"] is None for event in stored["events"] if event["type"].startswith("run."))
        replay = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
        assert replay == stored["events"]
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_parallel_reads_finish_in_reverse_order_without_duplicate_or_crossed_events(tmp_path, monkeypatch):
    app, client, server, root, body = await setup(tmp_path)
    owner, entered, second_done, release = app.state.desktop.runtime, asyncio.Event(), asyncio.Event(), asyncio.Event()
    original, active = owner.tool, set()

    async def controlled(run, path, invocation):
        active.add(invocation["id"])
        if len(active) == 2:
            entered.set()
        await entered.wait()
        if invocation["id"] == "first":
            await release.wait()
        output = await original(run, path, invocation)
        if invocation["id"] == "second":
            second_done.set()
        return output

    monkeypatch.setattr(owner, "tool", controlled)
    try:
        (root / "sample.py").write_text("value = 1\n", encoding="utf-8")
        server.responses = [response(*[{**call("read_code_file", {"rel_path": "sample.py"}), "id": key}
                                       for key in ("first", "second")]), response(text="读取完成，value 为 1。")]
        run_id = (await client.post("/agent-runs", json={**body, "permission_mode": "readonly"})).json()["id"]
        await asyncio.wait_for(second_done.wait(), 3)
        waiting = owner.store.run(run_id)
        by_call = {item["tool_call_id"]: item for item in waiting["steps"] if item["kind"] == "tool"}
        assert set(by_call) == {"first", "second"}
        assert by_call["first"]["id"] != by_call["second"]["id"]
        assert by_call["first"]["status"] == "running"
        release.set()
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed", final
        stored = owner.store.run(run_id)
        for identifier, item in by_call.items():
            events = [event for event in stored["events"] if event["payload"].get("tool_call_id") == identifier]
            assert {event["step_id"] for event in events} == {item["id"]}
            for kind in ("tool.requested", "tool.started", "tool.completed"):
                assert sum(event["type"] == kind for event in events) == 1
        completed = [event["payload"]["tool_call_id"] for event in stored["events"] if event["type"] == "tool.completed"]
        assert completed == ["second", "first"]
        assert [event["sequence"] for event in stored["events"]] == list(range(1, len(stored["events"]) + 1))
    finally:
        release.set()
        await close(app, client)


@pytest.mark.asyncio
async def test_approval_wait_is_durable_and_denial_never_emits_started(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    try:
        (root / "sample.py").write_text("value = 1\n", encoding="utf-8")
        server.responses = [response(call("read_code_file", {"rel_path": "sample.py"})),
                            response(call("write_project_file", {"rel_path": "sample.py", "content": "value = 2\n"})),
                            response(text="用户拒绝修改，原文件保留。")]
        run_id = (await client.post("/agent-runs", json=body)).json()["id"]
        await until(client, run_id, {"waiting_approval"})
        stored = owner.store.run(run_id)
        write = next(item for item in stored["steps"] if item.get("name") == "write_project_file")
        approval, = stored["approvals"]
        assert write["status"] == "waiting_approval" and approval["step_id"] == write["id"]
        assert not any(event["type"] == "tool.started" and event["step_id"] == write["id"] for event in stored["events"])
        await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/reject")
        await until(client, run_id, TERMINAL)
        stored = owner.store.run(run_id)
        assert next(item for item in stored["steps"] if item["id"] == write["id"])["status"] == "failed"
        assert not any(event["type"] == "tool.started" and event["step_id"] == write["id"] for event in stored["events"])
        assert (root / "sample.py").read_text(encoding="utf-8") == "value = 1\n"
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_plan_context_is_frozen_and_separate_from_evidence(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    try:
        (root / "sample.py").write_text("value = 1\n", encoding="utf-8")
        server.responses = [response(plan_call()), response(call("read_code_file", {"rel_path": "sample.py"})),
                            response(plan_call(1, [step(status="completed", evidence_calls=["call-read_code_file"])])),
                            response(text="读取并核对完毕。")]
        run_id = (await client.post("/agent-runs", json={**body, "recovery_contract_version": "1.0",
                                                        "permission_mode": "readonly"})).json()["id"]
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "completed", final
        stored = owner.store.run(run_id)
        read = next(item for item in stored["steps"] if item.get("name") == "read_code_file")
        assert read["plan_context"] == {"item_key": "read", "plan_version": 1, "goal_version": 1, "source": "model_report"}
        assert read["id"] != read["plan_context"]["item_key"] and stored["plan"]["version"] == 2
        related = [event for event in stored["events"] if event["step_id"] == read["id"]]
        assert all(event["payload"]["plan_context"] == read["plan_context"] for event in related)
        assert stored["plan"]["items"][0]["evidence"][0]["tool_call_id"] == read["tool_call_id"]
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_late_process_output_uses_original_step_after_call_id_reuse(session):
    owner, run, root = session
    observer_steps.sync_steps(run, [core_step("original")])
    execution = {"id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()), "tool_call_id": "same",
                 "step_id": "original", "arguments_sha256": "a" * 64, "status": "running", "tool_name": "exec_command"}
    run["executions"].append(execution)
    owner.store.save_run(run)
    args = ExecArgs(argv=[sys.executable, "-c", "import time;time.sleep(0.1);print('late output')"],
                    execution_mode="trusted_project", network_policy="approved", yield_time_ms=10)
    with observer_steps.call_scope(run, "original"):
        record = await owner.execution_sessions.start(run, execution, root, root, args.argv, args)
    observer_steps.sync_steps(run, [core_step("original", status="succeeded"), core_step("new", 2)])
    owner.store.save_run(run)
    with observer_steps.call_scope(run, "new"):
        await finished(session, record["execution_id"])
        event = owner.store.emit(run, "execution.output", {"execution_id": execution["id"]}, lightweight=True)
        assert event["step_id"] == "original"
    events = [event for event in owner.store.events(run["id"]) if event["payload"].get("execution_id") == execution["id"]]
    assert any(event["type"] == "execution.terminal" for event in events)
    assert {event["step_id"] for event in events} == {"original"}
    assert owner.store.execution_sessions.get(execution["id"], run["session_id"])["step_id"] == "original"


@pytest.mark.asyncio
async def test_old_execution_and_control_events_do_not_borrow_an_active_step(session):
    owner, run, root = session
    observer_steps.sync_steps(run, [core_step("current")])
    run["executions"].append({"id": "legacy", "tool_call_id": "same", "status": "completed"})
    owner.store.save_run(run)
    with observer_steps.call_scope(run, "current"):
        old = owner.store.emit(run, "execution.output", {"execution_id": "legacy"}, lightweight=True)
        control = owner.store.emit(run, "run.paused", {})
        unrelated = observer_steps.current_metadata({"id": "different", "steps": run["steps"]})
    assert old["step_id"] is None and control["step_id"] is None and unrelated == {}
    with pytest.raises(ValueError, match="不属于当前运行"):
        owner.store.emit(run, "tool.completed", {}, step_id="foreign-step")
    assert len(owner.store.events(run["id"])) == 2


@pytest.mark.asyncio
async def test_core_event_failure_rolls_back_steps_and_event_together(tmp_path, monkeypatch):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    try:
        run = owner.create(body, launch=False)
        adapter = LocalRunAdapter(owner, run, root)
        before = owner.store.run(run["id"])
        original = owner.store.emit

        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("模拟事件写入后失败")

        monkeypatch.setattr(owner.store, "emit", fail_after_insert)
        event = AgentEvent(run_id=run["id"], sequence=run["last_event_sequence"] + 1,
                           type=AgentEventType.MODEL_STARTED, step_id="new")
        with pytest.raises(OSError, match="模拟事件"):
            await adapter.emit_with_steps(event, (core_step("new", kind="model"),))
        after = owner.store.run(run["id"])
        assert after["steps"] == before["steps"] == run["steps"]
        assert after["events"] == before["events"] == run["events"]
        monkeypatch.setattr(owner.store, "emit", original)
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_cancel_closes_both_parallel_steps_without_assigning_control_to_either(tmp_path, monkeypatch):
    app, client, server, root, body = await setup(tmp_path)
    owner, entered, active, closed = app.state.desktop.runtime, asyncio.Event(), set(), set()

    async def wait_for_cancel(run, path, invocation):
        active.add(invocation["id"])
        if len(active) == 2:
            entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.add(invocation["id"])

    monkeypatch.setattr(owner, "tool", wait_for_cancel)
    try:
        server.responses = [response(*[{**call("read_code_file", {"rel_path": "sample.py"}), "id": key}
                                       for key in ("first", "second")])]
        run_id = (await client.post("/agent-runs", json={**body, "recovery_contract_version": "1.0",
                                                        "permission_mode": "readonly"})).json()["id"]
        await asyncio.wait_for(entered.wait(), 3)
        waiting = owner.store.run(run_id)
        assert len([item for item in waiting["steps"] if item["kind"] == "tool" and item["status"] == "running"]) == 2
        await client.post(f"/agent-runs/{run_id}/cancel")
        final = await until(client, run_id, TERMINAL)
        assert final["status"] == "cancelled" and closed == {"first", "second"}
        stored = owner.store.run(run_id)
        assert all(item["status"] == "cancelled" for item in stored["steps"] if item["kind"] == "tool")
        assert all(event["step_id"] is None for event in stored["events"] if event["type"].startswith(("run.", "control.")))
    finally:
        await close(app, client)


def test_restart_keeps_known_steps_but_marks_unfinished_invocations_unknown(tmp_path):
    path = tmp_path / "observer.sqlite3"
    store = Store(path)
    run = {"id": "unfinished", "status": "waiting_approval", "approvals": [{"status": "pending"}]}
    observer_steps.sync_steps(run, [core_step("finished", status="succeeded"), core_step("waiting", 2, status="waiting_approval")])
    store.save_run(run)
    store.db.close()
    reopened = Store(path)
    try:
        restored = reopened.run(run["id"])
        assert restored["steps"][0]["status"] == "succeeded"
        assert restored["steps"][1]["status"] == "failed"
        assert restored["steps"][1]["completed_at"] and "结果未确认" in restored["steps"][1]["error"]
        assert restored["events"][-1]["step_id"] is None and restored["events"][-1]["payload"]["replayed"] is False
    finally:
        reopened.db.close()
