"""单调代次与安全边界控制；控制接收和实际应用是两种持久事实。"""
from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager

from private_agent_core.contracts import ModelMessage
from private_agent_core.task_intent import interpret_task

from . import reflection, task_constraints
from .recovery import ACTIVE, ControlConflict
from .store import now


class RunControls:
    def __init__(self, owner):
        self.owner = owner
        self.changed = {}
        self.model_tasks = {}
        self.tool_tasks = {}
        self.boundary_locks = {}

    def signal(self, run_id):
        self.changed.setdefault(run_id, asyncio.Event()).set()

    @contextmanager
    def goal_transaction(self, run):
        """新目标的失败计数与检查点一并提交，失败时恢复内存上下文。"""
        context = self.owner.contexts.get(run["id"])
        previous = (context.failure_key, context.failure_count) if context else None
        try:
            with self.owner.store.transaction(run=run):
                if context:
                    context.failure_key, context.failure_count = None, 0
                if run.get("loop_budget"):
                    run["loop_budget"] = {**run["loop_budget"], "failure_key": None, "failure_count": 0}
                yield
        except BaseException:
            # 包括取消在内的事务失败均须回滚；异常原样交给调用方。
            if context:
                context.failure_key, context.failure_count = previous
            raise

    def guard(self, run, generation=None):
        if run.get("agent_parent_run_id"):
            parent = self.owner.live.get(run["agent_parent_run_id"])
            if not parent or parent.get("cancel_requested_at") or parent.get("pause_requested") or parent.get("generation", 0) != run.get("agent_parent_generation"):
                raise asyncio.CancelledError
        if run.get("cancel_requested_at"):
            raise asyncio.CancelledError
        if run.get("pause_requested") or generation is not None and generation != run.get("generation", 0):
            raise ValueError("运行控制已变化，旧操作未继续；请依据最新约束重新规划")

    async def request(self, run_id, kind, data):
        owner, store = self.owner, self.owner.store
        run = owner.live.get(run_id) or store.run(run_id)
        prior = owner.recovery.prior(run, kind, data)
        if prior:
            return prior
        if kind == "steer":
            interpret_task(data["message"])
        if kind == "resume":
            await owner.recovery.validate_resume(run, data)
            # 联网核验让出调度后，必须再次校验版本与重复请求。
            run = owner.live.get(run_id) or store.run(run_id)
            prior = owner.recovery.prior(run, kind, data)
            if prior:
                return prior
        elif run["status"] not in ACTIVE:
            raise ValueError("任务已结束，不能再追加或暂停")
        child = None
        with store.transaction(run=run):
            record = owner.recovery.insert(run, kind, data)
            if kind == "steer":
                message = store.create("message", {"session_id": run["session_id"], "role": "user", "content": data["message"]})
                record.update(message_id=message["id"], context_committed=False)
            if kind == "resume" and run["status"] != "paused":
                report = owner.recovery.inspect(run)
                if not report["can_resume"]:
                    raise ControlConflict("恢复现场已变化", run["state_version"])
                if len(run.get("ancestor_run_ids", [])) >= 32:
                    raise ValueError("逻辑任务已继续 32 次，请核对累计结果后开始新任务")
                parent = dict(run)
                task_constraints.restore_interpretation(owner, parent)
                child = owner.create({"session_id": run["session_id"], "project_id": run["project_id"],
                    "workspace_id": run["workspace_id"], "message": run["goal"], "permission_mode": run["permission_mode"],
                    "model_profile_id": run["model_profile_id"], "reasoning_effort": run["reasoning_effort"],
                    "context_limits": run["context_limits"], "execution_contract_version": run.get("execution_contract_version"),
                    "collaboration_mode": run.get("collaboration_mode", "default"),
                    "recovery_contract_version": "1.0", "client_request_id": f"resume:{run_id}:{data['request_id']}"}, parent=parent, launch=False)
                for pending in owner.recovery.controls(run_id):
                    if pending["kind"] == "steer" and pending["status"] == "interrupted":
                        carried = owner.recovery.insert(child, "steer", {"request_id": pending["request_id"],
                            "expected_state_version": child["state_version"], "message": pending["message"]})
                        carried.update(message_id=pending["message_id"], context_committed=True,
                                       source_run_id=pending.get("source_run_id", run_id))
                        owner.recovery.save_control(child["id"], carried["request_id"], carried)
                record.update(status="applied", applied_at=now(), result_run_id=child["id"])
                owner.recovery.save_control(run_id, data["request_id"], record)
            if not child:
                self.receive(run, kind, data, record)
        if child:
            # 控制回执和关联运行一并提交后才启动协程，旧运行保持不可变。
            owner.launch(store.run(child["id"]))
            return record
        self.signal(run_id)
        if kind in {"steer", "pause", "cancel"}:
            owner.planning_interaction.invalidate(run_id)
            for approval in run["approvals"]:
                future = owner.decisions.get(approval["id"])
                if approval["status"] == "pending" and future and not future.done():
                    approval["invalidated_by_control"] = True
                    future.set_result(False)
            model = self.model_tasks.get(run_id)
            if model and not model.done():
                model.cancel()
        if kind in {"pause", "steer", "cancel"}:
            await owner.agents.cancel_children(run_id)
        if kind == "pause":
            await owner.execution_sessions.stop_matching(lambda r: r["run_id"] == run_id and r["retention"] == "run")
        if kind in {"steer", "pause"}:
            for slot in tuple(self.tool_tasks.get(run_id, {}).values()):
                spec = owner.registry[slot["name"]]
                if spec.parallel_safe or spec.effect == "external" or kind == "pause" and slot["name"] in {"run_project_command", "run_powershell_command"}:
                    slot["task"].cancel()
        if kind == "cancel":
            await owner._cancel(run_id)
            with store.transaction():
                record.update(status="applied", applied_at=now(), cleanup_complete=all(
                    e.get("stopped") for e in store.execution_sessions.list(run["session_id"]) if e["run_id"] == run_id))
                owner.recovery.save_control(run_id, data["request_id"], record)
        return record

    def receive(self, run, kind, data, record):
        if kind in {"steer", "pause", "cancel"}:
            run["generation"] = run.get("generation", 0) + 1
        if kind == "pause":
            run["pause_requested"] = True
            if run["status"] == "paused":
                record.update(status="applied", applied_at=now())
        elif kind == "resume":
            task_constraints.restore_interpretation(self.owner, run)
            run.update(pause_requested=False, status="running")
            record.update(status="applied", applied_at=now())
        elif kind == "cancel":
            run["cancel_requested_at"] = now()
        self.owner.event(run, "control.received", request_id=data["request_id"], kind=kind)
        self.owner.recovery.save_control(run["id"], data["request_id"], record)

    def settle(self, run):
        with self.owner.store.transaction():
            for record in self.owner.recovery.controls(run["id"]):
                if record["status"] == "received":
                    record.update(status="interrupted", reason="运行已终结，未确认在安全边界应用")
                    self.owner.recovery.save_control(run["id"], record["request_id"], record)

    def commit_messages(self, run):
        for record in self.owner.recovery.controls(run["id"]):
            if record["kind"] == "steer" and not record.get("context_committed"):
                with self.owner.store.transaction():
                    self.owner.store.context.append(run["session_id"], run["id"], ModelMessage(role="user", content=record["message"]),
                                                   key=f"message:{record['message_id']}", source="user")
                    record["context_committed"] = True
                    self.owner.recovery.save_control(run["id"], record["request_id"], record)

    async def boundary(self, run, *, model=False):
        async with self.boundary_locks.setdefault(run["id"], asyncio.Lock()):
            await self._boundary(run, model=model)

    async def _boundary(self, run, *, model=False):
        if run.get("agent_parent_run_id"):
            self.guard(run)
        if run.get("recovery_contract_version") != "1.0":
            return
        self.guard_cancel(run)
        owner = self.owner
        for record in owner.recovery.controls(run["id"]):
            if record["kind"] == "steer" and record["status"] == "received":
                with self.goal_transaction(run):
                    task_constraints.apply_steer(run, record["message"], record["request_id"])
                    run["orchestration_progress"] = None
                    correction = reflection.reset(run)
                    if correction is not None:
                        run["reflection_state"] = correction
                    owner.planner.invalidate(run)
                    record.update(status="applied", applied_at=now(), goal_version=run["goal_version"])
                    owner.recovery.save_control(run["id"], record["request_id"], record)
                    owner.event(run, "steer.applied", request_id=record["request_id"], goal_version=run["goal_version"])
        if run.get("pause_requested"):
            started = time.monotonic()
            context = owner.contexts.get(run["id"])
            if context:
                context.paused_at = started
            with owner.store.transaction(run=run):
                run["status"] = "paused"
                for record in owner.recovery.controls(run["id"]):
                    if record["kind"] == "pause" and record["status"] == "received":
                        record.update(status="applied", applied_at=now())
                        owner.recovery.save_control(run["id"], record["request_id"], record)
                owner.event(run, "run.paused")
            signal = self.changed.setdefault(run["id"], asyncio.Event())
            try:
                while run.get("pause_requested"):
                    self.guard_cancel(run)
                    signal.clear()
                    await signal.wait()
            finally:
                if context:
                    context.paused_seconds += time.monotonic() - started
                    context.paused_at = None
            self.guard_cancel(run)
            owner.event(run, "run.resumed")
            await self._boundary(run, model=model)
        if model:
            self.commit_messages(run)

    @staticmethod
    def guard_cancel(run):
        if run.get("cancel_requested_at"):
            raise asyncio.CancelledError
