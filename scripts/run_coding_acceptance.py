"""S6 隔离评测：正式 IPC、逐次证据、Provider 回环矩阵与保守交付决议。"""
from __future__ import annotations

import argparse
import difflib
import json
import platform
import re
import sys
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from coding_acceptance_budget import ExperimentBudget, finite
from coding_acceptance_catalog import (
    judge,
    load_catalog,
    preflight,
    rebuild,
    scope_preserved,
    snapshot,
    verify_revision,
)
from coding_acceptance_evidence import (
    TERMINAL_EVENTS,
    Evidence,
    digest,
    event_integrity_errors,
    redact,
    write_json,
)
from coding_acceptance_identity import product_identity
from coding_acceptance_local import (
    ACCOUNT_MODE,
    LocalSession,
    local_config,
    secret_input,
)
from coding_acceptance_metrics import ResourceSampler, process_metrics
from coding_acceptance_models import (
    ProductSession,
    check_preflight,
    direct_config,
    model_identity_fingerprint,
    product_config,
)
from coding_acceptance_schema import (
    assessment_for,
    fingerprint,
    read_json,
    verify_catalog,
)
from coding_acceptance_transport import Fixture, RuntimeClient, reply
from run_coding_validation import ROOT, new_directory

TERMINAL = frozenset(TERMINAL_EVENTS)
POLL_INTERVAL_SECONDS = 0.05
ATTEMPT_TIMEOUT_SECONDS = 630
CANCEL_REQUEST_SECONDS = 5
CANCEL_OBSERVE_SECONDS = 5
VALIDATION_TIMEOUT_MS = 60_000


def model_config(path: Path) -> dict:
    data = read_json(path)
    if isinstance(data, dict) and data.get("connection_mode") == "product_proxy":
        product_config(data)
        raise ValueError("product_proxy 执行已停用：账号服务器不再推理；请在客户端配置模型并迁移到 schema 2 direct_provider，历史证据仍可读取")
    if isinstance(data, dict) and data.get("connection_mode") == "direct_provider":
        if data.get("schema_version") == 3 or "account_mode" in data:
            return local_config(data)
        return direct_config(data)
    required = {"model", "protocol", "endpoint", "context_tokens", "local_unbilled", "max_total_tokens"}
    if set(data) != required or data["protocol"] not in {"openai", "ollama"} or data["local_unbilled"] is not True:
        raise ValueError("真实质量模式仅接受显式确认不计费的本机模型配置，禁止凭据或额外字段")
    address = urlsplit(data["endpoint"])
    if (address.scheme != "http" or address.hostname not in {"127.0.0.1", "::1"} or address.username or address.password
            or address.query or address.fragment or address.port == 0 or address.path not in {"", "/", "/v1"}
            or data["protocol"] == "ollama" and address.path not in {"", "/"}):
        raise ValueError("质量模式只允许无凭据的字面回环模型地址")
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", data["model"]):
        raise ValueError("模型标识无效")
    if type(data["context_tokens"]) is not int or not 8192 <= data["context_tokens"] <= 1_000_000:
        raise ValueError("模型上下文容量无效")
    if type(data["max_total_tokens"]) is not int or not 1 <= data["max_total_tokens"] <= 10800000:
        raise ValueError("总 token 预算无效")
    return {**data, "connection_mode": "local_unbilled"}


def validation_arguments(task: dict) -> dict:
    restricted = task.get("_execution_mode") == "restricted"
    return {"argv": task["validation_command"], "cwd": ".", "retention": "run", "yield_time_ms": 30000,
            "timeout_ms": VALIDATION_TIMEOUT_MS, "execution_mode": "restricted" if restricted else "trusted_project",
            "network_policy": "none" if restricted else "approved"}


def task_prompt(task: dict) -> str:
    # 模型必须看到审批条件；隐藏的超时上限会把合法验证误导成被拒绝操作。
    parameters = validation_arguments(task)
    # 命令仅保留题面中的完整写法，避免数组里的片段被识别为另一条验收命令。
    parameters.pop("argv")
    return (task["files"]["README.md"] + "\n请完成上述修改并运行验证。只运行预定验证命令；不要安装依赖。"
            "\n使用 exec_command 执行验证；argv 必须按照题面验证命令的参数顺序传入数组，不得追加或省略参数。"
            "cwd、retention、execution_mode、network_policy 必须匹配以下值；"
            f"timeout_ms 单位为毫秒，必须大于 0 且不超过 {VALIDATION_TIMEOUT_MS}。其他范围不批准。"
            "\n其余执行参数（JSON）：\n" + json.dumps(parameters, ensure_ascii=False)
            + "\n若命令返回 starting 或 running，使用 read_execution 继续等待，核对最终退出码后再总结运行结果。")


def command_reply(task):
    return reply(name="exec_command", arguments=validation_arguments(task))


def script(task: dict) -> list[dict]:
    if task.get("purpose") == "independent_evaluation":
        raise ValueError("正式题集参考实现不得进入 Agent；正负控制须在独立验收侧执行")
    responses = [command_reply(task)] if task["scenario"] == "failure_then_fix" else []
    references = assessment_for(task)["reference_files"] if task.get("catalog_source") == "external_json" else task["reference_files"]
    for name, content in references.items():
        if task["category"] == "long_context":
            start_line = 1401
            responses += [reply(name="read_code_file", arguments={"rel_path": name, "start_line": start_line, "line_count": 100}),
                          {**reply(), "patch_from_read": {"operation": "update", "rel_path": name,
                           "edits": [{"start_line": start_line, "delete_count": len(task["files"][name].splitlines()) - 1400,
                                      "text": "\n".join(content.splitlines()[1400:]) + "\n"}]}},
                          {**reply(), "apply_from_preview": True}]
            continue
        responses += [reply(name="read_code_file", arguments={"rel_path": name}),
                      reply(name="write_project_file", arguments={"rel_path": name, "content": content})]
    if task["coding_goal"]:
        responses.append(command_reply(task))
    responses.extend(reply("文件和验证的实际结果见运行证据；受阻项保持未完成。") for _ in range(3))
    return responses


def approved(task: dict, approval: dict, preview: dict) -> bool:
    if task["scenario"] == "deny":
        return False
    if approval["tool_name"] in {"write_project_file", "apply_project_patch"}:
        paths = [change["rel_path"] for change in preview.get("changes", [])]
        if not paths and preview.get("rel_path"):
            paths = [preview["rel_path"]]
        return bool(paths) and set(paths) <= set(task["editable_files"])
    restricted = task.get("_execution_mode") == "restricted"
    return (approval["tool_name"] == "exec_command" and preview.get("argv") == task["validation_command"]
            and preview.get("cwd") == "." and preview.get("retention") == "run"
            and preview.get("timeout_ms", 0) <= VALIDATION_TIMEOUT_MS and preview.get("execution_mode") == ("restricted" if restricted else "trusted_project")
            and preview.get("network_policy") == ("none" if restricted else "approved"))


def events(client: RuntimeClient, run: dict) -> list[dict]:
    output, cursor = [], 0
    while cursor < run["last_event_sequence"]:
        page = client.request(f"/agent-runs/{run['id']}/events?after_sequence={cursor}&limit=100")
        if not page["items"]:
            raise ValueError("终态事件分页缺失")
        if any(type(item.get("sequence")) is not int or item["sequence"] != cursor + index
               for index, item in enumerate(page["items"], 1)):
            raise ValueError("事件分页序号不连续或重复，游标未推进")
        output.extend(page["items"])
        cursor = page["items"][-1]["sequence"]
        if len(output) > 10000 or cursor > run["last_event_sequence"]:
            raise ValueError("事件越界或超过配额")
    return output


def control(client: RuntimeClient, run_id: str, action: str):
    state = client.request(f"/agent-runs/{run_id}/recovery")
    body = {"request_id": uuid.uuid4().hex, "expected_state_version": state["state_version"]}
    if action == "resume":
        body["checkpoint_id"] = state["checkpoint_id"]
    return client.request(f"/agent-runs/{run_id}/{action}", "POST", body)


def poll_run(client: RuntimeClient, run: dict, *, deadline: float, on_active=None, max_attempt_tokens=120000) -> tuple[dict, dict]:
    observation = {"stop_reason": None, "cancel_requested": False, "cancel_response": "not_requested",
                   "cancel_error": None, "observation_error": None, "terminal_observed": False,
                   "observed_before_deadline": False}
    settle_deadline = None
    while True:
        remaining = (settle_deadline if settle_deadline is not None else deadline) - time.monotonic()
        if settle_deadline is not None and remaining <= 0:
            observation["observation_error"] = {"type": "TimeoutError", "message": "取消后未在观察期限内确认终态"}
            break
        try:
            # 即使评测期限刚到，也先取得最新状态，不能用旧快照取消已结束的运行。
            run = client.request(f"/agent-runs/{run['id']}", timeout=min(30, remaining) if remaining > 0 else 30)
        except (OSError, RuntimeError, ValueError) as error:
            observation["observation_error"] = {"type": type(error).__name__, "message": redact(str(error))[:500]}
            if isinstance(error, TimeoutError) and observation["stop_reason"] is None and time.monotonic() >= deadline:
                observation["stop_reason"] = "attempt_timeout"
            break
        if run["status"] in TERMINAL:
            observation.update(terminal_observed=True, observed_before_deadline=time.monotonic() < deadline)
            break
        if settle_deadline is not None:
            time.sleep(min(POLL_INTERVAL_SECONDS, max(0, settle_deadline - time.monotonic())))
            continue
        if run.get("usage_complete") and run.get("input_tokens", 0) + run.get("output_tokens", 0) > max_attempt_tokens:
            observation["stop_reason"] = "budget_exhausted"
        elif time.monotonic() >= deadline:
            observation["stop_reason"] = "attempt_timeout"
        if observation["stop_reason"]:
            # 先登记一次逻辑请求；响应丢失也只读核对，绝不重放取消、审批或工具操作。
            observation["cancel_requested"] = True
            try:
                receipt = client.request(f"/agent-runs/{run['id']}/cancel", "POST", timeout=CANCEL_REQUEST_SECONDS)
                if not isinstance(receipt, dict) or type(receipt.get("accepted")) is not bool:
                    raise ValueError("取消回执无效")
                observation["cancel_response"] = "accepted" if receipt["accepted"] else "not_accepted"
            except (OSError, RuntimeError, ValueError) as error:
                observation["cancel_response"] = "unknown"
                observation["cancel_error"] = {"type": type(error).__name__, "message": redact(str(error))[:500]}
            settle_deadline = time.monotonic() + CANCEL_OBSERVE_SECONDS
            continue
        if on_active:
            on_active(run)
        time.sleep(POLL_INTERVAL_SECONDS)
    return run, observation


def run_failure(run: dict, observation: dict, *, max_attempt_tokens=120000) -> str | None:
    if not observation["terminal_observed"]:
        if observation["stop_reason"]:
            return observation["stop_reason"]
        error = observation["observation_error"] or {}
        return "evaluator_transport_timeout" if error.get("type") == "TimeoutError" else "runner_error"
    # 活动时长上限在当前本机契约中也是 limit_exceeded，用原始错误码准确区分。
    if run["status"] == "timed_out" or run.get("error_code") == "max_active_seconds":
        return "runtime_timeout"
    if run["status"] == "limit_exceeded":
        return "budget_exhausted"
    if run["status"] == "cancelled":
        if observation["cancel_response"] == "not_accepted":
            return "user_cancelled"
        return observation["stop_reason"] or "user_cancelled"
    if run["status"] == "interrupted":
        return "runtime_interrupted"
    if run["status"] == "failed":
        return "runtime_failed"
    if run.get("usage_complete") and run.get("input_tokens", 0) + run.get("output_tokens", 0) > max_attempt_tokens:
        return "budget_exhausted"
    return observation["stop_reason"]


def attempt(task: dict, plan: dict, area: Path, evidence: Evidence, *, bundle=None, model=None, legacy_stream=False, isolation=None,
            connection=None, budget_override=None) -> dict:
    row = {**plan, "started": False, "failure_class": None, "human_interventions": 0,
           "report_matches_facts": None, "tokens": None, "cost_usd": None, "within_budget": False,
           "functional_passed": False, "validation_passed": False, "scope_preserved": False,
           "evidence_complete": False, "system_behavior_passed": False, "approvals": 0,
           "peak_sampled_storage_bytes": None, "peak_processes": None,
           "artifact_digest": evidence.manifest["product"].get("sha256")}
    started_at = time.monotonic()
    budget = budget_override or task.get("budget") or evidence.manifest.get("budget") or {
        "max_model_requests": 24, "max_tool_calls": 48, "max_active_seconds": 600, "max_attempt_tokens": 120000}
    sampler = None
    try:
        verify_revision(task)
        project = area / "project"
        runtime = isolation.agent_runtime(task["family"]) if isolation else None
        before = rebuild(task, project, runtime=runtime)
        protocol = plan["protocol"]
        with ExitStack() as stack:
            fixture = stack.enter_context(connection or Fixture(protocol, model=model, legacy_stream=legacy_stream))
            if not model:
                if task["scenario"] == "pause_resume":
                    fixture.responses.append({**reply("处理中"), "delay_seconds": 2})
                else:
                    fixture.responses.extend(script(task))
            tool_paths = [runtime["root"], runtime["root"] / "bin"] if runtime else []
            with RuntimeClient(area, fixture, bundle=bundle, rust_required=task["family"] == "rust", tool_paths=tool_paths,
                               tool_local_appdata=isolation.local_appdata() if isolation else None) as client, ResourceSampler(client.process, area) as sampler:
                client.request("/identity/local", "POST")
                capabilities = client.request("/capabilities")
                if capabilities.get("coding_recovery_contract_version") != "1.0":
                    raise ValueError("运行时恢复协议不兼容")
                if model:
                    description = client.request("/model-evaluation/preflight?profile_id=" + quote(model.get("profile_id") or fixture.profile_id, safe=""))
                    missing = check_preflight(description, {**model, "profile_id": model.get("profile_id") or fixture.profile_id}, capabilities)
                    if missing or model_identity_fingerprint(description) != evidence.manifest.get("model_preflight", {}).get("sha256"):
                        raise ValueError("模型预检或冻结身份变化：" + ",".join(missing))
                    row["model_identity"] = description
                project_info = client.request("/projects", "POST", {"name": task["id"], "root_path": str(project), "trust_instructions": True})
                workspace = client.request(f"/projects/{project_info['id']}/workspaces")[0]
                binding = {"project_id": project_info["id"], "workspace_id": workspace["id"]}
                session = client.request("/sessions", "POST", {**binding, "title": task["title"]})
                host_capabilities = client.request(f"/sessions/{session['id']}/execution-capabilities")
                if not host_capabilities.get("contract", {}).get("execution"):
                    raise RuntimeError("环境预检失败：持续执行宿主不可用，实验未启动")
                requirements = [{"requirement_id": f"file-{index}", "description": "按任务修改文件", "kind": "file_changed",
                                 "scope": name, "origin": "user", "evidence_policy": "disk"} for index, name in enumerate(task["editable_files"])]
                if task["coding_goal"]:
                    requirements.append({"requirement_id": "validation", "description": "执行预定验证命令", "kind": "command",
                                         "scope": " ".join(task["validation_command"]), "origin": "user", "evidence_policy": "exit"})
                prompt = task_prompt(task)
                # 在可能产生副作用的启动请求之前持久化；回执丢失也不能从分母中移除。
                evidence.start(plan)
                row["started"] = True
                run = client.request("/agent-runs", "POST", {**binding, "session_id": session["id"], "message": prompt,
                    "model_profile_id": model.get("profile_id") or fixture.profile_id if model else fixture.profile_id,
                    "reasoning_effort": model.get("parameters", {}).get("reasoning_effort") if model else None,
                    "client_request_id": plan["attempt_id"], "permission_mode": "confirm", "completion_contract_version": "1.0",
                    "execution_contract_version": "1.0", "recovery_contract_version": "1.0", "completion_requirements": requirements,
                    "context_limits": {**{key: budget[key] for key in ("max_model_requests", "max_tool_calls", "max_active_seconds")},
                        **({"max_total_tokens": budget["max_attempt_tokens"], "max_cost_usd": budget.get("cost_usd"),
                            "reserved_output_tokens": model.get("parameters", {}).get("max_output_tokens", 2048),
                            "auto_compact": model.get("parameters", {}).get("auto_compact", True)} if model else {})}})
                run_id, paused = run["id"], False
                deadline = time.monotonic() + min(ATTEMPT_TIMEOUT_SECONDS, budget["max_active_seconds"] + 30)
                handled_approvals = set()

                def on_active(run):
                    nonlocal paused
                    if (task["scenario"] == "pause_resume" and not paused and run["status"] == "running"
                            and run.get("loop_budget", {}).get("model_requests", 0) >= 1 and not run.get("tool_call_count")):
                        control(client, run_id, "pause")
                        if not model:
                            with fixture.lock:
                                fixture.responses.clear()
                                fixture.responses.extend(script(task))
                        control(client, run_id, "resume")
                        paused = True
                    elif run["status"] == "waiting_approval":
                        for approval in client.request(f"/agent-runs/{run_id}/approvals"):
                            if approval["status"] == "pending" and approval["id"] not in handled_approvals:
                                preview = client.request(f"/agent-runs/{run_id}/approvals/{approval['id']}/preview")
                                decision = "approve" if approved(task, approval, preview) else "reject"
                                handled_approvals.add(approval["id"])
                                client.request(f"/agent-runs/{run_id}/approvals/{approval['id']}/{decision}", "POST")
                                row["approvals"] += 1

                run, observation = poll_run(client, run, deadline=deadline, on_active=on_active, max_attempt_tokens=budget["max_attempt_tokens"])
                row.update(termination=observation, failure_class=run_failure(run, observation, max_attempt_tokens=budget["max_attempt_tokens"]),
                           run_id=run_id, run_status=run["status"], run_error_code=run.get("error_code"))
                history = events(client, run) if observation["terminal_observed"] else []
                row["process_metrics"] = process_metrics(history, run)
                row["active_seconds"] = row["process_metrics"]["active_seconds"]
                if isinstance(run.get("error_code"), str) and run["error_code"].startswith(("model_", "cloud_")):
                    row["failure_class"] = run["error_code"]
                elif run.get("error_code") in {"token_usage_unknown", "cost_usage_unknown"}:
                    row["failure_class"] = run["error_code"]
                integrity_errors = event_integrity_errors(history, run["last_event_sequence"], run["status"])
                execution = client.request(f"/agent-runs/{run_id}/executions") if observation["terminal_observed"] else []
                review = client.request(f"/agent-runs/{run_id}/review") if observation["terminal_observed"] else {"error": "run_terminal_unconfirmed"}
                verdict = (judge(task, project, area, before, isolation=isolation) if observation["terminal_observed"] else
                           {"passed": False, "scope_preserved": False, "reason": "run_terminal_unconfirmed"})
                after = snapshot(project)
                row.update(run_id=run_id, run_status=run["status"], goal_outcome=run.get("goal_outcome"),
                           isolation_verified=bool(isolation and verdict.get("isolation_verified") and evidence.manifest["isolation"]["verified"]),
                           scope_preserved=scope_preserved(task, before, after) and verdict["scope_preserved"],
                           functional_passed=verdict["passed"], evidence_complete=not integrity_errors,
                           event_integrity_errors=integrity_errors,
                           validation_passed=any(item.get("command") == " ".join(task["validation_command"])
                                                 and (item.get("execution_result") or {}).get("validation_outcome") == "succeeded" for item in execution),
                           tokens=run.get("input_tokens", 0) + run.get("output_tokens", 0) if run.get("usage_complete") else None,
                           cost_usd=run.get("cost_usd"), controls_applied=paused, model_requests=run.get("loop_budget", {}).get("model_requests"),
                           tool_calls=run.get("tool_call_count"), model_protocol_calls=fixture.calls,
                           budget=run.get("loop_budget"), run_error_code=run.get("error_code"),
                           provider_errors=fixture.errors)
                row["effective_budget"] = budget
                row["actual_permission_mode"] = run.get("permission_mode")
                row["usage_state"] = "reported" if row["tokens"] is not None else "unknown"
                row["cost_state"] = "reported" if finite(row["cost_usd"]) else "unknown_missing_price_or_usage"
                row["model_identity_matches"] = run.get("model") == (model["model"] if model else "s6-fixture")
                row["within_budget"] = (observation["observed_before_deadline"] and observation["stop_reason"] is None
                                        and row["tokens"] is not None and row["tokens"] <= budget["max_attempt_tokens"]
                                        and run["status"] not in {"limit_exceeded", "timed_out"})
                if model:
                    row["within_budget"] = row["within_budget"] and all(
                        finite(row.get(key)) and row[key] <= budget[field]
                        for key, field in (("model_requests", "max_model_requests"), ("tool_calls", "max_tool_calls"), ("active_seconds", "max_active_seconds")))
                    if budget.get("cost_usd") is not None:
                        row["within_budget"] = row["within_budget"] and finite(row["cost_usd"]) and row["cost_usd"] <= budget["cost_usd"]
                    if not row["within_budget"] and not row["failure_class"]:
                        row["failure_class"] = "budget_exhausted_or_usage_unknown"
                row["system_behavior_passed"] = (not row["failure_class"] and row["evidence_complete"] and row["scope_preserved"] and not fixture.errors
                    and (run.get("goal_outcome") == "blocked" and before == after if task["expected_system_behavior"] == "blocked_without_write"
                         else verdict["passed"] and run.get("goal_outcome") == "verified" and row["validation_passed"]
                         and (task["scenario"] != "pause_resume" or paused)))
                if not row["failure_class"] and not row["system_behavior_passed"]:
                    row["failure_class"] = ("write_protection" if not row["scope_preserved"] else "event_integrity" if not row["evidence_complete"]
                                            else "task_or_protocol_failed")
                event_file = evidence.directory / "events" / (plan["attempt_id"] + ".json")
                write_json(event_file, history)
                artifact_file = evidence.directory / "artifacts" / (plan["attempt_id"] + ".json")
                row["candidate_sha256"] = fingerprint(after)
                write_json(artifact_file, {"binding": plan.get("binding"), "candidate_sha256": row["candidate_sha256"],
                                          "run": run, "executions": execution, "review": review, "judge": verdict,
                                          "ipc_requests": client.request_correlations, "runtime_identity": client.process_identity(),
                                          "before": before, "after": after, "capabilities": capabilities, "execution_capabilities": host_capabilities})
                row["evidence_sha256"] = {event_file.relative_to(evidence.directory).as_posix(): digest(event_file),
                                          artifact_file.relative_to(evidence.directory).as_posix(): digest(artifact_file)}
                changes = []
                for name in task["editable_files"]:
                    path = project / name
                    if path.is_file() and not path.is_symlink():
                        changes.extend(difflib.unified_diff(task["files"][name].splitlines(True), path.read_text(encoding="utf-8").splitlines(True),
                                                            fromfile="before/" + name, tofile="after/" + name))
                difference = evidence.directory / "artifacts" / (plan["attempt_id"] + ".diff")
                difference.write_text(redact("".join(changes)), encoding="utf-8")
                row["evidence_sha256"][difference.relative_to(evidence.directory).as_posix()] = digest(difference)
    except KeyboardInterrupt:
        row.update(failure_class="runner_cancelled", system_behavior_passed=False)
        raise
    except Exception as error:
        # 运行器边界必须为编程错误同样保存失败；不吞掉异常后继续宣称门禁通过。
        row.update(failure_class=row["failure_class"] or "runner_error", system_behavior_passed=False, error_type=type(error).__name__,
                   error_message=redact(str(error))[:500])
        evidence.errors.append(plan["attempt_id"] + ":" + type(error).__name__)
    finally:
        if sampler:
            row["resource_metrics"] = sampler.snapshot()
            row["peak_processes"] = row["resource_metrics"]["peak_processes"]
            row["peak_sampled_storage_bytes"] = row["resource_metrics"]["peak_sampled_storage_bytes"]
        row["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
        row.setdefault("process_metrics", process_metrics([], {}))["total_seconds"] = row["elapsed_seconds"]
        row["process_metrics_complete"] = (not row["process_metrics"]["missing_reasons"] and sampler is not None
                                            and not row["resource_metrics"]["missing_reasons"])
        if model and row["started"] and not row["process_metrics_complete"]:
            row.update(system_behavior_passed=False, failure_class=row["failure_class"] or "process_metrics_unavailable")
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        evidence.append(row)
    return row


def run(args) -> int:
    catalog = load_catalog(getattr(args, "catalog", None))
    use_isolation = getattr(args, "isolation", "none") == "appcontainer"
    custody_path = getattr(args, "custody_receipt", None)
    custody_hash = getattr(args, "custody_sha256", None)
    if bool(custody_path) != bool(custody_hash):
        raise ValueError("独立回执必须同时提供路径和验收方确认的 SHA256")
    if use_isolation and catalog["catalog_source"] != "external_json":
        raise ValueError("隔离后端要求外部 JSON 题集")
    if catalog["purpose"] == "independent_evaluation" and args.mode in {"control", "matrix"}:
        raise ValueError("正式题集不得向 Agent 注入参考答案；请使用验收侧题集验证入口")
    tasks = [task for task in catalog["tasks"] if not args.tasks or task["id"] in args.tasks.split(",")]
    if (not tasks or args.tasks and (set(args.tasks.split(",")) != {task["id"] for task in tasks}
                                     or len(args.tasks.split(",")) != len(tasks))):
        raise ValueError("任务选择包含未知或空任务")
    for task in tasks:
        task["_execution_mode"] = "restricted" if use_isolation else "trusted_project"
    model = model_config(args.model_config) if args.model_config else None
    if (getattr(args, "expected_config_sha256", None) is not None
            and (not model or digest(args.model_config) != args.expected_config_sha256)):
        raise ValueError("模型配置已不同于刚才显示的调用范围，未读取凭据")
    if args.mode == "quality" and (not model or args.repetitions != 3):
        raise ValueError("真实质量模式需要显式 --model-config 和 --repetitions 3")
    if args.mode not in {"quality", "preflight", "probe"} and model:
        raise ValueError("仅质量、预检和小规模联调模式接受模型配置")
    if args.mode == "probe" and (not model or not args.tasks or len(tasks) > 3 or args.repetitions != 1):
        raise ValueError("小规模联调需指定模型、1～3 个公开任务、一次重复")
    if args.mode == "probe" and catalog["purpose"] != "public_calibration":
        raise ValueError("小规模联调仅使用公开校准题，不消费正式保留题")
    product = bool(model and model.get("connection_mode") == "direct_provider")
    local_account = bool(model and model.get("account_mode") == ACCOUNT_MODE)
    if local_account and (args.mode not in {"preflight", "probe"} or args.repetitions != 1
                          or catalog["purpose"] != "public_calibration" or args.tasks != ",".join(model["tasks"])):
        raise ValueError("隔离本机账号仅用于配置内固定公开题的一次预检或联调，不用于正式质量验收")
    if product and not use_isolation:
        raise ValueError("真实产品评测必须保持 AppContainer 工具隔离")
    if product and args.mode != "preflight" and not getattr(args, "authorize_model_calls", False):
        raise ValueError("未授权真实模型调用；请先确认测试账号、目标模型和单次/总预算")
    parent = args.work_dir.absolute()
    if parent.is_symlink() or parent.is_junction() or parent.exists() and parent.resolve() != parent:
        raise ValueError("评测父目录不能经链接跳转")
    parent.mkdir(parents=True, exist_ok=True)
    directory = new_directory(parent, args.mode)
    protocols = ["service", "openai", "ollama"] if args.mode == "matrix" else [model["protocol"] if model else args.protocol]
    schedule = []
    runner_paths = {*((ROOT / "scripts").glob("*coding_acceptance*.py")),
                    *(ROOT / "scripts" / name for name in ("coding_task_baseline.py", "coding_validation_process.py", "run_coding_validation.py",
                                                           "run_coding_local_probe.py"))}
    runner_hashes = {path.name: digest(path) for path in sorted(runner_paths)}
    for protocol in protocols:
        for task in tasks:
            for repetition in range(1, args.repetitions + 1):
                schedule.append({"attempt_id": f"{protocol}-{task['id']}-{repetition}", "task_id": task["id"],
                                 "model": model["model"] if model else "loopback-" + protocol, "mode": args.mode,
                                 "protocol": protocol, "family": task["family"], "category": task["category"], "split": task["split"],
                                 "coding_goal": task["coding_goal"], "repetition": repetition,
                                 "connection_mode": model["connection_mode"] if model else "fixture",
                                 "account_mode": ACCOUNT_MODE if local_account else "local_device" if product else "fixture",
                                 "holdout_exposure": task["holdout_exposure"],
                                 "binding": {"catalog_sha256": catalog["catalog_sha256"], "task_sha256": task["task_sha256"],
                                             "assessment_sha256": task.get("assessment_sha256", catalog["catalog_sha256"]),
                                             "runner_sha256": fingerprint(runner_hashes)}})
    manifest = {"mode": args.mode, "created_at": datetime.now(timezone.utc).isoformat(), "schedule": schedule,
                "catalog_version": catalog["version"], "catalog_sha256": catalog["catalog_sha256"],
                "sample_revisions": {task["id"]: verify_revision(task) for task in tasks}, "budget": catalog["budget"],
                "runner_sha256": runner_hashes, "catalog_source": catalog["catalog_source"], "purpose": catalog["purpose"],
                "catalog_path": catalog["catalog_path"], "isolation": catalog["isolation"],
                "statistics_version": "s6-attempt-ledger-1", "experiment_id": directory.name,
                "model": model, "quality_target": catalog["quality_target"],
                "connection_mode": model["connection_mode"] if model else "fixture",
                "account_mode": ACCOUNT_MODE if local_account else "local_device" if product else "fixture",
                "model_config_sha256": digest(args.model_config) if model else None,
                "model_config_path": str(args.model_config.resolve()) if model else None,
                "bundle_path": str(args.bundle.resolve()) if args.bundle else None,
                "parameters": model.get("parameters", {"reasoning_effort": None, "max_output_tokens": 2048, "auto_compact": True}) if model else {},
                "provider_defaults": "unknown_unless_returned_by_profile",
                "holdout_exposure": sorted({task["holdout_exposure"] for task in tasks}),
                "product": {}, "platform": sys.platform,
                "environment": {"os": platform.platform(), "machine": platform.machine(), "python": sys.version,
                                "python_executable_sha256": digest(Path(sys.executable)), "load": "unknown_not_sampled"},
                "permission_mode": "confirm",
                "approval_policy": "仅题目可编辑文件和预定可信项目验证命令；拒绝题不批准写入",
                "reproduce_argv": sys.argv}
    evidence = Evidence(directory, manifest)
    print(f"S6 证据目录：{directory}", flush=True)
    exit_code = 1
    isolation = None
    connection = None
    experiment_budget = ExperimentBudget(catalog["budget"], len(schedule), model=model, enforce_model_usage=model is not None)
    try:
        manifest["product"] = product_identity(args.bundle.resolve(strict=True) if args.bundle else None)
        for plan in schedule:
            plan["binding"]["product_sha256"] = fingerprint(manifest["product"])
        verify_catalog(catalog)
        manifest["preflight"] = preflight(tasks)
        if model and manifest["preflight"]["passed"]:
            connection = (LocalSession(model, directory, secret_input()) if local_account else
                          ProductSession(model) if product else None)
            if local_account:
                manifest["local_account"] = connection.identity()
            with connection or Fixture(model["protocol"], model=model) as account:
                model_area = new_directory(directory, "model-preflight")
                with RuntimeClient(model_area, account, bundle=args.bundle) as client:
                    client.request("/identity/local", "POST")
                    capabilities = client.request("/capabilities")
                    description = client.request("/model-evaluation/preflight?profile_id=" + quote(model.get("profile_id") or account.profile_id, safe=""))
                    missing = check_preflight(description, {**model, "profile_id": model.get("profile_id") or account.profile_id}, capabilities)
                    manifest["model_preflight"] = {"description": description, "sha256": model_identity_fingerprint(description), "missing": missing,
                                                  "passed": not missing, "inference_performed": False}
                    manifest["preflight"]["missing"].extend(missing)
                    manifest["preflight"]["passed"] = not manifest["preflight"]["missing"]
        if catalog["catalog_source"] == "external_json":
            if use_isolation and manifest["preflight"]["passed"]:
                from coding_acceptance_isolation import WindowsIsolation

                isolation = WindowsIsolation(directory / "tools")
                for family in {task["family"] for task in tasks}:
                    isolation.runtime(family)
                    isolation.agent_runtime(family)
                protected = [Path(tasks[0]["assessment_path"]), ROOT / "scripts/coding_acceptance_judge.py",
                             ROOT / "scripts/coding_acceptance_dataset.py"]
                candidate_probe = isolation.probe(protected, directory / "candidate-probe")
                marker = isolation.observer_directory("python") / "access-canary.txt"
                marker.write_text("S6_SYNTHETIC_EVALUATOR_ONLY", encoding="utf-8")
                isolation.seal_observer("python", marker)
                agent_probe = isolation.agent_probe([*protected, marker], directory / "agent-probe", bundle=args.bundle)
                manifest["isolation"] = {"verified": candidate_probe["verified"] and agent_probe["verified"],
                    "backend": "windows_appcontainer", "candidate_probe": candidate_probe, "agent_probe": agent_probe,
                    "runtime_sha256": isolation.identity(), "network_policy": "none"}
                if not manifest["isolation"]["verified"]:
                    manifest["preflight"]["missing"].append("actual_agent_or_judge_isolation_failed")
                manifest["approval_policy"] = "仅题目可编辑文件及预定 restricted/none 命令；拒绝可信执行降级"
            else:
                from coding_acceptance_judge import permission_probe

                manifest["isolation"] = permission_probe(Path(tasks[0]["assessment_path"]), directory)
            if catalog["purpose"] != "public_calibration":
                if not use_isolation:
                    manifest["preflight"]["missing"].append("independent_execution_backend_and_unexposed_holdout")
                if not custody_path:
                    manifest["preflight"]["missing"].append("independent_curator_receipt_and_unexposed_holdout")
                else:
                    from coding_acceptance_dataset import verify_custody

                    manifest["custody"] = verify_custody(catalog, custody_path, custody_hash)
            manifest["preflight"]["passed"] = not manifest["preflight"]["missing"]
        for plan in schedule:
            plan["binding"]["isolation_sha256"] = fingerprint(manifest["isolation"])
            plan["binding"]["model_sha256"] = fingerprint({"config": manifest["model_config_sha256"], "preflight": manifest.get("model_preflight")})
            if manifest.get("custody"):
                plan["binding"]["custody_sha256"] = manifest["custody"]["receipt_sha256"]
        write_json(directory / "manifest.json", manifest)
        if not manifest["preflight"]["passed"] or manifest["product"].get("source_matches") is False:
            evidence.errors.append("environment_or_product_preflight_failed")
        elif args.mode == "preflight":
            exit_code = 0
        else:
            lookup = {task["id"]: task for task in tasks}
            for plan in schedule:
                task = lookup[plan["task_id"]]
                attempt_budget = dict(task.get("budget", catalog["budget"]))
                if model and model.get("budget"):
                    for key, limit in model["budget"].items():
                        if limit is not None:
                            attempt_budget[key] = min(attempt_budget[key], limit) if attempt_budget.get(key) is not None else limit
                try:
                    attempt_budget = experiment_budget.allocate(attempt_budget)
                except ValueError as error:
                    evidence.append({**plan, "started": False, "failure_class": str(error), "human_interventions": 0})
                    continue
                area = new_directory(directory, plan["attempt_id"])
                verify_catalog(catalog)
                current_product = product_identity(args.bundle.resolve() if args.bundle else None)
                if current_product != manifest["product"]:
                    raise ValueError("候选身份在尝试前改变，未启动下一次尝试")
                if any(digest(ROOT / "scripts" / name) != sha for name, sha in runner_hashes.items()):
                    raise ValueError("运行器在尝试前改变，未启动下一次尝试")
                if model and digest(args.model_config) != manifest["model_config_sha256"]:
                    raise ValueError("模型配置在实验期间改变")
                if isolation:
                    isolation.verify()
                if custody_path:
                    from coding_acceptance_dataset import verify_custody

                    verify_custody(catalog, custody_path, custody_hash)
                row = attempt(lookup[plan["task_id"]], plan, area, evidence, bundle=args.bundle, model=model, isolation=isolation,
                              connection=connection, budget_override=attempt_budget)
                experiment_budget.settle(row)
                manifest["experiment_budget"] = experiment_budget.snapshot()
                print(f"{plan['attempt_id']}：{'通过' if row['system_behavior_passed'] else row['failure_class']}", flush=True)
                evidence.finish()
            exit_code = 0 if all(row.get("system_behavior_passed") for row in evidence.rows) and not evidence.errors else 1
    except (Exception, KeyboardInterrupt) as error:
        evidence.errors.append(type(error).__name__)
        # 仅保留脱敏定位帧，不记录异常正文、局部变量、账号或生产路径。
        import traceback

        manifest["runner_exception"] = {"type": type(error).__name__, "code": getattr(error, "code", None), "errno": getattr(error, "errno", None),
            "winerror": getattr(error, "winerror", None),
            "frames": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                       for frame in traceback.extract_tb(error.__traceback__)]}
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        if connection:
            connection.token = ""
            if isinstance(connection, LocalSession):
                try:
                    connection.close()
                except (OSError, RuntimeError):
                    evidence.errors.append("local_account_cleanup_failed")
        for row in evidence.rows:
            if row["attempt_id"] not in experiment_budget.settled:
                experiment_budget.settle(row)
        manifest["experiment_budget"] = experiment_budget.snapshot()
        try:
            if isolation:
                isolation.verify()
            if custody_path:
                from coding_acceptance_dataset import verify_custody

                verify_custody(catalog, custody_path, custody_hash)
            if any(digest(ROOT / "scripts" / name) != sha for name, sha in manifest["runner_sha256"].items()):
                evidence.errors.append("runner_changed_during_experiment")
            try:
                verify_catalog(catalog)
            except (OSError, ValueError):
                evidence.errors.append("catalog_or_assessment_changed_during_experiment")
            if manifest["product"] and product_identity(args.bundle.resolve() if args.bundle else None) != manifest["product"]:
                evidence.errors.append("product_changed_during_experiment")
            if model and digest(args.model_config) != manifest["model_config_sha256"]:
                evidence.errors.append("model_config_changed_during_experiment")
        except (OSError, ValueError, KeyError):
            evidence.errors.append("final_identity_unavailable")
        completed = {row["attempt_id"] for row in evidence.rows}
        for plan in schedule:
            if plan["attempt_id"] not in completed:
                evidence.append({**plan, "started": False, "failure_class": "preflight_only" if args.mode == "preflight" and exit_code == 0 else "not_started_after_runner_failure", "human_interventions": 0})
        write_json(directory / "manifest.json", manifest)
        evidence.finish()
    return exit_code if not evidence.errors else 130 if exit_code == 130 else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["preflight", "control", "matrix", "quality", "probe"], default="preflight")
    parser.add_argument("--tasks", help="逗号分隔的固定任务 ID；不设置时选择全部 30 题")
    parser.add_argument("--protocol", choices=["service", "openai", "ollama"], default="service")
    parser.add_argument("--repetitions", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--authorize-model-calls", action="store_true", help="确认专用测试账号及配置内的模型、单次/总预算已获授权")
    parser.add_argument("--catalog", type=Path, help="严格外部 JSON 清单；省略时保留既有公开校准")
    parser.add_argument("--isolation", choices=["none", "appcontainer"], default="none",
                        help="外部题集的原生隔离后端；正式用途必须为 appcontainer")
    parser.add_argument("--custody-receipt", type=Path, help="独立验收方的来源、未污染及正负控制回执")
    parser.add_argument("--custody-sha256", help="由验收方交接并人工核对的回执 SHA256")
    parser.add_argument("--work-dir", type=Path, default=ROOT / ".run/coding-acceptance")
    args = parser.parse_args()
    try:
        return run(args)
    except (ValueError, OSError) as error:
        print(f"S6 启动失败：{type(error).__name__}：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
