"""项目完成检查与有界诊断；只消费执行证据，不执行命令或授予权限。"""
from __future__ import annotations

import copy
import hashlib
import re
import shlex
from pathlib import Path, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from private_agent_core.coding_contracts import Requirement
from private_agent_core.completion import canonical_command, command_kind
from private_agent_core.contracts import AgentEventType
from private_agent_core.tool_specs import ToolFailure

from . import files, policy, reflection, task_constraints


class ObserverCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    kind: Literal["artifact", "test", "command"]
    scope: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_scope(self):
        if any(ord(char) < 32 for char in self.scope):
            raise ValueError("检查范围不能包含控制字符")
        if self.kind == "artifact":
            value = self.scope.replace("\\", "/")
            if (PureWindowsPath(value).drive or value.startswith("/")
                    or any(part in {"", ".", ".."} for part in value.split("/"))
                    or ":" in value or files.secret_path(Path(value))):
                raise ValueError("产物检查必须使用非敏感的项目内相对文件路径")
            self.scope = value
        else:
            try:
                policy.command_plan(self.scope, "confirm")
            except (ValueError, ToolFailure):
                raise ValueError("检查命令必须是登记的单个开发程序；不能包含内联代码、受保护路径或 Shell 拼接") from None
            if self.kind == "test" and command_kind(shlex.split(self.scope)) != "test":
                raise ValueError("测试检查需要可识别的测试命令；项目校验脚本请使用命令检查")
            self.scope = canonical_command(self.scope)
        return self


class ObserverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(default=0, ge=0)
    enabled: bool = False
    checks: list[ObserverCheck] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_checks(self):
        if len({item.id for item in self.checks}) != len(self.checks):
            raise ValueError("检查标识不能重复")
        if len({(item.kind, item.scope) for item in self.checks}) != len(self.checks):
            raise ValueError("检查内容不能重复")
        if self.enabled and not self.checks:
            raise ValueError("启用完成检查前至少配置一项检查")
        return self


class ObserverConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    enabled: bool
    checks: list[ObserverCheck] = Field(max_length=8)


def selected_checks(run: dict, root: Path | None) -> tuple[list[Requirement], list[dict]]:
    """配置是较低优先级的验收要求；当前用户限制不能被项目检查覆盖。"""
    config = ObserverConfig.model_validate(run.get("observer_config", {}))
    limits = task_constraints.restrictions(run)
    modifies = ("modify" in (run.get("task_interpretation") or {}).get("actions", [])
                or any(item.get("kind") == "file_changed" for item in run.get("completion_requirements", []))
                or run.get("workspace_version", 0) > 0)
    inactive = ("disabled" if not config.enabled else "plan_mode" if run.get("collaboration_mode") == "plan"
                else "readonly" if run.get("permission_mode") == "readonly"
                else "user_constraint" if limits.writes_forbidden else
                "not_applicable" if not modifies or limits.answer_only or limits.preview_only else None)
    requirements, checks = [], []
    used_ids = {item.get("requirement_id") for item in run.get("completion_requirements", [])}
    for check in config.checks:
        reason = inactive
        if reason is None and root is None:
            reason = "scope_unavailable"
        if reason is None:
            try:
                if check.kind == "artifact":
                    task_constraints.guard_paths(run, root, [check.scope])
                else:
                    # 不把配置当作命令授权；别名、测试禁令和路径范围仍由原策略判断。
                    task_constraints.guard_command(run, root, shlex.split(check.scope))
            except (ValueError, ToolFailure):
                reason = "user_constraint"
        requirement_id, suffix = f"observer-{check.id}", 1
        while requirement_id in used_ids:
            suffix += 1
            requirement_id = f"observer-{check.id}-{suffix}"
        used_ids.add(requirement_id)
        status = "unverified" if reason == "scope_unavailable" else "skipped" if reason else "pending"
        checks.append({"id": check.id, "kind": check.kind, "status": status,
                       "reason_code": reason or "awaiting_evidence", "evidence_ids": [], "requirement_id": requirement_id})
        if reason is None:
            requirements.append(Requirement(requirement_id=requirement_id, kind=check.kind,
                scope=check.scope, description=f"项目完成检查：{check.scope}", origin="tool",
                evidence_policy={"artifact": "disk", "test": "test_exit", "command": "exit"}[check.kind]))
    return requirements, checks


def check_guidance(run: dict, root: Path) -> dict | None:
    requirements, _ = selected_checks(run, root)
    if not requirements:
        return None
    return {"config_version": run["observer_config"]["version"],
            "checks": [{"kind": item.kind, "scope": item.scope} for item in requirements],
            "notice": "修改任务交付前需要这些完成证据。命令在项目根目录执行，通过现有工具及审批；配置不是授权，用户禁止项优先。"}


def check_version(run: dict) -> dict:
    return {key: run.get(key, 0) for key in ("goal_version", "workspace_version", "generation")}


def record_checks(owner, run: dict, checks: list[dict], results) -> None:
    by_id = {item.requirement_id: item for item in results}
    for check in checks:
        result = by_id.get(check["requirement_id"])
        if result is not None and check["status"] != "skipped":
            check.update(status=result.status, reason_code="evidence_" + result.status, evidence_ids=result.evidence_ids)
    if checks:
        with owner.store.transaction(run=run):
            run["observer_checks"] = checks
            run["observer_check_version"] = check_version(run)
            owner.event(run, "observer.checks_completed", config_version=run["observer_config"]["version"],
                        checks=checks, decision="block" if any(item["status"] in {"failed", "blocked", "unverified"} for item in checks) else "allow")


ERROR_CATEGORIES = {
    "no_progress": "progress", "output_validation_failed": "verification", "verification_error": "verification",
    "context_limit": "budget", "max_model_requests": "budget", "max_tool_calls": "budget",
    "max_active_seconds": "budget", "max_total_tokens": "budget", "max_cost_usd": "budget",
    "approval_denied": "permission", "user_constraint": "permission", "command_not_allowed": "permission",
    "local_tool_rejected": "tool", "tool_input_invalid": "tool", "tool_output_invalid": "tool",
    "command_failed": "execution", "command_timed_out": "execution", "command_cancelled": "execution",
    "model_invalid_response": "model", "model_not_configured": "model", "model_request_failed": "model",
    "cancelled": "control", "steering_superseded": "control", "desktop_restarted": "recovery",
    "local_execution_failed": "storage",
    "reflection_review_required": "verification", "reflection_review_unavailable": "verification",
}
EVENT_TYPES = {item.value for item in AgentEventType} | {
    "model.requested", "model.transport", "model.output.delta", "model.output.finished", "model.output.interrupted",
    "model.response_confirmed", "model.response_discarded", "tool.result_recorded", "tool.invocation_finished",
    "execution.output", "execution.terminal", "execution.started", "progress.observed", "progress.warning",
    "progress.stalled", "observer.checks_started", "observer.checks_completed", "observer.checks_failed",
    "evidence.revalidated", "run.interrupted", "run.paused", "run.resumed", "run.queued",
    "reflection.observed", "reflection.warning", "reflection.verification_observed",
    "reflection.review_started", "reflection.review_usage", "reflection.review_passed",
    "reflection.review_revise", "reflection.review_unavailable", "reflection.review_stale",
    "reflection.review_cancelled",
}


def category(kind: str, code=None) -> str:
    if code in ERROR_CATEGORIES:
        return ERROR_CATEGORIES[code]
    return {"model": "model", "tool": "tool", "execution": "execution", "progress": "progress",
            "observer": "verification", "reflection": "verification", "output": "verification", "context": "context",
            "plan": "plan", "run": "control", "evidence": "verification"}.get(kind.split(".")[0], "other")


def identifier(value):
    # 诊断只允许程序生成的 UUID；工具调用 ID 等模型自由文本不进入可复制摘要。
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{8}-[a-f0-9-]{27}", value) else None


class Observer:
    def __init__(self, owner):
        self.owner, self.store = owner, owner.store

    def config(self, project_id: int) -> dict:
        raw = self.store.get("project", project_id).get("observer_config", {})
        return ObserverConfig.model_validate(raw).model_dump()

    def save(self, project_id: int, data: ObserverConfigInput) -> dict:
        try:
            config = ObserverConfig(version=data.expected_version + 1, enabled=data.enabled, checks=data.checks)
        except ValidationError:
            raise ToolFailure("observer_config_invalid", "启用时至少需要一项检查，且检查标识和内容不能重复") from None
        project = self.store.get("project", project_id)
        root = files.authorize_root(project["root_path"])
        for check in config.checks:
            if check.kind == "artifact":
                policy.file_scope(root, check.scope, "readonly")
        with self.store.transaction():
            if self.config(project_id)["version"] != data.expected_version:
                raise ToolFailure("observer_config_changed", "完成检查配置已变化，请刷新后再保存")
            result = config.model_dump()
            self.store.update("project", project_id, observer_config=result)
        return result

    def bind(self, run: dict, parent: dict | None) -> None:
        # 同一逻辑任务沿用启动快照；中途修改设置不能隐式撤销原验收要求。
        run["observer_config"] = copy.deepcopy(parent.get("observer_config", ObserverConfig().model_dump())
                                               if parent is not None else self.config(run["project_id"]))

    def report(self, run_id: str) -> dict:
        with self.store.transaction():
            run = self.store.run_state(run_id)
            counts = {table: self.store.db.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)).fetchone()[0]
                      for table in ("events", "executions")}
            rows = self.store.db.execute("SELECT data FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 100", (run_id,)).fetchall()
        steps = run.get("steps", [])
        counts["steps"] = len(steps)
        events = []
        for row in reversed(rows):
            event = self.store._unpack(row[0])
            kind = event.get("type") if event.get("type") in EVENT_TYPES else "other"
            payload = event.get("payload") or {}
            events.append({"sequence": event["sequence"], "type": kind, "step_id": identifier(event.get("step_id")),
                           "execution_id": identifier(payload.get("execution_id")),
                           "category": category(kind, payload.get("error_code") or payload.get("error_type"))})
        code = run.get("error_code")
        known_code = code if code in ERROR_CATEGORIES else "unknown_error"
        checks = run.get("observer_checks")
        stale = checks is not None and run.get("observer_check_version") != check_version(run)
        if checks is None or stale:
            _, checks = selected_checks(run, None)
            if any(item["reason_code"] == "scope_unavailable" for item in checks):
                try:
                    root = self.owner.root(run["project_id"], run["workspace_id"])
                except (KeyError, OSError, ValueError, ToolFailure):
                    # 历史工作目录失效仍允许查看诊断，不据此声称检查通过或用户禁止。
                    pass
                else:
                    _, checks = selected_checks(run, root)
            if stale:
                for check in checks:
                    if check["status"] == "pending":
                        check["reason_code"] = "evidence_stale"
        return {"schema_version": "1.0", "run_id": run["id"], "status": run["status"],
                "goal_outcome": (run.get("run_outcome") or {}).get("goal_outcome"),
                "last_event_sequence": run["last_event_sequence"], "config_version": (run.get("observer_config") or {}).get("version"),
                "counts": counts, "truncated": counts["events"] > 100 or len(steps) > 100,
                "progress": {"repeated_observations": (run.get("orchestration_progress") or {}).get("repeats", 0),
                             "failure_repeats": max((run.get("loop_budget") or {}).get("failure_count", 0),
                                                    reflection.failure_repeats(run)),
                             "verification_retries": run.get("verification_retries", 0)},
                "error": {"category": ERROR_CATEGORIES.get(code, "other"), "code": known_code} if code else None,
                "steps": [{"id": identifier(item["id"]), "ordinal": item["ordinal"], "kind": item["kind"], "status": item["status"],
                           "name": item.get("name") if item.get("name") in self.owner.registry else None,
                           "plan_item_key": ("plan-" + hashlib.sha256(str(item["plan_context"]["item_key"]).encode()).hexdigest()[:12]
                                             if (item.get("plan_context") or {}).get("item_key") else None)} for item in steps[-100:]],
                "checks": [{key: item[key] for key in ("id", "kind", "status", "reason_code", "evidence_ids")} for item in checks],
                "events": events}
