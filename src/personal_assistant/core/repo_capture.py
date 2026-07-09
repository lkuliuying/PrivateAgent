"""快速捕获草稿仓储（第七阶段 M3）。照 repo_memories.py 模式。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CaptureItem
from .timeutil import utcnow


class CaptureItemRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        content_md: str,
        source: str = "manual",
        title: str | None = None,
        source_ref_json: dict | None = None,
        candidate_type: str | None = None,
    ) -> CaptureItem:
        item = CaptureItem(
            title=title,
            content_md=content_md,
            source=source,
            source_ref_json=source_ref_json,
            candidate_type=candidate_type,
            status="pending",
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get(self, capture_id: int) -> Optional[CaptureItem]:
        return await self.db.get(CaptureItem, capture_id)

    async def list(self, *, status: str | None = None, limit: int = 100) -> list[CaptureItem]:
        stmt = select(CaptureItem)
        if status:
            stmt = stmt.where(CaptureItem.status == status)
        stmt = stmt.order_by(CaptureItem.created_at.desc()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def mark_handled(
        self,
        capture_id: int,
        *,
        target_type: str,
        target_id: int,
    ) -> None:
        await self.db.execute(
            update(CaptureItem)
            .where(CaptureItem.id == capture_id)
            .values(
                status="handled",
                target_type=target_type,
                target_id=target_id,
                handled_at=utcnow(),
            )
        )
        await self.db.commit()

    async def discard(self, capture_id: int) -> None:
        await self.db.execute(
            update(CaptureItem)
            .where(CaptureItem.id == capture_id)
            .values(status="discarded", handled_at=utcnow())
        )
        await self.db.commit()
