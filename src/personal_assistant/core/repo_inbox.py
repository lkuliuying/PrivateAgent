"""统一收件箱异步仓储层（第六阶段 M1）。

照 core/repo_memories.py 模式：每仓储持 AsyncSession，方法内自带 commit；
仓储层不抛 HTTPException，缺失时返回 None；路由层负责 404。

收件箱是「待处理事项」的唯一入口：完成/归档/忽略只改 inbox 自身状态，
不删除原始来源对象（聊天/任务/活动/记忆）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import InboxItem
from .timeutil import utcnow


class InboxRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        title: str,
        item_type: str,
        body_md: str | None = None,
        status: str = "open",
        priority: str = "normal",
        due_at: datetime | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        meta_json: dict | None = None,
    ) -> InboxItem:
        item = InboxItem(
            title=title,
            body_md=body_md,
            item_type=item_type,
            status=status,
            priority=priority,
            due_at=due_at,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            meta_json=meta_json,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get(self, item_id: int) -> Optional[InboxItem]:
        return await self.db.get(InboxItem, item_id)

    async def get_fresh(self, item_id: int) -> Optional[InboxItem]:
        """强制从 DB 重新加载（populate_existing）。

        update() 后身份映射中的对象属性（尤其带 onupdate 的 updated_at）会被标记
        过期；db.get 命中缓存返回过期对象，序列化时触发同步懒加载报错。
        """
        stmt = (
            select(InboxItem)
            .where(InboxItem.id == item_id)
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        status: str | None = None,
        item_type: str | None = None,
        priority: str | None = None,
        source_type: str | None = None,
        limit: int = 200,
    ) -> list[InboxItem]:
        """收件箱列表，支持按状态/类型/优先级/来源过滤，默认按创建倒序。"""
        stmt = select(InboxItem)
        if status:
            stmt = stmt.where(InboxItem.status == status)
        if item_type:
            stmt = stmt.where(InboxItem.item_type == item_type)
        if priority:
            stmt = stmt.where(InboxItem.priority == priority)
        if source_type:
            stmt = stmt.where(InboxItem.source_type == source_type)
        stmt = stmt.order_by(InboxItem.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_open(self, limit: int = 200) -> list[InboxItem]:
        """今日中枢用：未处理项（open/snoozed），按截止时间升序。"""
        stmt = (
            select(InboxItem)
            .where(InboxItem.status.in_(["open", "snoozed"]))
            .order_by(InboxItem.due_at.is_(None).asc(), InboxItem.due_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def find_open_by_source(
        self, source_type: str, source_id: int
    ) -> Optional[InboxItem]:
        """按来源找未处理 inbox item（open/snoozed）。供提醒 tick 去重用。"""
        stmt = (
            select(InboxItem)
            .where(InboxItem.source_type == source_type)
            .where(InboxItem.source_id == source_id)
            .where(InboxItem.status.in_(["open", "snoozed"]))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        item_id: int,
        *,
        title: str | None = None,
        body_md: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        due_at: datetime | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        meta_json: dict | None = None,
    ) -> None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if body_md is not None:
            values["body_md"] = body_md
        if status is not None:
            values["status"] = status
            # 进入终态（done/ignored/archived）时补 handled_at。
            if status in ("done", "ignored", "archived"):
                values["handled_at"] = utcnow()
        if priority is not None:
            values["priority"] = priority
        if due_at is not None:
            values["due_at"] = due_at
        if target_type is not None:
            values["target_type"] = target_type
        if target_id is not None:
            values["target_id"] = target_id
        if meta_json is not None:
            values["meta_json"] = meta_json
        if not values:
            return
        await self.db.execute(
            update(InboxItem).where(InboxItem.id == item_id).values(**values)
        )
        await self.db.commit()

    async def mark(self, item_id: int, status: str) -> None:
        """便捷状态流转：complete(done)/snooze(snoozed)/ignore(ignored)/archive(archived)。"""
        await self.update(item_id, status=status)

    async def delete(self, item_id: int) -> None:
        item = await self.get(item_id)
        if item:
            await self.db.delete(item)
            await self.db.commit()
