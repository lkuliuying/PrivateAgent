"""诊断中心路由（第七阶段 M5）。

- GET  /diagnostics          诊断快照（聚合健康/版本/迁移/错误/失败活动/Provider/提醒/导入/备份/体检）
- POST /diagnostics/export   生成脱敏诊断包（zip），返回路径
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.diagnostics import DiagnosticsService

router = APIRouter(tags=["diagnostics"])


class ExportRequest(BaseModel):
    output_dir: str | None = None


class ExportResult(BaseModel):
    path: str
    run_id: int
    size_bytes: int


@router.get("/diagnostics")
async def get_diagnostics(db: AsyncSession = Depends(get_session)) -> dict:
    """诊断中心快照。"""
    return await DiagnosticsService(db).snapshot()


@router.post("/diagnostics/export", response_model=ExportResult)
async def export_diagnostics(
    body: ExportRequest, db: AsyncSession = Depends(get_session)
) -> ExportResult:
    """生成脱敏诊断包到 data/diagnostics。

    忽略调用方 output_dir（防路径注入：避免攻击者控制写入位置），始终用默认目录。
    """
    result = await DiagnosticsService(db).export(output_dir=None)
    return ExportResult(**result)
