"""全局搜索路由（第七阶段 M2）。

- GET  /search         全局搜索（跨会话/文档/切片/任务/证据/记忆/收件箱/提醒/目标/简报等）
- POST /search/recent  记录最近打开对象，供全局搜索按最近使用排序
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.models import SearchRecentItem
from ..core.search import SearchService
from ..core.timeutil import utcnow

router = APIRouter(tags=["search"])


class SearchResultOut(BaseModel):
    type: str
    id: int
    title: str
    snippet: str | None = None
    source: str
    updated_at: str | None = None
    action: str
    meta: dict | None = None


class RecentOpenIn(BaseModel):
    object_type: str
    object_id: int
    title: str | None = None


@router.get("/search", response_model=list[SearchResultOut])
async def search(
    q: str = Query(min_length=1),
    types: str | None = Query(default=None, description="逗号分隔的类型过滤"),
    limit: int = Query(default=30, le=100),
    db: AsyncSession = Depends(get_session),
) -> list:
    type_list = [t.strip() for t in types.split(",") if t.strip()] if types else None
    return await SearchService(db).search(q, types=type_list, limit=limit)


@router.post("/search/recent", status_code=201)
async def record_recent(body: RecentOpenIn, db: AsyncSession = Depends(get_session)) -> dict:
    """记录最近打开对象（upsert：存在则刷新 last_opened_at 并 +1 open_count）。"""
    stmt = select(SearchRecentItem).where(
        SearchRecentItem.object_type == body.object_type,
        SearchRecentItem.object_id == body.object_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    now: datetime = utcnow()
    if existing:
        existing.last_opened_at = now
        existing.open_count = (existing.open_count or 0) + 1
        if body.title:
            existing.title = body.title
    else:
        db.add(
            SearchRecentItem(
                object_type=body.object_type,
                object_id=body.object_id,
                title=body.title,
                last_opened_at=now,
                open_count=1,
            )
        )
    await db.commit()
    return {"ok": True}
