"""今日中枢路由（第六阶段 M2 + 第七阶段 M1 筛选）。

- GET /today  今日聚合快照（TodayService.snapshot），支持 type/priority/time/status 筛选。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.today import TodayFilters, TodayService

router = APIRouter(tags=["today"])


@router.get("/today")
async def get_today(
    type: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    time: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """今日中枢聚合快照：到期复习/待关注任务/失败活动/draft记忆/到期提醒/收件箱/备份
    + 最近 check-in/简报/文档/会话/维护摘要。

    筛选仅影响展示列表；summary 计数始终为真实全量。
    """
    filters = TodayFilters(type=type, priority=priority, time=time, status=status)
    has_filters = any([type, priority, time, status])
    return await TodayService(db).snapshot(filters=filters if has_filters else None)
