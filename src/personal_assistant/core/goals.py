"""Goal workspace service for phase 6.

The service keeps goal operations small and deterministic: repository writes are
still handled by the existing repos, while this layer composes goal detail,
check-ins, links, task drafts, and goal briefings.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Briefing, GoalCheckin, GoalLink, PersonalGoal
from .repo_briefings import BriefingRepository
from .repo_goals import (
    GoalCheckinRepository,
    GoalLinkRepository,
    PersonalGoalRepository,
)
from .tasks import AgentTaskService
from .timeutil import utcnow


class GoalNotFound(Exception):
    pass


class GoalService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.goals = PersonalGoalRepository(db)
        self.links = GoalLinkRepository(db)
        self.checkins = GoalCheckinRepository(db)
        self.briefings = BriefingRepository(db)

    async def create(
        self,
        *,
        title: str,
        description: str | None = None,
        domain: str = "custom",
        status: str = "active",
        priority: str = "normal",
        start_date: date | None = None,
        target_date: date | None = None,
        success_criteria_md: str | None = None,
    ) -> PersonalGoal:
        return await self.goals.create(
            title=title,
            description=description,
            domain=domain,
            status=status,
            priority=priority,
            start_date=start_date,
            target_date=target_date,
            success_criteria_md=success_criteria_md,
        )

    async def get(self, goal_id: int) -> PersonalGoal:
        goal = await self.goals.get(goal_id)
        if goal is None:
            raise GoalNotFound(f"Goal not found: {goal_id}")
        return goal

    async def list(
        self,
        *,
        status: str | None = None,
        domain: str | None = None,
        limit: int = 200,
    ) -> list[PersonalGoal]:
        return await self.goals.list(status=status, domain=domain, limit=limit)

    async def update(
        self,
        goal_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        domain: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        start_date: date | None = None,
        target_date: date | None = None,
        success_criteria_md: str | None = None,
    ) -> PersonalGoal:
        await self.get(goal_id)
        await self.goals.update(
            goal_id,
            title=title,
            description=description,
            domain=domain,
            status=status,
            priority=priority,
            start_date=start_date,
            target_date=target_date,
            success_criteria_md=success_criteria_md,
        )
        fresh = await self.goals.get_fresh(goal_id)
        if fresh is None:  # pragma: no cover - guarded by get()
            raise GoalNotFound(f"Goal not found: {goal_id}")
        return fresh

    async def add_link(
        self,
        goal_id: int,
        *,
        target_type: str,
        target_id: int,
        relation: str = "supports",
    ) -> GoalLink:
        await self.get(goal_id)
        link = await self.links.add(
            goal_id=goal_id,
            target_type=target_type,
            target_id=target_id,
            relation=relation,
        )
        if link is None:
            existing = await self.links.get_by_target(
                goal_id, target_type, target_id, relation
            )
            if existing is None:  # pragma: no cover
                raise GoalNotFound(f"Goal link not found: {goal_id}")
            return existing
        return link

    async def add_checkin(
        self,
        goal_id: int,
        *,
        checkin_date: date | None = None,
        progress_note_md: str | None = None,
        confidence: float | None = None,
        blockers_json: list | None = None,
        next_actions_json: list | None = None,
    ) -> GoalCheckin:
        await self.get(goal_id)
        return await self.checkins.create(
            goal_id=goal_id,
            checkin_date=checkin_date,
            progress_note_md=progress_note_md,
            confidence=confidence,
            blockers_json=blockers_json,
            next_actions_json=next_actions_json,
        )

    async def detail(self, goal_id: int) -> dict:
        goal = await self.get(goal_id)
        return {
            "goal": goal,
            "links": await self.links.list_by_goal(goal_id),
            "checkins": await self.checkins.list_by_goal(goal_id),
        }

    async def create_task_draft(self, goal_id: int) -> int:
        goal = await self.get(goal_id)
        task = await AgentTaskService(self.db).create_draft(
            title=f"Goal: {goal.title}",
            goal=goal.description or goal.success_criteria_md or goal.title,
            source_type="personal_goal",
            source_id=goal.id,
        )
        await self.add_link(
            goal_id,
            target_type="agent_task",
            target_id=task.id,
            relation="supports",
        )
        return task.id

    async def create_briefing(self, goal_id: int) -> Briefing:
        detail = await self.detail(goal_id)
        goal: PersonalGoal = detail["goal"]
        links: list[GoalLink] = detail["links"]
        checkins: list[GoalCheckin] = detail["checkins"]
        lines = [
            f"# {goal.title}",
            "",
            f"- Status: {goal.status}",
            f"- Domain: {goal.domain}",
            f"- Priority: {goal.priority}",
        ]
        if goal.target_date:
            lines.append(f"- Target date: {goal.target_date.isoformat()}")
        if goal.description:
            lines.extend(["", "## Context", goal.description])
        if goal.success_criteria_md:
            lines.extend(["", "## Success Criteria", goal.success_criteria_md])
        lines.extend(["", "## Recent Check-ins"])
        if checkins:
            for c in checkins[:5]:
                note = c.progress_note_md or "(no note)"
                lines.append(f"- {c.checkin_date.isoformat()}: {note}")
                if c.next_actions_json:
                    actions = ", ".join(str(x) for x in c.next_actions_json[:5])
                    lines.append(f"  Next: {actions}")
        else:
            lines.append("- No check-ins yet.")
        lines.extend(["", "## Links"])
        if links:
            for link in links:
                lines.append(
                    f"- {link.relation}: {link.target_type} #{link.target_id}"
                )
        else:
            lines.append("- No linked work yet.")
        sources = [{"type": "personal_goal", "id": goal.id}]
        sources += [
            {
                "type": "goal_link",
                "id": link.id,
                "target_type": link.target_type,
                "target_id": link.target_id,
            }
            for link in links[:20]
        ]
        sources += [{"type": "goal_checkin", "id": c.id} for c in checkins[:20]]
        return await self.briefings.create(
            kind="goal",
            title=f"Goal briefing: {goal.title}",
            body_md="\n".join(lines),
            sources_json=sources,
        )

    async def weekly_checkin_candidates(self) -> list[dict]:
        today = utcnow().date()
        active = await self.goals.list_active()
        rows: list[dict] = []
        for goal in active:
            checkins = await self.checkins.list_by_goal(goal.id, limit=1)
            latest = checkins[0] if checkins else None
            stale_days = (
                (today - latest.checkin_date).days if latest else None
            )
            if latest is None or stale_days is None or stale_days >= 7:
                rows.append(
                    {
                        "goal_id": goal.id,
                        "title": goal.title,
                        "last_checkin_date": latest.checkin_date.isoformat()
                        if latest
                        else None,
                        "stale_days": stale_days,
                    }
                )
        return rows
