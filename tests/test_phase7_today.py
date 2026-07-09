"""第七阶段 M1 测试：今日页真实数据化 + 筛选。

覆盖（对齐 docs/phase7-plan.md §M1 / docs/phase7-requirements.md §5.1）：
- snapshot 新增字段（recent_checkins/briefings/docs/sessions/maintenance）空数据为零/空。
- 有数据时 recent_* 返回真实来源（目标 check-in / 简报 / 文档 / 会话）。
- 筛选 type/priority/time/status 仅过滤展示列表，summary 计数始终为真实全量。
- GET /today 路由支持 query 筛选。
- 空数据不出现任何演示/固定内容（后端只返回真实数据）。

LLM 不参与。共享 MySQL DB，cleanup fixture 逆序删除本测试创建的 ORM 对象。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from personal_assistant.core.models import (
    Briefing,
    ChatSession,
    Document,
    LearningCard,
    LearningTopic,
    PersonalGoal,
)
from personal_assistant.core.repo_goals import GoalCheckinRepository, PersonalGoalRepository
from personal_assistant.core.repo_inbox import InboxRepository
from personal_assistant.core.repo_reminders import ReminderRepository
from personal_assistant.core.today import TodayFilters, TodayService
from personal_assistant.core.timeutil import utcnow


# ============ fixtures ============


@pytest.fixture
async def cleanup(db):
    """追踪并删除本测试创建的 ORM 对象（逆序：子先于父），避免共享 DB 污染。"""
    created: list = []
    yield created
    for obj in reversed(created):
        try:
            await db.delete(obj)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


# ============ 新增字段 / 空数据 ============


@pytest.mark.asyncio
async def test_today_phase7_new_fields_present_empty(db):
    """snapshot 含第七阶段新字段且为列表结构（共享 DB 可能有残留，不断言空）。"""
    snap = await TodayService(db).snapshot()
    for key in (
        "recent_checkins",
        "recent_briefings",
        "recent_docs",
        "recent_sessions",
        "maintenance",
    ):
        assert key in snap, f"缺少第七阶段字段 {key}"
    assert isinstance(snap["recent_checkins"], list)
    assert isinstance(snap["recent_briefings"], list)
    assert isinstance(snap["recent_docs"], list)
    assert isinstance(snap["recent_sessions"], list)
    m = snap["maintenance"]
    assert "failed_activities" in m
    assert "draft_memories" in m
    assert "orphan_evidence" in m
    assert "backup_count" in m


@pytest.mark.asyncio
async def test_today_phase7_no_demo_content(db):
    """后端快照不包含任何固定演示文案/文档名（只返回真实数据）。"""
    snap = await TodayService(db).snapshot()
    demo_names = {"PRD_智能笔记应用_v1.3.md", "用户反馈汇总_202505.md", "系统设计_存储模块.md"}
    for d in snap["recent_docs"]:
        assert d["name"] not in demo_names
    # 不存在固定日程字段
    assert "schedule" not in snap
    assert "insights" not in snap


# ============ recent_* 真实数据 ============


@pytest.mark.asyncio
async def test_today_phase7_recent_with_data(db, cleanup):
    """创建目标 check-in / 简报 / 文档 / 会话后，recent_* 返回真实来源。"""
    # 目标 + check-in
    goal = await PersonalGoalRepository(db).create(title="第七阶段目标", domain="custom")
    cleanup.append(goal)
    checkin = await GoalCheckinRepository(db).create(
        goal_id=goal.id, progress_note_md="推进 M1", confidence=0.7
    )
    cleanup.append(checkin)

    # 简报
    briefing = Briefing(kind="today", title="第七阶段今日简报", body_md="## M1")
    db.add(briefing)
    await db.commit()
    await db.refresh(briefing)
    cleanup.append(briefing)

    # 文档
    doc = Document(name="第七阶段设计文档.md", status="ready", doc_type="markdown")
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    cleanup.append(doc)

    # 会话
    session = ChatSession(title="第七阶段讨论")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    cleanup.append(session)

    snap = await TodayService(db).snapshot()
    assert any(c["id"] == checkin.id for c in snap["recent_checkins"])
    assert any(c["goal_title"] == "第七阶段目标" for c in snap["recent_checkins"])
    assert any(b["id"] == briefing.id for b in snap["recent_briefings"])
    assert any(d["id"] == doc.id for d in snap["recent_docs"])
    assert any(s["id"] == session.id for s in snap["recent_sessions"])

    # 跳转来源字段齐备
    assert snap["recent_checkins"][0]["source_type"] == "goal_checkin"
    assert snap["recent_briefings"][0]["source_type"] == "briefing"
    assert snap["recent_docs"][0]["source_type"] == "document"
    assert snap["recent_sessions"][0]["source_type"] == "chat_session"


@pytest.mark.asyncio
async def test_today_phase7_dangling_checkin_goal_title_fallback(db, cleanup):
    """checkin 的目标已删（软引用悬空）时，goal_title 回退为「目标 #id」。"""
    goal = await PersonalGoalRepository(db).create(title="临时目标")
    checkin = await GoalCheckinRepository(db).create(
        goal_id=goal.id, progress_note_md="临时回顾"
    )
    goal_id = goal.id
    # 删除目标（checkin 保留，goal_id 软引用悬空）
    await db.delete(goal)
    await db.commit()
    cleanup.append(checkin)

    snap = await TodayService(db).snapshot()
    found = [c for c in snap["recent_checkins"] if c["id"] == checkin.id]
    assert found, "悬空 checkin 仍应出现"
    assert found[0]["goal_title"] == f"目标 #{goal_id}"


# ============ 筛选 ============


@pytest.mark.asyncio
async def test_today_filter_type_scopes_sections(db, cleanup):
    """type 筛选只保留对应列表，其余置空；summary 计数不变。"""
    now = utcnow().replace(microsecond=0)
    past = now - timedelta(hours=1)

    # 到期提醒 + 未处理收件箱
    reminder = await ReminderRepository(db).create(title="到期提醒", due_at=past)
    cleanup.append(reminder)
    inbox = await InboxRepository(db).create(title="收件箱项", item_type="todo")
    cleanup.append(inbox)

    full = await TodayService(db).snapshot()
    assert len(full["due_reminders"]) >= 1
    assert len(full["open_inbox"]) >= 1
    full_rem_count = full["summary"]["due_reminders"]
    full_inbox_count = full["summary"]["open_inbox"]

    # type=reminder：只保留 due_reminders
    snap = await TodayService(db).snapshot(filters=TodayFilters(type="reminder"))
    assert len(snap["due_reminders"]) >= 1
    assert snap["open_inbox"] == []
    assert snap["recent_docs"] == []
    # summary 计数仍是真实全量
    assert snap["summary"]["due_reminders"] == full_rem_count
    assert snap["summary"]["open_inbox"] == full_inbox_count


@pytest.mark.asyncio
async def test_today_filter_priority_on_inbox(db, cleanup):
    """priority 筛选仅作用于 inbox（有 priority 字段）。"""
    urgent = await InboxRepository(db).create(
        title="紧急事项", item_type="todo", priority="urgent"
    )
    normal = await InboxRepository(db).create(
        title="普通事项", item_type="todo", priority="normal"
    )
    cleanup.append(urgent)
    cleanup.append(normal)

    snap = await TodayService(db).snapshot(filters=TodayFilters(priority="urgent"))
    inbox_ids = {i["id"] for i in snap["open_inbox"]}
    assert urgent.id in inbox_ids
    assert normal.id not in inbox_ids


@pytest.mark.asyncio
async def test_today_filter_status_on_inbox(db, cleanup):
    """status 筛选作用于 inbox 状态。"""
    open_item = await InboxRepository(db).create(title="待处理", item_type="todo")
    snoozed = await InboxRepository(db).create(title="已暂缓", item_type="todo")
    await InboxRepository(db).mark(snoozed.id, "snoozed")
    cleanup.append(open_item)
    cleanup.append(snoozed)

    snap = await TodayService(db).snapshot(filters=TodayFilters(status="snoozed"))
    inbox_ids = {i["id"] for i in snap["open_inbox"]}
    assert snoozed.id in inbox_ids
    assert open_item.id not in inbox_ids


@pytest.mark.asyncio
async def test_today_filter_time_on_reminders(db, cleanup):
    """time 筛选按 due_at 过滤到期提醒（overdue 保留，future 清空）。"""
    now = utcnow().replace(microsecond=0)
    past = now - timedelta(hours=2)
    overdue = await ReminderRepository(db).create(title="逾期提醒", due_at=past)
    cleanup.append(overdue)

    snap_overdue = await TodayService(db).snapshot(filters=TodayFilters(time="overdue"))
    assert any(r["id"] == overdue.id for r in snap_overdue["due_reminders"])

    snap_future = await TodayService(db).snapshot(filters=TodayFilters(time="future"))
    assert all(r["id"] != overdue.id for r in snap_future["due_reminders"])


# ============ 路由 ============


@pytest.mark.asyncio
async def test_today_route_returns_new_fields(client):
    """GET /today 返回第七阶段新字段。"""
    r = await client.get("/today")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "recent_checkins",
        "recent_briefings",
        "recent_docs",
        "recent_sessions",
        "maintenance",
    ):
        assert key in data


@pytest.mark.asyncio
async def test_today_route_with_type_filter(client, db, cleanup):
    """GET /today?type=reminder 仅返回到期提醒列表，其余列表为空。"""
    now = utcnow().replace(microsecond=0)
    past = now - timedelta(hours=1)
    reminder = await ReminderRepository(db).create(title="路由筛选提醒", due_at=past)
    cleanup.append(reminder)

    r = await client.get("/today", params={"type": "reminder"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["due_reminders"]) >= 1
    assert data["open_inbox"] == []
    assert data["recent_docs"] == []
