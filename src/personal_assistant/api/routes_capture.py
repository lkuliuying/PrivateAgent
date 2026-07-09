"""快速捕获路由（第七阶段 M3）。

- POST /capture              创建捕获草稿
- GET  /capture              列出捕获草稿
- POST /capture/{id}/to-inbox    转收件箱
- POST /capture/{id}/to-reminder 转提醒
- POST /capture/{id}/to-memory   转记忆候选
- DELETE /capture/{id}       丢弃捕获草稿
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.capture import CaptureService
from ..core.db import get_session

router = APIRouter(tags=["capture"])


class CaptureCreate(BaseModel):
    content_md: str
    source: str = "manual"
    title: str | None = None
    source_ref_json: dict | None = None
    candidate_type: str | None = None


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    content_md: str
    source: str
    candidate_type: str | None
    status: str
    target_type: str | None
    target_id: int | None
    created_at: datetime
    handled_at: datetime | None


class ToInboxReq(BaseModel):
    item_type: str = "note"


class ToReminderReq(BaseModel):
    due_at: datetime | None = None


class ToMemoryReq(BaseModel):
    kind: str = "note"


@router.post("/capture", response_model=CaptureOut, status_code=201)
async def create_capture(body: CaptureCreate, db: AsyncSession = Depends(get_session)):
    return await CaptureService(db).create(
        content_md=body.content_md,
        source=body.source,
        title=body.title,
        source_ref_json=body.source_ref_json,
        candidate_type=body.candidate_type,
    )


@router.get("/capture", response_model=list[CaptureOut])
async def list_capture(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_session),
):
    return await CaptureService(db).list(status=status, limit=limit)


@router.post("/capture/{capture_id}/to-inbox")
async def capture_to_inbox(
    capture_id: int, body: ToInboxReq, db: AsyncSession = Depends(get_session)
):
    inbox = await CaptureService(db).to_inbox(capture_id, item_type=body.item_type)
    if inbox is None:
        raise HTTPException(404, "capture not found")
    return {"target_type": "inbox", "target_id": inbox.id}


@router.post("/capture/{capture_id}/to-reminder")
async def capture_to_reminder(
    capture_id: int, body: ToReminderReq, db: AsyncSession = Depends(get_session)
):
    reminder = await CaptureService(db).to_reminder(capture_id, due_at=body.due_at)
    if reminder is None:
        raise HTTPException(404, "capture not found")
    return {"target_type": "reminder", "target_id": reminder.id}


@router.post("/capture/{capture_id}/to-memory")
async def capture_to_memory(
    capture_id: int, body: ToMemoryReq, db: AsyncSession = Depends(get_session)
):
    mem = await CaptureService(db).to_memory(capture_id, kind=body.kind)
    if mem is None:
        raise HTTPException(404, "capture not found")
    return {"target_type": "memory", "target_id": mem.id}


@router.delete("/capture/{capture_id}")
async def discard_capture(capture_id: int, db: AsyncSession = Depends(get_session)):
    svc = CaptureService(db)
    cap = await svc.repo.get(capture_id)
    if cap is None:
        raise HTTPException(404, "capture not found")
    await svc.repo.discard(capture_id)
    return {"ok": True}
