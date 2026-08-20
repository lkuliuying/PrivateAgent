"""v0.6.0 RunPlan 仓储层：持久化 run 计划项（C0 契约 §4.2）。

- 同一 ``(run_id, plan_version, item_key)`` 唯一；``(run_id, plan_version, ordinal)`` 唯一。
- 同一 run 同时最多一个 ``in_progress``，由 service 层事务校验。
- plan version 只增不减；item completed 不自动把 run 标记 completed。
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import RunPlanItem

# 合法 item 状态（C0 §4.3）
PLAN_ITEM_STATUSES = frozenset(
    {"pending", "in_progress", "completed", "blocked", "failed", "cancelled"}
)


class RunPlanRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_plan(
        self,
        *,
        run_id: str,
        items: list[dict],
        plan_version: int = 1,
    ) -> list[RunPlanItem]:
        """批量创建计划项。每个 item 包含 item_key/title/detail/status。

        调用方必须保证 plan_version 是下一个版本（版本冲突由 service 校验）。
        """
        records = []
        for ordinal, item in enumerate(items, start=1):
            status = item.get("status", "pending")
            if status not in PLAN_ITEM_STATUSES:
                raise ValueError(f"invalid plan item status: {status}")
            record = RunPlanItem(
                id=str(uuid4()),
                run_id=run_id,
                plan_version=plan_version,
                item_key=item["item_key"],
                ordinal=ordinal,
                title=item["title"],
                detail=item.get("detail"),
                status=status,
            )
            self.db.add(record)
            records.append(record)
        await self.db.commit()
        for r in records:
            await self.db.refresh(r)
        return records

    async def get_plan(
        self, run_id: str, plan_version: int | None = None
    ) -> list[RunPlanItem]:
        """获取 run 的计划项。不指定版本返回最新版本。"""
        from sqlalchemy import func

        if plan_version is not None:
            stmt = (
                select(RunPlanItem)
                .where(
                    RunPlanItem.run_id == run_id,
                    RunPlanItem.plan_version == plan_version,
                )
                .order_by(RunPlanItem.ordinal)
            )
        else:
            latest = (
                select(func.max(RunPlanItem.plan_version))
                .where(RunPlanItem.run_id == run_id)
                .scalar_subquery()
            )
            stmt = (
                select(RunPlanItem)
                .where(
                    RunPlanItem.run_id == run_id,
                    RunPlanItem.plan_version == latest,
                )
                .order_by(RunPlanItem.ordinal)
            )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_plan_version(self, run_id: str) -> int:
        from sqlalchemy import func

        stmt = select(func.max(RunPlanItem.plan_version)).where(
            RunPlanItem.run_id == run_id
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def update_plan_item(
        self,
        *,
        item_id: str,
        status: str,
        evidence_json: dict | None = None,
    ) -> RunPlanItem | None:
        """更新单个计划项状态（状态机校验由 service 负责）。

        使用 ORM 更新而非 bulk ``update()``：bulk 语句会 expire identity map
        中的实例，后续同步属性访问会触发异步 lazy load（MissingGreenlet）。
        """
        record = await self.db.get(RunPlanItem, item_id)
        if record is None:
            return None
        record.status = status
        if evidence_json is not None:
            record.evidence_json = evidence_json
        await self.db.commit()
        # onupdate 列（updated_at）由数据库生成，commit 后 refresh 取回新值
        await self.db.refresh(record)
        return record

    async def replace_plan(
        self,
        *,
        run_id: str,
        items: list[dict],
        plan_version: int,
    ) -> list[RunPlanItem]:
        """写入计划新版本（旧版本数据保留，用于审计与重放）。"""
        return await self.create_plan(
            run_id=run_id,
            items=items,
            plan_version=plan_version,
        )

    async def count_in_progress(self, run_id: str) -> int:
        """统计 run 当前 in_progress 的计划项数量。"""
        from sqlalchemy import func

        stmt = (
            select(func.count(RunPlanItem.id))
            .where(
                RunPlanItem.run_id == run_id,
                RunPlanItem.status == "in_progress",
            )
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)
