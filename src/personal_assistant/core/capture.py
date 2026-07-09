"""快速捕获服务（第七阶段 M3）。

捕获草稿可转为 inbox / reminder / memory candidate。
to-memory 复用 memory_items status='draft'（候选待确认），不新建表。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from .models import MemoryItem
from .repo_capture import CaptureItemRepository
from .repo_inbox import InboxRepository
from .repo_reminders import ReminderRepository
from .timeutil import utcnow


class CaptureService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CaptureItemRepository(db)

    async def create(
        self,
        *,
        content_md: str,
        source: str = "manual",
        title: str | None = None,
        source_ref_json: dict | None = None,
        candidate_type: str | None = None,
    ):
        return await self.repo.create(
            content_md=content_md,
            source=source,
            title=title,
            source_ref_json=source_ref_json,
            candidate_type=candidate_type,
        )

    async def list(self, *, status: str | None = None, limit: int = 100):
        return await self.repo.list(status=status, limit=limit)

    async def to_inbox(self, capture_id: int, *, item_type: str = "note"):
        cap = await self.repo.get(capture_id)
        if cap is None:
            return None
        title = (cap.title or cap.content_md.split("\n")[0])[:255] or f"捕获 #{cap.id}"
        inbox = await InboxRepository(self.db).create(
            title=title,
            item_type=item_type,
            body_md=cap.content_md,
            source_type="capture",
            source_id=cap.id,
        )
        await self.repo.mark_handled(capture_id, target_type="inbox", target_id=inbox.id)
        return inbox

    async def to_reminder(self, capture_id: int, *, due_at=None):
        cap = await self.repo.get(capture_id)
        if cap is None:
            return None
        title = (cap.title or cap.content_md.split("\n")[0])[:255] or f"捕获 #{cap.id}"
        when = due_at or (utcnow() + timedelta(days=1))
        reminder = await ReminderRepository(self.db).create(
            title=title,
            due_at=when,
            body_md=cap.content_md,
            source_type="capture",
            source_id=cap.id,
        )
        await self.repo.mark_handled(
            capture_id, target_type="reminder", target_id=reminder.id
        )
        return reminder

    async def to_memory(self, capture_id: int, *, kind: str = "note"):
        """转为记忆候选（memory_items status='draft'）。"""
        cap = await self.repo.get(capture_id)
        if cap is None:
            return None
        title = (cap.title or cap.content_md.split("\n")[0])[:255] or f"捕获 #{cap.id}"
        mem = MemoryItem(
            kind=kind,
            title=title,
            content_md=cap.content_md,
            source_type="capture",
            source_id=cap.id,
            status="draft",
        )
        self.db.add(mem)
        await self.db.commit()
        await self.db.refresh(mem)
        await self.repo.mark_handled(
            capture_id, target_type="memory", target_id=mem.id
        )
        return mem
