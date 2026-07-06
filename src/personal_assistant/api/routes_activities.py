"""活动流路由（第二阶段 M4）。

- GET  /activities            活动列表（可按 session/kind/status 过滤）
- GET  /activities/{id}       活动详情
- POST /activities/{id}/retry 重试失败活动（目前支持文档导入/索引重建）
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.activities import ActivityService
from ..core.db import get_session
from ..core.repo import DocumentRepository
from ..workers.importer import reindex_document, retry_import

router = APIRouter(tags=["activities"])


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int | None
    kind: str
    title: str
    status: str
    ref_type: str | None
    ref_id: int | None
    detail_json: dict | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _upload_path(doc_id: int, name: str) -> Path:
    """与 routes_documents._upload_path 一致：data/uploads/{doc_id}{ext}。"""
    ext = Path(name).suffix
    return Path("./data/uploads") / f"{doc_id}{ext}"


@router.get("/activities", response_model=list[ActivityOut])
async def list_activities(
    session_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_session),
):
    return await ActivityService(db).list(
        session_id=session_id, kind=kind, status=status, limit=limit
    )


@router.get("/activities/{activity_id}", response_model=ActivityOut)
async def get_activity(activity_id: int, db: AsyncSession = Depends(get_session)):
    act = await ActivityService(db).get(activity_id)
    if act is None:
        raise HTTPException(404, "活动不存在")
    return act


@router.post("/activities/{activity_id}/retry", response_model=ActivityOut)
async def retry_activity(activity_id: int, db: AsyncSession = Depends(get_session)):
    act = await ActivityService(db).get(activity_id)
    if act is None:
        raise HTTPException(404, "活动不存在")
    if act.status != "failed":
        raise HTTPException(400, f"仅失败活动可重试，当前: {act.status}")
    if not act.ref_id or act.ref_type not in ("document_import", "document_reindex"):
        raise HTTPException(400, "该活动类型不支持重试（工具调用请在对话中重新发起）")

    doc = await DocumentRepository(db).get(act.ref_id)
    if doc is None:
        raise HTTPException(400, "关联文档已删除，无法重试")
    upload_path = _upload_path(doc.id, doc.name)
    if not upload_path.exists():
        raise HTTPException(400, "原始文件不存在，无法重试，请重新导入")

    if act.ref_type == "document_reindex":
        asyncio.create_task(reindex_document(doc.id, str(upload_path)))
    else:
        asyncio.create_task(retry_import(doc.id, str(upload_path)))
    return act
