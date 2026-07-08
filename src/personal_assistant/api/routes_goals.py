"""Goal routes for phase 6."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.goals import GoalNotFound, GoalService

router = APIRouter(tags=["goals"])

GoalStatus = Literal["active", "paused", "done", "archived"]
GoalPriority = Literal["low", "normal", "high"]


class GoalCreate(BaseModel):
    title: str
    description: str | None = None
    domain: str = "custom"
    status: GoalStatus = "active"
    priority: GoalPriority = "normal"
    start_date: date | None = None
    target_date: date | None = None
    success_criteria_md: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title is required")
        return v[:255]


class GoalUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    domain: str | None = None
    status: GoalStatus | None = None
    priority: GoalPriority | None = None
    start_date: date | None = None
    target_date: date | None = None
    success_criteria_md: str | None = None


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    domain: str
    status: str
    priority: str
    start_date: date | None
    target_date: date | None
    success_criteria_md: str | None
    created_at: datetime
    updated_at: datetime


class GoalLinkCreate(BaseModel):
    target_type: str
    target_id: int
    relation: str = "supports"


class GoalLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    target_type: str
    target_id: int
    relation: str
    created_at: datetime


class GoalCheckinCreate(BaseModel):
    checkin_date: date | None = None
    progress_note_md: str | None = None
    confidence: float | None = None
    blockers_json: list | None = None
    next_actions_json: list | None = None


class GoalCheckinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    checkin_date: date
    progress_note_md: str | None
    confidence: float | None
    blockers_json: list | None
    next_actions_json: list | None
    created_at: datetime


class BriefingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    body_md: str
    sources_json: list | None
    created_at: datetime


class GoalDetailOut(BaseModel):
    goal: GoalOut
    links: list[GoalLinkOut]
    checkins: list[GoalCheckinOut]


async def _svc(db: AsyncSession) -> GoalService:
    return GoalService(db)


def _not_found(exc: GoalNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/goals", response_model=list[GoalOut])
async def list_goals(
    status: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
):
    return await GoalService(db).list(status=status, domain=domain, limit=limit)


@router.post("/goals", response_model=GoalOut, status_code=201)
async def create_goal(req: GoalCreate, db: AsyncSession = Depends(get_session)):
    return await GoalService(db).create(**req.model_dump())


@router.get("/goals/{goal_id}", response_model=GoalDetailOut)
async def get_goal(goal_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await GoalService(db).detail(goal_id)
    except GoalNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/goals/{goal_id}", response_model=GoalOut)
async def update_goal(
    goal_id: int,
    req: GoalUpdate,
    db: AsyncSession = Depends(get_session),
):
    try:
        return await GoalService(db).update(
            goal_id, **req.model_dump(exclude_unset=True)
        )
    except GoalNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/goals/{goal_id}/links", response_model=GoalLinkOut, status_code=201)
async def add_goal_link(
    goal_id: int,
    req: GoalLinkCreate,
    db: AsyncSession = Depends(get_session),
):
    try:
        return await GoalService(db).add_link(goal_id, **req.model_dump())
    except GoalNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/goals/{goal_id}/checkins", response_model=GoalCheckinOut, status_code=201
)
async def add_goal_checkin(
    goal_id: int,
    req: GoalCheckinCreate,
    db: AsyncSession = Depends(get_session),
):
    try:
        return await GoalService(db).add_checkin(goal_id, **req.model_dump())
    except GoalNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/goals/{goal_id}/task-draft")
async def goal_to_task(goal_id: int, db: AsyncSession = Depends(get_session)):
    try:
        task_id = await GoalService(db).create_task_draft(goal_id)
    except GoalNotFound as exc:
        raise _not_found(exc) from exc
    return {"task_id": task_id}


@router.post("/goals/{goal_id}/briefing", response_model=BriefingOut)
async def goal_briefing(goal_id: int, db: AsyncSession = Depends(get_session)):
    try:
        return await GoalService(db).create_briefing(goal_id)
    except GoalNotFound as exc:
        raise _not_found(exc) from exc
