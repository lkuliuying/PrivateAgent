"""Briefing routes for phase 6."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.briefings import BriefingNotFound, BriefingService
from ..core.db import get_session

router = APIRouter(tags=["briefings"])


class BriefingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    body_md: str
    sources_json: list | None
    created_at: datetime


@router.post("/today/briefing", response_model=BriefingOut, status_code=201)
async def create_today_briefing(db: AsyncSession = Depends(get_session)):
    return await BriefingService(db).create_today_briefing()


@router.post("/briefings/weekly", response_model=BriefingOut, status_code=201)
async def create_weekly_briefing(db: AsyncSession = Depends(get_session)):
    return await BriefingService(db).create_weekly_briefing()


@router.get("/briefings", response_model=list[BriefingOut])
async def list_briefings(
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    return await BriefingService(db).list(kind=kind, limit=limit)


@router.post("/briefings/{briefing_id}/to-task")
async def briefing_to_task(
    briefing_id: int,
    db: AsyncSession = Depends(get_session),
):
    try:
        task_id = await BriefingService(db).to_task(briefing_id)
    except BriefingNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"task_id": task_id}
