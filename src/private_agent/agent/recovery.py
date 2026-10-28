"""持久化恢复事实与控制请求；检查点从不充当可重放的授权。"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from private_agent.agent import reflection
from private_agent.agent.planning import state_digest
from private_agent.agent.progress import STOP_AT
from private_agent.context.budget import ContextLimits, configuration_version
from private_agent.storage.store import encode, now
from private_agent.workspace import files

VERSION = "1.0"
# 活动计时回执的内部格式版本；与恢复协议版本分开演进，旧记录缺该字段时保守派生。
TIMING_VERSION = "1.0"
# 人工核对记录的格式版本；决定只追加，不改写原执行、补丁日志与未知结果。
RESOLUTION_VERSION = "1.0"
RESOLUTION_LIMIT = 64
NOTE_LIMIT = 2000
# 只有模型传输或供应商暂时故障才允许人工续跑；这些错误码由适配器实际产生（见 direct_models/local_models/llm.gateway），
# 不按错误文案猜测。权限、历史损坏、预算与未知副作用不在此列。
RESUMABLE_ERRORS = frozenset({"model_network_error", "model_timeout", "model_stream_interrupted",
                              "model_rate_limited", "model_provider_unavailable"})
# 跨模型续跑的交接格式版本；只记录身份、配置差异与用户确认，不含旧供应商不透明状态。
HANDOFF_VERSION = "1.0"
ACTIVE = {"created", "queued", "running", "waiting_approval", "waiting_input", "paused"}


def resolutions_digest(run: dict) -> str:
    """核对决定的摘要，用于和恢复检查点绑定，防止事后替换处理结论。"""
    return hashlib.sha256(encode(run.get("recovery_resolutions") or []).encode()).hexdigest()


def item_identity(kind: str, **fields) -> str:
    """待处理项的稳定标识：只由类型与原始操作身份构成，不随文案变化。"""
    data = {"kind": kind, **{key: value for key, value in fields.items() if value is not None}}
    return hashlib.sha256(encode(data).encode()).hexdigest()[:32]


def covers(record: dict, item: dict) -> bool:
    """判断一条核对记录是否指向同一个待处理项。

    文件项按补丁组与路径绑定，不能靠共享操作标识覆盖同组其他文件；
    其余项允许同一原始操作换运行后仍视为同一项，避免续跑链重复阻塞。
    """
    if record.get("item_id") == item.get("item_id"):
        return True
    if item.get("kind") == "file_operation":
        return False
    target, want = record.get("target") or {}, item.get("target") or {}
    return bool(target.get("operation_id")) and target.get("operation_id") == want.get("operation_id")


def evidence_matches(record: dict, item: dict) -> bool:
    """核对记录必须绑定当时观察到的证据，现场变化后旧决定失去放行效力。"""
    if item.get("kind") not in {"file_operation", "mcp_write"}:
        return True
    bound = record.get("evidence")
    if bound is None:
        # 旧记录没有证据绑定：无法证明现场未变，保守视为失效（仍保留作审计）。
        return False
    return encode(bound) == encode(item.get("evidence") or {})


def reconcile_mcp_execution(run: dict, execution: dict) -> bool:
    """发送后的写调用在确认前中断，保留副作用未知事实并阻止恢复重放。"""
    call = execution.get("mcp_call") or {}
    if call.get("phase") == "acknowledged" and isinstance(execution.get("output"), dict):
        execution.update(status="completed", error_code=None, error_message=None,
                         completed_at=execution.get("completed_at") or now())
        return True
    if call.get("phase") != "dispatched" or call.get("readonly") is not False:
        return False
    scope = execution.get("scope") or {"kind": "external", "source_id": call.get("source_id"), "tool": call.get("tool")}
    execution.update(status="unknown", error_code="execution_unknown", scope=scope,
                     error_message="MCP 写操作已发送，远端结果未确认；请先核对远端结果，不会自动重放",
                     completed_at=execution.get("completed_at") or now())
    operation = {"operation_id": execution["operation_id"], "scope": scope,
                 # 有完整身份的新记录只阻止同一原调用重发；缺指纹的旧记录继续按来源与工具保守限制。
                 "tool_name": execution.get("tool_name") or call.get("tool"),
                 "tool_version": execution.get("tool_version"),
                 "arguments_sha256": execution.get("arguments_sha256"),
                 "run_id": run.get("id")}
    uncertain = run.setdefault("uncertain_operations", [])
    if operation not in uncertain:
        uncertain.append(operation)
    return True


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    request_id: str = Field(min_length=1, max_length=100)
    expected_state_version: int = Field(ge=0)
    checkpoint_id: str | None = Field(default=None, max_length=128)


class SteerInput(ControlInput):
    message: str = Field(min_length=1, max_length=32000)


class ReconcileInput(ControlInput):
    """人工核对提交：绑定待处理项身份、现场检查点与处理方式。"""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    item_id: str = Field(min_length=1, max_length=64)
    kind: Literal["file_operation", "mcp_write", "command", "operation", "abandon_task"]
    decision: Literal["record_observation", "externally_confirmed", "externally_failed", "abandon"]
    note: str | None = Field(default=None, max_length=NOTE_LIMIT)
    # 核对依据：必须是本次现场 report 中该项的 evidence，用于拒绝凭旧内容或猜测放行。
    evidence: dict | None = None


class ResumeInput(ControlInput):
    """续跑输入：可选择目标模型并显式确认模型变化与未确认计时尾段。"""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    model_profile_id: str | None = Field(default=None, max_length=100)
    preview_sha256: str | None = Field(default=None, max_length=128)
    accept_model_change: bool | None = None
    accept_unconfirmed_timing: bool | None = None


class ResumePreviewInput(BaseModel):
    """只读预览输入；不创建运行、不改默认模型、不调用真实模型。"""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    model_profile_id: str | None = Field(default=None, max_length=100)
    checkpoint_id: str | None = Field(default=None, max_length=128)


def model_facts(profile: dict) -> dict:
    """恢复与切换模型时公开的模型身份与能力事实。"""
    return {"model_profile_id": profile.get("id"), "model_name": profile.get("model_name"),
            "provider": profile.get("provider"), "api_format": profile.get("api_format"),
            "endpoint": profile.get("endpoint"), "context_tokens": profile.get("context_tokens"),
            "native_tool_calls": profile.get("native_tool_calls") is True,
            "supports_vision": profile.get("supports_vision") is True,
            "supports_structured_output": profile.get("supports_structured_output") is True,
            "configuration_version": configuration_version(profile),
            "capability_version": model_capability_version(profile)}


class ControlConflict(ValueError):
    def __init__(self, message, version):
        super().__init__(message)
        self.version = version


def create_schema(db):
    db.execute("CREATE TABLE run_checkpoints(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL, sha256 TEXT NOT NULL, data TEXT NOT NULL)")
    db.execute("CREATE INDEX run_checkpoints_run ON run_checkpoints(run_id,sequence)")
    db.execute("CREATE TABLE run_control_requests(run_id TEXT NOT NULL REFERENCES runs(id), request_id TEXT NOT NULL, kind TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,request_id))")
    db.execute("CREATE TABLE workspace_leases(workspace_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner TEXT NOT NULL, generation INTEGER NOT NULL, state TEXT NOT NULL, updated_at TEXT NOT NULL)")


def model_capability_version(profile):
    keys = ("id", "provider", "model_name", "context_tokens", "native_tool_calls", "supports_streaming",
            "supports_structured_output", "supports_vision", "reasoning_efforts", "usage_reporting")
    data = {key: profile.get(key) for key in keys}
    data.update({key: profile[key] for key in ("api_format", "endpoint") if key in profile})
    return hashlib.sha256(encode(data).encode()).hexdigest()


def checkpoint(store, run, boundary, **facts):
    """由 Store.emit 的同一事务调用，内容先落盘再发布引用。"""
    cursor = store.db.execute("SELECT COALESCE(MAX(ordinal),0) FROM context_items WHERE session_id=?", (run.get("session_id"),)).fetchone()[0]
    value = {"format_version": VERSION, "run_id": run["id"], "logical_task_id": run["logical_task_id"],
             "project_id": run["project_id"], "workspace_id": run["workspace_id"], "session_id": run["session_id"],
             "workspace_key": run.get("workspace_key"), "root_identity": run.get("root_identity"),
             "context_cursor": cursor, "context_checkpoint_id": (store.context.checkpoint(run["session_id"]) or {}).get("id"),
             "state_version": run["state_version"], "event_sequence": run["last_event_sequence"],
             "boundary": boundary, "created_at": now(), "budget": run.get("loop_budget", {}),
             "model_config_version": run.get("model_config_version"),
             "model_capability_version": run.get("model_capability_version"),
             "execution_contract_version": run.get("execution_contract_version"),
             "goal_version": run.get("goal_version", 1), "generation": run.get("generation", 0),
             "pending_response": run.get("pending_response"),
             "orchestration_digest": state_digest(run),
             "timing": run.get("timing"),
             "resolutions_digest": resolutions_digest(run),
             "operation_ids": [e.get("operation_id") for e in run.get("executions", [])], **facts}
    identifier = str(uuid.uuid4())
    digest = hashlib.sha256(encode(value).encode()).hexdigest()
    store.db.execute("INSERT INTO run_checkpoints VALUES (?,?,?,?,?)", (identifier, run["id"], run["last_event_sequence"], digest, store._pack(value)))
    run["checkpoint_id"] = identifier


class Recovery:
    def __init__(self, owner):
        self.owner, self.store = owner, owner.store

    def controls(self, run_id):
        return [json.loads(row[0]) for row in self.store.db.execute("SELECT data FROM run_control_requests WHERE run_id=? ORDER BY rowid", (run_id,))]

    def save_control(self, run_id, request_id, record):
        self.store.db.execute("UPDATE run_control_requests SET data=? WHERE run_id=? AND request_id=?", (encode(record), run_id, request_id))

    def prior(self, run, kind, data):
        row = self.store.db.execute("SELECT fingerprint,data FROM run_control_requests WHERE run_id=? AND request_id=?", (run["id"], data["request_id"])).fetchone()
        fingerprint = hashlib.sha256(encode({"kind": kind, **data}).encode()).hexdigest()
        if row:
            if row[0] != fingerprint:
                raise ControlConflict("请求标识已用于不同的控制内容", run.get("state_version", 0))
            return json.loads(row[1])
        if run.get("recovery_contract_version") != VERSION:
            raise ValueError("旧记录不支持恢复控制，请基于历史创建新任务")
        if run.get("state_version", 0) != data["expected_state_version"]:
            raise ControlConflict("任务状态已变化，请刷新现场后重试", run.get("state_version", 0))
        return None

    def insert(self, run, kind, data):
        if len(self.controls(run["id"])) >= 256:
            raise ValueError("本次运行控制请求达到 256 条上限")
        record = {"request_id": data["request_id"], "kind": kind, "status": "received", "received_at": now(),
                  "applied_at": None, "run_id": run["id"], "result_run_id": run["id"]}
        if kind == "steer":
            record["message"] = data["message"]
        fingerprint = hashlib.sha256(encode({"kind": kind, **data}).encode()).hexdigest()
        self.store.db.execute("INSERT INTO run_control_requests VALUES (?,?,?,?,?)", (run["id"], data["request_id"], kind, fingerprint, encode(record)))
        return record

    def load_checkpoint(self, run):
        row = self.store.db.execute("SELECT run_id,sha256,data FROM run_checkpoints WHERE id=?", (run.get("checkpoint_id"),)).fetchone()
        if not row or row[0] != run["id"]:
            raise ValueError("缺少属于本运行的恢复检查点")
        value = self.store._unpack(row[2])
        if hashlib.sha256(encode(value).encode()).hexdigest() != row[1]:
            raise ValueError("检查点摘要校验失败")
        if value.get("format_version") != VERSION:
            raise ValueError("检查点格式不兼容，请使用匹配的客户端")
        if value.get("run_id") != run["id"]:
            raise ValueError("检查点运行归属不一致")
        for key in ("logical_task_id", "project_id", "workspace_id", "session_id", "workspace_key", "root_identity"):
            if value.get(key) != run.get(key):
                raise ValueError("检查点归属或工作区身份不一致")
        if value["event_sequence"] > run["last_event_sequence"]:
            raise ValueError("检查点引用未提交事件")
        if value.get("orchestration_digest") is not None and value["orchestration_digest"] != state_digest(run):
            raise ValueError("计划或进度与已提交检查点不一致，不能继续")
        # 核对决定必须与检查点绑定；出现决定却缺摘要时按失败关闭处理。
        if "resolutions_digest" in value:
            if value["resolutions_digest"] != resolutions_digest(run):
                raise ValueError("核对记录与已提交检查点不一致，请重新核对现场")
        elif run.get("recovery_resolutions"):
            raise ValueError("核对记录缺少检查点绑定，不能继续")
        # 读取会校验内容块摘要与工具关联，不能恢复损坏的历史。
        self.store.context.messages(run["session_id"])
        return value

    def inspect(self, run, *, for_lease=False):
        effects, failures, patch_facts, latest = [], [], [], {}
        try:
            if not for_lease or run.get("recovery_contract_version"):
                self.load_checkpoint(run)
            root = self.owner.root(run["project_id"], run["workspace_id"])
            if files.file_identity(root) != run["root_identity"]:
                raise ValueError("工作区根身份已变化")
            for patch in self.owner.patches.list(run["id"]):
                for fact in self.owner.patches.facts(run["id"], patch["patch_set_id"], root):
                    fact = {**fact, "patch_set_id": patch["patch_set_id"], "operation_id": patch.get("operation_id")}
                    patch_facts.append(fact)
                    if fact["journal_status"] != "not_started":
                        latest[fact["rel_path"]] = fact
            for fact in latest.values():
                if fact["observation"] in {"conflict", "unreadable"} or fact["journal_status"] == "applying":
                    # 只有当前内容能对上写入前或写入后的摘要，才算机器可判定的核对。
                    readable = fact["observation"] in {"matches_after", "matches_before"}
                    effects.append({
                        "item_id": item_identity("file_operation", patch_set_id=fact["patch_set_id"], relative_path=fact["rel_path"]),
                        "kind": "file_operation", "label": "文件操作需核对：" + fact["rel_path"],
                        "target": {"patch_set_id": fact["patch_set_id"], "relative_path": fact["rel_path"],
                                   "operation_id": fact.get("operation_id")},
                        "observation": fact["observation"],
                        "evidence": {"journal_status": fact["journal_status"],
                                     "expected_before_sha256": fact.get("before_sha256"),
                                     "expected_after_sha256": fact.get("after_sha256"),
                                     "actual_sha256": fact.get("actual_sha256")},
                        "actions": ["record_observation"] if readable else [], "resolvable": readable,
                        "reason": None if readable else "文件内容与写入前、写入后摘要都不匹配；请先还原文件或重新读取，不能忽略冲突解锁"})
        except (ValueError, OSError) as error:
            label = str(error) if isinstance(error, ValueError) else "恢复内容不可读取"
            failures.append({"item_id": item_identity("history", code=label), "kind": "history", "label": label,
                             "target": {}, "actions": [], "resolvable": False,
                             "reason": "需要在原工作区修复检查点或历史后刷新现场"})
        executions = [e for e in self.store.execution_sessions.list(run["session_id"]) if e["run_id"] == run["id"]]
        for execution in executions:
            if execution["status"] == "unknown" or not execution.get("stopped") and execution["status"] not in {"running", "starting"}:
                effects.append({
                    "item_id": item_identity("command", execution_id=execution["execution_id"]),
                    "kind": "command", "label": "命令结果或进程身份未知：" + execution["execution_id"],
                    "target": {"execution_id": execution["execution_id"], "operation_id": execution.get("operation_id"),
                               "run_id": run["id"]},
                    "observation": {"status": execution["status"], "stopped": execution.get("stopped"),
                                    "process_id": execution.get("process_id")},
                    "evidence": {"host": "execution_sessions", "stopped": execution.get("stopped")},
                    "actions": [], "resolvable": False,
                    "reason": "只有执行宿主报告终态或进程树停止证据才能解除；不能凭 PID、时间经过或人工勾选认定停止"})
        known = {item["target"].get("execution_id") for item in effects if item["kind"] == "command"}
        for execution in run.get("executions", []):
            mcp = execution.get("mcp_call") or {}
            if mcp.get("phase") == "dispatched" and mcp.get("readonly") is False:
                effects.append({
                    "item_id": item_identity("mcp_write", execution_id=execution["id"]),
                    "kind": "mcp_write", "label": "MCP 写入结果未知，请先核对远端结果：" + execution["id"],
                    "target": {"execution_id": execution["id"], "operation_id": execution.get("operation_id"),
                               "tool": mcp.get("tool"), "source_id": mcp.get("source_id"),
                               "tool_version": execution.get("tool_version"),
                               "arguments_sha256": execution.get("arguments_sha256")},
                    "observation": {"phase": mcp.get("phase")},
                    "evidence": {"call_id": mcp.get("call_id"), "phase": mcp.get("phase"),
                                 "source_id": mcp.get("source_id"), "tool": mcp.get("tool"),
                                 "tool_version": execution.get("tool_version"),
                                 "arguments_sha256": execution.get("arguments_sha256")},
                    "actions": ["externally_confirmed", "externally_failed"], "resolvable": True,
                    "reason": "系统无法验证远端结果；人工说明只解除续跑阻塞，不产生成功证据，也不会重发请求"})
            if execution.get("command") and execution["id"] not in known and (
                    execution["status"] == "unknown" or execution.get("error_code") == "execution_unknown"):
                effects.append({
                    "item_id": item_identity("command", execution_id=execution["id"]),
                    "kind": "command", "label": "命令副作用未知：" + execution["id"],
                    "target": {"execution_id": execution["id"], "operation_id": execution.get("operation_id"),
                               "run_id": run["id"]},
                    "observation": {"status": execution["status"], "error_code": execution.get("error_code")},
                    "evidence": {"host": "run.executions"}, "actions": [], "resolvable": False,
                    "reason": "命令副作用没有机器终态证据；不能在恢复时重新执行或假定已停止"})
        covered = {item["target"].get("operation_id") for item in effects if item["target"].get("operation_id")}
        for operation in run.get("uncertain_operations") or []:
            operation_id = operation.get("operation_id")
            if operation_id and operation_id in covered:
                continue
            effects.append({
                "item_id": item_identity("operation", operation_id=operation_id, run_id=run["id"] if not operation_id else None),
                "kind": "operation", "label": "存在未核实的副作用；不能自动继续",
                "target": {"operation_id": operation_id, "scope": operation.get("scope"),
                           "tool_name": operation.get("tool_name"), "tool_version": operation.get("tool_version"),
                           "arguments_sha256": operation.get("arguments_sha256")},
                "observation": None, "evidence": None, "actions": [], "resolvable": False,
                "reason": "原副作用仍无机器证据；人工说明不会把它改写成成功，也不能据此重放"})
        return self._report(run, effects, failures, patch_facts, executions, latest, for_lease=for_lease)

    def _report(self, run, effects, failures, patch_facts, executions, latest, *, for_lease=False):
        records = self.resolutions(run)
        details, open_effects, blockers = [], [], []

        def resolution(item):
            """返回 (有效记录, 失效记录)；失效记录只保留审计，不再放行当前现场。"""
            stale = None
            for record in reversed(records):
                if not covers(record, item):
                    continue
                if evidence_matches(record, item):
                    return record, None
                stale = stale or record
            return None, stale

        stale_count = 0
        for item in effects:
            record, stale = resolution(item)
            if record:
                details.append({**item, "source": item.get("source", "machine"), "status": "resolved", "resolution": {
                    "decision": record.get("decision"), "source": record.get("source", "user_statement"),
                    "verified": record.get("verified", False),
                    "note": record.get("note"), "created_at": record.get("created_at")}})
            else:
                entry = {**item, "source": item.get("source", "machine"), "status": "open"}
                if stale:
                    stale_count += 1
                    entry["stale_resolution"] = {"resolution_id": stale.get("resolution_id"),
                                                 "decision": stale.get("decision"), "created_at": stale.get("created_at")}
                    entry["reason"] = "此前的核对记录基于不同的现场内容，已失去放行效力（保留作审计）；请重新核对当前内容"
                details.append(entry)
                open_effects.append(item)
                blockers.append(item["label"])
        for failure in failures:
            details.append({**failure, "source": "machine", "status": "open"})
            blockers.append(failure["label"])
        if open_effects:
            reasons = self.local_activity(run)
            details.append({"item_id": item_identity("abandon_task", run_id=run["id"]), "kind": "abandon_task",
                            "label": "放弃后续恢复（保留已改文件与未知结果）", "target": {"run_id": run["id"]},
                            "observation": None, "evidence": {"active": reasons}, "actions": ["abandon"],
                            "status": "open", "resolvable": True,
                            "reason": ("；".join(reasons) + "；可以先记录放弃，但工作区租约要等本地活动确认静止后才释放")
                                      if reasons else None})
        limits = ContextLimits.model_validate(run.get("context_limits", {}))
        budget = run.get("loop_budget", {})
        if not for_lease and (budget.get("model_requests", 0) >= limits.max_model_requests or run["tool_call_count"] >= limits.max_tool_calls
                or budget.get("active_seconds", 0) >= limits.max_active_seconds
                or budget.get("failure_count", 0) >= 4
                or reflection.stalled(run)
                or (run.get("orchestration_progress") or {}).get("repeats", 0) >= STOP_AT
                or limits.max_cost_usd is not None and (budget.get("cost_usd") is None or budget["cost_usd"] >= limits.max_cost_usd)):
            blockers.append("逻辑任务累计预算不足或费用未知")
            details.append({"item_id": item_identity("budget", run_id=run["id"]), "kind": "budget",
                            "label": "逻辑任务累计预算不足或费用未知", "target": {}, "observation": None,
                            "evidence": {"budget": budget, "limits": run.get("context_limits")},
                            "status": "open", "actions": [], "resolvable": False,
                            "reason": "预算或失败记录不能因人工核对清零；请核对结果后新建任务"})
        if not for_lease and self.store.get("session", run["session_id"]).get("last_run_id") != run["id"]:
            blockers.append("会话已有后续运行，请从最新运行继续")
            details.append({"item_id": item_identity("session", run_id=run["id"]), "kind": "session",
                            "label": "会话已有后续运行，请从最新运行继续", "target": {}, "observation": None,
                            "evidence": None, "status": "open", "actions": [], "resolvable": False, "reason": "请在最新运行上恢复"})
        timing = run.get("timing") if isinstance(run.get("timing"), dict) else None
        limitations = ["重启后的命令不凭 PID 重新附着；身份或结果不明时阻止继续",
                       "继续会重新核对模型与权限，并从已提交历史重新规划；不重放旧工具序列"]
        if timing and timing.get("unconfirmed_tail"):
            limitations.append("已记录活动时间，末段耗时未确认；继续不会补算离线间隔")
        if stale_count:
            limitations.append(f"有 {stale_count} 条核对记录因现场内容变化而失效；需要重新核对后才能继续")
        if any(not operation.get("arguments_sha256") for operation in run.get("uncertain_operations") or []):
            limitations.append("存在缺少参数指纹的旧未确认操作；同一来源与工具的新调用仍会被保守阻止")
        return {"run_id": run["id"], "supported": run.get("recovery_contract_version") == VERSION,
                "status": run["status"], "state_version": run.get("state_version", 0),
                "checkpoint_id": run.get("checkpoint_id"), "logical_task_id": run.get("logical_task_id"),
                "resumed_from_run_id": run.get("resumed_from_run_id"), "goal_version": run.get("goal_version", 1),
                "model_profile_id": run.get("model_profile_id"),
                "can_resume": not blockers and self.resumable(run),
                "recovery_class": self.classification(run), "resumable_error": run.get("error_code") if self.classification(run) == "model_error" else None,
                "blockers": list(dict.fromkeys(blockers)), "blocker_details": details,
                "open_items": [item["item_id"] for item in details if item.get("status") == "open" and item.get("actions")],
                "resolutions": records[-RESOLUTION_LIMIT:], "patch_facts": patch_facts, "executions": executions,
                "controls": self.controls(run["id"]), "budget": budget, "timing": timing,
                "time_policy": budget.get("recovery_time_policy"),
                "queue_reason": run.get("queue_reason"), "queue_position": run.get("queue_position"),
                "expired_approvals": [a["id"] for a in run.get("approvals", []) if a["status"] in {"cancelled", "expired"}],
                "limitations": limitations}

    @staticmethod
    def resumable(run) -> bool:
        """哪些结束状态允许人工续跑：常规中断/取消/暂停，以及明确的模型传输故障。"""
        if run["status"] in {"paused", "interrupted", "cancelled"}:
            return True
        return run["status"] in {"failed", "timed_out"} and run.get("error_code") in RESUMABLE_ERRORS

    def classification(self, run) -> str:
        """把结束状态映射为恢复方式，供界面与接口使用，避免解析中文错误字符串。"""
        if run["status"] in ACTIVE:
            return "active"
        if run["status"] in {"paused", "interrupted", "cancelled"}:
            return "manual_resume"
        if run["status"] in {"failed", "timed_out"} and run.get("error_code") in RESUMABLE_ERRORS:
            return "model_error"
        if run["status"] == "limit_exceeded":
            return "budget_stop"
        return "not_resumable"

    def capability_gaps(self, run, profile) -> list[str]:
        """切换模型前的必需能力核对；缺能力时不发起真实请求。"""
        gaps = []
        if run.get("output_schema") and profile.get("supports_structured_output") is not True:
            gaps.append("目标模型未声明结构化输出能力")
        if self.vision_required(run) and profile.get("supports_vision") is not True:
            gaps.append("目标模型未声明图片输入能力")
        if profile.get("native_tool_calls") is not True:
            root = self.owner.root(run["project_id"], run["workspace_id"])
            if self.owner.model_tools(run, root):
                gaps.append("目标模型未声明原生工具调用能力；恢复后无法执行工具")
        # 单次窗口按当前待发上下文核对；累计用量是预算约束，另由预算规则继承。
        capacity = profile.get("context_tokens")
        estimate = self.pending_context_tokens(run)
        if type(capacity) is int and capacity > 0 and estimate:
            limits = ContextLimits.model_validate(run.get("context_limits", {}))
            available = max(0, capacity - limits.reserved_output_tokens - max(512, math.ceil(capacity * 0.05)))
            if estimate > available:
                gaps.append("目标模型的上下文容量不足以容纳当前待发上下文")
        return gaps

    def vision_required(self, run) -> bool:
        """按附件现有元数据判断是否真的需要视觉能力；纯文本附件不占用图片能力。"""
        for identifier in run.get("attachment_ids") or []:
            try:
                item = self.owner.store.attachments.get(identifier)
            except (ValueError, KeyError, OSError):
                # 元数据不可读时不猜测附件类型，先阻止换到无视觉能力的模型。
                return True
            if isinstance(item, dict) and item.get("requires_vision") is True:
                return True
        return False

    @staticmethod
    def pending_context_tokens(run) -> int | None:
        """当前待发上下文规模；未知时返回 None，不用累计用量替代。"""
        budget = run.get("context_budget")
        value = budget.get("estimated_input_tokens") if isinstance(budget, dict) else None
        return value if type(value) is int and value > 0 else None

    async def preview(self, run, *, model_profile_id=None) -> dict:
        """只读预览：返回资格、目标模型差异、能力缺口、预算说明与绑定摘要。"""
        report = self.inspect(run)
        await self.owner.cloud.identity(self.owner.token)
        profiles = await self.owner.cloud.profiles(self.owner.token)
        by_id = {profile.get("id"): profile for profile in profiles}
        target = by_id.get(model_profile_id or run.get("model_profile_id"))
        if target is None and model_profile_id is None:
            # 旧记录没有模型标识：预览按当前默认模型展示，除非用户另行指定。
            target = next((item for item in profiles if item.get("is_default")), None)
        if not target or target.get("enabled") is False:
            raise ValueError("目标模型不可用或未启用，请刷新模型配置")
        switched = bool(model_profile_id) and target.get("id") != run.get("model_profile_id")
        # 同一 profile 改了端点或能力也算配置变化，必须显式接受，不能当成“未切换”。
        configuration_changed = bool(run.get("model_config_version")) and configuration_version(target) != run["model_config_version"]
        capability_changed = bool(run.get("model_capability_version")) and model_capability_version(target) != run["model_capability_version"]
        changed = switched or configuration_changed or capability_changed
        gaps = self.capability_gaps(run, target)
        timing = run.get("timing") if isinstance(run.get("timing"), dict) else None
        unconfirmed = bool(timing and timing.get("unconfirmed_tail"))
        payload = {"format_version": HANDOFF_VERSION, "run_id": run["id"],
                   "checkpoint_id": run.get("checkpoint_id"), "state_version": run.get("state_version", 0),
                   "source": self.recorded_model_facts(run), "target": model_facts(target),
                   "switched": switched, "configuration_changed": configuration_changed,
                   "capability_changed": capability_changed, "capability_gaps": gaps,
                   "blockers": report["blockers"],
                   "resolutions_digest": resolutions_digest(run), "unconfirmed_tail": unconfirmed,
                   "budget": report["budget"]}
        limitations = list(report["limitations"])
        if self.pending_context_tokens(run) is None:
            limitations.append("未记录待发上下文规模；容量按目标模型配置核对，首次请求会重新计量")
        return {**payload, "preview_sha256": hashlib.sha256(encode(payload).encode()).hexdigest(),
                "can_resume": report["can_resume"], "recovery_class": report["recovery_class"],
                "eligible": report["can_resume"] and not gaps,
                "requires_model_change_acceptance": changed,
                "requires_timing_acceptance": unconfirmed,
                "changes": self.changes(run, target),
                "budget_note": "沿用原逻辑任务的累计用量、失败记录与上限；切换模型不清零、不扩额",
                "limitations": limitations}

    @staticmethod
    def recorded_model_facts(run) -> dict:
        """原运行记录的模型事实；同一 profile 改配置时不能把当前配置当成变更前。"""
        handoff = run.get("model_handoff") or {}
        return {"model_profile_id": run.get("model_profile_id"),
                "model_name": run.get("model") or handoff.get("to_model_name"),
                "provider": run.get("provider"),
                "configuration_version": run.get("model_config_version"),
                "capability_version": run.get("model_capability_version")}

    def changes(self, run, target) -> list[str]:
        """面向界面的配置差异说明；只用已记录事实，不拿当前配置冒充变更前。"""
        result = []
        if target.get("id") != run.get("model_profile_id"):
            result.append("模型已更换：" + str(run.get("model") or run.get("model_profile_id")) + " → " + str(target.get("model_name")))
        if run.get("model_config_version") and configuration_version(target) != run["model_config_version"]:
            result.append("同一模型配置已变化（端点、协议或参数），需要显式接受新配置")
        if run.get("model_capability_version") and model_capability_version(target) != run["model_capability_version"]:
            result.append("同一模型的能力声明已变化，需要重新核对能力")
        return result

    def resolutions(self, run) -> list[dict]:
        return list(run.get("recovery_resolutions") or [])

    def local_activity(self, run) -> list[str]:
        """本地是否仍有未确认停止的进程或进行中的文件操作；决定能否释放租约。"""
        reasons = []
        for execution in self.store.execution_sessions.list(run["session_id"]):
            if execution["run_id"] != run["id"]:
                continue
            if execution["status"] in {"running", "starting"} or not execution.get("stopped"):
                reasons.append("进程未确认停止：" + execution["execution_id"])
        for patch in self.owner.patches.list(run["id"]):
            if any(item.get("status") == "applying" for item in patch.get("journal") or []):
                reasons.append("文件操作仍在进行：" + str(patch.get("patch_set_id")))
        return reasons

    def apply_reconcile(self, run, data) -> dict:
        """记录一次人工核对；只追加决定，不改写原执行、补丁日志或未知结果。"""
        if run.get("recovery_contract_version") != VERSION:
            raise ValueError("旧记录不支持恢复控制，请基于历史创建新任务")
        report = self.inspect(run)
        if data.get("checkpoint_id") != run.get("checkpoint_id"):
            raise ControlConflict("检查点已变化，请重新核对现场", run.get("state_version", 0))
        item = next((entry for entry in report["blocker_details"] if entry["item_id"] == data["item_id"]), None)
        if item is None:
            raise ValueError("待核对项已不存在，请刷新现场")
        if item.get("status") != "open":
            raise ValueError("该待核对项已处理，不能重复提交")
        if item["kind"] != data["kind"]:
            raise ValueError("核对类型与待处理项不一致")
        if data["decision"] not in item.get("actions", []):
            raise ValueError(item.get("reason") or "该待处理项不支持这种处理方式")
        note = (data.get("note") or "").strip()
        if data["decision"] in {"externally_confirmed", "externally_failed", "abandon"} and len(note) < 4:
            raise ValueError("请填写核对说明（至少 4 个字）；系统无法代为验证外部结果")
        if item["kind"] in {"file_operation", "mcp_write"}:
            # 文件与外部写必须绑定当前机器观察到的证据，避免用旧页面或猜测解锁。
            submitted = data.get("evidence")
            if submitted is None:
                raise ValueError("核对依据缺失；请刷新现场并按当前内容重新核对")
            if encode(submitted) != encode(item.get("evidence") or {}):
                raise ControlConflict("核对依据与当前现场不一致，请重新核对现场", run.get("state_version", 0))
        resolutions = run.setdefault("recovery_resolutions", [])
        if len(resolutions) >= RESOLUTION_LIMIT:
            raise ValueError(f"本次运行的人工核对记录达到 {RESOLUTION_LIMIT} 条上限，请整理后新建任务")
        record = self.insert(run, "reconcile", data)
        evidence = {"format_version": RESOLUTION_VERSION, "resolution_id": uuid.uuid4().hex,
                    "item_id": item["item_id"], "kind": item["kind"],
                    "target": item["target"], "decision": data["decision"],
                    "source": "machine_observation" if data["decision"] == "record_observation" else "user_statement",
                    "verified": data["decision"] == "record_observation",
                    "observation": item.get("observation"),
                    # 绑定核对当时的现场证据；内容再变化时该决定自动失去放行效力。
                    "evidence": item.get("evidence"),
                    "note": self.owner.secret_filter.redact_text(note, context="人工核对说明")[:NOTE_LIMIT] if note else None,
                    "created_at": now(), "request_id": data["request_id"],
                    "state_version": run.get("state_version", 0)}
        resolutions.append(evidence)
        # 控制回执保留自己的 kind="reconcile"，只附加核对事实，避免覆盖控制类型。
        record.update(resolution_id=evidence["resolution_id"], item_id=evidence["item_id"],
                      item_kind=evidence["kind"], decision=evidence["decision"], source=evidence["source"],
                      verified=evidence["verified"], note=evidence["note"])
        if data["decision"] == "abandon":
            run["recovery_abandoned_at"] = evidence["created_at"]
            # 放弃意图总是记录；只有本地活动已静止时才释放工作区租约。
            if not self.local_activity(run):
                self.release_abandoned_lease(run)
        self.owner.event(run, "recovery.reconciled", item_id=evidence["item_id"], kind=evidence["kind"],
                         decision=evidence["decision"], source=evidence["source"], request_id=evidence["request_id"])
        return record

    def release_abandoned_lease(self, run) -> None:
        """放弃原任务后只释放工作区租约；未知结果与已改文件全部保留。"""
        if not run.get("workspace_key"):
            return
        self.store.db.execute("UPDATE workspace_leases SET state='released',updated_at=? "
                              "WHERE workspace_key=? AND run_id=? AND state IN ('held','reconcile')",
                              (now(), run["workspace_key"], run["id"]))

    async def validate_resume(self, run, data, *, for_plan=False):
        from private_agent.agent.task_constraints import restore_interpretation

        restore_interpretation(self.owner, dict(run))
        report = self.inspect(run)
        if data.get("checkpoint_id") != run.get("checkpoint_id"):
            raise ControlConflict("检查点已变化，请重新核对现场", run["state_version"])
        if not (report["can_resume"] or for_plan and run["status"] == "completed" and not report["blockers"]):
            raise ValueError("；".join(report["blockers"]) or "当前状态不允许继续")
        timing = run.get("timing") if isinstance(run.get("timing"), dict) else None
        if timing and timing.get("unconfirmed_tail") and data.get("accept_unconfirmed_timing") is False:
            raise ValueError("上次运行存在未确认的活动时间尾段；请核对计时说明后显式确认继续")
        authorized = run
        if run["status"] != "paused" and run["permission_mode"] == "full_access":
            grant = self.store.active_grant(run["session_id"])
            if not grant:
                raise ValueError("继续前需要重新确认当前会话的完全访问授权")
            authorized = {**run, "full_access_grant_id": grant["id"]}
        self.owner.require_grant(authorized)
        await self.owner.cloud.identity(self.owner.token)
        profiles = await self.owner.cloud.profiles(self.owner.token)
        by_id = {item["id"]: item for item in profiles}
        handoff = None
        requested = data.get("model_profile_id")
        target_id = requested or run.get("model_profile_id")
        target = by_id.get(target_id)
        switched = bool(requested) and requested != run.get("model_profile_id")
        configuration_changed = bool(run.get("model_config_version")) and (
            not target or configuration_version(target) != run["model_config_version"])
        capability_changed = bool(run.get("model_capability_version")) and (
            not target or model_capability_version(target) != run["model_capability_version"])
        if target is not None and target.get("enabled") is False:
            raise ValueError("模型配置已变化或不可用，未切换模型恢复")
        # 旧记录没有模型版本事实时无法比对；只在用户明确要求换模型时才必须找到目标配置。
        if target is None and (requested or run.get("model_config_version")):
            raise ValueError("模型配置已变化或不可用，未切换模型恢复")
        if switched or configuration_changed or capability_changed:
            if run["status"] == "paused":
                if switched:
                    raise ValueError("暂停中的运行不能直接切换模型；请先取消，再基于历史选择模型继续")
                raise ValueError("暂停中的运行不能直接接受新的模型配置；请先取消，再基于历史重新核对")
            if data.get("accept_model_change") is not True:
                raise ValueError("切换模型或接受新的模型配置需要显式确认目标模型与能力差异")
            detail = await self.preview(run, model_profile_id=target_id)
            if not data.get("preview_sha256") or data["preview_sha256"] != detail["preview_sha256"]:
                raise ControlConflict("恢复预览已过期，请重新核对模型差异与预算", run["state_version"])
            if detail["capability_gaps"]:
                raise ValueError("目标模型缺少恢复所需能力：" + "；".join(detail["capability_gaps"]))
            source = by_id.get(run.get("model_profile_id"))
            handoff = {"format_version": HANDOFF_VERSION, "from_run_id": run["id"],
                       "from_profile_id": run.get("model_profile_id"),
                       "from_model_name": run.get("model") or (source.get("model_name") if source else None),
                       # 旧路由缺失时按未知处理：出站只使用公开历史投影。
                       "from_route": ({"provider": run.get("provider") or source.get("provider"),
                                       "model_name": run.get("model") or source.get("model_name"),
                                       "api_format": source.get("api_format"), "endpoint": source.get("endpoint")}
                                      if source else None),
                       "from_configuration_version": run.get("model_config_version"),
                       "to_profile_id": target_id, "to_model_name": target.get("model_name"),
                       "preview_sha256": detail["preview_sha256"],
                       "configuration_changed": configuration_changed,
                       "capability_changed": capability_changed,
                       "target_configuration_version": configuration_version(target),
                       "target_capability_version": model_capability_version(target),
                       "accepted_model_change": True,
                       "accepted_unconfirmed_timing": data.get("accept_unconfirmed_timing") is True,
                       "switched_at": now()}
        if run.get("execution_contract_version") == VERSION:
            capability = await self.owner.execution_sessions.capabilities()
            if capability["session_protocol"] != VERSION:
                raise ValueError("执行宿主协议不可用或不兼容")
        return {**report, "handoff": handoff}
