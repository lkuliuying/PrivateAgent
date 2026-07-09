"""统一通知中心路由（第七阶段 M4）。

- GET /notifications            通知历史（可按 status/kind 过滤）
- POST /notifications           创建通知（前端持久化 toast / 内部调用）
- PATCH /notifications/{id}     标记已读/归档
- POST /notifications/read-all  全部标为已读
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.notifications import NotificationService

router = APIRouter(tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    kind: str
    title: str
    message: str | None = None
    status: str
    source_type: str | None = None
    source_id: int | None = None
    action_type: str | None = None
    action_payload_json: dict | None = None
    created_at: datetime
    read_at: datetime | None = None


class NotificationCreate(BaseModel):
    kind: str
    title: str
    level: str = "info"
    message: str | None = None
    source_type: str | None = None
    source_id: int | None = None
    action_type: str | None = None
    action_payload: dict | None = None


class NotificationPatch(BaseModel):
    status: str  # read / archived


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_session),
) -> list:
    return await NotificationService(db).list(status=status, kind=kind, limit=limit)


@router.post("/notifications", response_model=NotificationOut, status_code=201)
async def create_notification(
    body: NotificationCreate,
    db: AsyncSession = Depends(get_session),
) -> NotificationOut:
    svc = NotificationService(db)
    n = await svc.notify(
        kind=body.kind,
        title=body.title,
        level=body.level,
        message=body.message,
        source_type=body.source_type,
        source_id=body.source_id,
        action_type=body.action_type,
        action_payload=body.action_payload,
    )
    return n


@router.patch("/notifications/{notification_id}", response_model=NotificationOut)
async def patch_notification(
    notification_id: int,
    body: NotificationPatch,
    db: AsyncSession = Depends(get_session),
) -> NotificationOut:
    svc = NotificationService(db)
    await svc.mark(notification_id, body.status)
    n = await svc.repo.get(notification_id)
    if n is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return n


@router.post("/notifications/read-all")
async def read_all_notifications(
    db: AsyncSession = Depends(get_session),
) -> dict:
    count = await NotificationService(db).mark_all_read()
    return {"marked": count}
