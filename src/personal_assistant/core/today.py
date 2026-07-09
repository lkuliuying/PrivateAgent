"""今日中枢聚合服务（第六阶段 M1 + 第七阶段 M1 真实数据化）。

把分散在各模块的「待处理事项」聚合成一个快照，供今日入口一屏看清。
**零 UI 依赖**：只依赖 core 仓储与服务，不 import FastAPI / Vue，可被任意 async 调用方复用。

聚合来源（对齐 docs/phase6-requirements.md §5.1 + docs/phase7-requirements.md §5.1）：
- 到期学习复习：LearningCardRepository.list_due（due_at 为空或 <= now）。
- 待关注 Agent 任务：AgentTaskRepository.list_by_status（待审批 + 失败 + 暂停）。
- 失败活动：ActivityService.list(status="failed")（文档导入/索引/工具失败）。
- draft 记忆候选：MemoryRepository.list(status="draft")。
- 到期提醒：ReminderRepository.list_due（M3 tick 才会真正生成到期项；M1 表已就绪）。
- 未处理收件箱：InboxRepository.list_open（open/snoozed）。
- 备份状态：BackupService.list（最近备份时间）。
- 第七阶段新增：最近目标 check-in / 最近简报 / 最近文档 / 最近会话 / 维护健康摘要。
- 第七阶段筛选：type / priority / time / status（仅过滤展示列表，summary 计数始终为真实全量）。

输出为轻量 dict：每条只含展示与跳转来源所需字段（source_type/source_id），
不携带大段原文（phase6 §6）。空数据返回空列表与零计数，不报错。

注意：PrivacyService.maintenance_health_report 内部会调用本服务 snapshot()，
故本服务 **不得** 反向调用 maintenance_health_report，否则无限递归；
维护摘要在此直接计算（backup + failed_activities + draft_memories + orphan_evidence）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .activities import ActivityService
from .backup import BackupService
from .models import (
    Activity,
    AgentEvidence,
    AgentTask,
    Briefing,
    ChatSession,
    Document,
    GoalCheckin,
    InboxItem,
    LearningCard,
    MemoryItem,
    PersonalGoal,
    Reminder,
)
from .repo_inbox import InboxRepository
from .repo_learning import LearningCardRepository
from .repo_memories import MemoryRepository
from .repo_reminders import ReminderRepository
from .repo_tasks import AgentTaskRepository
from .timeutil import utcnow

# 今日中枢「待关注」任务状态：计划待审批 + 步骤待审批 + 暂停 + 失败。
# （requirements §5.1 列 waiting_approval/failed/paused；plan_draft/plan_approved
#  为第四阶段 M5 新增的「计划待审批」状态，同样需要用户处理，故一并纳入。）
ATTENTION_TASK_STATUSES: list[str] = [
    "plan_draft",
    "plan_approved",
    "waiting_approval",
    "paused",
    "failed",
]

_TRUNCATE = 200

# 第七阶段筛选：type -> 展示列表键。type 过滤时只保留对应列表，其余置空。
TYPE_SECTION: dict[str, str] = {
    "learning": "due_cards",
    "task": "attention_tasks",
    "doc": "recent_docs",
    "memory": "draft_memories",
    "reminder": "due_reminders",
    "goal": "recent_checkins",
    "inbox": "open_inbox",
    "system": "failed_activities",
}

# status 筛选 -> reminder 状态映射（reminder 用 active/snoozed/done/cancelled）。
REMINDER_STATUS_MAP: dict[str, str | None] = {
    "open": "active",
    "snoozed": "snoozed",
    "done": "done",
    "ignored": None,
}


@dataclass
class TodayFilters:
    """今日页筛选（第七阶段 §5.1）。None 表示不过滤该维度。"""

    type: str | None = None  # learning/task/doc/memory/reminder/goal/inbox/system
    priority: str | None = None  # urgent/high/normal/low（仅 inbox 有 priority）
    time: str | None = None  # today/overdue/this-week/future（按 due_at）
    status: str | None = None  # open/snoozed/done/ignored（inbox + reminder）


def _trunc(text: str | None, limit: int = _TRUNCATE) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _time_match(iso_due: str | None, window: str, now: datetime) -> bool:
    """due_at（ISO 字符串）是否落入时间窗口。无 due_at 不匹配任何窗口。"""
    if not iso_due:
        return False
    try:
        due = datetime.fromisoformat(iso_due)
    except ValueError:
        return False
    if window == "today":
        return due.date() == now.date()
    if window == "overdue":
        return due < now
    if window == "this-week":
        return now <= due <= now + timedelta(days=7)
    if window == "future":
        return due > now
    return True


class TodayService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def snapshot(
        self,
        now: datetime | None = None,
        filters: TodayFilters | None = None,
    ) -> dict:
        """聚合今日快照。空数据库返回零计数与空列表，不报错。

        summary 计数始终为真实全量（不受 filters 影响）；展示列表受 filters 过滤。
        """
        now = now or utcnow()

        # 下列查询串行执行：SQLAlchemy async session 不支持同一 session 并发查询
        # （会报错/损坏），并发需独立 read pool（后续优化，见 scripts/measure_perf_baseline.py 基线）。
        cards = await LearningCardRepository(self.db).list_due(now)
        tasks = await AgentTaskRepository(self.db).list_by_status(
            ATTENTION_TASK_STATUSES
        )
        activities = await ActivityService(self.db).list(status="failed")
        memories = await MemoryRepository(self.db).list(status="draft")
        reminders = await ReminderRepository(self.db).list_due(now)
        inbox = await InboxRepository(self.db).list_open()
        backup = await BackupService(self.db).list()

        # 第七阶段新增：最近目标 check-in / 简报 / 文档 / 会话 / 维护摘要。
        recent_checkins = await self._recent_checkins()
        recent_briefings = await self._recent_briefings()
        recent_docs = await self._recent_docs()
        recent_sessions = await self._recent_sessions()
        orphan_evidence = await self._orphan_evidence_count()

        data = {
            "generated_at": now.isoformat(),
            "summary": {
                "due_cards": len(cards),
                "attention_tasks": len(tasks),
                "failed_activities": len(activities),
                "draft_memories": len(memories),
                "due_reminders": len(reminders),
                "open_inbox": len(inbox),
                "last_backup_at": backup.get("last_backup_at"),
            },
            "due_cards": [self._card_summary(c) for c in cards],
            "attention_tasks": [self._task_summary(t) for t in tasks],
            "failed_activities": [self._activity_summary(a) for a in activities],
            "draft_memories": [self._memory_summary(m) for m in memories],
            "due_reminders": [self._reminder_summary(r) for r in reminders],
            "open_inbox": [self._inbox_summary(i) for i in inbox],
            "backup": {
                "last_backup_at": backup.get("last_backup_at"),
                "count": len(backup.get("items") or []),
            },
            "recent_checkins": recent_checkins,
            "recent_briefings": recent_briefings,
            "recent_docs": recent_docs,
            "recent_sessions": recent_sessions,
            "maintenance": {
                "last_backup_at": backup.get("last_backup_at"),
                "backup_count": len(backup.get("items") or []),
                "failed_activities": len(activities),
                "draft_memories": len(memories),
                "orphan_evidence": orphan_evidence,
            },
        }

        if filters:
            data = self._apply_filters(data, filters, now)
        return data

    # ---- 第七阶段新增聚合 ----

    async def _recent_checkins(self, limit: int = 5) -> list[dict]:
        """最近目标 check-in（带目标标题，软引用目标可能已删 -> LEFT JOIN）。"""
        stmt = (
            select(GoalCheckin, PersonalGoal.title)
            .join(
                PersonalGoal,
                PersonalGoal.id == GoalCheckin.goal_id,
                isouter=True,
            )
            .order_by(GoalCheckin.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            {
                "id": c.id,
                "goal_id": c.goal_id,
                "goal_title": title or f"目标 #{c.goal_id}",
                "checkin_date": c.checkin_date.isoformat() if c.checkin_date else None,
                "progress_note_md": _trunc(c.progress_note_md, 120),
                "confidence": c.confidence,
                "source_type": "goal_checkin",
                "source_id": c.id,
            }
            for c, title in rows
        ]

    async def _recent_briefings(self, limit: int = 5) -> list[dict]:
        stmt = (
            select(Briefing)
            .order_by(Briefing.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "id": b.id,
                "kind": b.kind,
                "title": b.title,
                "created_at": _iso(b.created_at),
                "source_type": "briefing",
                "source_id": b.id,
            }
            for b in result.scalars().all()
        ]

    async def _recent_docs(self, limit: int = 5) -> list[dict]:
        stmt = (
            select(Document)
            .order_by(Document.updated_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "id": d.id,
                "name": d.name,
                "status": d.status,
                "doc_type": d.doc_type,
                "updated_at": _iso(d.updated_at),
                "source_type": "document",
                "source_id": d.id,
            }
            for d in result.scalars().all()
        ]

    async def _recent_sessions(self, limit: int = 5) -> list[dict]:
        stmt = (
            select(ChatSession)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "id": s.id,
                "title": s.title,
                "updated_at": _iso(s.updated_at),
                "source_type": "chat_session",
                "source_id": s.id,
            }
            for s in result.scalars().all()
        ]

    async def _orphan_evidence_count(self) -> int:
        """孤儿证据：step_id 为空（所属步骤被 SET NULL 删除）。"""
        stmt = select(func.count(AgentEvidence.id)).where(
            AgentEvidence.step_id.is_(None)
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    # ---- 筛选 ----

    @staticmethod
    def _apply_filters(data: dict, f: TodayFilters, now: datetime) -> dict:
        """过滤展示列表。summary 计数不变。"""
        list_keys = [
            "due_cards",
            "attention_tasks",
            "failed_activities",
            "draft_memories",
            "due_reminders",
            "open_inbox",
            "recent_checkins",
            "recent_briefings",
            "recent_docs",
            "recent_sessions",
        ]
        # type：只保留对应列表，其余置空。
        if f.type:
            keep = TYPE_SECTION.get(f.type)
            for k in list_keys:
                if k != keep:
                    data[k] = []
        # priority：仅 inbox 有 priority。
        if f.priority:
            data["open_inbox"] = [
                i for i in data["open_inbox"] if i.get("priority") == f.priority
            ]
        # status：inbox + reminder。
        if f.status:
            data["open_inbox"] = [
                i for i in data["open_inbox"] if i.get("status") == f.status
            ]
            rem_status = REMINDER_STATUS_MAP.get(f.status)
            if rem_status:
                data["due_reminders"] = [
                    r for r in data["due_reminders"] if r.get("status") == rem_status
                ]
            else:
                data["due_reminders"] = []
        # time：cards + reminders + inbox（按 due_at）。
        if f.time:
            data["due_cards"] = [
                c for c in data["due_cards"] if _time_match(c.get("due_at"), f.time, now)
            ]
            data["due_reminders"] = [
                r
                for r in data["due_reminders"]
                if _time_match(r.get("due_at"), f.time, now)
            ]
            data["open_inbox"] = [
                i for i in data["open_inbox"] if _time_match(i.get("due_at"), f.time, now)
            ]
        return data

    # ---- 单条摘要：轻量 dict，含跳转来源 ----

    @staticmethod
    def _card_summary(c: LearningCard) -> dict:
        return {
            "id": c.id,
            "topic_id": c.topic_id,
            "front": _trunc(c.front),
            "due_at": _iso(c.due_at),
            "source_type": "learning_card",
            "source_id": c.id,
        }

    @staticmethod
    def _task_summary(t: AgentTask) -> dict:
        return {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "source_type": "agent_task",
            "source_id": t.id,
        }

    @staticmethod
    def _activity_summary(a: Activity) -> dict:
        return {
            "id": a.id,
            "title": a.title,
            "kind": a.kind,
            "status": a.status,
            "ref_type": a.ref_type,
            "ref_id": a.ref_id,
            "error_message": _trunc(a.error_message),
            "source_type": "activity",
            "source_id": a.id,
        }

    @staticmethod
    def _memory_summary(m: MemoryItem) -> dict:
        return {
            "id": m.id,
            "title": m.title,
            "kind": m.kind,
            "summary": _trunc(m.summary),
            "source_type": "memory",
            "source_id": m.id,
        }

    @staticmethod
    def _reminder_summary(r: Reminder) -> dict:
        return {
            "id": r.id,
            "title": r.title,
            "due_at": _iso(r.due_at),
            "next_fire_at": _iso(r.next_fire_at),
            "recurring": r.recurrence_rule is not None,
            "status": r.status,
            "source_type": "reminder",
            "source_id": r.id,
        }

    @staticmethod
    def _inbox_summary(i: InboxItem) -> dict:
        return {
            "id": i.id,
            "title": i.title,
            "item_type": i.item_type,
            "status": i.status,
            "priority": i.priority,
            "due_at": _iso(i.due_at),
            "source_type": "inbox",
            "source_id": i.id,
            "origin_source_type": i.source_type,
            "origin_source_id": i.source_id,
        }
