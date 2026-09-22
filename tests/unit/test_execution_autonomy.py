"""通过真实工具入口验证普通命令的自动授权及最后执行边界。"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from test_local_executor import call

from private_agent_core.execution.exec_host_client import ExecHostClient
from private_agent_local import execution_tools, files, policy
from private_agent_local.runtime import Runtime
from private_agent_local.store import Store

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def session(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "task.py").write_text("print('autonomous execution')\n", encoding="utf-8")
    store = Store(tmp_path / "state.sqlite3")
    project = store.create("project", {"status": "active", "authorized": True})
    workspace = store.create("workspace", {"project_id": project["id"], "root_path": str(root), "status": "active"})
    item = store.create("session", {"project_id": project["id"], "workspace_id": workspace["id"]})
    run = {"id": str(uuid.uuid4()), "project_id": project["id"], "workspace_id": workspace["id"], "session_id": item["id"],
           "permission_mode": "workspace", "execution_contract_version": "1.0", "status": "running", "events": [],
           "executions": [], "approvals": [], "last_event_sequence": 0, "root_identity": files.file_identity(root),
           "tool_call_count": 0, "output": None}
    store.save_run(run)
    identity = type("Identity", (), {"identity": AsyncMock(return_value={"id": 1})})()
    # 使用独立的合成令牌，避免与普通 fixture 文件名冲突而触发真实秘密过滤。
    owner = Runtime(store, identity, "session-" + uuid.uuid4().hex)
    try:
        yield owner, run, root
    finally:
        await owner.close()


def permission(session, mode):
    owner, run, _ = session
    run["permission_mode"] = mode
    if mode == "full_access":
        grant = owner.store.grant(run["session_id"], run["project_id"],
                                  (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        run["full_access_grant_id"] = grant["id"]


def capture_start(monkeypatch, owner):
    async def result(run, execution, root, cwd, argv, args, **kwargs):
        return {"execution_id": execution["id"], "status": "running", "dropped_bytes": 0}
    start = AsyncMock(side_effect=result)
    monkeypatch.setattr(owner.execution_sessions, "start", start)
    return start


@pytest.mark.parametrize("mode", ["workspace", "full_access"])
async def test_ordinary_command_uses_project_permission_and_bound_audit(session, monkeypatch, mode):
    owner, run, root = session
    permission(session, mode)
    approval = AsyncMock(side_effect=AssertionError("普通受限命令不应再次请求审批"))
    monkeypatch.setattr(owner, "approve", approval)
    start = capture_start(monkeypatch, owner)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "task.py"]}))
    assert "error" not in result
    approval.assert_not_awaited()
    start.assert_awaited_once()
    options = start.call_args.args[5]
    assert (options.execution_mode, options.network_policy, options.tty, options.stdin, options.retention) == (
        "restricted", "none", False, False, "run")
    event = next(item for item in run["events"] if item["type"] == "tool.auto_approved")
    record = run["executions"][-1]
    assert event["payload"]["authorization_sha256"] == record["authorization_sha256"]
    assert event["payload"]["arguments_sha256"] == record["arguments_sha256"]
    assert event["payload"]["grant_id"] == run.get("full_access_grant_id")
    assert "系统沙箱" in event["payload"]["preview"]["reason"]
    assert record["workspace_digest"] and len(record["authorization_sha256"]) == 64
    assert not run["approvals"]


@pytest.mark.parametrize("mode,name,options", [
    ("confirm", "exec_command", {}),
    ("workspace", "request_execution", {}),
    ("full_access", "request_execution", {}),
    ("workspace", "exec_command", {"stdin": True}),
    ("workspace", "exec_command", {"retention": "session"}),
    ("workspace", "exec_command", {"execution_mode": "trusted_project", "network_policy": "approved"}),
    ("full_access", "exec_command", {"execution_mode": "trusted_project", "network_policy": "approved", "tty": True}),
])
async def test_confirm_and_advanced_calls_still_request_approval(session, monkeypatch, mode, name, options):
    owner, run, root = session
    permission(session, mode)
    approval = AsyncMock(return_value=True)
    monkeypatch.setattr(owner, "approve", approval)
    start = capture_start(monkeypatch, owner)
    result = await owner.tool(run, root, call(name, {"argv": ["python", "task.py"], **options}))
    assert "error" not in result
    approval.assert_awaited_once()
    start.assert_awaited_once()
    assert not any(item["type"] == "tool.auto_approved" for item in run["events"])


async def test_stdin_retains_per_input_approval(session, monkeypatch):
    owner, run, root = session
    monkeypatch.setattr(owner.execution_sessions.store, "get", lambda *args: {"argv": ["python", "task.py"], "cwd": "."})
    approval, write = AsyncMock(return_value=False), AsyncMock()
    monkeypatch.setattr(owner, "approve", approval)
    monkeypatch.setattr(owner.execution_sessions, "write", write)
    result = await owner.tool(run, root, call("write_stdin", {
        "execution_id": "fixture-execution", "data": "continue", "expected_state_version": 1}))
    assert "stdin 输入已拒绝" in result["error"]
    approval.assert_awaited_once()
    write.assert_not_awaited()


@pytest.mark.parametrize("collection", ["denied_operations", "uncertain_operations"])
@pytest.mark.parametrize("during_wait", [False, True])
async def test_prior_or_new_unknown_and_denied_commands_cannot_be_replayed(session, monkeypatch, collection, during_wait):
    owner, run, root = session
    def prohibit():
        run[collection] = [{"scope": {"kind": "command"}}]
    if during_wait:
        calls = 0
        async def identity(token):
            nonlocal calls
            calls += 1
            if calls == 2:
                prohibit()
            return {"id": 1}
        monkeypatch.setattr(owner.cloud, "identity", identity)
    else:
        prohibit()
    start = capture_start(monkeypatch, owner)
    approval = AsyncMock()
    monkeypatch.setattr(owner, "approve", approval)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "task.py"]}))
    assert "已拒绝或结果未知" in result["error"]
    start.assert_not_awaited()
    approval.assert_not_awaited()


@pytest.mark.parametrize("mode", ["workspace", "confirm"])
@pytest.mark.parametrize("changed", ["script", "environment", "program"])
async def test_authorization_rechecks_workspace_environment_and_program(session, monkeypatch, tmp_path, mode, changed):
    owner, run, root = session
    permission(session, mode)
    program = tmp_path / "fixture.exe"
    program.write_bytes(b"fixture-v1")
    if changed == "program":
        monkeypatch.setattr(files, "prepare_process", lambda argv: ([str(program), *argv[1:]], {}))
    calls = 0
    async def identity(token):
        nonlocal calls
        calls += 1
        if calls == 2:
            if changed == "script":
                (root / "task.py").write_text("print('changed')\n", encoding="utf-8")
            elif changed == "environment":
                monkeypatch.setenv("LANG", "fixture-changed-language")
            else:
                program.write_bytes(b"fixture-v2")
        return {"id": 1}
    monkeypatch.setattr(owner.cloud, "identity", identity)
    approval = AsyncMock(return_value=True)
    monkeypatch.setattr(owner, "approve", approval)
    start = capture_start(monkeypatch, owner)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "task.py"]}))
    assert "变化" in result["error"]
    assert approval.await_count == (mode == "confirm")
    start.assert_not_awaited()
    assert not any(item["type"] == "tool.auto_approved" for item in run["events"])


@pytest.mark.parametrize("mode", ["workspace", "confirm"])
@pytest.mark.parametrize("changed", ["constraint", "generation", "cancel"])
async def test_final_control_and_task_guards_follow_both_authorization_paths(session, monkeypatch, mode, changed):
    owner, run, root = session
    permission(session, mode)
    calls = 0
    async def identity(token):
        nonlocal calls
        calls += 1
        if calls == 2:
            if changed == "constraint":
                run["completion_policy"] = {"commands_forbidden": True}
            elif changed == "generation":
                run["generation"] = run.get("generation", 0) + 1
            else:
                run["cancel_requested_at"] = "fixture-cancellation"
        return {"id": 1}
    monkeypatch.setattr(owner.cloud, "identity", identity)
    monkeypatch.setattr(owner, "approve", AsyncMock(return_value=True))
    start = capture_start(monkeypatch, owner)
    request = call("exec_command", {"argv": ["python", "task.py"]})
    if changed == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await owner.tool(run, root, request)
    else:
        result = await owner.tool(run, root, request)
        assert result.get("error")
        if changed == "constraint":
            assert result["error_code"] == "user_constraint"
    start.assert_not_awaited()
    assert not any(item["type"] in {"tool.started", "tool.auto_approved"} for item in run["events"])


@pytest.mark.parametrize("revoke_during_wait", [False, True])
async def test_full_access_never_bypasses_missing_or_revoked_grant(session, monkeypatch, revoke_during_wait):
    owner, run, root = session
    permission(session, "full_access")
    grant_id = run["full_access_grant_id"]
    if revoke_during_wait:
        calls = 0
        async def identity(token):
            nonlocal calls
            calls += 1
            if calls == 2:
                owner.store.revoke_grant(grant_id, "fixture")
            return {"id": 1}
        monkeypatch.setattr(owner.cloud, "identity", identity)
    else:
        run.pop("full_access_grant_id")
    start = capture_start(monkeypatch, owner)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "task.py"]}))
    assert result.get("error")
    start.assert_not_awaited()


@pytest.mark.parametrize("mode", ["readonly", "confirm", "workspace", "full_access"])
async def test_capabilities_report_current_approval_policy(session, monkeypatch, mode):
    owner, run, root = session
    permission(session, mode)
    monkeypatch.setattr(owner.execution_sessions, "capabilities", AsyncMock(return_value={"contract": {"execution": True}}))
    result = await owner.tool(run, root, call("get_execution_capabilities", {}))
    automatic = mode in {"workspace", "full_access"}
    assert result["approval_required"] is not automatic
    assert result["approval_policy"]["ordinary_restricted"] == ("policy" if automatic else "required")
    assert result["approval_policy"]["advanced_request"] == "required"
    assert result["approval_policy"]["stdin_input"] == ("policy" if automatic else "required")
    assert result["approval_policy"]["stdin_automatic_conditions"]["approved_start"] is True
    assert result["approval_policy"]["sandbox_unavailable"] == "reject_without_fallback"
    assert execution_tools.SPECS[0].approval == "policy"
    assert policy.execution_capabilities()["approval_required"] is True


async def test_auto_approved_command_executes_in_real_restricted_host(session, monkeypatch):
    owner, run, root = session
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("不应再次审批")))
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "task.py"], "yield_time_ms": 1000}))
    assert "error" not in result
    for _ in range(60):
        result = await owner.execution_sessions.read(result["execution_id"], run["session_id"], wait_ms=1000)
        if result["status"] not in {"starting", "running"}:
            break
    assert result["status"] == "exited" and result["exit_code"] == 0 and result["stopped"]
    record = owner.execution_sessions.store.get(result["execution_id"], run["session_id"])
    assert record["execution_mode"] == "restricted" and record["network_policy"] == "none"
    assert "autonomous execution" in run["executions"][-1]["output"]["stdout"]
    assert not owner.execution_sessions.slots


async def test_auto_approved_command_fails_closed_without_host_sandbox(session, monkeypatch):
    owner, run, root = session
    original = ExecHostClient.start
    async def unavailable(client):
        health = await original(client)
        return health.model_copy(update={"sandbox_available": False})
    monkeypatch.setattr(ExecHostClient, "start", unavailable)
    start_execution = AsyncMock(side_effect=AssertionError("缺少系统沙箱时不得启动目标进程"))
    monkeypatch.setattr(ExecHostClient, "start_execution", start_execution)
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("不得通过再次审批降级执行")))
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "task.py"]}))
    assert "受限执行需要独立沙箱协议" in result["error"]
    start_execution.assert_not_awaited()
    assert not owner.execution_sessions.slots
    assert owner.execution_sessions.list(run["session_id"])[0]["status"] == "failed"
