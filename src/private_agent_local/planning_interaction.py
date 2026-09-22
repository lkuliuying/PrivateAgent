"""规划澄清与计划交接；用户输入、版本及回执在同一事务内提交。"""
from __future__ import annotations

import asyncio
import time
import uuid

from pydantic import Field, field_validator

from private_agent_core.contracts import ModelMessage
from private_agent_core.planning import UserInputRequest
from private_agent_core.tool_specs import ToolFailure

from . import reflection, task_constraints
from .planning import proposal_blockers
from .recovery import ControlConflict, ControlInput
from .store import now


class AnswerInput(ControlInput):
    input_id: str = Field(min_length=1, max_length=100)
    answers: dict[str, str] = Field(min_length=1, max_length=3)

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, values):
        if any(not key or len(key) > 64 or not value.strip() or len(value) > 4000 for key, value in values.items()):
            raise ValueError("每个问题必须有非空回答，回答最长 4000 字符")
        return {key: value.strip() for key, value in values.items()}


class ImplementPlanInput(ControlInput):
    expected_plan_version: int = Field(ge=1)


class PlanningInteraction:
    def __init__(self, owner):
        self.owner, self.store = owner, owner.store
        self.pending: dict[str, asyncio.Future] = {}

    async def ask(self, run: dict, arguments: dict) -> dict:
        if run.get("collaboration_mode") != "plan" or run.get("recovery_contract_version") != "1.0":
            raise ToolFailure("plan_input_unavailable", "仅规划模式支持结构化澄清")
        request = UserInputRequest.model_validate(arguments)
        if run.get("pending_input") or run["id"] in self.pending:
            raise ToolFailure("plan_input_pending", "请等待当前问题的回答")
        question = {"input_id": str(uuid.uuid4()), "questions": request.model_dump()["questions"],
                    "goal_version": run["goal_version"], "generation": run["generation"], "created_at": now()}
        future = asyncio.get_running_loop().create_future()
        context = self.owner.contexts.get(run["id"])
        started = time.monotonic()
        self.pending[run["id"]] = future
        if context:
            context.input_started = started
        try:
            with self.store.transaction(run=run):
                run.update(status="waiting_input", pending_input=question)
                self.owner.event(run, "input.requested", pending_input=question)
            return await future
        finally:
            self.pending.pop(run["id"], None)
            run["input_wait_seconds"] = run.get("input_wait_seconds", 0) + time.monotonic() - started
            if context:
                context.input_started = None
            with self.store.transaction(run=run):
                if (run.get("pending_input") or {}).get("input_id") == question["input_id"]:
                    run.pop("pending_input", None)
                    if run["status"] == "waiting_input":
                        run["status"] = "running"
                    self.owner.event(run, "input.invalidated", input_id=question["input_id"])
                self.store.save_run(run)

    def invalidate(self, run_id: str) -> None:
        future = self.pending.get(run_id)
        if future and not future.done():
            future.cancel()

    def answer(self, run_id: str, data: dict) -> dict:
        run = self.owner.live.get(run_id) or self.store.run(run_id)
        prior = self.owner.recovery.prior(run, "answer", data)
        if prior:
            return prior
        question = run.get("pending_input") or {}
        future = self.pending.get(run_id)
        if (run["status"] != "waiting_input" or question.get("input_id") != data["input_id"]
                or question.get("generation") != run.get("generation")
                or question.get("goal_version") != run.get("goal_version") or not future or future.done()):
            raise ControlConflict("问题已失效，请刷新任务后回答当前问题", run["state_version"])
        if set(data["answers"]) != {item["id"] for item in question["questions"]}:
            raise ValueError("回答必须与当前全部问题一一对应")
        # 仅把用户实际填写的回答作为新约束，模型提出的问题不提升为用户指令。
        message = "用户补充：\n" + "\n".join(f"{key}：{value}" for key, value in data["answers"].items())
        with self.owner.controls.goal_transaction(run):
            record = self.owner.recovery.insert(run, "answer", data)
            task_constraints.apply_steer(run, message, data["request_id"])
            run["generation"] += 1
            run["orchestration_progress"] = None
            correction = reflection.reset(run)
            if correction is not None:
                run["reflection_state"] = correction
            run.pop("pending_input", None)
            run["status"] = "running"
            self.owner.planner.invalidate(run)
            stored = self.store.create("message", {"session_id": run["session_id"], "role": "user", "content": message})
            self.store.context.append(run["session_id"], run_id, ModelMessage(role="user", content=message),
                                      key=f"message:{stored['id']}", source="user")
            record.update(status="applied", applied_at=now(), message=message, message_id=stored["id"],
                          input_id=data["input_id"], goal_version=run["goal_version"])
            self.owner.recovery.save_control(run_id, data["request_id"], record)
            self.owner.event(run, "input.resolved", input_id=data["input_id"], goal_version=run["goal_version"])
        future.set_result({"input_id": data["input_id"], "answers": data["answers"], "goal_version": run["goal_version"]})
        return record

    async def implement(self, run_id: str, data: dict) -> dict:
        run = self.store.run(run_id)
        prior = self.owner.recovery.prior(run, "implement", data)
        if prior:
            return prior
        if (run.get("collaboration_mode") != "plan" or run["status"] != "completed"
                or run.get("verification_state") != "passed" or proposal_blockers(run)):
            raise ValueError("只有已完成且核对通过的规划任务可以开始实施")
        if (run.get("plan") or {}).get("version") != data["expected_plan_version"]:
            raise ControlConflict("计划版本已变化，请核对最新计划", run["state_version"])
        if len(run.get("ancestor_run_ids", [])) >= 32:
            raise ValueError("逻辑任务已继续 32 次，请核对累计结果后开始新任务")
        await self.owner.recovery.validate_resume(run, data, for_plan=True)
        # 外部能力检查期间可能已有新操作，重新读取并检查状态及幂等回执。
        run = self.store.run(run_id)
        prior = self.owner.recovery.prior(run, "implement", data)
        if prior:
            return prior
        with self.store.transaction():
            if self.store.get("session", run["session_id"]).get("last_run_id") != run_id:
                raise ControlConflict("会话已有后续任务，请核对最新计划", run["state_version"])
            record = self.owner.recovery.insert(run, "implement", data)
            task_constraints.restore_interpretation(self.owner, run)
            child = self.owner.create({"session_id": run["session_id"], "project_id": run["project_id"],
                "workspace_id": run["workspace_id"], "message": run["goal"], "permission_mode": run["permission_mode"],
                "collaboration_mode": "default", "model_profile_id": run["model_profile_id"],
                "reasoning_effort": run["reasoning_effort"], "context_limits": run["context_limits"],
                "execution_contract_version": run.get("execution_contract_version"), "recovery_contract_version": "1.0",
                "client_request_id": f"plan:{run_id}:{data['request_id']}"}, parent=run, launch=False)
            record.update(status="applied", applied_at=now(), result_run_id=child["id"],
                          plan_version=data["expected_plan_version"])
            self.owner.recovery.save_control(run_id, data["request_id"], record)
        self.owner.launch(self.store.run(child["id"]))
        return record
