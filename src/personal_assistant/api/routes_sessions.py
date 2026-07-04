"""会话与消息路由。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
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


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(db: AsyncSession = Depends(get_session)):
    """获取会话列表（按最近更新倒序）。"""
    items = await SessionRepository(db).list()
    logger.info("sessions listed", count=len(items))
    return items


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(db: AsyncSession = Depends(get_session)):
    """新建会话，标题默认「新对话」，首轮对话后由后端自动生成。"""
    s = await SessionRepository(db).create()
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
