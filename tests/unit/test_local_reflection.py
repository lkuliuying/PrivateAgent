"""反思记录只保留有来源的事实，覆盖恢复隔离、重复失败和原生命令去重。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from private_agent_core.completion import interpret_execution
from private_agent_core.contracts import ToolCall, ToolResult
from private_agent_local import reflection
from private_agent_local.tool_registry import REGISTRY


class Facts:
    def __init__(self, run):
        self.runs = {run["id"]: run}
        self.records = {}
        self.execution_sessions = self

    def run(self, run_id):
        return json.loads(json.dumps(self.runs[run_id]))

    def get(self, execution_id, session_id):
        record = self.records.get(execution_id)
        if not record or record["session_id"] != session_id:
            raise ValueError("执行不存在或不属于当前会话")
        return json.loads(json.dumps(record))


@pytest.fixture
def context():
    run = {"id": "run-1", "logical_task_id": "run-1", "session_id": 1, "workspace_id": 1,
           "recovery_contract_version": "1.0", "goal_version": 1, "workspace_version": 0,
           "executions": [], "events": []}
    return SimpleNamespace(store=Facts(run), registry=REGISTRY), run


def result(owner, run, *, name="read_code_file", arguments=None, code="invalid_tool_arguments", success=False,
           output=None, call_id=None, scope=None):
    ordinal = len(run["executions"]) + 1
    call = ToolCall(id=call_id or f"call-{ordinal}", name=name,
                    arguments=arguments if arguments is not None else {"rel_path": "missing.py"})
    execution = {"id": f"execution-{ordinal}", "tool_call_id": call.id, "tool_name": name,
                 "error_code": None if success else code, "source_sequence": ordinal}
    if scope:
        execution["scope"] = scope
    run["executions"].append(execution)
    run["events"].append({"sequence": ordinal, "type": "tool.completed" if success else "tool.failed",
                          "payload": {"execution_id": execution["id"]}})
    value = ToolResult(tool_call_id=call.id, name=name, success=success, output=output or {},
                       error_code=None if success else code, error=None if success else "工具失败；任意错误正文不进入纠错状态")
    state, feedback = reflection.observe(owner, run, call, value)
    if state is not None:
        run["reflection_state"] = state
    return feedback


def native(owner, run, identifier, *, argv=None, exit_code=1, outcome="exited", terminal=True):
    argv = argv or ["python", "-m", "pytest"]
    execution = {"id": identifier, "tool_call_id": "start-" + identifier, "tool_name": "exec_command",
                 "source_sequence": len(run["events"]) + 1}
    verdict = interpret_execution(execution_id=identifier, operation_id="operation-" + identifier,
                                  argv=argv, outcome=outcome, exit_code=exit_code).model_dump(mode="json")
    execution["execution_result"] = verdict
    run["executions"].append(execution)
    run["events"].append({"sequence": execution["source_sequence"], "type": "tool.failed",
                          "payload": {"execution_id": identifier}})
    owner.store.records[identifier] = {"execution_id": identifier, "run_id": run["id"],
        "session_id": run["session_id"], "workspace_id": run["workspace_id"], "tool_call_id": execution["tool_call_id"],
        "argv": argv, "cwd": ".", "stopped": True, "execution_result": verdict if terminal else None}


def test_legacy_does_not_create_state(context):
    owner, run = context
    run.pop("recovery_contract_version")
    assert result(owner, run) is None
    assert "reflection_state" not in run
    assert reflection.reset(run) is None
    assert not reflection.stalled(run) and not reflection.requires_review(run)


def test_failures_survive_successful_other_reads_and_changed_arguments(context):
    owner, run = context
    for index in range(4):
        feedback = result(owner, run, arguments={"rel_path": "missing.py", "start_line": index + 1})
        assert feedback["attempts"] == index + 1
        result(owner, run, name="list_project_directory", arguments={}, success=True)
    assert reflection.stalled(run)
    assert reflection.requires_review(run)
    assert len(run["reflection_state"]["entries"]) == 1
    assert reflection.guidance(run)["failures"][0]["retry_policy"] == "change_required"


def test_matching_success_and_workspace_progress_reset_cycle_but_keep_review_trigger(context):
    owner, run = context
    result(owner, run)
    result(owner, run)
    original = json.loads(json.dumps(run["reflection_state"]))
    result(owner, run, success=True)
    assert original["entries"][0]["status"] == "open"
    assert run["reflection_state"]["entries"][0]["status"] == "resolved"
    assert reflection.guidance(run) is None and reflection.requires_review(run)
    assert result(owner, run)["attempts"] == 1
    run["workspace_version"] += 1
    assert result(owner, run)["attempts"] == 1
    assert reflection.requires_review(run) and not reflection.stalled(run)
    run["goal_version"] += 1
    assert not reflection.requires_review(run) and reflection.guidance(run) is None
    assert result(owner, run)["attempts"] == 1
    assert run["reflection_state"]["correctable_failures"] == 1


def test_entries_are_bounded_and_contain_no_arguments_output_or_errors(context):
    owner, run = context
    secret = "sk-reflection-secret-with-many-characters"
    for index in range(30):
        result(owner, run, arguments={"rel_path": f"{secret}-{index}"}, call_id=secret + str(index),
               output={"stderr": secret, "api_key": secret, "error_code": secret})
    state = run["reflection_state"]
    assert len(state["entries"]) == 16
    assert secret not in json.dumps(state)
    assert "任意错误正文" not in json.dumps(state, ensure_ascii=False)
    assert state["entries"][-1]["source"]["execution_id"] == "execution-30"
    assert state["entries"][-1]["source"]["source_sequence"] == 30
    assert len(reflection.guidance(run)["failures"]) == 4


@pytest.mark.parametrize("code,category", [("permission_blocked", "permission"), ("user_constraint", "permission"),
                                            ("command_not_allowed", "permission"), ("operation_denied", "permission"),
                                            ("mcp_tool_not_allowed", "permission"), ("mcp_unsafe_target", "permission"),
                                            ("execution_unknown", "unknown"), ("unrecognized_failure", "unknown")])
def test_blocked_and_unknown_never_suggest_automatic_replay(context, code, category):
    owner, run = context
    for _ in range(4):
        feedback = result(owner, run, code=code)
        assert feedback["category"] == category and feedback["retry_policy"] == "do_not_replay"
    assert not reflection.stalled(run) and not reflection.requires_review(run)


@pytest.mark.parametrize("code", ["steering_superseded", "command_cancelled"])
def test_superseded_and_cancelled_results_do_not_create_failure(context, code):
    owner, run = context
    assert result(owner, run, code=code) is None
    assert "reflection_state" not in run


def test_generic_rejection_still_obeys_persisted_denial_and_unknown_scope(context):
    owner, run = context
    scope = {"kind": "command"}
    run["denied_operations"] = [{"scope": scope}]
    feedback = result(owner, run, name="run_project_command", arguments={"command": "python sample.py"},
                      code="local_tool_rejected", scope=scope)
    assert feedback["category"] == "permission" and feedback["retry_policy"] == "do_not_replay"
    run["denied_operations"] = []
    run["uncertain_operations"] = [{"scope": scope}]
    feedback = result(owner, run, name="run_project_command", arguments={"command": "python sample.py"},
                      code="local_tool_rejected", scope=scope)
    assert feedback["category"] == "unknown" and not reflection.requires_review(run)


def test_native_failures_use_persisted_facts_and_each_execution_counts_once(context):
    owner, run = context
    for index in range(4):
        identifier = f"managed-execution-{index}"
        native(owner, run, identifier)
        feedback = result(owner, run, name="read_execution", arguments={"execution_id": identifier}, success=True,
                          output={"status": "exited", "exit_code": 0, "error_code": "permission_blocked"})
        assert feedback["category"] == "execution" and feedback["attempts"] == index + 1
        assert result(owner, run, name="read_execution", arguments={"execution_id": identifier}, success=True) is None
    assert reflection.stalled(run) and len(run["reflection_state"]["seen_executions"]) == 4
    native(owner, run, "managed-success", exit_code=0)
    result(owner, run, name="read_execution", arguments={"execution_id": "managed-success"}, success=True)
    assert not reflection.stalled(run) and reflection.guidance(run) is None
    assert reflection.requires_review(run)


@pytest.mark.parametrize("damage", ["foreign_goal", "foreign_run", "mismatched_result", "missing_terminal", "active"])
def test_native_untrusted_or_stale_output_does_not_become_failure(context, damage):
    owner, run = context
    identifier = "managed-failure"
    native(owner, run, identifier, terminal=damage != "active")
    if damage == "foreign_goal":
        origin = {**run, "id": "old-run", "goal_version": 0}
        owner.store.runs["old-run"] = origin
        owner.store.records[identifier]["run_id"] = "old-run"
        run["ancestor_run_ids"] = ["old-run"]
    elif damage == "foreign_run":
        owner.store.records[identifier]["run_id"] = "unrelated-run"
    elif damage == "mismatched_result":
        run["executions"][0]["execution_result"] = {**run["executions"][0]["execution_result"], "exit_code": 0}
    elif damage == "missing_terminal":
        run["events"].clear()
    feedback = result(owner, run, name="read_execution", arguments={"execution_id": identifier}, success=True,
                      output={"error_code": "command_failed", "exit_code": 1})
    assert feedback is None and not reflection.requires_review(run)
    assert not run["reflection_state"]["entries"]


def test_native_search_exit_one_is_not_failure_and_unknown_never_replays(context):
    owner, run = context
    native(owner, run, "search-not-found", argv=["rg", "missing"], exit_code=1)
    assert result(owner, run, name="read_execution", arguments={"execution_id": "search-not-found"}, success=True) is None
    native(owner, run, "unknown-process", outcome="unknown", exit_code=None)
    feedback = result(owner, run, name="read_execution", arguments={"execution_id": "unknown-process"}, success=True)
    assert feedback["category"] == "unknown" and feedback["retry_policy"] == "do_not_replay"
    native(owner, run, "cancelled-process", outcome="cancelled", exit_code=None)
    assert result(owner, run, name="read_execution", arguments={"execution_id": "cancelled-process"}, success=True) is None
    assert not reflection.requires_review(run)


def test_native_false_error_code_cannot_override_successful_persisted_facts(context):
    owner, run = context
    call = ToolCall(id="false-failure", name="read_execution", arguments={"execution_id": "missing-process"})
    value = ToolResult(tool_call_id=call.id, name=call.name, success=False,
                       error="未登记的假失败", error_code="command_failed", output={"exit_code": 1})
    state, feedback = reflection.observe(owner, run, call, value)
    assert feedback is None and not state["entries"]
    native(owner, run, "cleanup-unknown", exit_code=0)
    owner.store.records["cleanup-unknown"]["stopped"] = False
    feedback = result(owner, run, name="read_execution", arguments={"execution_id": "cleanup-unknown"}, success=True)
    assert feedback["category"] == "unknown" and feedback["retry_policy"] == "do_not_replay"
    assert not reflection.requires_review(run)


def test_verification_counts_rounds_with_hashed_requirement_ids_and_no_messages(context):
    _, run = context
    secret = "sk-requirement-secret-with-many-characters"
    outcome = {"run_id": run["id"], "goal_outcome": "unmet",
        "requirements": [{"requirement_id": secret}, {"requirement_id": "second"}, {"requirement_id": "third"}],
        "verification_results": [{"requirement_id": secret, "status": "failed", "message": secret},
                                 {"requirement_id": "second", "status": "failed", "message": secret},
                                 {"requirement_id": "third", "status": "failed", "message": secret}]}
    run["reflection_state"] = reflection.record_verification(run, outcome)
    assert not reflection.requires_review(run)
    assert run["reflection_state"]["correctable_failures"] == 1
    assert secret not in json.dumps(run["reflection_state"])
    run["verification_retries"] = 1
    run["reflection_state"] = reflection.record_verification(run, outcome)
    assert reflection.requires_review(run)
    assert [item["attempts"] for item in run["reflection_state"]["entries"]] == [2, 2, 2]
    for item in outcome["verification_results"]:
        item["status"] = "passed"
    run["reflection_state"] = reflection.record_verification(run, outcome)
    assert reflection.guidance(run) is None and reflection.requires_review(run)
    assert not reflection.stalled(run)
    with pytest.raises(ValueError, match="不属于"):
        reflection.record_verification(run, {**outcome, "run_id": "foreign"})


def test_state_updates_are_copy_on_write_and_workspace_only_resets_open_cycles(context):
    owner, run = context
    result(owner, run)
    prior = run["reflection_state"]
    before = json.loads(json.dumps(prior))
    result(owner, run)
    assert prior == before and run["reflection_state"] is not prior
    run["workspace_version"] = 2
    prior = run["reflection_state"]
    before = json.loads(json.dumps(prior))
    assert reflection.guidance(run) is None
    assert prior == before
