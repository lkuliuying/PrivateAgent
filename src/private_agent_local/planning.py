"""本地计划、来源摘要和完成门禁，复用运行记录及事务事件。"""
from __future__ import annotations

import hashlib
import json

from private_agent_core.planning import PlanUpdate, validate_transition
from private_agent_core.tool_specs import ToolFailure

from .store import encode, now


def state_digest(run: dict) -> str:
    state = {"plan": run.get("plan"), "progress": run.get("orchestration_progress")}
    # 老检查点保持原摘要；新增状态仅在出现后绑定，恢复不能重置纠错与复核次数。
    for key in ("collaboration_mode", "pending_input", "observer_config", "reflection_state", "reflection_review"):
        if key in run:
            state[key] = run[key]
    return hashlib.sha256(encode(state).encode()).hexdigest()


def completion_blockers(run: dict) -> tuple[str | None, list[str]]:
    plan = run.get("plan")
    if not plan:
        return None, []
    if plan.get("needs_review") or plan["goal_version"] != run.get("goal_version", 1):
        return "unmet", ["用户目标已变化，请核对并更新计划后再交付"]
    resolved = {key for item in plan["items"] if item["status"] == "completed" for key in item.get("supersedes", [])}
    by_key = {item["item_key"]: item for item in plan["items"]}
    remaining = list(resolved)
    while remaining:
        item = by_key.get(remaining.pop(), {})
        for key in item.get("supersedes", []):
            if key not in resolved:
                resolved.add(key)
                remaining.append(key)
    blocked = [item["title"] for item in plan["items"] if item["status"] == "blocked"
               or item["status"] == "failed" and item["item_key"] not in resolved]
    if blocked:
        return "blocked", ["计划步骤受阻或失败：" + "、".join(blocked)[:1200]]
    unfinished = [item["title"] for item in plan["items"] if item["status"] in {"pending", "in_progress"}]
    if unfinished:
        return "unmet", ["计划仍有未完成步骤：" + "、".join(unfinished)[:1200]]
    return None, []


def proposal_blockers(run: dict) -> list[str]:
    plan = run.get("plan")
    if not plan or plan.get("needs_review") or plan["goal_version"] != run.get("goal_version", 1):
        return ["请先使用 update_run_plan 保存与当前目标一致的实施计划"]
    if (any(item["status"] not in {"pending", "cancelled"} for item in plan["items"])
            or not any(item["status"] == "pending" for item in plan["items"])):
        return ["规划模式只制定未来实施步骤，至少保留一个 pending 步骤；过时步骤可取消"]
    covered = {key for item in plan["items"] if item["status"] == "pending" for key in item.get("requirement_ids", [])}
    missing = [item["description"] for item in run.get("completion_requirements", [])
               if item.get("required", True) and item["requirement_id"] not in covered]
    return ["计划尚未关联验收要求：" + "；".join(missing)[:1600]] if missing else []


class LocalPlanner:
    def __init__(self, owner):
        self.owner, self.store = owner, owner.store

    def update(self, run: dict, arguments: dict, call_id: str) -> dict:
        if run.get("recovery_contract_version") != "1.0":
            raise ToolFailure("plan_unavailable", "当前运行不支持持久计划，请在新版工作区新建任务")
        update = PlanUpdate.model_validate(arguments)
        if run.get("collaboration_mode") == "plan" and any(item.status not in {"pending", "cancelled"} for item in update.items):
            raise ToolFailure("plan_proposal_invalid", "规划模式的实施步骤必须保持 pending，过时步骤可取消；实际工作在确认执行后进行")
        current = self.store.run_state(run["id"]).get("plan")
        version = current["version"] if current else 0
        if update.expected_plan_version != version:
            raise ToolFailure("plan_version_conflict", f"计划版本已变化，当前版本为 {version}，请重新核对")
        if update.goal_version != run.get("goal_version", 1):
            raise ToolFailure("plan_goal_conflict", "用户目标已变化，请按当前 goal_version 重新规划")
        try:
            validate_transition(current["items"] if current else [], update.items)
        except ValueError as error:
            raise ToolFailure("plan_transition_invalid", str(error)) from None
        requirements = {item["requirement_id"] for item in run.get("completion_requirements", [])}
        histories = [self.store.run(identifier) for identifier in run.get("ancestor_run_ids", [])]
        for history in histories:
            if history.get("logical_task_id") != run.get("logical_task_id") or history["session_id"] != run["session_id"]:
                raise ToolFailure("plan_evidence_invalid", "历史计划证据不属于当前逻辑任务")
        records = []
        for history in [*histories, self.store.run(run["id"])]:
            events = {event["sequence"]: event for event in history["events"]}
            for execution in history["executions"]:
                event = events.get(execution.get("source_sequence"), {})
                if (execution["tool_name"] != "update_run_plan"
                        and event.get("type") in {"tool.completed", "tool.failed"}
                        and event.get("payload", {}).get("execution_id") == execution["id"]):
                    records.append({"run_id": history["id"], "execution_id": execution["id"],
                                    "tool_call_id": execution["tool_call_id"], "sequence": event["sequence"],
                                    "status": execution["status"], "workspace_version": execution.get("workspace_version")})
        items = []
        for ordinal, item in enumerate(update.items, 1):
            if not set(item.requirement_ids).issubset(requirements):
                raise ToolFailure("plan_requirement_invalid", "计划引用了当前任务不存在的验收要求")
            evidence = []
            for identifier in item.evidence_calls:
                matching = [record for record in records if record["tool_call_id"] == identifier]
                if len(matching) != 1:
                    raise ToolFailure("plan_evidence_invalid", "证据调用不存在、尚未落盘或标识不唯一；不能作为计划依据")
                evidence.append(matching[0])
            items.append({**item.model_dump(), "ordinal": ordinal, "evidence": evidence})
        notes = list((current or {}).get("notes", []))
        if update.explanation and (not notes or notes[-1]["text"] != update.explanation):
            notes.append({"text": update.explanation, "source": "model", "tool_call_id": call_id, "run_id": run["id"],
                          "goal_version": update.goal_version, "plan_version": version + 1})
        plan = {"version": version + 1, "goal_version": update.goal_version, "needs_review": False,
                "items": items, "explanation": update.explanation, "notes": notes[-8:], "updated_at": now()}
        with self.store.transaction(run=run):
            run["plan"] = plan
            self.owner.event(run, "plan.updated" if current else "plan.created",
                             previous_version=version, plan_version=plan["version"], **{k: v for k, v in plan.items() if k != "version"})
        return {"plan": plan, "notice": "计划进度是模型报告；执行记录不等于需求验证通过"}

    def invalidate(self, run: dict) -> None:
        plan = run.get("plan")
        if not plan or plan.get("needs_review"):
            return
        run["plan"] = {**plan, "version": plan["version"] + 1, "needs_review": True, "updated_at": now()}
        self.owner.event(run, "plan.updated", previous_version=plan["version"],
                         plan_version=run["plan"]["version"], **{k: v for k, v in run["plan"].items() if k != "version"})

    def context(self, run: dict) -> dict | None:
        plan = run.get("plan")
        if not plan:
            return None
        notes = []
        for note in plan.get("notes", [])[-4:]:
            row = self.store.db.execute(
                "SELECT data FROM context_items WHERE session_id=? AND json_extract(data,'$.run_id')=? AND json_extract(data,'$.tool_call_id')=? AND json_extract(data,'$.role')='tool' ORDER BY ordinal DESC LIMIT 1",
                (run["session_id"], note["run_id"], note["tool_call_id"]),
            ).fetchone()
            notes.append({"text": note["text"][:400], "goal_version": note["goal_version"],
                          "source": "model_report", "content_ref": json.loads(row[0])["item_id"] if row else None})
        return {"logical_task_id": run.get("logical_task_id", run["id"]), "goal_version": run.get("goal_version", 1),
                "workspace_version": run.get("workspace_version", 0),
                "plan": {**{key: value for key, value in plan.items() if key not in {"notes", "updated_at", "items"}},
                         "items": [{key: value for key, value in item.items() if key not in {"evidence", "ordinal"}}
                                   for item in plan["items"]]},
                "decisions": notes, "verification": "计划与历史调用仅供定位；当前需求必须由完成验证器复核"}
