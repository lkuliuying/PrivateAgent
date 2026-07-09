"""OCR 队列路由（第七阶段 M3）。

- GET  /ocr/availability      OCR 引擎可用性检测（供 UI 降级提示）
- GET  /ocr-jobs              OCR 任务列表
- GET  /ocr-jobs/{job_id}     单个 OCR 任务状态
- POST /ocr-jobs/{job_id}/retry  重试失败的 OCR 任务
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.ocr import ocr_engine_available
from ..core.repo_ocr_jobs import OcrJobRepository

router = APIRouter(tags=["ocr"])


class OcrAvailability(BaseModel):
    available: bool
    reason: str
    engine: str | None


class OcrJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_id: int | None
    file_path: str | None
    source: str
    status: str
    engine: str | None
    output_text: str | None = None
    error_message: str | None
    source_type: str | None
    source_id: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@router.get("/ocr/availability", response_model=OcrAvailability)
async def ocr_availability() -> OcrAvailability:
    available, reason, engine = ocr_engine_available()
    return OcrAvailability(available=available, reason=reason, engine=engine)


@router.get("/ocr-jobs", response_model=list[OcrJobOut])
async def list_ocr_jobs(
    status: str | None = Query(default=None),
    doc_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_session),
):
    return await OcrJobRepository(db).list(status=status, doc_id=doc_id, limit=limit)


@router.get("/ocr-jobs/{job_id}", response_model=OcrJobOut)
async def get_ocr_job(job_id: int, db: AsyncSession = Depends(get_session)):
    job = await OcrJobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(404, "ocr job not found")
    return job


@router.post("/ocr-jobs/{job_id}/retry", response_model=OcrJobOut)
async def retry_ocr_job(job_id: int, db: AsyncSession = Depends(get_session)):
    import asyncio

    from ..workers.ocr import run_ocr_job

    repo = OcrJobRepository(db)
    job = await repo.get(job_id)
    if job is None:
        raise HTTPException(404, "ocr job not found")
    await repo.mark(job_id, status="pending", error_message=None)
    asyncio.create_task(run_ocr_job(job_id, job.file_path))
    return await repo.get(job_id)
