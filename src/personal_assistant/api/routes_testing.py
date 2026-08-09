"""测试 / 发布运行摘要路由（第八阶段 M3，dev / 本地用）。

- GET /testing/runs                最近测试运行摘要（release_check/e2e/performance/upgrade_smoke/diagnostic_smoke）
- GET /testing/upgrade-smoke-runs  升级 smoke 运行列表

对齐 docs/archive/phases/phase8-requirements.md §7。只读摘要，不泄露敏感正文。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.models import TestRun, UpgradeSmokeRun

router = APIRouter(tags=["testing"])


class TestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    version: str | None
    git_commit: str | None
    schema_head: str | None
    artifact_path: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class UpgradeSmokeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_version: str
    to_version: str
    platform: str
    result: str
    data_preserved: bool | None
    schema_ok: bool | None
    created_at: datetime


@router.get("/testing/runs", response_model=list[TestRunOut])
async def list_test_runs(
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> list:
    stmt = select(TestRun)
    if kind:
        stmt = stmt.where(TestRun.kind == kind)
    stmt = stmt.order_by(TestRun.created_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/testing/upgrade-smoke-runs", response_model=list[UpgradeSmokeRunOut])
async def list_upgrade_smoke_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> list:
    stmt = select(UpgradeSmokeRun).order_by(UpgradeSmokeRun.created_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())
