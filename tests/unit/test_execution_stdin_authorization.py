"""验证受限交互进程的审批复用、最终权限核对和实际输入回收。"""
import asyncio
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_execution_autonomy import permission
from test_execution_autonomy import session as session
from test_local_executor import call

pytestmark = pytest.mark.asyncio


def approved_execution(session, **changes):
    owner, run, _ = session
    record = {"execution_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
              "host_instance_id": str(uuid.uuid4()), "run_id": run["id"], "session_id": run["session_id"],
              "project_id": run["project_id"], "workspace_id": run["workspace_id"], "tool_call_id": "approved-start",
              "argv": ["python", "task.py"], "cwd": ".", "status": "running", "state_version": 2,
              "stdin_open": True, "tty": False, "execution_mode": "restricted", "network_policy": "none",
              "authorization_sha256": "a" * 64, "stopped": False, "last_output_sequence": 0,
              "total_output_bytes": 0, "dropped_bytes": 0, "retention": "run"}
    record.update(changes)
    owner.execution_sessions.store.save(record)
    run["approvals"].append({"id": str(uuid.uuid4()), "status": "consumed", "run_id": run["id"],
                             "tool_name": "request_execution", "tool_call_id": record["tool_call_id"],
                             "operation_id": record["operation_id"],
                             "preview": {"authorization_sha256": record["authorization_sha256"]}})
    owner.store.save_run(run)
    return record


def input_call(record, *, data="继续🙂\n", eof=False, version=None):
    return {**call("write_stdin", {"execution_id": record["execution_id"], "data": data, "eof": eof,
                                   "expected_state_version": record["state_version"] if version is None else version}),
            "id": str(uuid.uuid4())}


def capture_write(monkeypatch, owner):
    async def send(execution_id, session_id, data, close, version, *, before_send=None):
        if before_send is not None:
            before_send(owner.execution_sessions.store.get(execution_id, session_id))
        return {"status": "running", "state_version": 3, "stdin_open": True}

    write = AsyncMock(side_effect=send)
    monkeypatch.setattr(owner.execution_sessions, "write", write)
    return write


def change_after_identity(monkeypatch, owner, change):
    count = 0

    async def identity(token):
        nonlocal count
        count += 1
        if count == 2:
            change()
        return {"id": 1}

    monkeypatch.setattr(owner.cloud, "identity", identity)


@pytest.mark.parametrize("mode", ["workspace", "full_access"])
@pytest.mark.parametrize("start_tool", ["exec_command", "request_execution"])
@pytest.mark.parametrize("data,eof", [("继续🙂\n", False), ("", True)])
async def test_reuses_consumed_start_approval_in_same_restricted_run(session, monkeypatch, mode, start_tool, data, eof):
    owner, run, root = session
    permission(session, mode)
    record = approved_execution(session)
    run["approvals"][0]["tool_name"] = start_tool
    approve = AsyncMock(side_effect=AssertionError("已批准的受限进程输入不应重复审批"))
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    request = input_call(record, data=data, eof=eof)
    result = await owner.tool(run, root, request)
    assert "error" not in result
    approve.assert_not_awaited()
    write.assert_awaited_once()
    assert write.call_args.args == (record["execution_id"], run["session_id"], data, eof, 2)
    assert callable(write.call_args.kwargs["before_send"])
    event, = [item for item in run["events"] if item["type"] == "tool.auto_approved"]
    assert event["payload"]["policy_profile"] == "restricted-stdin"
    assert event["payload"]["execution_id"] == record["execution_id"]
    assert event["payload"]["authorization_sha256"] == record["authorization_sha256"]
    assert event["payload"]["grant_id"] == run.get("full_access_grant_id")
    assert event["payload"]["arguments_sha256"] == run["executions"][-1]["arguments_sha256"]


@pytest.mark.parametrize("change", [
    {"tty": True}, {"execution_mode": "trusted_project", "network_policy": "approved"},
    {"network_policy": "approved"}, {"authorization_sha256": None}, {"authorization_sha256": "short"},
    {"authorization_sha256": "x" * 64}, {"stopped": True}, {"workspace_id": -1}, {"project_id": -1},
    {"tool_call_id": None}, {"operation_id": None},
])
async def test_non_reusable_execution_requires_per_input_approval(session, monkeypatch, change):
    owner, run, root = session
    record = approved_execution(session, **change)
    approve = AsyncMock(return_value=False)
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    result = await owner.tool(run, root, input_call(record))
    assert "stdin 输入已拒绝" in result["error"]
    approve.assert_awaited_once()
    write.assert_not_awaited()


@pytest.mark.parametrize("change", [
    {"status": "pending"}, {"status": "rejected"}, {"status": "expired"}, {"status": "cancelled"},
    {"tool_name": "write_stdin"}, {"tool_call_id": "other-call"}, {"operation_id": "other-operation"},
    {"run_id": "other-run"}, {"preview": {}}, {"preview": {"authorization_sha256": "b" * 64}},
    {"invalidated_by_control": True},
])
async def test_missing_or_mismatched_original_approval_never_reuses_authorization(session, monkeypatch, change):
    owner, run, root = session
    record = approved_execution(session)
    run["approvals"][0].update(change)
    approve = AsyncMock(return_value=False)
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    result = await owner.tool(run, root, input_call(record))
    assert "stdin 输入已拒绝" in result["error"]
    approve.assert_awaited_once()
    write.assert_not_awaited()


async def test_confirm_permission_keeps_each_input_approval(session, monkeypatch):
    owner, run, root = session
    run["permission_mode"] = "confirm"
    record = approved_execution(session)
    approve = AsyncMock(return_value=True)
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    for text in ("first\n", "second\n"):
        result = await owner.tool(run, root, input_call(record, data=text))
        assert "error" not in result
    assert approve.await_count == write.await_count == 2
    assert not any(item["type"] == "tool.auto_approved" for item in run["events"])


async def test_other_run_in_same_session_cannot_reuse_original_approval(session, monkeypatch):
    owner, run, root = session
    record = approved_execution(session)
    other = {**run, "id": str(uuid.uuid4()), "events": [], "executions": [], "last_event_sequence": 0}
    owner.store.save_run(other)
    approve = AsyncMock(return_value=False)
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    result = await owner.tool(other, root, input_call(record))
    assert "stdin 输入已拒绝" in result["error"]
    approve.assert_awaited_once()
    write.assert_not_awaited()


async def test_foreign_session_execution_is_rejected_before_approval(session, monkeypatch):
    owner, run, root = session
    record = approved_execution(session, session_id=run["session_id"] + 100)
    approve = AsyncMock()
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    result = await owner.tool(run, root, input_call(record))
    assert "不属于当前会话" in result["error"]
    approve.assert_not_awaited()
    write.assert_not_awaited()


@pytest.mark.parametrize("change", [{"state_version": 3}, {"stdin_open": False}, {"status": "exited"}, {"status": "unknown"}])
async def test_stale_or_closed_input_fails_before_approval(session, monkeypatch, change):
    owner, run, root = session
    record = approved_execution(session, **change)
    approve = AsyncMock()
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    result = await owner.tool(run, root, input_call(record, version=2))
    assert "状态已变化或 stdin 已关闭" in result["error"]
    approve.assert_not_awaited()
    write.assert_not_awaited()


@pytest.mark.parametrize("mode", ["workspace", "confirm"])
@pytest.mark.parametrize("change", [
    {"host_instance_id": "replacement-host"}, {"operation_id": "replacement-operation"},
    {"tool_call_id": "replacement-call"}, {"argv": ["node", "task.js"]}, {"cwd": "changed"},
    {"workspace_id": -1}, {"project_id": -1}, {"session_id": -1}, {"run_id": "replacement-run"},
    {"state_version": 3}, {"stdin_open": False},
    {"status": "exited"}, {"authorization_sha256": "b" * 64}, {"execution_mode": "trusted_project"},
    {"network_policy": "approved"}, {"tty": True}, {"stopped": True},
])
async def test_input_binding_is_rechecked_after_identity_or_approval(session, monkeypatch, mode, change):
    owner, run, root = session
    permission(session, mode)
    record = approved_execution(session)
    approve = AsyncMock(return_value=True)
    monkeypatch.setattr(owner, "approve", approve)
    write = capture_write(monkeypatch, owner)
    change_after_identity(monkeypatch, owner, lambda: owner.execution_sessions.store.save({**record, **change}))
    result = await owner.tool(run, root, input_call(record))
    assert "核对期间变化" in result["error"]
    assert approve.await_count == (mode == "confirm")
    write.assert_not_awaited()


async def test_output_cursor_progress_does_not_invalidate_input_authorization(session, monkeypatch):
    owner, run, root = session
    record = approved_execution(session)
    change_after_identity(monkeypatch, owner, lambda: owner.execution_sessions.store.append(record, [("stdout", "READY\n", 1)]))
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("输出推进不应要求重新审批")))
    write = capture_write(monkeypatch, owner)
    result = await owner.tool(run, root, input_call(record))
    assert "error" not in result
    write.assert_awaited_once()


@pytest.mark.parametrize("mode", ["workspace", "confirm"])
@pytest.mark.parametrize("change", ["readonly", "cancel", "pause", "generation", "project", "approval"])
async def test_controls_and_authorization_changes_prevent_input(session, monkeypatch, mode, change):
    owner, run, root = session
    permission(session, mode)
    record = approved_execution(session)
    monkeypatch.setattr(owner, "approve", AsyncMock(return_value=True))
    write = capture_write(monkeypatch, owner)

    def mutate():
        if change == "readonly":
            run["permission_mode"] = "readonly"
        elif change == "cancel":
            run["cancel_requested_at"] = "fixture-cancel"
        elif change == "pause":
            run["pause_requested"] = True
        elif change == "generation":
            run["generation"] = run.get("generation", 0) + 1
        elif change == "project":
            owner.project_context_set, owner.active_project_id = True, run["project_id"] + 100
        else:
            run["approvals"][0]["status"] = "cancelled"

    change_after_identity(monkeypatch, owner, mutate)
    if change == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await owner.tool(run, root, input_call(record))
    else:
        result = await owner.tool(run, root, input_call(record))
        if change == "approval" and mode == "confirm":
            assert "error" not in result
            write.assert_awaited_once()
            return
        assert result.get("error")
    write.assert_not_awaited()


@pytest.mark.parametrize("during_wait", [False, True])
async def test_revoked_full_access_grant_prevents_input(session, monkeypatch, during_wait):
    owner, run, root = session
    permission(session, "full_access")
    record = approved_execution(session)
    write = capture_write(monkeypatch, owner)
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("已撤销权限不应转为审批绕过")))

    def revoke():
        owner.store.revoke_grant(run["full_access_grant_id"], "fixture")

    if during_wait:
        change_after_identity(monkeypatch, owner, revoke)
    else:
        revoke()
    result = await owner.tool(run, root, input_call(record))
    assert result.get("error")
    write.assert_not_awaited()


@pytest.mark.parametrize("during_wait", [False, True])
@pytest.mark.parametrize("limits", [
    {"commands_forbidden": True}, {"tests_forbidden": True}, {"writes_forbidden": True},
    {"preview_only": True}, {"write_scopes": [["allowed/"]]}, {"access_scopes": [["allowed/"]]},
    {"forbidden_write_paths": ["protected.txt"]},
])
async def test_task_restrictions_block_reused_input(session, monkeypatch, during_wait, limits):
    owner, run, root = session
    record = approved_execution(session)
    write = capture_write(monkeypatch, owner)
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("审批不能解除用户限制")))

    def restrict():
        run["completion_policy"] = limits

    if during_wait:
        change_after_identity(monkeypatch, owner, restrict)
    else:
        restrict()
    result = await owner.tool(run, root, input_call(record))
    assert result["error_code"] == "user_constraint"
    write.assert_not_awaited()


@pytest.mark.parametrize("collection", ["denied_operations", "uncertain_operations"])
@pytest.mark.parametrize("during_wait", [False, True])
async def test_denied_and_unknown_commands_cannot_continue_through_stdin(session, monkeypatch, collection, during_wait):
    owner, run, root = session
    record = approved_execution(session)
    write = capture_write(monkeypatch, owner)
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("拒绝或未知操作不能重复申请")))

    def prohibit():
        run[collection] = [{"scope": {"kind": "command"}}]

    if during_wait:
        change_after_identity(monkeypatch, owner, prohibit)
    else:
        prohibit()
    result = await owner.tool(run, root, input_call(record))
    assert "已拒绝或结果未知" in result["error"]
    write.assert_not_awaited()


@pytest.mark.parametrize("change", [
    "readonly", "confirm", "approval", "host", "operation", "network", "generation", "cancel",
    "grant", "constraint", "denied", "unknown",
])
async def test_input_lock_rechecks_authorization_and_actual_host_before_sending(session, monkeypatch, change):
    owner, run, root = session
    if change == "grant":
        permission(session, "full_access")
    record = approved_execution(session)
    client = SimpleNamespace(write_stdin=AsyncMock())
    lock = asyncio.Lock()
    owner.execution_sessions.slots[record["execution_id"]] = {
        "record": record, "client": client, "nonce": "fixture-nonce", "lock": lock, "run": run, "root": root}
    owner.live[run["id"]] = run
    waiting = asyncio.Event()
    original = owner.execution_sessions.write

    async def write(*args, **kwargs):
        waiting.set()
        return await original(*args, **kwargs)

    monkeypatch.setattr(owner.execution_sessions, "write", write)
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("已撤销或失效的输入不能重新审批绕过")))
    await lock.acquire()
    pending = asyncio.create_task(owner.tool(run, root, input_call(record)))
    try:
        await asyncio.wait_for(waiting.wait(), 3)
        if change in {"readonly", "confirm"}:
            run["permission_mode"] = change
        elif change == "approval":
            run["approvals"][0]["status"] = "cancelled"
        elif change in {"host", "operation", "network"}:
            # 只修改内存槽位，持久记录仍匹配旧审批，确保实际发送对象也被核对。
            key = {"host": "host_instance_id", "operation": "operation_id", "network": "network_policy"}[change]
            record[key] = "approved" if change == "network" else "replacement"
        elif change == "generation":
            run["generation"] = run.get("generation", 0) + 1
        elif change == "cancel":
            run["cancel_requested_at"] = "fixture-cancel"
        elif change == "grant":
            owner.store.revoke_grant(run["full_access_grant_id"], "fixture")
        elif change == "constraint":
            run["completion_policy"] = {"tests_forbidden": True}
        else:
            collection = "denied_operations" if change == "denied" else "uncertain_operations"
            run[collection] = [{"scope": {"kind": "command"}}]
        lock.release()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            result = await pending
            assert result.get("error"), result
        client.write_stdin.assert_not_awaited()
        assert not any(item["type"] == "tool.auto_approved" for item in run["events"])
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        owner.execution_sessions.slots.pop(record["execution_id"], None)
        owner.live.pop(run["id"], None)


async def test_concurrent_old_state_version_sends_input_only_once(session, monkeypatch):
    owner, run, root = session
    record = approved_execution(session)
    client = SimpleNamespace(write_stdin=AsyncMock())
    slot = {"record": record, "client": client, "nonce": "fixture-nonce", "lock": asyncio.Lock(),
            "run": run, "root": root}
    owner.execution_sessions.slots[record["execution_id"]] = slot
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("受限输入不应重复审批")))
    entered = asyncio.Event()
    identity_calls = 0

    async def identity(token):
        nonlocal identity_calls
        identity_calls += 1
        if identity_calls == 4:
            entered.set()
        return {"id": 1}

    monkeypatch.setattr(owner.cloud, "identity", identity)
    await slot["lock"].acquire()
    pending = [asyncio.create_task(owner.tool(run, root, input_call(record))) for _ in range(2)]
    try:
        await asyncio.wait_for(entered.wait(), 3)
        slot["lock"].release()
        results = await asyncio.gather(*pending)
        assert sum("error" not in result for result in results) == 1
        assert "状态已变化" in next(result["error"] for result in results if "error" in result)
        client.write_stdin.assert_awaited_once()
        assert owner.execution_sessions.store.get(record["execution_id"], run["session_id"])["state_version"] == 3
        assert len([item for item in run["events"] if item["type"] == "tool.auto_approved"]) == 1
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        owner.execution_sessions.slots.pop(record["execution_id"], None)


async def test_real_restricted_interactive_process_reuses_start_approval_and_releases_sandbox(session, monkeypatch):
    owner, run, root = session
    monkeypatch.setenv("PATH", str(Path(sys._base_executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    (root / "interactive.py").write_text(
        "import sys\nprint('READY', flush=True)\nprint(sys.stdin.read(), end='', flush=True)\n", encoding="utf-8")
    start = asyncio.create_task(owner.tool(run, root, call("request_execution", {
        "argv": ["python", "interactive.py"], "stdin": True, "yield_time_ms": 1000, "timeout_ms": 30_000})))
    try:
        async with asyncio.timeout(5):
            while not owner.decisions:
                if start.done():
                    pytest.fail(f"命令未进入启动审批：{start.result()}")
                await asyncio.sleep(0.01)
        approval_id, = owner.decisions
        owner.decide(run["id"], approval_id, True)
        result = await asyncio.wait_for(start, 180)
        assert "error" not in result, result
        assert result["status"] == "running" and result["execution_mode"] == "restricted"
        assert result["network_policy"] == "none" and result["tty"] is False
        assert len(run["approvals"]) == 1 and run["approvals"][0]["status"] == "consumed"
        first = await asyncio.wait_for(owner.tool(run, root, input_call(result, data="第一段🙂\n")), 5)
        assert "error" not in first, first
        second = await asyncio.wait_for(owner.tool(run, root, input_call(first, data="第二段\n", eof=True)), 5)
        assert "error" not in second, second
        cursor = result["next_cursor"]
        async with asyncio.timeout(180):
            while True:
                final = await owner.execution_sessions.read(result["execution_id"], run["session_id"], after=cursor, wait_ms=1000)
                cursor = final["next_cursor"]
                if final["status"] not in {"starting", "running"}:
                    break
        assert final["status"] == "exited" and final["exit_code"] == 0 and final["stopped"]
        final = await owner.execution_sessions.read(result["execution_id"], run["session_id"])
        output = "".join(chunk["data"] for chunk in final["chunks"] if chunk["stream"] == "stdout")
        assert "READY" in output and "第一段🙂\n第二段\n" in output.replace("\r\n", "\n")
        assert len(run["approvals"]) == 1
        assert len([item for item in run["events"] if item["type"] == "tool.auto_approved"]) == 2
        assert not owner.execution_sessions.slots
        assert not list((owner.store.path.parent / "sandbox-leases").glob("*.json"))
    finally:
        if not start.done():
            start.cancel()
        await asyncio.gather(start, return_exceptions=True)
