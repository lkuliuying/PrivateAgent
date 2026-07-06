"""Agent task repositories."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentEvidence, AgentTask, AgentTaskStep
from .timeutil import utcnow


class AgentTaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        title: str,
        goal: str | None,
        session_id: int | None,
        plan_json: dict | None,
    ) -> AgentTask:
        task = AgentTask(
            title=title,
            goal=goal,
            session_id=session_id,
            status="planned",
            plan_json=plan_json,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def get(self, task_id: int) -> Optional[AgentTask]:
        return await self.db.get(AgentTask, task_id)

    async def list(self, limit: int = 100) -> list[AgentTask]:
        stmt = select(AgentTask).order_by(AgentTask.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        task_id: int,
        *,
        status: str,
        final_report_md: str | None = None,
    ) -> None:
        values: dict = {"status": status}
        if final_report_md is not None:
            values["final_report_md"] = final_report_md
        await self.db.execute(
            update(AgentTask).where(AgentTask.id == task_id).values(**values)
        )
        await self.db.commit()


class AgentTaskStepRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_many(self, task_id: int, steps: list[dict]) -> list[AgentTaskStep]:
        objs = [
            AgentTaskStep(
                task_id=task_id,
                ordinal=i + 1,
                title=s["title"],
                tool_name=s.get("tool_name"),
                input_json=s.get("input_json") or {},
                status="planned",
            )
            for i, s in enumerate(steps)
        ]
        self.db.add_all(objs)
        await self.db.commit()
        for obj in objs:
            await self.db.refresh(obj)
        return objs

    async def get(self, step_id: int) -> Optional[AgentTaskStep]:
        return await self.db.get(AgentTaskStep, step_id)

    async def list_by_task(self, task_id: int) -> list[AgentTaskStep]:
        stmt = (
            select(AgentTaskStep)
            .where(AgentTaskStep.task_id == task_id)
            .order_by(AgentTaskStep.ordinal.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        step_id: int,
        *,
        status: str | None = None,
        tool_call_id: int | None = None,
        clear_tool_call: bool = False,
        output_json: dict | None = None,
        error_message: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        values: dict = {}
        if status is not None:
            values["status"] = status
        if tool_call_id is not None:
            values["tool_call_id"] = tool_call_id
        if clear_tool_call:
            values["tool_call_id"] = None
        if output_json is not None:
            values["output_json"] = output_json
        if error_message is not None:
            values["error_message"] = error_message
        if started:
            values["started_at"] = utcnow()
        if finished:
            values["finished_at"] = utcnow()
        if not values:
            return
        await self.db.execute(
            update(AgentTaskStep).where(AgentTaskStep.id == step_id).values(**values)
        )
        await self.db.commit()


class AgentEvidenceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        task_id: int,
        step_id: int | None,
        kind: str,
        title: str,
        content_md: str,
        meta_json: dict | None = None,
    ) -> AgentEvidence:
        ev = AgentEvidence(
            task_id=task_id,
            step_id=step_id,
            kind=kind,
            title=title,
            content_md=content_md,
            meta_json=meta_json,
        )
        self.db.add(ev)
        await self.db.commit()
        await self.db.refresh(ev)
        return ev

    async def list_by_task(self, task_id: int) -> list[AgentEvidence]:
        stmt = (
            select(AgentEvidence)
            .where(AgentEvidence.task_id == task_id)
            .order_by(AgentEvidence.created_at.asc(), AgentEvidence.id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
