"""长期记忆异步仓储层：记忆项 / 事件流。

照 core/repo.py 模式：每个仓储持有一个 AsyncSession，方法内自带 commit。
仓储层不抛 HTTPException，缺失时返回 None；路由层负责 404。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MemoryEvent, MemoryItem


def _escape_like(term: str) -> str:
    """转义 LIKE 元字符（% _ \\），避免用户输入被当通配符。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MemoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        kind: str,
        title: str,
        content_md: str,
        summary: str | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
        project_id: int | None = None,
        topic_id: int | None = None,
        tags_json: list | None = None,
        confidence: float | None = None,
        enabled: bool = True,
        sensitive: bool = False,
        status: str = "confirmed",
    ) -> MemoryItem:
        item = MemoryItem(
            kind=kind,
            title=title,
            content_md=content_md,
            summary=summary,
            source_type=source_type,
            source_id=source_id,
            project_id=project_id,
            topic_id=topic_id,
            tags_json=tags_json,
            confidence=confidence,
            enabled=enabled,
            sensitive=sensitive,
            status=status,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get(self, memory_id: int) -> Optional[MemoryItem]:
        return await self.db.get(MemoryItem, memory_id)

    async def get_fresh(self, memory_id: int) -> Optional[MemoryItem]:
        """强制从 DB 重新加载（populate_existing）。

        update() 后身份映射中的对象属性（尤其带 onupdate 的 updated_at）会被标记
        过期；db.get 会命中缓存返回过期对象，序列化时触发同步懒加载报错。
        """
        stmt = (
            select(MemoryItem)
            .where(MemoryItem.id == memory_id)
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        enabled: bool | None = None,
        project_id: int | None = None,
        topic_id: int | None = None,
        search: str | None = None,
    ) -> list[MemoryItem]:
        """记忆列表，支持按类型/状态/启用/项目/主题过滤与标题/内容/摘要搜索。"""
        stmt = select(MemoryItem)
        if kind:
            stmt = stmt.where(MemoryItem.kind == kind)
        if status:
            stmt = stmt.where(MemoryItem.status == status)
        if enabled is not None:
            stmt = stmt.where(MemoryItem.enabled == enabled)
        if project_id is not None:
            stmt = stmt.where(MemoryItem.project_id == project_id)
        if topic_id is not None:
            stmt = stmt.where(MemoryItem.topic_id == topic_id)
        if search and search.strip():
            term = _escape_like(search.strip())
            like = f"%{term}%"
            stmt = stmt.where(
                or_(
                    MemoryItem.title.like(like, escape="\\"),
                    MemoryItem.content_md.like(like, escape="\\"),
                    MemoryItem.summary.like(like, escape="\\"),
                )
            )
        stmt = stmt.order_by(MemoryItem.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        memory_id: int,
        *,
        title: str | None = None,
        content_md: str | None = None,
        summary: str | None = None,
        tags_json: list | None = None,
        confidence: float | None = None,
        enabled: bool | None = None,
        sensitive: bool | None = None,
        status: str | None = None,
    ) -> None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if content_md is not None:
            values["content_md"] = content_md
        if summary is not None:
            values["summary"] = summary or None
        if tags_json is not None:
            values["tags_json"] = tags_json
        if confidence is not None:
            values["confidence"] = confidence
        if enabled is not None:
            values["enabled"] = enabled
        if sensitive is not None:
            values["sensitive"] = sensitive
        if status is not None:
            values["status"] = status
        if not values:
            return
        await self.db.execute(
            update(MemoryItem).where(MemoryItem.id == memory_id).values(**values)
        )
        await self.db.commit()

    async def delete(self, memory_id: int) -> None:
        # memory_events 有 ON DELETE CASCADE，删 memory_item 自动删事件
        item = await self.get(memory_id)
        if item:
            await self.db.delete(item)
            await self.db.commit()


class MemoryEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        memory_id: int,
        event_type: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
        detail_json: dict | None = None,
    ) -> MemoryEvent:
        ev = MemoryEvent(
            memory_id=memory_id,
            event_type=event_type,
            ref_type=ref_type,
            ref_id=ref_id,
            detail_json=detail_json,
        )
        self.db.add(ev)
        await self.db.commit()
        await self.db.refresh(ev)
        return ev

    async def create_many(
        self,
        *,
        memory_ids: list[int],
        event_type: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> list[MemoryEvent]:
        """批量写同类型事件（如多条记忆被同一次会话使用）。"""
        if not memory_ids:
            return []
        objs = [
            MemoryEvent(
                memory_id=mid,
                event_type=event_type,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            for mid in memory_ids
        ]
        self.db.add_all(objs)
        await self.db.commit()
        for o in objs:
            await self.db.refresh(o)
        return objs

    async def list_by_memory(self, memory_id: int) -> list[MemoryEvent]:
        stmt = (
            select(MemoryEvent)
            .where(MemoryEvent.memory_id == memory_id)
            .order_by(MemoryEvent.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
