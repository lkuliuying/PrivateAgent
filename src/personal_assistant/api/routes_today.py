"""今日中枢路由（第六阶段 M2）。

- GET /today  今日聚合快照（TodayService.snapshot）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.today import TodayService

router = APIRouter(tags=["today"])


@router.get("/today")
async def get_today(db: AsyncSession = Depends(get_session)) -> dict:
    """今日中枢聚合快照：到期复习/待关注任务/失败活动/draft记忆/到期提醒/收件箱/备份。"""
    return await TodayService(db).snapshot()
