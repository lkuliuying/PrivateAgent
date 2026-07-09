"""Privacy and maintenance routes for phase 6."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.privacy import PrivacyService

router = APIRouter(tags=["privacy"])


class PrivacyPreviewRequest(BaseModel):
    purpose: str = "chat"
    provider_type: str | None = None
    include_kb: bool = False
    include_memories: bool = True
    include_messages: bool = True
    estimated_message_chars: int = 0


class PrivacyPreviewOut(BaseModel):
    audit_id: int
    provider_type: str
    remote: bool
    remote_provider_enabled: bool
    context_types: list[str]
    estimated_input_chars: int
    safe_memory_count: int
    sensitive_memory_excluded: int
    will_send_raw_sensitive_memory: bool


class ProviderAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_type: str
    model: str | None
    purpose: str
    remote: bool
    context_types_json: list | None
    estimated_input_chars: int | None
    estimated_output_chars: int | None
    # 第七阶段 M6：调用耗时、token 估算、错误分类、回退标记、开始时间。
    started_at: datetime | None = None
    duration_ms: int | None = None
    estimated_input_tokens: int | None = None
    estimated_output_tokens: int | None = None
    error_code: str | None = None
    fallback_used: bool = False
    status: str
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


@router.get("/privacy/audits", response_model=list[ProviderAuditOut])
async def list_privacy_audits(
    remote: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
):
    return await PrivacyService(db).list_audits(remote=remote, limit=limit)


@router.post("/privacy/preview", response_model=PrivacyPreviewOut)
async def privacy_preview(
    req: PrivacyPreviewRequest,
    db: AsyncSession = Depends(get_session),
):
    return await PrivacyService(db).preview(**req.model_dump())


@router.get("/maintenance/health-report")
async def maintenance_health_report(db: AsyncSession = Depends(get_session)):
    return await PrivacyService(db).maintenance_health_report()
