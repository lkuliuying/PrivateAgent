"""统一通知中心仓储层（第七阶段 M4）。

照 core/repo_memories.py 模式：持 AsyncSession，方法内自带 commit。
通知只保存摘要（title/message），不保存敏感正文（聊天全文/文档原文/敏感记忆）。
source_type/source_id 软引用来源对象供跳转；action_* 描述可重试/可跳转动作。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppNotification
from .timeutil import utcnow


class NotificationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        kind: str,
        title: str,
        level: str = "info",
        message: str | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
        action_type: str | None = None,
        action_payload_json: dict | None = None,
        status: str = "unread",
    ) -> AppNotification:
        n = AppNotification(
            level=level,
            kind=kind,
            title=title,
            message=message,
            status=status,
            source_type=source_type,
            source_id=source_id,
            action_type=action_type,
            action_payload_json=action_payload_json,
        )
        self.db.add(n)
        await self.db.commit()
        await self.db.refresh(n)
        return n

    async def get(self, notification_id: int) -> Optional[AppNotification]:
        return await self.db.get(AppNotification, notification_id)

    async def list(
        self,
        *,
        status: str | None = None,
        level: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[AppNotification]:
        """通知历史，默认按创建倒序。可按 status/level/kind 过滤。"""
        stmt = select(AppNotification)
        if status:
            stmt = stmt.where(AppNotification.status == status)
        if level:
            stmt = stmt.where(AppNotification.level == level)
        if kind:
            stmt = stmt.where(AppNotification.kind == kind)
        stmt = stmt.order_by(AppNotification.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark(self, notification_id: int, status: str) -> None:
        """更新通知状态（read/archived），read 时补 read_at。"""
        values: dict = {"status": status}
        if status == "read":
            values["read_at"] = utcnow()
        await self.db.execute(
            update(AppNotification)
            .where(AppNotification.id == notification_id)
            .values(**values)
        )
        await self.db.commit()

    async def mark_all_read(self) -> int:
        """全部未读标为已读，返回影响行数。"""
        result = await self.db.execute(
            update(AppNotification)
            .where(AppNotification.status == "unread")
            .values(status="read", read_at=utcnow())
        )
        await self.db.commit()
        return int(result.rowcount or 0)

    async def delete(self, notification_id: int) -> None:
        n = await self.get(notification_id)
        if n:
            await self.db.delete(n)
            await self.db.commit()
