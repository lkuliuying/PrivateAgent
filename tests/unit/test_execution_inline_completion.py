"""使用合成执行事实和真实 SQLite，核对内联命令的完成证据边界。"""
import shlex
from types import SimpleNamespace

import pytest

from private_agent_core.coding_contracts import Requirement
from private_agent_core.completion import interpret_execution
from private_agent_local.completion import (
    LocalCompletionVerifier,
    script_exit_check,
    workspace_state,
)
from private_agent_local.store import Store

pytestmark = pytest.mark.asyncio


@pytest.fixture
def completion(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "task.py").write_text("print('fixture')\n", encoding="utf-8")
    store = Store(tmp_path / "state.sqlite3")
    project = store.create("project", {"status": "active", "authorized": True})
    workspace = store.create("workspace", {"project_id": project["id"], "root_path": str(root), "status": "active"})
    session = store.create("session", {"project_id": project["id"], "workspace_id": workspace["id"]})
    run = {"id": "inline-completion", "session_id": session["id"], "project_id": project["id"],
           "status": "running", "permission_mode": "workspace", "workspace_version": 0,
           "executions": [], "events": [], "approvals": [], "last_event_sequence": 0,
           "completion_requirements": []}
    owner = SimpleNamespace(store=store)
    verifier = LocalCompletionVerifier(owner, run, root)
    try:
        yield verifier, store, run, root
    finally:
        store.db.close()


def record_command(completion, argv, *, exit_code=0, kind="command", evidence_policy="exit", terminal=True):
    _, store, run, root = completion
    command = shlex.join(argv)
    run["completion_requirements"] = [Requirement(
        requirement_id="explicit-command", kind=kind, scope=command, description="核对用户指定命令",
        origin="user", evidence_policy=evidence_policy,
    ).model_dump()]
    result = interpret_execution(execution_id="execution-inline", operation_id="operation-inline", argv=argv,
                                 outcome="exited", exit_code=exit_code)
    execution = {"id": "execution-inline", "operation_id": "operation-inline", "tool_call_id": "call-inline",
                 "tool_name": "exec_command", "command": command, "execution_result": result.model_dump(mode="json"),
                 "workspace_digest": workspace_state(root)["digest"], "workspace_version": 0,
                 "workspace_changed": False, "status": "completed" if exit_code == 0 else "failed"}
    run["executions"].append(execution)
    store.save_run(run)
    store.emit(run, "tool.started", {"execution_id": execution["id"]})
    if terminal:
        event = store.emit(run, "tool.completed" if exit_code == 0 else "tool.failed", {"execution_id": execution["id"]})
        execution["source_sequence"] = event["sequence"]
    store.save_run(run)
    return execution


@pytest.mark.parametrize("argv", [
    ["python", "-c", "print('中文')\nprint(2)"],
    ["python3", "-B", "-c", "print(1)"],
    ["python", "-Icprint(1)"],
    ["node", "-e", "console.log(1)"],
    ["node", "--eval=console.log(1)"],
    ["node", "-p", "1 + 1"],
    ["node", "-pe", "1 + 1"],
    ["python", "task.py"],
    ["node", "task.js"],
])
async def test_explicit_command_exit_uses_persisted_evidence_without_claiming_business_success(completion, argv):
    execution = record_command(completion, argv)
    outcome = await completion[0].load_outcome("命令退出码为 0")
    assert script_exit_check(execution["command"])
    assert execution["execution_result"]["validation_outcome"] == "unknown"
    assert outcome.goal_outcome == "verified"
    assert outcome.verification_results[0].status == "passed"
    assert "不代表任意需求成立" in outcome.verification_results[0].message
    assert outcome.evidence_refs[0].execution_id == execution["id"]
    assert outcome.evidence_refs[0].source_sequence == execution["source_sequence"]


@pytest.mark.parametrize("exit_code", [1, 2])
async def test_inline_nonzero_exit_remains_failed(completion, exit_code):
    record_command(completion, ["python", "-c", "raise SystemExit(1)"], exit_code=exit_code)
    outcome = await completion[0].load_outcome("业务已完成")
    assert outcome.goal_outcome == "unmet"
    assert outcome.verification_results[0].status == "failed"
    assert f"退出码 {exit_code}" in outcome.verification_results[0].message


@pytest.mark.parametrize("kind,evidence_policy", [("command", "manual"), ("test", "test_exit")])
async def test_inline_exit_does_not_replace_manual_or_test_evidence(completion, kind, evidence_policy):
    record_command(completion, ["python", "-c", "print('passed')"], kind=kind, evidence_policy=evidence_policy)
    outcome = await completion[0].load_outcome("所有测试通过")
    assert outcome.goal_outcome == "unknown"
    assert outcome.verification_results[0].status == "unverified"


async def test_successful_inline_command_cannot_satisfy_additional_business_requirement(completion):
    _, store, run, _ = completion
    record_command(completion, ["node", "-p", "1 + 1"])
    run["completion_requirements"].append(Requirement(
        requirement_id="business", kind="manual", description="确认订单结算业务符合需求",
        origin="user", evidence_policy="manual",
    ).model_dump())
    store.save_run(run)
    outcome = await completion[0].load_outcome("业务已验证")
    assert outcome.goal_outcome == "unknown"
    assert [item.status for item in outcome.verification_results] == ["passed", "unverified"]


async def test_inline_exit_without_terminal_evidence_is_unverified(completion):
    record_command(completion, ["python", "-c", "print(1)"], terminal=False)
    outcome = await completion[0].load_outcome("命令成功")
    assert outcome.goal_outcome == "unknown"
    assert outcome.verification_results[0].status == "unverified"
    assert not outcome.evidence_refs


async def test_inline_exit_evidence_expires_after_workspace_change(completion):
    record_command(completion, ["python", "-c", "print(1)"])
    (completion[3] / "task.py").write_text("print('changed')\n", encoding="utf-8")
    outcome = await completion[0].load_outcome("命令成功")
    assert outcome.goal_outcome == "unmet"
    assert outcome.verification_results[0].status == "failed"
    assert "过期" in outcome.verification_results[0].message


@pytest.mark.parametrize("argv", [
    ["python", "-m", "pytest", "--help"],
    ["python", "-m", "pytest", "--version"],
    ["python", "-m", "pytest", "--collect-only"],
    ["pytest", "--help"],
    ["python", "--version"],
    ["node", "--print=1 + 1"],
    ["node", "--print=check.js"],
    ["node", "-econsole.log(1)"],
])
async def test_diagnostic_or_unsupported_command_exit_does_not_verify(completion, argv):
    record_command(completion, argv)
    outcome = await completion[0].load_outcome("测试已通过")
    assert not script_exit_check(shlex.join(argv))
    assert outcome.goal_outcome == "unknown"
    assert outcome.verification_results[0].status == "unverified"


@pytest.mark.parametrize("command", ["", "python -c '", "python -c", "python -c ''"])
async def test_missing_or_malformed_inline_command_has_no_exit_rule(command):
    assert not script_exit_check(command)
