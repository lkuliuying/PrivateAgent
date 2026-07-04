"""会话与消息的异步仓储层。

封装 sessions / messages 表的访问，供 ChatService 与 API 路由使用。
不依赖 FastAPI，可被任意 async 调用方复用。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatSession, Message


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, title: str = "新对话") -> ChatSession:
        obj = ChatSession(title=title)
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def list(self) -> list[ChatSession]:
        """按最近更新时间倒序返回会话。"""
        stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, session_id: int) -> Optional[ChatSession]:
        return await self.db.get(ChatSession, session_id)

    async def rename(self, session_id: int, title: str) -> None:
        stmt = (
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(title=title)
        )
        await self.db.execute(stmt)
        await self.db.commit()


class MessageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, session_id: int, role: str, content: str) -> Message:
        """追加一条消息，并 touch 会话的 updated_at（用于会话列表排序）。"""
        msg = Message(session_id=session_id, role=role, content=content)
        self.db.add(msg)
        await self.db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(updated_at=func.now())
        )
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def list_by_session(self, session_id: int) -> list[Message]:
        """按时间正序返回该会话的全部消息。"""
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
