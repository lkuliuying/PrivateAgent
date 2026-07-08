"""目标系统异步仓储层（第六阶段 M1）。

照 core/repo_memories.py 模式：每仓储持 AsyncSession，方法内自带 commit；
仓储层不抛 HTTPException，缺失时返回 None。

三个仓储：
- PersonalGoalRepository：目标 CRUD + 按 status/domain 过滤 + 归档。
- GoalLinkRepository：目标关联对象（learning_topic/project/agent_task/collection），
  uk_goal_target 去重；同域 goal_id 不建 FK CASCADE，遵循「不自动级联删除用户数据」。
- GoalCheckinRepository：目标回顾（进度笔记/信心度/阻塞/下一步），供周回顾引用。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GoalCheckin, GoalLink, PersonalGoal
from .timeutil import utcnow


class PersonalGoalRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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
        goal = PersonalGoal(
            title=title,
            description=description,
            domain=domain,
            status=status,
            priority=priority,
            start_date=start_date,
            target_date=target_date,
            success_criteria_md=success_criteria_md,
        )
        self.db.add(goal)
        await self.db.commit()
        await self.db.refresh(goal)
        return goal

    async def get(self, goal_id: int) -> Optional[PersonalGoal]:
        return await self.db.get(PersonalGoal, goal_id)

    async def get_fresh(self, goal_id: int) -> Optional[PersonalGoal]:
        """强制从 DB 重新加载，避免 update 后身份映射返回过期对象。"""
        stmt = (
            select(PersonalGoal)
            .where(PersonalGoal.id == goal_id)
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        status: str | None = None,
        domain: str | None = None,
        limit: int = 200,
    ) -> list[PersonalGoal]:
        """目标列表，默认按 status/priority/创建时间排序。"""
        stmt = select(PersonalGoal)
        if status:
            stmt = stmt.where(PersonalGoal.status == status)
        if domain:
            stmt = stmt.where(PersonalGoal.domain == domain)
        stmt = stmt.order_by(
            PersonalGoal.status.asc(),
            PersonalGoal.priority.asc(),
            PersonalGoal.created_at.desc(),
        ).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self, limit: int = 200) -> list[PersonalGoal]:
        """今日中枢用：活跃目标（active），归档/完成不进待处理。"""
        return await self.list(status="active", limit=limit)

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
    ) -> None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if description is not None:
            values["description"] = description
        if domain is not None:
            values["domain"] = domain
        if status is not None:
            values["status"] = status
        if priority is not None:
            values["priority"] = priority
        if start_date is not None:
            values["start_date"] = start_date
        if target_date is not None:
            values["target_date"] = target_date
        if success_criteria_md is not None:
            values["success_criteria_md"] = success_criteria_md
        if not values:
            return
        await self.db.execute(
            update(PersonalGoal).where(PersonalGoal.id == goal_id).values(**values)
        )
        await self.db.commit()

    async def archive(self, goal_id: int) -> None:
        await self.update(goal_id, status="archived")

    async def delete(self, goal_id: int) -> None:
        """删除目标。链接/回顾为软引用不级联，由调用方决定是否一并清理。"""
        goal = await self.get(goal_id)
        if goal:
            await self.db.delete(goal)
            await self.db.commit()


class GoalLinkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(
        self,
        *,
        goal_id: int,
        target_type: str,
        target_id: int,
        relation: str = "supports",
    ) -> Optional[GoalLink]:
        """关联对象到目标。uk_goal_target 去重：已存在同 goal+target+relation 返回 None。"""
        existing = await self.get_by_target(goal_id, target_type, target_id, relation)
        if existing:
            return None
        link = GoalLink(
            goal_id=goal_id,
            target_type=target_type,
            target_id=target_id,
            relation=relation,
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        return link

    async def get(self, link_id: int) -> Optional[GoalLink]:
        return await self.db.get(GoalLink, link_id)

    async def get_by_target(
        self,
        goal_id: int,
        target_type: str,
        target_id: int,
        relation: str,
    ) -> Optional[GoalLink]:
        stmt = (
            select(GoalLink)
            .where(GoalLink.goal_id == goal_id)
            .where(GoalLink.target_type == target_type)
            .where(GoalLink.target_id == target_id)
            .where(GoalLink.relation == relation)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_goal(self, goal_id: int) -> list[GoalLink]:
        stmt = (
            select(GoalLink)
            .where(GoalLink.goal_id == goal_id)
            .order_by(GoalLink.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def remove(self, link_id: int) -> None:
        link = await self.get(link_id)
        if link:
            await self.db.delete(link)
            await self.db.commit()

    async def remove_by_goal(self, goal_id: int) -> None:
        """删除目标下全部链接（目标删除时显式清理用）。"""
        await self.db.execute(delete(GoalLink).where(GoalLink.goal_id == goal_id))
        await self.db.commit()


class GoalCheckinRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        goal_id: int,
        checkin_date: date | None = None,
        progress_note_md: str | None = None,
        confidence: float | None = None,
        blockers_json: list | None = None,
        next_actions_json: list | None = None,
    ) -> GoalCheckin:
        checkin = GoalCheckin(
            goal_id=goal_id,
            checkin_date=checkin_date or utcnow().date(),
            progress_note_md=progress_note_md,
            confidence=confidence,
            blockers_json=blockers_json,
            next_actions_json=next_actions_json,
        )
        self.db.add(checkin)
        await self.db.commit()
        await self.db.refresh(checkin)
        return checkin

    async def get(self, checkin_id: int) -> Optional[GoalCheckin]:
        return await self.db.get(GoalCheckin, checkin_id)

    async def list_by_goal(self, goal_id: int, limit: int = 100) -> list[GoalCheckin]:
        stmt = (
            select(GoalCheckin)
            .where(GoalCheckin.goal_id == goal_id)
            .order_by(GoalCheckin.checkin_date.desc(), GoalCheckin.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
