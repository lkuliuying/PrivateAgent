"""会话与消息路由。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.history import MessageRepository, SessionRepository
from ..logging_setup import get_logger

router = APIRouter(tags=["sessions"])
logger = get_logger(__name__)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    # v0.6.0 Coding Agent
    project_id: int | None = None
    workspace_id: int | None = None
    kind: str | None = None
    last_run_id: str | None = None
    pinned_at: datetime | None = None
    archived_at: datetime | None = None


class SessionCreateRequest(BaseModel):
    title: str = Field(default="新对话", max_length=255)
    project_id: int | None = None
    workspace_id: int | None = None
    kind: str | None = Field(default=None, max_length=32)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    project_id: int | None = Query(default=None, gt=0),
    kind: str | None = Query(default=None, max_length=32),
    db: AsyncSession = Depends(get_session),
):
    """获取会话列表（按最近更新倒序）。可选按 project/kind 过滤。"""
    items = await SessionRepository(db).list(project_id=project_id, kind=kind)
    logger.info("sessions listed", count=len(items))
    return items


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session_detail(
    session_id: int,
    db: AsyncSession = Depends(get_session),
):
    """获取会话详情（v0.6.0 返回 project/workspace 绑定）。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    return sess


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    request: SessionCreateRequest = SessionCreateRequest(),
    db: AsyncSession = Depends(get_session),
):
    """新建会话。v0.6.0 支持可选 project/workspace 绑定。"""
    s = await SessionRepository(db).create(
        title=request.title,
        project_id=request.project_id,
        workspace_id=request.workspace_id,
        kind=request.kind,
    )
    logger.info("session created", session_id=s.id)
    return s


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: int, db: AsyncSession = Depends(get_session)):
    """获取指定会话的消息历史。"""
    sess = await SessionRepository(db).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = await MessageRepository(db).list_by_session(session_id)
    logger.info("messages listed", session_id=session_id, count=len(msgs))
    return msgs
