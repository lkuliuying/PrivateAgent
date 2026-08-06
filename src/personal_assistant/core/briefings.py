"""Briefing generation service for phase 6."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .goals import GoalService
from .models import Briefing
from .repo_briefings import BriefingRepository
from .tasks import AgentTaskService
from .timeutil import utcnow
from .today import TodayService


class BriefingNotFound(Exception):
    pass


class BriefingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BriefingRepository(db)

    async def get(self, briefing_id: int) -> Briefing:
        briefing = await self.repo.get(briefing_id)
        if briefing is None:
            raise BriefingNotFound(f"Briefing not found: {briefing_id}")
        return briefing

    async def list(self, *, kind: str | None = None, limit: int = 50) -> list[Briefing]:
        return await self.repo.list(kind=kind, limit=limit)

    async def create_today_briefing(self) -> Briefing:
        snap = await TodayService(self.db).snapshot()
        sm = snap["summary"]
        title = f"Today briefing {utcnow().date().isoformat()}"
        lines = [
            f"# {title}",
            "",
            "## Attention",
            f"- Due cards: {sm['due_cards']}",
            f"- Attention tasks: {sm['attention_tasks']}",
            f"- Failed activities: {sm['failed_activities']}",
            f"- Draft memories: {sm['draft_memories']}",
            f"- Due reminders: {sm['due_reminders']}",
            f"- Open inbox: {sm['open_inbox']}",
        ]
        sections = [
            ("due_cards", "Due Cards"),
            ("attention_tasks", "Attention Tasks"),
            ("failed_activities", "Failed Activities"),
            ("draft_memories", "Draft Memories"),
            ("due_reminders", "Due Reminders"),
            ("open_inbox", "Inbox"),
        ]
        sources: list[dict] = []
        for key, heading in sections:
            rows = snap.get(key) or []
            lines.extend(["", f"## {heading}"])
            if not rows:
                lines.append("- None")
                continue
            for row in rows[:10]:
                label = row.get("title") or row.get("front") or f"#{row.get('id')}"
                lines.append(f"- {label}")
                if row.get("source_type") and row.get("source_id") is not None:
                    sources.append(
                        {
                            "type": row["source_type"],
                            "id": row["source_id"],
                        }
                    )
        last_backup = snap["backup"].get("last_backup_at")
        lines.extend(
            [
                "",
                "## Maintenance",
                f"- Last backup: {last_backup or 'none'}",
                f"- Backup packages: {snap['backup'].get('count', 0)}",
            ]
        )
        return await self.repo.create(
            kind="today",
            title=title,
            body_md="\n".join(lines),
            sources_json=sources[:100],
        )

    async def create_weekly_briefing(self) -> Briefing:
        snap = await TodayService(self.db).snapshot()
        goal_candidates = await GoalService(self.db).weekly_checkin_candidates()
        title = f"Weekly review {utcnow().date().isoformat()}"
        sm = snap["summary"]
        lines = [
            f"# {title}",
            "",
            "## This Week's Open Loops",
            f"- Attention tasks: {sm['attention_tasks']}",
            f"- Failed activities: {sm['failed_activities']}",
            f"- Draft memories: {sm['draft_memories']}",
            f"- Open inbox: {sm['open_inbox']}",
            "",
            "## Goal Check-ins",
        ]
        sources: list[dict] = []
        if goal_candidates:
            for item in goal_candidates[:20]:
                lines.append(
                    f"- {item['title']} (last check-in: {item['last_checkin_date'] or 'never'})"
                )
                sources.append({"type": "personal_goal", "id": item["goal_id"]})
        else:
            lines.append("- No stale active goals.")
        lines.extend(["", "## Suggested Next Steps"])
        if sm["open_inbox"]:
            lines.append("- Triage open inbox items before starting new work.")
        if sm["failed_activities"]:
            lines.append("- Review failed activities and retry or archive them.")
        if sm["draft_memories"]:
            lines.append("- Confirm or archive draft memories.")
        if not any([sm["open_inbox"], sm["failed_activities"], sm["draft_memories"]]):
            lines.append("- Keep current routines; no urgent maintenance surfaced.")
        return await self.repo.create(
            kind="weekly",
            title=title,
            body_md="\n".join(lines),
            sources_json=sources[:100],
        )

    async def to_task(self, briefing_id: int) -> int:
        briefing = await self.get(briefing_id)
        task = await AgentTaskService(self.db).create_draft(
            title=f"Follow up: {briefing.title}",
            goal=briefing.body_md[:4000],
            source_type="briefing",
            source_id=briefing.id,
        )
        return task.id
