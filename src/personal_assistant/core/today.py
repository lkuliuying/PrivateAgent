"""今日中枢聚合服务（第六阶段 M1）。

把分散在各模块的「待处理事项」聚合成一个快照，供今日入口一屏看清。
**零 UI 依赖**：只依赖 core 仓储与服务，不 import FastAPI / Vue，可被任意 async 调用方复用。

聚合来源（对齐 docs/phase6-requirements.md §5.1）：
- 到期学习复习：LearningCardRepository.list_due（due_at 为空或 <= now）。
- 待关注 Agent 任务：AgentTaskRepository.list_by_status（待审批 + 失败 + 暂停）。
- 失败活动：ActivityService.list(status="failed")（文档导入/索引/工具失败）。
- draft 记忆候选：MemoryRepository.list(status="draft")。
- 到期提醒：ReminderRepository.list_due（M3 tick 才会真正生成到期项；M1 表已就绪）。
- 未处理收件箱：InboxRepository.list_open（open/snoozed）。
- 备份状态：BackupService.list（最近备份时间）。

输出为轻量 dict：每条只含展示与跳转来源所需字段（source_type/source_id），
不携带大段原文（phase6 §6）。空数据返回空列表与零计数，不报错。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .activities import ActivityService
from .backup import BackupService
from .models import (
    Activity,
    AgentTask,
    InboxItem,
    LearningCard,
    MemoryItem,
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


def _trunc(text: str | None, limit: int = _TRUNCATE) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class TodayService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def snapshot(self, now: datetime | None = None) -> dict:
        """聚合今日快照。空数据库返回零计数与空列表，不报错。"""
        now = now or utcnow()

        cards = await LearningCardRepository(self.db).list_due(now)
        tasks = await AgentTaskRepository(self.db).list_by_status(
            ATTENTION_TASK_STATUSES
        )
        activities = await ActivityService(self.db).list(status="failed")
        memories = await MemoryRepository(self.db).list(status="draft")
        reminders = await ReminderRepository(self.db).list_due(now)
        inbox = await InboxRepository(self.db).list_open()
        backup = await BackupService(self.db).list()

        return {
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
        }

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
