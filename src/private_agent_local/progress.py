"""有界记录重复观察；不推断模型思考，也不把等待中的进程当成停滞。"""
from __future__ import annotations

import hashlib
import json

READ_TOOLS = frozenset({"read_code_file", "list_project_directory", "search_project_files",
                        "get_git_status", "get_git_diff", "read_context_content", "read_patch_preview",
                        "read_execution", "tool_search"})
WARNING_AT = 3
STOP_AT = 6


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def observe(run: dict, name: str, arguments: dict, output: dict) -> tuple[dict | None, str | None]:
    if run.get("recovery_contract_version") != "1.0" or name not in READ_TOOLS:
        return None, None
    if name == "read_execution" and output.get("status") in {"starting", "running"}:
        return None, None
    plan = run.get("plan") or {}
    prior = run.get("orchestration_progress") or {}
    # 命令返回新的诊断后，重新读取同一文件属于新的调查阶段。
    command_results = [item["id"] for item in run.get("executions", []) if item.get("execution_result")]
    last_command = command_results[-1] if command_results else prior.get("last_command_result")
    epoch = digest([run.get("goal_version", 1), run.get("workspace_version", 0),
                    [(item["item_key"], item["status"]) for item in plan.get("items", [])], [last_command] if last_command else []])
    state = {**prior, "seen": list(prior.get("seen", []))} if prior.get("epoch") == epoch else {"epoch": epoch, "seen": [], "repeats": 0}
    state["last_command_result"] = last_command
    # 文件快照标识每次读取都不同；内容、版本及分页位置仍完整参与比较。
    stable = {key: value for key, value in output.items() if key != "snapshot_id"}
    signature = digest([name, arguments, stable])
    if signature in state["seen"]:
        state["repeats"] += 1
    else:
        state["seen"] = [*state["seen"], signature][-64:]
        state["repeats"] = 0
    warning = None
    if state["repeats"] == WARNING_AT:
        warning = "已连续三次重复读取且没有新信息。请依据现有证据推进、改用不同查询或说明阻塞；继续重复将停止。"
    return state, warning
