"""第六阶段 M3 测试：提醒服务 / tick / snooze / 重复规则 / 持久化。

覆盖（对齐 docs/phase6-plan.md §5 M3）：
- create：next_fire_at = due_at，status=active。
- snooze：next_fire_at 延后、due_at 保留、status=snoozed。
- mark_done：一次性 -> done；重复 -> active 且 next_fire_at > now。
- tick：到期提醒生成 open inbox item（来源去重），last_fired_at 写入，但不自动 done。
- POST /reminders/tick 手动触发；重启后状态不丢（重新查询）。
- compute_next_fire：none/daily/weekly/monthly。

共享 MySQL DB：用 db 按 id 清理 reminder/inbox，避免跨测试污染。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select

from personal_assistant.core.models import InboxItem, Reminder
from personal_assistant.core.reminders import compute_next_fire
from personal_assistant.core.timeutil import utcnow

# ============ fixtures ============


@pytest.fixture
async def cleanup(db):
    to_delete: list[tuple[type, int]] = []
    yield to_delete
    for model, oid in reversed(to_delete):
        try:
            await db.execute(delete(model).where(model.id == oid))
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


async def _create_reminder(client, cleanup, **overrides) -> dict:
    past = (utcnow() - timedelta(hours=1)).replace(microsecond=0).isoformat()
    payload = {"title": "复习 MySQL 索引", "due_at": past}
    payload.update(overrides)
    res = await client.post("/reminders", json=payload)
    assert res.status_code == 201, res.text
    r = res.json()
    cleanup.append((Reminder, r["id"]))
    return r


# ============ create / snooze / done ============


@pytest.mark.asyncio
async def test_reminder_create(client, cleanup):
    r = await _create_reminder(client, cleanup)
    assert r["status"] == "active"
    assert r["next_fire_at"] == r["due_at"]  # create 时 next_fire_at = due_at
    assert r["last_fired_at"] is None


@pytest.mark.asyncio
async def test_reminder_snooze(client, cleanup):
    r = await _create_reminder(client, cleanup)
    rid = r["id"]
    due_at = r["due_at"]

    res = await client.post(
        f"/reminders/{rid}/snooze", json={"minutes": 10}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "snoozed"
    assert body["due_at"] == due_at  # 原定时间保留溯源
    # next_fire_at 延后到 ~now+10min
    nf = datetime.fromisoformat(body["next_fire_at"].replace("Z", ""))
    assert nf > utcnow()


@pytest.mark.asyncio
async def test_reminder_done_one_time(client, cleanup):
    r = await _create_reminder(client, cleanup)
    res = await client.post(f"/reminders/{r['id']}/done")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "done"


@pytest.mark.asyncio
async def test_reminder_done_recurring_generates_next(client, cleanup):
    r = await _create_reminder(
        client,
        cleanup,
        recurrence_rule={"freq": "daily", "interval": 1},
    )
    res = await client.post(f"/reminders/{r['id']}/done")
    assert res.status_code == 200, res.text
    body = res.json()
    # 重复提醒保持 active，生成下次 next_fire_at（~明天）
    assert body["status"] == "active"
    nf = datetime.fromisoformat(body["next_fire_at"].replace("Z", ""))
    assert nf > utcnow() + timedelta(hours=20)


# ============ tick ============


@pytest.mark.asyncio
async def test_reminder_tick_creates_inbox_item(client, db, cleanup):
    r = await _create_reminder(client, cleanup)
    rid = r["id"]

    res = await client.post("/reminders/tick")
    assert res.status_code == 200, res.text
    assert res.json()["fired"] >= 1

    # 生成 open inbox item，来源指向 reminder
    row = (
        await db.execute(
            select(InboxItem)
            .where(InboxItem.source_type == "reminder")
            .where(InboxItem.source_id == rid)
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.status == "open"
    assert row.item_type == "reminder"
    cleanup.append((InboxItem, row.id))

    # reminder 未被自动完成（由用户处理），last_fired_at 已写
    rem = (
        await db.execute(select(Reminder).where(Reminder.id == rid))
    ).scalar_one()
    assert rem.status == "active"
    assert rem.last_fired_at is not None

    # 再次 tick 不重复生成 inbox item
    await client.post("/reminders/tick")
    cnt = (
        await db.execute(
            select(InboxItem)
            .where(InboxItem.source_type == "reminder")
            .where(InboxItem.source_id == rid)
        )
    ).scalars().all()
    assert len(cnt) == 1


@pytest.mark.asyncio
async def test_reminder_tick_skips_future(client, db, cleanup):
    future = (utcnow() + timedelta(days=2)).replace(microsecond=0).isoformat()
    r = await _create_reminder(client, cleanup, due_at=future)
    rid = r["id"]

    await client.post("/reminders/tick")
    row = (
        await db.execute(
            select(InboxItem)
            .where(InboxItem.source_type == "reminder")
            .where(InboxItem.source_id == rid)
        )
    ).scalar_one_or_none()
    assert row is None  # 未到期不生成 inbox


@pytest.mark.asyncio
async def test_reminder_persistence_across_restart(client, cleanup):
    """重启后提醒状态不丢：创建后重新查询仍存在且字段一致。"""
    r = await _create_reminder(
        client, cleanup, recurrence_rule={"freq": "weekly", "interval": 2}
    )
    # 模拟重启：重新 GET
    res = await client.get(f"/reminders/{r['id']}")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "复习 MySQL 索引"
    assert body["status"] == "active"
    assert body["recurrence_rule"] == {"freq": "weekly", "interval": 2}


# ============ compute_next_fire（纯函数）============


@pytest.mark.asyncio
async def test_compute_next_fire():
    now = datetime(2026, 1, 15, 10, 0, 0)
    assert compute_next_fire(None, now) is None
    assert compute_next_fire({"freq": "none", "interval": 1}, now) is None
    assert compute_next_fire({"freq": "daily", "interval": 1}, now) == now + timedelta(
        days=1
    )
    assert compute_next_fire(
        {"freq": "weekly", "interval": 2}, now
    ) == now + timedelta(weeks=2)
    # 月加：1/15 +1 月 = 2/15
    assert compute_next_fire({"freq": "monthly", "interval": 1}, now) == datetime(
        2026, 2, 15, 10, 0, 0
    )
    # 月末溢出：1/31 +1 月 = 2/28
    jan31 = datetime(2026, 1, 31, 9, 0, 0)
    assert compute_next_fire({"freq": "monthly", "interval": 1}, jan31) == datetime(
        2026, 2, 28, 9, 0, 0
    )
