"""提醒服务（第六阶段 M3）：到期扫描 / snooze / 重复规则 / 生成 inbox item / 后台 tick。

设计要点：
- tick：扫描到期提醒（list_due），为每条生成一个 open inbox item（按来源去重，
  同 reminder 已有 open/snoozed inbox 则跳过），使到期提醒同时进入今日收件箱。
  不自动改 reminder 状态--由用户 snooze/done 处理，尊重用户审批边界。
- mark_done：一次性提醒 -> done；重复提醒 -> 计算 next_fire_at，保持 active（生成下一次）。
- snooze：next_fire_at 延后，due_at 保留溯源（见 repo_reminders）。
- compute_next_fire：纯函数，支持 none/daily/weekly/monthly + interval。
- reminder_tick_loop：sidecar lifespan 启动的后台轮询。**先 sleep 再 tick**，确保即使
  测试意外运行 lifespan，首次 tick 也晚于任何测试结束（避免与断言竞态）。
  读 reminders_enabled/reminder_tick_seconds，关闭则跳过 tick。
"""
from __future__ import annotations

import asyncio
import calendar
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .db import async_session_factory  # 后台 tick 用；请求路径用注入的 db
from .models import Reminder
from .repo_inbox import InboxRepository
from .repo_reminders import ReminderRepository
from .settings import SettingsService
from .timeutil import utcnow

logger = get_logger(__name__)

# 重复规则支持的 freq。
RECURRENCE_FREQS = ("none", "daily", "weekly", "monthly")


def _add_months(dt: datetime, months: int) -> datetime:
    """加 months 个月（日溢出则截到月末，如 1/31 +1 月 -> 2/28）。"""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def compute_next_fire(
    recurrence_rule: dict | None, now: datetime | None = None
) -> datetime | None:
    """根据重复规则计算下一次到期时间。无规则或 freq=none 返回 None。"""
    if not recurrence_rule:
        return None
    freq = str(recurrence_rule.get("freq", "none")).lower()
    if freq == "none":
        return None
    interval = max(1, int(recurrence_rule.get("interval", 1) or 1))
    now = now or utcnow()
    if freq == "daily":
        return now + timedelta(days=interval)
    if freq == "weekly":
        return now + timedelta(weeks=interval)
    if freq == "monthly":
        return _add_months(now, interval)
    return None


def normalize_rule(rule: dict | None) -> dict | None:
    """归一化重复规则：{freq: <one of RECURRENCE_FREQS>, interval: pos int}。无效则 None。"""
    if not rule:
        return None
    freq = str(rule.get("freq", "none")).lower()
    if freq not in RECURRENCE_FREQS:
        freq = "none"
    try:
        interval = max(1, int(rule.get("interval", 1) or 1))
    except (TypeError, ValueError):
        interval = 1
    return {"freq": freq, "interval": interval}


class ReminderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ReminderRepository(db)
        self.inbox = InboxRepository(db)

    async def create(
        self,
        *,
        title: str,
        due_at: datetime,
        body_md: str | None = None,
        recurrence_rule: dict | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
    ) -> Reminder:
        return await self.repo.create(
            title=title,
            due_at=due_at,
            body_md=body_md,
            recurrence_rule=normalize_rule(recurrence_rule),
            source_type=source_type,
            source_id=source_id,
        )

    async def get(self, reminder_id: int) -> Reminder | None:
        return await self.repo.get(reminder_id)

    async def list(self, *, status: str | None = None) -> list[Reminder]:
        return await self.repo.list(status=status)

    async def update(
        self,
        reminder_id: int,
        *,
        title: str | None = None,
        body_md: str | None = None,
        due_at: datetime | None = None,
        recurrence_rule: dict | None = None,
        status: str | None = None,
    ) -> Reminder | None:
        await self.repo.update(
            reminder_id,
            title=title,
            body_md=body_md,
            due_at=due_at,
            recurrence_rule=normalize_rule(recurrence_rule)
            if recurrence_rule is not None
            else None,
            status=status,
        )
        return await self.repo.get_fresh(reminder_id)

    async def snooze(self, reminder_id: int, next_fire_at: datetime) -> Reminder | None:
        await self.repo.snooze(reminder_id, next_fire_at)
        return await self.repo.get_fresh(reminder_id)

    async def mark_done(self, reminder_id: int) -> Reminder | None:
        """完成提醒：一次性 -> done；重复 -> 计算下次 next_fire_at，保持 active。"""
        r = await self.repo.get(reminder_id)
        if r is None:
            return None
        now = utcnow()
        next_fire = compute_next_fire(r.recurrence_rule, now)
        if next_fire is not None:
            await self.repo.update(
                reminder_id, next_fire_at=next_fire, last_fired_at=now
            )
        else:
            await self.repo.mark_done(reminder_id)
        return await self.repo.get_fresh(reminder_id)

    async def cancel(self, reminder_id: int) -> Reminder | None:
        await self.repo.cancel(reminder_id)
        return await self.repo.get_fresh(reminder_id)

    async def delete(self, reminder_id: int) -> None:
        await self.repo.delete(reminder_id)

    async def tick(self, now: datetime | None = None) -> int:
        """扫描到期提醒：为每条生成/去重 inbox item，记录 last_fired_at。

        不改 reminder 状态/next_fire_at（由用户 snooze/done 处理）。返回触发的条数。
        """
        now = now or utcnow()
        due = await self.repo.list_due(now)
        fired = 0
        for r in due:
            await self._ensure_inbox_item(r)
            if r.last_fired_at is None:
                await self.repo.update(r.id, last_fired_at=now)
            fired += 1
        if fired:
            logger.info("reminder tick fired", count=fired)
        return fired

    async def _ensure_inbox_item(self, r: Reminder) -> None:
        """为到期提醒确保存在一个 open inbox item（同来源已有则跳过，避免重复）。"""
        existing = await self.inbox.find_open_by_source("reminder", r.id)
        if existing:
            return
        await self.inbox.create(
            title=r.title,
            item_type="reminder",
            body_md=r.body_md,
            due_at=r.due_at,
            source_type="reminder",
            source_id=r.id,
        )


async def reminder_tick_loop() -> None:
    """后台轻量轮询：每 reminder_tick_seconds 扫描到期提醒（reminders_enabled 关闭则跳过）。

    **先 sleep 再 tick**：确保首次 tick 晚于启动后一个周期，避免与测试断言竞态
    （测试用 POST /reminders/tick 手动触发，不依赖此循环）。
    """
    while True:
        sleep_secs = 60
        try:
            async with async_session_factory() as session:
                settings = SettingsService(session)
                tick_secs = int(await settings.get("reminder_tick_seconds") or 60)
                sleep_secs = max(15, tick_secs)
        except Exception as e:  # noqa: BLE001
            logger.warning("reminder tick 读取设置失败", error=str(e))
        await asyncio.sleep(sleep_secs)
        try:
            async with async_session_factory() as session:
                settings = SettingsService(session)
                enabled = (await settings.get("reminders_enabled")).lower() == "true"
                if enabled:
                    await ReminderService(session).tick()
        except Exception as e:  # noqa: BLE001
            logger.warning("reminder tick 失败", error=str(e))
