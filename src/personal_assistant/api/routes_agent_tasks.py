"""Agent task routes for phase3 M6."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.models import AgentTask
from ..core.tasks import AgentTaskService, StepNotFound, TaskNotFound

router = APIRouter(tags=["agent-tasks"])


class StepIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    tool_name: str = Field(min_length=1, max_length=128)
    input_json: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    goal: str | None = None
    session_id: int | None = None
    project_id: int | None = None
    steps: list[StepIn] | None = None


class TaskPlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1)
    session_id: int | None = None
    project_id: int | None = None


class TaskPlanUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    goal: str | None = None
    steps: list[StepIn] = Field(min_length=1)


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    ordinal: int
    title: str
    tool_name: str | None
    status: str
    tool_call_id: int | None
    input_json: dict | None
    output_json: dict | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    step_id: int | None
    kind: str
    title: str
    content_md: str
    meta_json: dict | None
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int | None
    title: str
    goal: str | None
    status: str
    plan_json: dict | None
    final_report_md: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[StepOut] = []
    evidence: list[EvidenceOut] = []


async def _full_task(db: AsyncSession, task: AgentTask) -> TaskOut:
    svc = AgentTaskService(db)
    await db.refresh(task)
    steps = await svc.list_steps(task.id)
    evidence = await svc.list_evidence(task.id)
    return TaskOut.model_validate(
        {
            "id": task.id,
            "session_id": task.session_id,
            "title": task.title,
            "goal": task.goal,
            "status": task.status,
            "plan_json": task.plan_json,
            "final_report_md": task.final_report_md,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "steps": steps,
            "evidence": evidence,
        }
    )


@router.get("/agent-tasks", response_model=list[TaskOut])
async def list_tasks(db: AsyncSession = Depends(get_session)):
    svc = AgentTaskService(db)
    tasks = await svc.list()
    return [await _full_task(db, t) for t in tasks]


@router.post("/agent-tasks", response_model=TaskOut, status_code=201)
async def create_task(req: TaskCreate, db: AsyncSession = Depends(get_session)):
    svc = AgentTaskService(db)
    task = await svc.create(
        title=req.title,
        goal=req.goal,
        session_id=req.session_id,
        project_id=req.project_id,
        steps=[s.model_dump() for s in req.steps] if req.steps else None,
    )
    return await _full_task(db, task)


@router.post("/agent-tasks/plan", response_model=TaskOut, status_code=201)
async def create_task_plan(
    req: TaskPlanCreate, db: AsyncSession = Depends(get_session)
):
    task = await AgentTaskService(db).create_plan_draft(
        title=req.title,
        goal=req.goal,
        session_id=req.session_id,
        project_id=req.project_id,
    )
    return await _full_task(db, task)


@router.get("/agent-tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).get(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    return await _full_task(db, task)


@router.post("/agent-tasks/{task_id}/run", response_model=TaskOut)
async def run_task(task_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).run(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return await _full_task(db, task)


@router.patch("/agent-tasks/{task_id}/plan", response_model=TaskOut)
async def update_task_plan(
    task_id: int, req: TaskPlanUpdate, db: AsyncSession = Depends(get_session)
):
    try:
        task = await AgentTaskService(db).update_plan(
            task_id,
            title=req.title,
            goal=req.goal,
            steps=[s.model_dump() for s in req.steps],
        )
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return await _full_task(db, task)


@router.post("/agent-tasks/{task_id}/approve-plan", response_model=TaskOut)
async def approve_task_plan(task_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).approve_plan(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return await _full_task(db, task)


@router.post("/agent-tasks/{task_id}/pause", response_model=TaskOut)
async def pause_task(task_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).pause(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return await _full_task(db, task)


@router.post("/agent-tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(task_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).cancel(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    return await _full_task(db, task)


@router.post("/agent-tasks/{task_id}/resume", response_model=TaskOut)
async def resume_task(task_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).resume(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return await _full_task(db, task)


@router.post("/agent-tasks/{task_id}/resume-from/{step_id}", response_model=TaskOut)
async def resume_task_from(
    task_id: int, step_id: int, db: AsyncSession = Depends(get_session)
):
    try:
        task = await AgentTaskService(db).resume_from(task_id, step_id)
    except (TaskNotFound, StepNotFound) as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return await _full_task(db, task)


@router.post("/agent-task-steps/{step_id}/approve", response_model=TaskOut)
async def approve_step(step_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).approve_step(step_id)
    except StepNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return await _full_task(db, task)


@router.post("/agent-task-steps/{step_id}/retry", response_model=TaskOut)
async def retry_step(step_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).retry_step(step_id)
    except StepNotFound as e:
        raise HTTPException(404, str(e))
    return await _full_task(db, task)


@router.get("/agent-tasks/{task_id}/evidence", response_model=list[EvidenceOut])
async def list_task_evidence(
    task_id: int,
    step_id: int | None = None,
    kind: str | None = None,
    tool_name: str | None = None,
    text: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    try:
        return await AgentTaskService(db).list_evidence(
            task_id, step_id=step_id, kind=kind, tool_name=tool_name, text=text
        )
    except TaskNotFound as e:
        raise HTTPException(404, str(e))


@router.get("/agent-tasks/{task_id}/report")
async def get_task_report(task_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task = await AgentTaskService(db).get(task_id)
    except TaskNotFound as e:
        raise HTTPException(404, str(e))
    return {"task_id": task.id, "markdown": task.final_report_md or ""}
