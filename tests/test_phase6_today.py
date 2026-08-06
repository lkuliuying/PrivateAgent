"""第六阶段 M1 测试：今日聚合服务 + 新增仓储。

覆盖（对齐 docs/phase6-plan.md §5 M1）：
- TodayService.snapshot 空数据不报错、结构完整、summary 计数与列表长度一致。
- TodayService.snapshot 有数据时各来源项按 id 出现。
- 五个新仓储基本 CRUD / 状态流转：inbox / reminders / goals / briefings / privacy。

LLM 不参与（M1 无简报生成）。共享 MySQL DB，用 cleanup fixture 追踪并删除本测试
创建的 ORM 对象（逆序，FK 子先于父），避免跨测试污染。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from personal_assistant.core.models import (
    Activity,
    AgentTask,
    LearningCard,
    LearningTopic,
    MemoryItem,
)
from personal_assistant.core.repo_briefings import BriefingRepository
from personal_assistant.core.repo_goals import (
    GoalCheckinRepository,
    GoalLinkRepository,
    PersonalGoalRepository,
)
from personal_assistant.core.repo_inbox import InboxRepository
from personal_assistant.core.repo_privacy import ProviderCallAuditRepository
from personal_assistant.core.repo_reminders import ReminderRepository
from personal_assistant.core.timeutil import utcnow
from personal_assistant.core.today import TodayService

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


# ============ 今日聚合 ============


@pytest.mark.asyncio
async def test_today_snapshot_empty_safe(db):
    """空/最小数据下 snapshot 不报错、结构完整、summary 计数与列表长度一致。"""
    snap = await TodayService(db).snapshot()
    assert "generated_at" in snap
    summary = snap["summary"]
    for key in (
        "due_cards",
        "attention_tasks",
        "failed_activities",
        "draft_memories",
        "due_reminders",
        "open_inbox",
        "last_backup_at",
    ):
        assert key in summary
    # 内部一致性：每个 summary 计数 == 对应列表长度（不依赖共享 DB 是否为空）。
    assert summary["due_cards"] == len(snap["due_cards"])
    assert summary["attention_tasks"] == len(snap["attention_tasks"])
    assert summary["failed_activities"] == len(snap["failed_activities"])
    assert summary["draft_memories"] == len(snap["draft_memories"])
    assert summary["due_reminders"] == len(snap["due_reminders"])
    assert summary["open_inbox"] == len(snap["open_inbox"])
    assert "backup" in snap and "count" in snap["backup"]


@pytest.mark.asyncio
async def test_today_snapshot_with_data(db, cleanup):
    """各来源创建一条数据后，snapshot 按 id 出现对应项。"""
    now = utcnow()
    past = now - timedelta(hours=1)

    # 到期学习卡片（需先建主题，FK）
    topic = LearningTopic(title="今日测试主题")
    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    cleanup.append(topic)
    card = LearningCard(topic_id=topic.id, front="今日卡片问题", back="答案", due_at=past)
    db.add(card)
    await db.commit()
    await db.refresh(card)
    cleanup.append(card)

    # 待关注任务
    task = AgentTask(title="待审批任务", status="waiting_approval")
    db.add(task)
    await db.commit()
    await db.refresh(task)
    cleanup.append(task)

    # 失败活动
    activity = Activity(
        kind="document_import",
        title="导入失败：bad.pdf",
        status="failed",
        ref_type="document_import",
        ref_id=999,
        error_message="解析失败",
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    cleanup.append(activity)

    # draft 记忆候选
    memory = MemoryItem(
        kind="note",
        title="候选记忆",
        content_md="待确认内容",
        status="draft",
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    cleanup.append(memory)

    # 到期提醒
    reminder = await ReminderRepository(db).create(
        title="到期提醒", due_at=past, body_md="该复习了"
    )
    cleanup.append(reminder)

    # 未处理收件箱项
    inbox = await InboxRepository(db).create(
        title="收件箱待办", item_type="todo"
    )
    cleanup.append(inbox)

    snap = await TodayService(db).snapshot()
    assert any(c["id"] == card.id for c in snap["due_cards"])
    assert any(t["id"] == task.id for t in snap["attention_tasks"])
    assert any(a["id"] == activity.id for a in snap["failed_activities"])
    assert any(m["id"] == memory.id for m in snap["draft_memories"])
    assert any(r["id"] == reminder.id for r in snap["due_reminders"])
    assert any(i["id"] == inbox.id for i in snap["open_inbox"])

    # 跳转来源字段齐备
    assert snap["due_cards"][0]["source_type"] == "learning_card"
    assert snap["attention_tasks"][0]["source_type"] == "agent_task"
    assert snap["open_inbox"][0]["source_type"] == "inbox"


# ============ 收件箱仓储 ============


@pytest.mark.asyncio
async def test_inbox_repo_crud_and_status(db, cleanup):
    repo = InboxRepository(db)
    item = await repo.create(
        title="整理 MySQL 笔记",
        item_type="todo",
        priority="high",
        source_type="chat_message",
        source_id=42,
    )
    cleanup.append(item)
    assert item.status == "open"
    assert item.priority == "high"

    fetched = await repo.get(item.id)
    assert fetched is not None and fetched.title == "整理 MySQL 笔记"

    # 状态流转：完成补 handled_at
    await repo.mark(item.id, "done")
    fresh = await repo.get_fresh(item.id)
    assert fresh.status == "done"
    assert fresh.handled_at is not None

    # 过滤
    listed = await repo.list(status="done")
    assert any(i.id == item.id for i in listed)
    open_items = await repo.list_open()
    assert all(i.id != item.id for i in open_items)  # done 不在 open 列表


# ============ 提醒仓储 ============


@pytest.mark.asyncio
async def test_reminders_repo_due_snooze_done(db, cleanup):
    repo = ReminderRepository(db)
    # 对齐到整秒：MySQL DATETIME(3) 毫秒精度，避免微秒被截断后 == 比较失败。
    now = utcnow().replace(microsecond=0)
    past = now - timedelta(minutes=30)
    future = now + timedelta(hours=2)

    # 到期提醒
    due = await repo.create(title="到期提醒", due_at=past)
    cleanup.append(due)
    assert due.next_fire_at == past  # create 时 next_fire_at = due_at

    # 未到期提醒
    not_due = await repo.create(title="未来提醒", due_at=future)
    cleanup.append(not_due)

    due_list = await repo.list_due(now)
    due_ids = {r.id for r in due_list}
    assert due.id in due_ids
    assert not_due.id not in due_ids

    # snooze：next_fire_at 延后，due_at 保留溯源
    await repo.snooze(due.id, future)
    fresh = await repo.get_fresh(due.id)
    assert fresh.status == "snoozed"
    assert fresh.next_fire_at == future
    assert fresh.due_at == past  # 原定时间不变
    # snooze 到未来后不再到期
    assert all(r.id != due.id for r in await repo.list_due(now))

    # mark_done：status=done，last_fired_at 写入
    await repo.mark_done(due.id)
    done = await repo.get_fresh(due.id)
    assert done.status == "done"
    assert done.last_fired_at is not None


# ============ 目标仓储 ============


@pytest.mark.asyncio
async def test_goals_repo_link_checkin(db, cleanup):
    goal_repo = PersonalGoalRepository(db)
    link_repo = GoalLinkRepository(db)
    checkin_repo = GoalCheckinRepository(db)

    goal = await goal_repo.create(
        title="掌握 MySQL 索引",
        domain="learning",
        priority="high",
        target_date=utcnow().date() + timedelta(days=30),
    )
    cleanup.append(goal)
    assert goal.status == "active"

    # 关联学习主题与任务（软引用）
    link1 = await link_repo.add(
        goal_id=goal.id, target_type="learning_topic", target_id=101, relation="supports"
    )
    assert link1 is not None
    cleanup.append(link1)
    link2 = await link_repo.add(
        goal_id=goal.id, target_type="agent_task", target_id=202, relation="evidence"
    )
    cleanup.append(link2)

    # uk 去重：同 goal+target+relation 再加返回 None
    dup = await link_repo.add(
        goal_id=goal.id, target_type="learning_topic", target_id=101, relation="supports"
    )
    assert dup is None

    links = await link_repo.list_by_goal(goal.id)
    assert len(links) == 2

    # check-in
    checkin = await checkin_repo.create(
        goal_id=goal.id,
        progress_note_md="本周学了 B+ 树",
        confidence=0.6,
        next_actions_json=["复习覆盖索引", "做 3 道题"],
    )
    cleanup.append(checkin)
    checkins = await checkin_repo.list_by_goal(goal.id)
    assert len(checkins) == 1
    assert checkins[0].confidence == 0.6

    # 归档
    await goal_repo.archive(goal.id)
    archived = await goal_repo.get_fresh(goal.id)
    assert archived.status == "archived"
    # 归档目标不进 list_active
    assert all(g.id != goal.id for g in await goal_repo.list_active())


# ============ 简报仓储 ============


@pytest.mark.asyncio
async def test_briefings_repo(db, cleanup):
    repo = BriefingRepository(db)
    b = await repo.create(
        kind="today",
        title="今日简报",
        body_md="## 重点\n- 复习 MySQL",
        sources_json=[{"type": "learning_card", "id": 1}],
    )
    cleanup.append(b)
    assert b.kind == "today"

    listed = await repo.list(kind="today")
    assert any(x.id == b.id for x in listed)
    fetched = await repo.get(b.id)
    assert fetched is not None
    assert fetched.sources_json == [{"type": "learning_card", "id": 1}]


# ============ 隐私审计仓储 ============


@pytest.mark.asyncio
async def test_privacy_repo_audit_finish(db, cleanup):
    repo = ProviderCallAuditRepository(db)
    audit = await repo.create(
        provider_type="openai",
        purpose="chat",
        model="gpt-4o-mini",
        remote=True,
        context_types_json=["chat_messages", "kb_chunks", "memories"],
        estimated_input_chars=1200,
        status="planned",
    )
    cleanup.append(audit)
    assert audit.remote is True
    assert audit.status == "planned"
    assert audit.finished_at is None

    # 远程过滤
    remote_list = await repo.list(remote=True)
    assert any(a.id == audit.id for a in remote_list)

    # 标记终态
    await repo.finish(
        audit.id, status="succeeded", estimated_output_chars=800
    )
    fresh = await repo.get(audit.id)
    assert fresh.status == "succeeded"
    assert fresh.finished_at is not None
    assert fresh.estimated_output_chars == 800

    # 不保存完整 prompt：审计字段不含 prompt 原文
    cols = {c.name for c in fresh.__table__.columns}
    assert "prompt" not in cols and "messages" not in cols
