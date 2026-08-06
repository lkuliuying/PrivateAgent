"""提醒路由（第六阶段 M3）。

- GET    /reminders                提醒列表（status 过滤）
- POST   /reminders                创建提醒（next_fire_at = due_at）
- GET    /reminders/{id}           提醒详情
- PATCH  /reminders/{id}           更新提醒（标题/正文/due_at/重复规则/状态）
- POST   /reminders/{id}/snooze    稍后提醒（next_fire_at 延后）
- POST   /reminders/{id}/done      完成（一次性->done；重复->生成下一次）
- POST   /reminders/tick           手动触发到期扫描（测试/开发）
- DELETE /reminders/{id}           删除提醒
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.models import Reminder
from ..core.reminders import ReminderService
from ..core.timeutil import utcnow

router = APIRouter(tags=["reminders"])

ReminderStatus = Literal["active", "snoozed", "done", "cancelled"]
RecurrenceFreq = Literal["none", "daily", "weekly", "monthly"]


# ---- Schemas ----


class RecurrenceRule(BaseModel):
    freq: RecurrenceFreq = "none"
    interval: int = 1

    @field_validator("interval")
    @classmethod
    def _check_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval 必须 >= 1")
        return v


class ReminderCreate(BaseModel):
    title: str
    due_at: datetime
    body_md: str | None = None
    recurrence_rule: RecurrenceRule | None = None
    source_type: str | None = None
    source_id: int | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title 不能为空")
        return v[:255]


class ReminderUpdate(BaseModel):
    title: str | None = None
    body_md: str | None = None
    due_at: datetime | None = None
    recurrence_rule: RecurrenceRule | None = None
    status: ReminderStatus | None = None


class SnoozeRequest(BaseModel):
    next_fire_at: datetime | None = None
    minutes: int | None = None


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body_md: str | None
    status: str
    due_at: datetime
    recurrence_rule: dict | None
    next_fire_at: datetime | None
    last_fired_at: datetime | None
    source_type: str | None
    source_id: int | None
    created_at: datetime
    updated_at: datetime


def _to_out(r: Reminder) -> ReminderOut:
    return ReminderOut.model_validate(r)


async def _get_or_404(db: AsyncSession, reminder_id: int) -> Reminder:
    r = await ReminderService(db).get(reminder_id)
    if r is None:
        raise HTTPException(404, "提醒不存在")
    return r


# ---- Routes ----


@router.get("/reminders", response_model=list[ReminderOut])
async def list_reminders(
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    return await ReminderService(db).list(status=status)


@router.post("/reminders", response_model=ReminderOut, status_code=201)
async def create_reminder(req: ReminderCreate, db: AsyncSession = Depends(get_session)):
    svc = ReminderService(db)
    return await svc.create(
        title=req.title,
        due_at=req.due_at,
        body_md=req.body_md,
        recurrence_rule=req.recurrence_rule.model_dump() if req.recurrence_rule else None,
        source_type=req.source_type,
        source_id=req.source_id,
    )


@router.get("/reminders/{reminder_id}", response_model=ReminderOut)
async def get_reminder(reminder_id: int, db: AsyncSession = Depends(get_session)):
    return _to_out(await _get_or_404(db, reminder_id))


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: int, req: ReminderUpdate, db: AsyncSession = Depends(get_session)
):
    svc = ReminderService(db)
    await _get_or_404(db, reminder_id)
    updated = await svc.update(
        reminder_id,
        title=req.title,
        body_md=req.body_md,
        due_at=req.due_at,
        recurrence_rule=req.recurrence_rule.model_dump()
        if req.recurrence_rule
        else None,
        status=req.status,
    )
    return _to_out(updated)


@router.post("/reminders/{reminder_id}/snooze", response_model=ReminderOut)
async def snooze_reminder(
    reminder_id: int, req: SnoozeRequest, db: AsyncSession = Depends(get_session)
):
    svc = ReminderService(db)
    await _get_or_404(db, reminder_id)
    if req.next_fire_at:
        next_fire = req.next_fire_at
    elif req.minutes:
        next_fire = utcnow() + timedelta(minutes=req.minutes)
    else:
        next_fire = utcnow() + timedelta(days=1)
    r = await svc.snooze(reminder_id, next_fire)
    return _to_out(r)


@router.post("/reminders/{reminder_id}/done", response_model=ReminderOut)
async def done_reminder(reminder_id: int, db: AsyncSession = Depends(get_session)):
    svc = ReminderService(db)
    await _get_or_404(db, reminder_id)
    r = await svc.mark_done(reminder_id)
    return _to_out(r)


@router.post("/reminders/tick")
async def tick_reminders(db: AsyncSession = Depends(get_session)):
    """手动触发到期扫描（测试/开发）。后台 tick 由 sidecar lifespan 自动运行。"""
    fired = await ReminderService(db).tick()
    return {"fired": fired}


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: int, db: AsyncSession = Depends(get_session)):
    svc = ReminderService(db)
    if await svc.get(reminder_id) is None:
        raise HTTPException(404, "提醒不存在")
    await svc.delete(reminder_id)
    return None
