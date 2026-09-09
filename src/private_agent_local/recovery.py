"""持久化恢复事实与控制请求；检查点从不充当可重放的授权。"""
from __future__ import annotations

import hashlib
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field

from private_agent_core.context import ContextLimits, configuration_version

from . import files
from .store import encode, now

VERSION = "1.0"
ACTIVE = {"created", "queued", "running", "waiting_approval", "paused"}


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    request_id: str = Field(min_length=1, max_length=100)
    expected_state_version: int = Field(ge=0)
    checkpoint_id: str | None = Field(default=None, max_length=128)


class SteerInput(ControlInput):
    message: str = Field(min_length=1, max_length=32000)


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
    return hashlib.sha256(encode({key: profile.get(key) for key in keys}).encode()).hexdigest()


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
        # 读取会校验内容块摘要与工具关联，不能恢复损坏的历史。
        self.store.context.messages(run["session_id"])
        return value

    def inspect(self, run, *, for_lease=False):
        blockers, patch_facts = [], []
        try:
            if not for_lease or run.get("recovery_contract_version"):
                self.load_checkpoint(run)
            root = self.owner.root(run["project_id"], run["workspace_id"])
            if files.file_identity(root) != run["root_identity"]:
                raise ValueError("工作区根身份已变化")
            latest = {}
            for patch in self.owner.patches.list(run["id"]):
                for fact in self.owner.patches.facts(run["id"], patch["patch_set_id"], root):
                    fact = {**fact, "patch_set_id": patch["patch_set_id"]}
                    patch_facts.append(fact)
                    if fact["journal_status"] != "not_started":
                        latest[fact["rel_path"]] = fact
            for fact in latest.values():
                if fact["observation"] in {"conflict", "unreadable"} or fact["journal_status"] == "applying":
                    blockers.append("文件操作需核对：" + fact["rel_path"])
        except (ValueError, OSError) as error:
            blockers.append(str(error) if isinstance(error, ValueError) else "恢复内容不可读取")
        executions = [e for e in self.store.execution_sessions.list(run["session_id"]) if e["run_id"] == run["id"]]
        for execution in executions:
            if execution["status"] == "unknown" or not execution.get("stopped") and execution["status"] not in {"running", "starting"}:
                blockers.append("命令结果或进程身份未知：" + execution["execution_id"])
        for execution in run.get("executions", []):
            if execution.get("command") and (execution["status"] == "unknown" or execution.get("error_code") == "execution_unknown"):
                blockers.append("命令副作用未知：" + execution["id"])
        if run.get("uncertain_operations"):
            blockers.append("存在未核实的副作用；不能自动继续")
        limits = ContextLimits.model_validate(run.get("context_limits", {}))
        budget = run.get("loop_budget", {})
        if not for_lease and (budget.get("model_requests", 0) >= limits.max_model_requests or run["tool_call_count"] >= limits.max_tool_calls
                or budget.get("active_seconds", 0) >= limits.max_active_seconds
                or budget.get("failure_count", 0) >= 4
                or limits.max_cost_usd is not None and (budget.get("cost_usd") is None or budget["cost_usd"] >= limits.max_cost_usd)):
            blockers.append("逻辑任务累计预算不足或费用未知")
        if not for_lease and self.store.get("session", run["session_id"]).get("last_run_id") != run["id"]:
            blockers.append("会话已有后续运行，请从最新运行继续")
        return {"run_id": run["id"], "supported": run.get("recovery_contract_version") == VERSION,
                "status": run["status"], "state_version": run.get("state_version", 0),
                "checkpoint_id": run.get("checkpoint_id"), "logical_task_id": run.get("logical_task_id"),
                "resumed_from_run_id": run.get("resumed_from_run_id"), "goal_version": run.get("goal_version", 1),
                "can_resume": not blockers and run["status"] in {"paused", "interrupted", "cancelled"},
                "blockers": list(dict.fromkeys(blockers)), "patch_facts": patch_facts, "executions": executions,
                "controls": self.controls(run["id"]), "budget": budget,
                "queue_reason": run.get("queue_reason"), "queue_position": run.get("queue_position"),
                "expired_approvals": [a["id"] for a in run.get("approvals", []) if a["status"] in {"cancelled", "expired"}],
                "limitations": ["重启后的命令不凭 PID 重新附着；身份或结果不明时阻止继续", "继续会重新核对模型与权限，并从已提交历史重新规划；不重放旧工具序列"]}

    async def validate_resume(self, run, data):
        report = self.inspect(run)
        if data.get("checkpoint_id") != run.get("checkpoint_id"):
            raise ControlConflict("检查点已变化，请重新核对现场", run["state_version"])
        if not report["can_resume"]:
            raise ValueError("；".join(report["blockers"]) or "当前状态不允许继续")
        authorized = run
        if run["status"] != "paused" and run["permission_mode"] == "full_access":
            grant = self.store.active_grant(run["session_id"])
            if not grant:
                raise ValueError("继续前需要重新确认当前会话的完全访问授权")
            authorized = {**run, "full_access_grant_id": grant["id"]}
        self.owner.require_grant(authorized)
        await self.owner.cloud.identity(self.owner.token)
        profiles = await self.owner.cloud.profiles(self.owner.token)
        profile = next((p for p in profiles if p["id"] == run.get("model_profile_id")), None)
        if run.get("model_config_version") and (not profile or profile.get("enabled") is False or configuration_version(profile) != run["model_config_version"]):
            raise ValueError("模型配置已变化或不可用，未切换模型恢复")
        if run.get("model_capability_version") and (not profile or model_capability_version(profile) != run["model_capability_version"]):
            raise ValueError("模型能力已变化，未切换能力恢复")
        if run.get("execution_contract_version") == VERSION:
            capability = await self.owner.execution_sessions.capabilities()
            if capability["session_protocol"] != VERSION:
                raise ValueError("执行宿主协议不可用或不兼容")
        return report
