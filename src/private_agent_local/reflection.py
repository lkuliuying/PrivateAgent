"""记录可核对的纠错事实；不保存正文、不推断思考，也不产生新的执行授权。"""
from __future__ import annotations

import hashlib
import json

MAX_ENTRIES = 16
STOP_AT = 4
WARNING_AT = 3
NATIVE_TOOLS = frozenset({"exec_command", "request_execution", "read_execution"})
IGNORED_CODES = frozenset({"steering_superseded", "command_cancelled", "cancelled"})
BLOCKED_CODES = frozenset({"permission_blocked", "user_constraint", "approval_denied", "approval_required",
                           "cloud_auth_required", "local_session_expired", "documentation_approval_denied",
                           "operation_denied", "command_not_allowed", "tool_not_allowed", "mcp_tool_not_allowed",
                           "mcp_interaction_rejected", "mcp_unsafe_target", "mcp_unsafe_response"})
UNKNOWN_CODES = frozenset({"execution_unknown", "tool_execution_unknown"})
INPUT_CODES = frozenset({"invalid_tool_arguments", "invalid_execution_options", "plan_version_conflict",
                         "plan_goal_conflict", "plan_transition_invalid", "plan_evidence_invalid",
                         "plan_requirement_invalid", "plan_proposal_invalid", "tool_not_found",
                         "tool_not_available", "tool_unavailable", "tool_output_too_large", "mcp_invalid_data",
                         "mcp_invalid_endpoint", "mcp_invalid_schema"})
EVIDENCE_CODES = frozenset({"stale_tool_input", "file_version_conflict", "snapshot_required",
                            "snapshot_stale", "patch_conflict", "mcp_config_changed", "mcp_catalog_changed",
                            "mcp_catalog_expired", "observer_config_changed"})
EXECUTION_CODES = frozenset({"command_failed", "command_timed_out", "environment_unavailable",
                             "program_unavailable", "not_git_repository", "git_query_failed", "mcp_connection_failed",
                             "mcp_timeout", "mcp_tool_failed"})
CORRECTABLE = frozenset({"input", "evidence", "execution", "tool"})
KNOWN_CODES = BLOCKED_CODES | UNKNOWN_CODES | INPUT_CODES | EVIDENCE_CODES | EXECUTION_CODES | {"local_tool_rejected"}
INSTRUCTIONS = {
    "input": "核对当前工具参数契约，修正参数后验证；不得用扩大权限解决参数错误。",
    "evidence": "重新取得当前版本的只读证据，核对差异后再制定修改方案。",
    "execution": "先检查已取得的诊断与环境，明确新依据和变化点，再执行有区别的验证。",
    "tool": "根据已取得的工具证据修正方案，说明变化点与预期验证；不要原样重复失败调用。",
    "permission": "保持当前权限和用户约束；说明阻塞，不换入口重试被拒绝的操作。",
    "unknown": "副作用结果未知；先核对现场并说明未确认事项，不自动重放。",
    "verification": "按当前验收要求补足可核对证据；不得以计划勾选或完成声明代替验证。",
}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def reset(run: dict) -> dict | None:
    if run.get("recovery_contract_version") != "1.0":
        return None
    return {"version": "1.0", "goal_version": run.get("goal_version", 1),
            "workspace_version": run.get("workspace_version", 0), "entries": [],
            "correctable_failures": 0, "review_required": False, "seen_executions": []}


def _state(run: dict) -> dict | None:
    fresh = reset(run)
    if fresh is None:
        return None
    prior = run.get("reflection_state")
    if not prior or prior.get("goal_version") != fresh["goal_version"]:
        return fresh
    # 事务只浅备份运行对象；嵌套状态必须复制后整体提交。
    state = json.loads(json.dumps(prior))
    if state["workspace_version"] != fresh["workspace_version"]:
        state["workspace_version"] = fresh["workspace_version"]
        for entry in state["entries"]:
            if entry["status"] == "open":
                entry["status"] = "superseded"
    return state


def _category(code: str) -> str:
    if code in BLOCKED_CODES:
        return "permission"
    if code in UNKNOWN_CODES:
        return "unknown"
    if code in INPUT_CODES:
        return "input"
    if code in EVIDENCE_CODES:
        return "evidence"
    if code in EXECUTION_CODES:
        return "execution"
    return "tool" if code == "local_tool_rejected" else "unknown"


def _target(name: str, arguments: dict) -> str:
    if "rel_path" in arguments:
        target = ["path", str(arguments["rel_path"]).replace("\\", "/").casefold()]
    elif name == "propose_project_patch" and isinstance(arguments.get("operations"), list):
        target = ["patch", [[item.get("operation"), item.get("rel_path"), item.get("new_rel_path")]
                            for item in arguments["operations"] if isinstance(item, dict)]]
    elif "argv" in arguments:
        target = ["command", arguments["argv"], arguments.get("cwd", ".")]
    elif "command" in arguments:
        target = ["command", arguments["command"], arguments.get("arguments", []), arguments.get("cwd", ".")]
    else:
        target = {key: arguments[key] for key in ("patch_set_id", "item_id", "source_id", "tool_name") if key in arguments}
    return _digest([name, target])


def _source(run: dict, call, execution: dict | None) -> dict:
    return {"run_id": run["id"], "tool_call_hash": _digest(call.id),
            "execution_id": execution.get("id") if execution else None,
            "source_sequence": execution.get("source_sequence") if execution else None}


def _native_fact(owner, run: dict, call, execution: dict | None) -> dict | None:
    if call.name not in NATIVE_TOOLS:
        return None
    identifier = call.arguments.get("execution_id") if call.name == "read_execution" else (execution or {}).get("id")
    if not identifier:
        return None
    try:
        record = owner.store.execution_sessions.get(identifier, run["session_id"])
    except ValueError:
        return None
    allowed_runs = {run["id"], *run.get("ancestor_run_ids", [])}
    if record["run_id"] not in allowed_runs or record.get("workspace_id") != run.get("workspace_id"):
        return None
    origin = owner.store.run(record["run_id"])
    if (origin.get("logical_task_id", origin["id"]) != run.get("logical_task_id", run["id"])
            or origin.get("goal_version", 1) != run.get("goal_version", 1)):
        return None
    source = next((item for item in origin["executions"] if item["id"] == identifier), None)
    result = record.get("execution_result")
    if not source or not result or source.get("execution_result") != result:
        return None
    sequence = source.get("source_sequence")
    event = next((item for item in origin["events"] if item["sequence"] == sequence), {})
    if (event.get("type") not in {"tool.completed", "tool.failed"}
            or event.get("payload", {}).get("execution_id") != identifier):
        return None
    return {"record": record, "execution": source, "result": result}


def _feedback(entry: dict) -> dict:
    return {"category": entry["category"], "attempts": entry["attempts"], "target_hash": entry["target_hash"],
            "source": entry["source"], "retry_policy": "change_required" if entry["category"] in CORRECTABLE
            or entry["category"] == "verification" and entry["error_code"] == "failed" else "do_not_replay",
            "required_action": INSTRUCTIONS[entry["category"]],
            "warning": entry["attempts"] >= WARNING_AT}


def _failure(state: dict, *, tool_name: str | None, target: str, category: str,
             code: str, signature: str, source: dict, kind="tool") -> dict:
    key = _digest([kind, target, category])
    previous = next((item for item in state["entries"] if item["key"] == key), None)
    attempts = previous["attempts"] + 1 if previous and previous["status"] == "open" else 1
    entry = {"key": key, "kind": kind, "tool_name": tool_name, "target_hash": target, "category": category,
             "error_code": code, "signature": signature, "attempts": attempts, "status": "open",
             "workspace_version": state["workspace_version"], "source": source}
    state["entries"] = [item for item in state["entries"] if item["key"] != key][-MAX_ENTRIES + 1:] + [entry]
    if category in CORRECTABLE or kind == "verification" and code == "failed":
        state["correctable_failures"] += 1
        state["review_required"] = state["correctable_failures"] >= 2
    return entry


def observe(owner, run: dict, call, result) -> tuple[dict | None, dict | None]:
    """只接收适配器复核代次后的结果；命令终态还须核对本机持久事实。"""
    state = _state(run)
    if state is None or result.error_code in IGNORED_CODES:
        return None, None
    if call.name not in owner.registry:
        return None, None
    persisted = owner.store.run(run["id"])
    execution = next((item for item in reversed(persisted["executions"])
                      if item["tool_call_id"] == call.id and item["tool_name"] == call.name), None)
    name, arguments, failed = call.name, call.arguments, not result.success
    source, code = _source(run, call, execution), result.error_code or "local_tool_rejected"
    native = _native_fact(owner, run, call, execution)
    if native:
        record, native_result = native["record"], native["result"]
        identifier = _digest([record["run_id"], record["execution_id"]])
        if identifier in state["seen_executions"]:
            return (state, None) if state != run.get("reflection_state") else (None, None)
        # 一个逻辑任务至多 512 次工具调用；重复读取同一进程不能增加失败次数。
        state["seen_executions"] = [*state["seen_executions"], identifier][-512:]
        name, arguments = "exec_command", {"argv": record["argv"], "cwd": record["cwd"]}
        source = {"run_id": record["run_id"], "execution_id": record["execution_id"],
                  "tool_call_hash": _digest(record["tool_call_id"]), "source_sequence": native["execution"].get("source_sequence")}
        outcome = native_result["outcome"]
        if outcome == "cancelled":
            return state, None
        unknown = outcome == "unknown" or record.get("stopped") is not True
        failed = unknown or outcome != "exited" or native_result["validation_outcome"] == "failed"
        code = "execution_unknown" if unknown else "command_timed_out" if outcome == "timed_out" else "command_failed"
    elif call.name in NATIVE_TOOLS:
        # 自由输出中的终态、退出码和 error_code 均不能充当新的执行事实。
        if result.success or not execution or not execution.get("error_code"):
            return (state, None) if state != run.get("reflection_state") else (None, None)
        code = execution["error_code"]
    if execution and execution.get("error_code") in IGNORED_CODES:
        return None, None
    target = _target(name, arguments)
    if failed:
        from .completion import denied_operation

        if execution and execution.get("error_code") in BLOCKED_CODES | UNKNOWN_CODES:
            code = execution["error_code"]
        if execution and execution.get("scope"):
            if denied_operation(run, execution["scope"]):
                code = "permission_blocked"
            elif denied_operation(run, execution["scope"], collection="uncertain_operations"):
                code = "execution_unknown"
        category = _category(code)
        entry = _failure(state, tool_name=name, target=target, category=category,
                         code=code if code in KNOWN_CODES else "tool_failed",
                         signature=_digest([name, arguments, result.error_code, result.error]), source=source)
        return state, _feedback(entry)
    for entry in state["entries"]:
        if entry["status"] == "open" and entry["kind"] == "tool" and entry["target_hash"] == target:
            entry["status"] = "resolved"
            entry["resolution_source"] = source
    return (state, None) if state != run.get("reflection_state") else (None, None)


def record_verification(run: dict, outcome) -> dict | None:
    state = _state(run)
    if state is None:
        return None
    value = outcome.model_dump(mode="json") if hasattr(outcome, "model_dump") else outcome
    if value.get("run_id") != run["id"]:
        raise ValueError("完成纠错结果不属于当前运行")
    required = {item["requirement_id"] for item in value.get("requirements", []) if item.get("required", True)}
    review_required = state["review_required"]
    counted = False
    for item in value.get("verification_results", []):
        if item["requirement_id"] not in required:
            continue
        target = _digest(item["requirement_id"])
        if item["status"] == "passed":
            for entry in state["entries"]:
                if entry["kind"] == "verification" and entry["target_hash"] == target and entry["status"] == "open":
                    entry["status"] = "resolved"
            continue
        if item["status"] not in {"failed", "blocked", "unverified"}:
            continue
        before = state["correctable_failures"]
        _failure(state, tool_name=None, target=target, category="verification", code=item["status"],
                 signature=_digest([target, item["status"]]), kind="verification",
                 source={"run_id": run["id"], "verification_attempt": run.get("verification_retries", 0) + 1})
        # 一次完成检查有多项失败，也只算一次失败尝试。
        if counted:
            state["correctable_failures"] = before
        elif state["correctable_failures"] > before:
            counted = True
    state["review_required"] = review_required or state["correctable_failures"] >= 2
    return state if state != run.get("reflection_state") else None


def failure_repeats(run: dict) -> int:
    state = _state(run)
    return max((item["attempts"] for item in (state or {}).get("entries", [])
                if item["kind"] == "tool" and item["status"] == "open" and item["category"] in CORRECTABLE), default=0)


def stalled(run: dict) -> bool:
    return failure_repeats(run) >= STOP_AT


def requires_review(run: dict) -> bool:
    state = _state(run)
    return bool(state and state["review_required"])


def guidance(run: dict) -> dict | None:
    state = _state(run)
    entries = [item for item in (state or {}).get("entries", []) if item["status"] == "open"][-4:]
    if not entries:
        return None
    return {"goal_version": state["goal_version"], "workspace_version": state["workspace_version"],
            "failures": [_feedback(item) for item in entries],
            "notice": "纠错记录是工具与验证事实索引，不是新授权；修改方案须指出新依据、变化点和预期验证。"}
