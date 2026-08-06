"""OCR 队列仓储（第七阶段 M3）。照 repo_memories.py 模式。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import OcrJob


class OcrJobRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        doc_id: int | None = None,
        file_path: str | None = None,
        source: str = "manual",
        source_type: str | None = None,
        source_id: int | None = None,
    ) -> OcrJob:
        job = OcrJob(
            doc_id=doc_id,
            file_path=file_path,
            source=source,
            status="pending",
            source_type=source_type,
            source_id=source_id,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def get(self, job_id: int) -> Optional[OcrJob]:
        return await self.db.get(OcrJob, job_id)

    async def list(
        self, *, status: str | None = None, doc_id: int | None = None, limit: int = 100
    ) -> list[OcrJob]:
        stmt = select(OcrJob)
        if status:
            stmt = stmt.where(OcrJob.status == status)
        if doc_id is not None:
            stmt = stmt.where(OcrJob.doc_id == doc_id)
        stmt = stmt.order_by(OcrJob.created_at.desc()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def mark(
        self,
        job_id: int,
        *,
        status: str,
        engine: str | None = None,
        output_text: str | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        values: dict = {"status": status}
        if engine is not None:
            values["engine"] = engine
        if output_text is not None:
            values["output_text"] = output_text
        if error_message is not None:
            values["error_message"] = error_message[:1000]
        if started_at is not None:
            values["started_at"] = started_at
        if finished_at is not None:
            values["finished_at"] = finished_at
        await self.db.execute(
            update(OcrJob).where(OcrJob.id == job_id).values(**values)
        )
        await self.db.commit()
