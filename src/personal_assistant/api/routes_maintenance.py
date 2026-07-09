"""数据完整性体检与修复计划路由（第七阶段 M7）。

- GET  /maintenance/integrity              数据体检发现项列表
- POST /maintenance/repair-plan            生成修复计划（预览）
- POST /maintenance/repair-plan/{id}/apply 执行单条修复（不默认删用户数据）
- PATCH /maintenance/findings/{id}         标记 finding 为 ignored/resolved
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.integrity import IntegrityService

router = APIRouter(tags=["maintenance-integrity"])


class IntegrityFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    check_name: str
    severity: str
    ref_type: str | None
    ref_id: int | None
    detail_json: dict | None
    suggested_action: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class FindingPatch(BaseModel):
    status: str  # open / ignored / resolved


@router.get("/maintenance/integrity", response_model=list[IntegrityFindingOut])
async def list_integrity(
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> list:
    return await IntegrityService(db).list_findings(status=status)


@router.post("/maintenance/integrity/run", response_model=list[IntegrityFindingOut])
async def run_integrity(db: AsyncSession = Depends(get_session)) -> list:
    """执行体检（持久化新发现项，跳过已 ignored/resolved）。"""
    return await IntegrityService(db).check()


@router.post("/maintenance/repair-plan")
async def repair_plan(db: AsyncSession = Depends(get_session)) -> list:
    """生成修复计划（预览，不执行）。"""
    return await IntegrityService(db).repair_plan()


@router.post("/maintenance/repair-plan/{finding_id}/apply")
async def apply_repair(
    finding_id: int, db: AsyncSession = Depends(get_session)
) -> dict:
    result = await IntegrityService(db).apply(finding_id)
    if not result.get("ok") and result.get("error") == "finding not found":
        raise HTTPException(404, "finding not found")
    return result


@router.patch("/maintenance/findings/{finding_id}", response_model=IntegrityFindingOut)
async def patch_finding(
    finding_id: int,
    body: FindingPatch,
    db: AsyncSession = Depends(get_session),
) -> IntegrityFindingOut:
    f = await IntegrityService(db).set_status(finding_id, body.status)
    if f is None:
        raise HTTPException(404, "finding not found")
    return f
