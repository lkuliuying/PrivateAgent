"""统一收件箱路由（第六阶段 M2）。

- GET    /inbox                  收件箱列表（status/item_type/priority/source_type 过滤）
- POST   /inbox                  手动创建收件箱项（可带来源 source_type/source_id）
- GET    /inbox/{id}             收件箱项详情
- PATCH  /inbox/{id}             更新状态/优先级/截止时间/标题/正文（完成/稍后/忽略/归档）
- POST   /inbox/{id}/to-task     转为任务计划草稿（plan_draft，不调 LLM）
- POST   /inbox/{id}/to-reminder 转为提醒
- DELETE /inbox/{id}             删除收件箱项（不删原始来源对象）

完成/归档只改 inbox 自身状态，不删除原始聊天/任务/活动/记忆。
转任务/转提醒后会 link target 并把 inbox 项标记为 done。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.models import InboxItem
from ..core.repo_inbox import InboxRepository
from ..core.repo_reminders import ReminderRepository
from ..core.tasks import AgentTaskService, TaskNotFound
from ..core.timeutil import utcnow

router = APIRouter(tags=["inbox"])

InboxItemType = Literal[
    "todo", "reminder", "review", "approval", "failure", "memory", "note", "system"
]
InboxStatus = Literal["open", "snoozed", "done", "ignored", "archived"]
InboxPriority = Literal["low", "normal", "high", "urgent"]


# ---- Schemas ----


class InboxCreate(BaseModel):
    title: str
    item_type: InboxItemType
    body_md: str | None = None
    status: InboxStatus = "open"
    priority: InboxPriority = "normal"
    due_at: datetime | None = None
    source_type: str | None = None
    source_id: int | None = None
    target_type: str | None = None
    target_id: int | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title 不能为空")
        return v[:255]


class InboxUpdate(BaseModel):
    title: str | None = None
    body_md: str | None = None
    status: InboxStatus | None = None
    priority: InboxPriority | None = None
    due_at: datetime | None = None


class InboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body_md: str | None
    item_type: str
    status: str
    priority: str
    due_at: datetime | None
    source_type: str | None
    source_id: int | None
    target_type: str | None
    target_id: int | None
    meta_json: dict | None
    created_at: datetime
    updated_at: datetime
    handled_at: datetime | None


class ToReminderRequest(BaseModel):
    due_at: datetime | None = None
    recurrence_rule: dict | None = None


# ---- Routes ----


async def _get_or_404(db: AsyncSession, item_id: int) -> InboxItem:
    item = await InboxRepository(db).get(item_id)
    if item is None:
        raise HTTPException(404, "收件箱项不存在")
    return item


@router.get("/inbox", response_model=list[InboxOut])
async def list_inbox(
    status: str | None = Query(default=None),
    item_type: str | None = Query(default=None, alias="item_type"),
    priority: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    """收件箱列表，支持按状态/类型/优先级/来源过滤。"""
    return await InboxRepository(db).list(
        status=status,
        item_type=item_type,
        priority=priority,
        source_type=source_type,
    )


@router.post("/inbox", response_model=InboxOut, status_code=201)
async def create_inbox(req: InboxCreate, db: AsyncSession = Depends(get_session)):
    return await InboxRepository(db).create(
        title=req.title,
        item_type=req.item_type,
        body_md=req.body_md,
        status=req.status,
        priority=req.priority,
        due_at=req.due_at,
        source_type=req.source_type,
        source_id=req.source_id,
        target_type=req.target_type,
        target_id=req.target_id,
    )


@router.get("/inbox/{item_id}", response_model=InboxOut)
async def get_inbox(item_id: int, db: AsyncSession = Depends(get_session)):
    return await _get_or_404(db, item_id)


@router.patch("/inbox/{item_id}", response_model=InboxOut)
async def update_inbox(
    item_id: int, req: InboxUpdate, db: AsyncSession = Depends(get_session)
):
    repo = InboxRepository(db)
    await _get_or_404(db, item_id)
    await repo.update(
        item_id,
        title=req.title,
        body_md=req.body_md,
        status=req.status,
        priority=req.priority,
        due_at=req.due_at,
    )
    return await repo.get_fresh(item_id)


@router.post("/inbox/{item_id}/to-task", response_model=InboxOut)
async def inbox_to_task(item_id: int, db: AsyncSession = Depends(get_session)):
    """转为任务计划草稿（plan_draft，不调 LLM）。link target 并标记 inbox 为 done。"""
    repo = InboxRepository(db)
    item = await _get_or_404(db, item_id)
    try:
        task = await AgentTaskService(db).create_draft(
            title=item.title,
            goal=item.body_md or item.title,
            source_type="inbox_item",
            source_id=item.id,
        )
    except TaskNotFound as e:  # pragma: no cover - create_draft 不会触发
        raise HTTPException(404, str(e))
    await repo.update(
        item_id,
        status="done",
        target_type="agent_task",
        target_id=task.id,
    )
    return await repo.get_fresh(item_id)


@router.post("/inbox/{item_id}/to-reminder", response_model=InboxOut)
async def inbox_to_reminder(
    item_id: int,
    req: ToReminderRequest,
    db: AsyncSession = Depends(get_session),
):
    """转为提醒。due_at 缺省用 inbox.due_at，再缺省用现在+1天。link target 并标记 done。"""
    repo = InboxRepository(db)
    item = await _get_or_404(db, item_id)
    due_at = req.due_at or item.due_at or (utcnow() + timedelta(days=1))
    reminder = await ReminderRepository(db).create(
        title=item.title,
        due_at=due_at,
        body_md=item.body_md,
        recurrence_rule=req.recurrence_rule,
        source_type="inbox_item",
        source_id=item.id,
    )
    await repo.update(
        item_id,
        status="done",
        target_type="reminder",
        target_id=reminder.id,
    )
    return await repo.get_fresh(item_id)


@router.delete("/inbox/{item_id}", status_code=204)
async def delete_inbox(item_id: int, db: AsyncSession = Depends(get_session)):
    repo = InboxRepository(db)
    item = await repo.get(item_id)
    if item is None:
        raise HTTPException(404, "收件箱项不存在")
    # 只删 inbox 项本身，不触碰原始来源对象（聊天/任务/活动/记忆）。
    await repo.delete(item_id)
    return None
