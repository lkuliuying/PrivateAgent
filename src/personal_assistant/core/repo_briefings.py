"""主动简报异步仓储层（第六阶段 M1）。

照 core/repo_memories.py 模式：每仓储持 AsyncSession，方法内自带 commit；
仓储层不抛 HTTPException，缺失时返回 None。

简报只持久化结构化结果：kind/title/body_md/sources_json。
sources_json 只存摘要与 id，不存大段原文（phase6 §6）。
简报的「生成」逻辑（聚合数据 + 可选 LLM）属 M5 BriefingService，不在仓储层。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Briefing


class BriefingRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        kind: str,
        title: str,
        body_md: str,
        sources_json: list | None = None,
    ) -> Briefing:
        briefing = Briefing(
            kind=kind,
            title=title,
            body_md=body_md,
            sources_json=sources_json,
        )
        self.db.add(briefing)
        await self.db.commit()
        await self.db.refresh(briefing)
        return briefing

    async def get(self, briefing_id: int) -> Optional[Briefing]:
        return await self.db.get(Briefing, briefing_id)

    async def list(
        self,
        *,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[Briefing]:
        """简报历史，默认按创建倒序。可按 kind 过滤。"""
        stmt = select(Briefing)
        if kind:
            stmt = stmt.where(Briefing.kind == kind)
        stmt = stmt.order_by(Briefing.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, briefing_id: int) -> None:
        briefing = await self.get(briefing_id)
        if briefing:
            await self.db.delete(briefing)
            await self.db.commit()
