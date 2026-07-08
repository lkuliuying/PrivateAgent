"""提醒异步仓储层（第六阶段 M1）。

照 core/repo_memories.py 模式：每仓储持 AsyncSession，方法内自带 commit；
仓储层不抛 HTTPException，缺失时返回 None。

提醒状态机：active -> snoozed（稍后）/ done（完成）/ cancelled（取消）。
- create 时 next_fire_at 初始化为 due_at。
- list_due 扫描 status in (active, snoozed) AND next_fire_at <= now，供今日中枢与 tick。
- snooze 只改 next_fire_at 与 status=snoozed，不改 due_at（原定时间保留溯源）。
- mark_done 写 last_fired_at；重复提醒的下次 next_fire_at 计算由 M3 tick 服务负责
  （recurrence 计算依赖业务规则，不在仓储层）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Reminder
from .timeutil import utcnow


class ReminderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        title: str,
        due_at: datetime,
        body_md: str | None = None,
        recurrence_rule: dict | None = None,
        status: str = "active",
        source_type: str | None = None,
        source_id: int | None = None,
    ) -> Reminder:
        reminder = Reminder(
            title=title,
            body_md=body_md,
            status=status,
            due_at=due_at,
            recurrence_rule=recurrence_rule,
            # next_fire_at 初始化为 due_at，tick 扫描据此判断到期。
            next_fire_at=due_at,
            source_type=source_type,
            source_id=source_id,
        )
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)
        return reminder

    async def get(self, reminder_id: int) -> Optional[Reminder]:
        return await self.db.get(Reminder, reminder_id)

    async def get_fresh(self, reminder_id: int) -> Optional[Reminder]:
        """强制从 DB 重新加载，避免 update 后身份映射返回过期对象。"""
        stmt = (
            select(Reminder)
            .where(Reminder.id == reminder_id)
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        status: str | None = None,
        limit: int = 200,
    ) -> list[Reminder]:
        stmt = select(Reminder)
        if status:
            stmt = stmt.where(Reminder.status == status)
        stmt = stmt.order_by(Reminder.due_at.asc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_due(self, now: datetime | None = None, limit: int = 200) -> list[Reminder]:
        """到期提醒：status in (active, snoozed) AND next_fire_at <= now。

        供今日中枢与 M3 tick 扫描复用。空表或无到期项返回空列表。
        """
        now = now or utcnow()
        stmt = (
            select(Reminder)
            .where(Reminder.status.in_(["active", "snoozed"]))
            .where(Reminder.next_fire_at <= now)
            .order_by(Reminder.next_fire_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        reminder_id: int,
        *,
        title: str | None = None,
        body_md: str | None = None,
        due_at: datetime | None = None,
        recurrence_rule: dict | None = None,
        status: str | None = None,
        next_fire_at: datetime | None = None,
        last_fired_at: datetime | None = None,
    ) -> None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if body_md is not None:
            values["body_md"] = body_md
        if due_at is not None:
            values["due_at"] = due_at
        if recurrence_rule is not None:
            values["recurrence_rule"] = recurrence_rule
        if status is not None:
            values["status"] = status
        if next_fire_at is not None:
            values["next_fire_at"] = next_fire_at
        if last_fired_at is not None:
            values["last_fired_at"] = last_fired_at
        if not values:
            return
        await self.db.execute(
            update(Reminder).where(Reminder.id == reminder_id).values(**values)
        )
        await self.db.commit()

    async def snooze(self, reminder_id: int, next_fire_at: datetime) -> None:
        """稍后提醒：status=snoozed，next_fire_at 延后，due_at 保留溯源。"""
        await self.update(
            reminder_id, status="snoozed", next_fire_at=next_fire_at
        )

    async def mark_done(self, reminder_id: int) -> None:
        """完成提醒：status=done，记录 last_fired_at。

        重复提醒的下一次 next_fire_at 生成由 M3 tick 服务依据 recurrence_rule 计算，
        再调 set_next_fire 生成新提醒或更新本条。此处只标记本次完成。
        """
        await self.update(
            reminder_id, status="done", last_fired_at=utcnow()
        )

    async def cancel(self, reminder_id: int) -> None:
        await self.update(reminder_id, status="cancelled")

    async def delete(self, reminder_id: int) -> None:
        reminder = await self.get(reminder_id)
        if reminder:
            await self.db.delete(reminder)
            await self.db.commit()
