"""长期记忆异步仓储层：记忆项 / 事件流。

照 core/repo.py 模式：每个仓储持有一个 AsyncSession，方法内自带 commit。
仓储层不抛 HTTPException，缺失时返回 None；路由层负责 404。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MemoryConflict, MemoryEvent, MemoryItem, MemoryRevision
from .timeutil import utcnow


def _escape_like(term: str) -> str:
    """转义 LIKE 元字符（% _ \\），避免用户输入被当通配符。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _revision_state(item: MemoryItem) -> dict:
    return {
        "source_type": item.source_type,
        "source_id": item.source_id,
        "project_id": item.project_id,
        "topic_id": item.topic_id,
        "tags": item.tags_json,
        "confidence": item.confidence,
        "importance": item.importance,
        "enabled": item.enabled,
        "sensitive": item.sensitive,
        "sensitivity_level": item.sensitivity_level,
        "status": item.status,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
        "last_confirmed_at": (
            item.last_confirmed_at.isoformat() if item.last_confirmed_at else None
        ),
        "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
    }


def _revision(item: MemoryItem, *, change_type: str) -> MemoryRevision:
    return MemoryRevision(
        memory_id=item.id,
        stable_key=item.stable_key,
        memory_version=item.memory_version,
        kind=item.kind,
        title=item.title,
        content_md=item.content_md,
        content_sha256=item.content_sha256,
        summary=item.summary,
        state_json=_revision_state(item),
        change_type=change_type,
    )


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
        stable_key: str | None = None,
        importance: float = 0.5,
        expires_at: datetime | None = None,
        sensitivity_level: str | None = None,
    ) -> MemoryItem:
        if not 0.0 <= importance <= 1.0:
            raise ValueError("memory importance must be between 0 and 1")
        level = sensitivity_level or ("sensitive" if sensitive else "normal")
        if level not in {"normal", "sensitive", "restricted"}:
            raise ValueError("invalid memory sensitivity level")
        if sensitive and level == "normal":
            level = "sensitive"
        now = utcnow()
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
            stable_key=stable_key or uuid4().hex,
            memory_version=1,
            content_sha256=_content_sha256(content_md),
            importance=importance,
            expires_at=expires_at,
            sensitivity_level=level,
            confirmed_at=now if status == "confirmed" else None,
            last_confirmed_at=now if status == "confirmed" else None,
        )
        self.db.add(item)
        await self.db.flush()
        self.db.add(_revision(item, change_type="created"))
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get(self, memory_id: int) -> Optional[MemoryItem]:
        result = await self.db.execute(
            select(MemoryItem).where(
                MemoryItem.id == memory_id,
                MemoryItem.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_including_deleted(self, memory_id: int) -> Optional[MemoryItem]:
        return await self.db.get(MemoryItem, memory_id)

    async def get_fresh(self, memory_id: int) -> Optional[MemoryItem]:
        """强制从 DB 重新加载（populate_existing）。

        update() 后身份映射中的对象属性（尤其带 onupdate 的 updated_at）会被标记
        过期；db.get 会命中缓存返回过期对象，序列化时触发同步懒加载报错。
        """
        stmt = (
            select(MemoryItem)
            .where(
                MemoryItem.id == memory_id,
                MemoryItem.deleted_at.is_(None),
            )
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
        stmt = select(MemoryItem).where(MemoryItem.deleted_at.is_(None))
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
        importance: float | None = None,
        expires_at: datetime | None = None,
        sensitivity_level: str | None = None,
    ) -> MemoryItem | None:
        item = (
            await self.db.execute(
                select(MemoryItem)
                .where(
                    MemoryItem.id == memory_id,
                    MemoryItem.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if item is None:
            await self.db.rollback()
            return None
        values: dict[str, object] = {}
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
            if sensitivity_level is None:
                values["sensitivity_level"] = (
                    "sensitive" if sensitive else "normal"
                )
        if status is not None:
            values["status"] = status
        if importance is not None:
            if not 0.0 <= importance <= 1.0:
                await self.db.rollback()
                raise ValueError("memory importance must be between 0 and 1")
            values["importance"] = importance
        if expires_at is not None:
            values["expires_at"] = expires_at
        if sensitivity_level is not None:
            if sensitivity_level not in {"normal", "sensitive", "restricted"}:
                await self.db.rollback()
                raise ValueError("invalid memory sensitivity level")
            values["sensitivity_level"] = sensitivity_level
            values["sensitive"] = sensitivity_level != "normal"
        if not values:
            await self.db.rollback()
            return await self.get(memory_id)
        previous_status = item.status
        for key, value in values.items():
            setattr(item, key, value)
        if content_md is not None:
            item.content_sha256 = _content_sha256(item.content_md)
        now = utcnow()
        if item.status == "confirmed" and previous_status != "confirmed":
            item.confirmed_at = item.confirmed_at or now
            item.last_confirmed_at = now
        item.memory_version += 1
        change_type = (
            "confirmed"
            if item.status == "confirmed" and previous_status != "confirmed"
            else "edited"
        )
        self.db.add(_revision(item, change_type=change_type))
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete(self, memory_id: int) -> bool:
        """Soft-delete while preserving the item, events and immutable revisions."""

        item = (
            await self.db.execute(
                select(MemoryItem)
                .where(
                    MemoryItem.id == memory_id,
                    MemoryItem.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if item is None:
            await self.db.rollback()
            return False
        item.deleted_at = utcnow()
        item.enabled = False
        item.status = "archived"
        item.memory_version += 1
        self.db.add(_revision(item, change_type="deleted"))
        self.db.add(MemoryEvent(memory_id=item.id, event_type="deleted"))
        await self.db.commit()
        return True


class MemoryRevisionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_memory(self, memory_id: int) -> list[MemoryRevision]:
        result = await self.db.execute(
            select(MemoryRevision)
            .where(MemoryRevision.memory_id == memory_id)
            .order_by(MemoryRevision.memory_version.asc())
        )
        return list(result.scalars().all())


class MemoryConflictRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        left_memory_id: int,
        right_memory_id: int,
        *,
        reason: str,
    ) -> MemoryConflict:
        left, right = sorted((left_memory_id, right_memory_id))
        if left == right:
            raise ValueError("a memory cannot conflict with itself")
        if not reason.strip():
            raise ValueError("memory conflict reason is required")
        try:
            records = (
                await self.db.execute(
                    select(MemoryItem)
                    .where(
                        MemoryItem.id.in_([left, right]),
                        MemoryItem.deleted_at.is_(None),
                    )
                    .order_by(MemoryItem.id.asc())
                    .with_for_update()
                )
            ).scalars().all()
            if len(records) != 2:
                raise LookupError("both active memories are required")
            existing = (
                await self.db.execute(
                    select(MemoryConflict).where(
                        MemoryConflict.left_memory_id == left,
                        MemoryConflict.right_memory_id == right,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                await self.db.commit()
                return existing
            conflict = MemoryConflict(
                left_memory_id=left,
                right_memory_id=right,
                reason=reason.strip(),
                status="open",
            )
            self.db.add(conflict)
            await self.db.commit()
            await self.db.refresh(conflict)
            return conflict
        except Exception:
            await self.db.rollback()
            raise

    async def resolve(
        self,
        conflict_id: int,
        *,
        resolution: dict,
    ) -> MemoryConflict | None:
        conflict = (
            await self.db.execute(
                select(MemoryConflict)
                .where(MemoryConflict.id == conflict_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if conflict is None:
            await self.db.rollback()
            return None
        if conflict.status != "open":
            await self.db.rollback()
            raise ValueError(f"memory conflict is already {conflict.status}")
        conflict.status = "resolved"
        conflict.resolution_json = resolution
        conflict.resolved_at = utcnow()
        await self.db.commit()
        await self.db.refresh(conflict)
        return conflict

    async def list_open(self) -> list[MemoryConflict]:
        result = await self.db.execute(
            select(MemoryConflict)
            .where(MemoryConflict.status == "open")
            .order_by(MemoryConflict.created_at.asc())
        )
        return list(result.scalars().all())


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
