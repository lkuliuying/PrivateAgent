"""Multi-step agent task orchestration."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from .activities import ActivityService
from .models import AgentEvidence, AgentTask, AgentTaskStep
from .repo_tasks import (
    AgentEvidenceRepository,
    AgentTaskRepository,
    AgentTaskStepRepository,
)
from .repo_tools import ToolCallRepository
from .tools import ToolError, ToolExecutor, default_registry


class TaskNotFound(LookupError):
    pass


class StepNotFound(LookupError):
    pass


def default_plan(title: str, goal: str, project_id: int | None = None) -> list[dict]:
    """A conservative fallback plan for coding-oriented tasks."""
    base: dict = {"project_id": project_id} if project_id else {}
    steps = [
        {
            "title": "检查项目状态",
            "tool_name": "get_git_status",
            "input_json": base,
        },
        {
            "title": "运行验证命令",
            "tool_name": "run_whitelisted_command",
            "input_json": {**base, "command": "pytest -q"},
        },
        {
            "title": "查看最终 diff",
            "tool_name": "get_git_diff",
            "input_json": base,
        },
    ]
    return steps


def _brief_json(data: object, limit: int = 4000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if len(text) > limit:
        return text[:limit] + "\n... truncated"
    return text


class AgentTaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tasks = AgentTaskRepository(db)
        self.steps = AgentTaskStepRepository(db)
        self.evidence = AgentEvidenceRepository(db)
        self.tool_calls = ToolCallRepository(db)
        self.activities = ActivityService(db)

    async def create(
        self,
        *,
        title: str,
        goal: str | None,
        session_id: int | None,
        steps: list[dict] | None = None,
        project_id: int | None = None,
        status: str = "planned",
    ) -> AgentTask:
        planned_steps = steps or default_plan(title, goal or title, project_id)
        plan = {"goal": goal, "steps": planned_steps}
        task = await self.tasks.create(
            title=title,
            goal=goal,
            session_id=session_id,
            plan_json=plan,
            status=status,
        )
        await self.steps.create_many(task.id, planned_steps)
        await self.activities.sync_system(
            ref_type="agent_task",
            ref_id=task.id,
            title=f"Agent 任务：{title}",
            act_status="pending",
            detail={"task_id": task.id, "goal": goal, "steps": planned_steps},
        )
        return await self.get(task.id)

    async def create_plan_draft(
        self,
        *,
        title: str,
        goal: str,
        session_id: int | None,
        project_id: int | None = None,
    ) -> AgentTask:
        from .task_planner import TaskPlannerService

        plan = await TaskPlannerService(self.db).generate(
            title=title, goal=goal, project_id=project_id
        )
        task = await self.tasks.create(
            title=title,
            goal=goal,
            session_id=session_id,
            plan_json=plan,
            status="plan_draft",
        )
        await self.steps.create_many(task.id, plan["steps"])
        await self.activities.sync_system(
            ref_type="agent_task",
            ref_id=task.id,
            title=f"Agent 计划草稿：{title}",
            act_status="pending",
            detail={"task_id": task.id, "goal": goal, "steps": plan["steps"]},
        )
        return await self.get(task.id)

    async def get(self, task_id: int) -> AgentTask:
        task = await self.tasks.get(task_id)
        if task is None:
            raise TaskNotFound(f"任务不存在: {task_id}")
        return task

    async def list(self) -> list[AgentTask]:
        return await self.tasks.list()

    async def list_steps(self, task_id: int) -> list[AgentTaskStep]:
        await self.get(task_id)
        return await self.steps.list_by_task(task_id)

    async def list_evidence(
        self,
        task_id: int,
        *,
        step_id: int | None = None,
        kind: str | None = None,
        tool_name: str | None = None,
        text: str | None = None,
    ) -> list[AgentEvidence]:
        await self.get(task_id)
        rows = await self.evidence.list_by_task(task_id, step_id=step_id, kind=kind)
        if tool_name:
            rows = [
                r
                for r in rows
                if (r.meta_json or {}).get("tool_name") == tool_name
            ]
        if text:
            needle = text.lower()
            rows = [
                r
                for r in rows
                if needle in r.title.lower() or needle in r.content_md.lower()
            ]
        return rows

    async def update_plan(
        self,
        task_id: int,
        *,
        title: str | None,
        goal: str | None,
        steps: list[dict],
    ) -> AgentTask:
        task = await self.get(task_id)
        if task.status in {"running", "waiting_approval", "succeeded", "cancelled"}:
            raise ValueError("当前任务状态不允许编辑计划")
        clean_steps = [self._normalize_step(s) for s in steps]
        plan = {
            **(task.plan_json or {}),
            "title": title or task.title,
            "goal": goal if goal is not None else task.goal,
            "steps": clean_steps,
        }
        await self.tasks.update_plan(
            task_id,
            title=title,
            goal=goal,
            plan_json=plan,
            status="plan_draft",
        )
        await self.steps.replace_many(task_id, clean_steps)
        return await self.get(task_id)

    async def approve_plan(self, task_id: int) -> AgentTask:
        task = await self.get(task_id)
        if task.status not in {"plan_draft", "planned"}:
            raise ValueError("只有计划草稿可以批准")
        await self.tasks.update_status(task_id, status="plan_approved")
        await self.evidence.create(
            task_id=task_id,
            step_id=None,
            kind="note",
            title="计划已批准",
            content_md="用户已批准整体计划，后续执行仍遵守工具风险审批。",
        )
        await self._sync_task_activity(task_id, "pending")
        return await self.get(task_id)

    async def pause(self, task_id: int) -> AgentTask:
        task = await self.get(task_id)
        if task.status in {"succeeded", "failed", "cancelled"}:
            raise ValueError("终态任务不能暂停")
        await self.tasks.update_status(task_id, status="paused")
        await self._sync_task_activity(task_id, "running")
        return await self.get(task_id)

    async def cancel(self, task_id: int) -> AgentTask:
        await self.get(task_id)
        await self.steps.cancel_pending(task_id)
        await self.tasks.update_status(task_id, status="cancelled")
        await self._sync_task_activity(task_id, "cancelled")
        return await self.get(task_id)

    async def resume(self, task_id: int) -> AgentTask:
        task = await self.get(task_id)
        if task.status not in {"paused", "failed", "plan_approved", "planned"}:
            raise ValueError("当前任务状态不能继续")
        await self.tasks.update_status(task_id, status="running")
        await self._sync_task_activity(task_id, "running")
        return await self._run_until_pause_or_done(task_id)

    async def resume_from(self, task_id: int, step_id: int) -> AgentTask:
        task = await self.get(task_id)
        step = await self.steps.get(step_id)
        if step is None or step.task_id != task.id:
            raise StepNotFound(f"步骤不存在: {step_id}")
        if task.status in {"succeeded", "cancelled"}:
            raise ValueError("终态任务不能从步骤继续")
        await self.steps.reset_from(task_id, step.ordinal)
        await self.tasks.update_status(task_id, status="running")
        await self._sync_task_activity(task_id, "running")
        return await self._run_until_pause_or_done(task_id)

    async def run(self, task_id: int) -> AgentTask:
        task = await self.get(task_id)
        if task.status == "plan_draft":
            raise ValueError("计划批准前不会执行")
        if task.status == "paused":
            raise ValueError("任务已暂停，请先继续")
        if task.status == "cancelled":
            raise ValueError("任务已取消")
        await self.tasks.update_status(task_id, status="running")
        await self._sync_task_activity(task_id, "running")
        return await self._run_until_pause_or_done(task_id)

    async def approve_step(self, step_id: int) -> AgentTask:
        step = await self.steps.get(step_id)
        if step is None:
            raise StepNotFound(f"步骤不存在: {step_id}")
        if step.tool_call_id is None:
            raise ValueError("步骤没有待审批工具调用")
        if step.status != "waiting_approval":
            raise ValueError("步骤当前不在待审批状态")
        await self.steps.update(step.id, status="running", started=True)
        try:
            tc = await ToolExecutor(self.db).execute_tool_call(step.tool_call_id)
        except ToolError:
            tc = await self.tool_calls.get_fresh(step.tool_call_id)
        if tc is None or tc.status != "succeeded":
            err = tc.error_message if tc else "工具调用失败"
            await self.steps.update(
                step.id, status="failed", error_message=err, finished=True
            )
            await self.evidence.create(
                task_id=step.task_id,
                step_id=step.id,
                kind="error",
                title=f"步骤失败：{step.title}",
                content_md=err or "工具调用失败",
            )
            await self.tasks.update_status(step.task_id, status="failed")
            await self._sync_task_activity(step.task_id, "failed", err)
            return await self.get(step.task_id)
        await self.steps.update(
            step.id,
            status="succeeded",
            output_json=tc.output_json,
            finished=True,
        )
        await self.evidence.create(
            task_id=step.task_id,
            step_id=step.id,
            kind="tool_output",
            title=f"步骤完成：{step.title}",
            content_md=f"```json\n{_brief_json(tc.output_json)}\n```",
            meta_json={"tool_call_id": tc.id, "tool_name": tc.tool_name},
        )
        return await self._run_until_pause_or_done(step.task_id)

    async def retry_step(self, step_id: int) -> AgentTask:
        step = await self.steps.get(step_id)
        if step is None:
            raise StepNotFound(f"步骤不存在: {step_id}")
        await self.steps.update(
            step.id,
            status="planned",
            clear_tool_call=True,
            output_json={},
            error_message="",
        )
        await self.tasks.update_status(step.task_id, status="running")
        return await self._run_until_pause_or_done(step.task_id)

    async def _run_until_pause_or_done(self, task_id: int) -> AgentTask:
        while True:
            task = await self.get(task_id)
            if task.status in {"paused", "cancelled"}:
                return task
            steps = await self.steps.list_by_task(task_id)
            next_step = next((s for s in steps if s.status == "planned"), None)
            if next_step is None:
                report = await self._build_report(task_id)
                await self.tasks.update_status(
                    task_id, status="succeeded", final_report_md=report
                )
                await self.evidence.create(
                    task_id=task_id,
                    step_id=None,
                    kind="report",
                    title="最终报告",
                    content_md=report,
                )
                await self._sync_task_activity(task_id, "succeeded")
                return await self.get(task_id)
            tool_name = next_step.tool_name
            tool = default_registry.get(tool_name or "")
            if tool is None:
                err = f"未知工具: {tool_name}"
                await self.steps.update(
                    next_step.id, status="failed", error_message=err, finished=True
                )
                await self.tasks.update_status(task_id, status="failed")
                await self._sync_task_activity(task_id, "failed", err)
                return await self.get(task_id)
            if next_step.tool_call_id is None:
                tc = await self.tool_calls.create(
                    session_id=None,
                    task_id=task_id,
                    step_id=next_step.id,
                    tool_name=tool.name,
                    risk_level=tool.risk_level,
                    input_json=next_step.input_json,
                )
                await self.steps.update(next_step.id, tool_call_id=tc.id)
                await self.activities.sync_tool_call(tc)
            else:
                tc = await self.tool_calls.get_fresh(next_step.tool_call_id)
                assert tc is not None
            if tool.risk_level == "confirm":
                await self.steps.update(next_step.id, status="waiting_approval")
                await self.tasks.update_status(task_id, status="waiting_approval")
                await self._sync_task_activity(task_id, "running")
                return await self.get(task_id)
            await self.steps.update(next_step.id, status="running", started=True)
            try:
                tc = await ToolExecutor(self.db).execute_tool_call(tc.id)
            except ToolError:
                tc = await self.tool_calls.get_fresh(tc.id)
            if tc is None or tc.status != "succeeded":
                err = tc.error_message if tc else "工具调用失败"
                await self.steps.update(
                    next_step.id, status="failed", error_message=err, finished=True
                )
                await self.evidence.create(
                    task_id=task_id,
                    step_id=next_step.id,
                    kind="error",
                    title=f"步骤失败：{next_step.title}",
                    content_md=err or "工具调用失败",
                )
                await self.tasks.update_status(task_id, status="failed")
                await self._sync_task_activity(task_id, "failed", err)
                return await self.get(task_id)
            await self.steps.update(
                next_step.id,
                status="succeeded",
                output_json=tc.output_json,
                finished=True,
            )
            await self.evidence.create(
                task_id=task_id,
                step_id=next_step.id,
                kind="tool_output",
                title=f"步骤完成：{next_step.title}",
                content_md=f"```json\n{_brief_json(tc.output_json)}\n```",
                meta_json={"tool_call_id": tc.id, "tool_name": tc.tool_name},
            )

    @staticmethod
    def _normalize_step(step: dict) -> dict:
        title = str(step.get("title") or "").strip()
        tool_name = step.get("tool_name")
        if not title:
            raise ValueError("步骤标题不能为空")
        if tool_name is not None:
            tool_name = str(tool_name).strip() or None
        input_json = step.get("input_json") or {}
        if not isinstance(input_json, dict):
            raise ValueError("input_json 必须是对象")
        return {
            "title": title[:255],
            "tool_name": tool_name,
            "input_json": input_json,
        }

    async def _build_report(self, task_id: int) -> str:
        task = await self.get(task_id)
        steps = await self.steps.list_by_task(task_id)
        lines = [f"# {task.title}", ""]
        if task.goal:
            lines += [f"目标：{task.goal}", ""]
        lines.append("## 步骤")
        for s in steps:
            lines.append(f"- {s.ordinal}. {s.title}：{s.status}")
            if s.error_message:
                lines.append(f"  - 错误：{s.error_message}")
        lines.append("")
        lines.append("## 证据")
        evidence = await self.evidence.list_by_task(task_id)
        for ev in evidence:
            if ev.kind == "report":
                continue
            lines.append(f"### {ev.title}")
            lines.append(ev.content_md)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    async def _sync_task_activity(
        self, task_id: int, status: str, error_message: str | None = None
    ) -> None:
        task = await self.get(task_id)
        await self.activities.sync_system(
            ref_type="agent_task",
            ref_id=task_id,
            title=f"Agent 任务：{task.title}",
            act_status=status,
            detail={"task_id": task_id, "status": task.status},
            error_message=error_message,
        )
