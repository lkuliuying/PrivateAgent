"""学习系统异步仓储层：主题 / 节点 / 笔记 / 卡片 / 练习 / 答题记录 / 复习记录。

照 core/repo.py 模式：每仓储持 AsyncSession，方法内自带 commit。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    LearningCard,
    LearningNode,
    LearningNote,
    LearningQuiz,
    LearningQuizAttempt,
    LearningReview,
    LearningTopic,
)
from .timeutil import utcnow


class LearningTopicRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, *, title: str, goal: str | None = None, level: str | None = None,
        tags: list[str] | None = None,
    ) -> LearningTopic:
        t = LearningTopic(title=title, goal=goal, level=level, tags_json=tags)
        self.db.add(t)
        await self.db.commit()
        await self.db.refresh(t)
        return t

    async def get(self, topic_id: int) -> Optional[LearningTopic]:
        return await self.db.get(LearningTopic, topic_id)

    async def list(self) -> list[LearningTopic]:
        stmt = select(LearningTopic).order_by(
            LearningTopic.status.asc(), LearningTopic.created_at.desc()
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        topic_id: int,
        *,
        title: str | None = None,
        goal: str | None = None,
        level: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if goal is not None:
            values["goal"] = goal
        if level is not None:
            values["level"] = level
        if status is not None:
            values["status"] = status
        if tags is not None:
            values["tags_json"] = tags
        if not values:
            return
        await self.db.execute(
            update(LearningTopic).where(LearningTopic.id == topic_id).values(**values)
        )
        await self.db.commit()


class LearningNodeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_many(self, topic_id: int, nodes: list[dict]) -> list[LearningNode]:
        objs = [
            LearningNode(
                topic_id=topic_id,
                parent_id=n.get("parent_id"),
                title=n["title"],
                summary=n.get("summary"),
                order_index=n.get("order_index", i),
            )
            for i, n in enumerate(nodes)
        ]
        self.db.add_all(objs)
        await self.db.commit()
        for o in objs:
            await self.db.refresh(o)
        return objs

    async def list_by_topic(self, topic_id: int) -> list[LearningNode]:
        stmt = (
            select(LearningNode)
            .where(LearningTopic.id == LearningNode.topic_id)
            .where(LearningNode.topic_id == topic_id)
            .order_by(LearningNode.order_index.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, node_id: int) -> Optional[LearningNode]:
        return await self.db.get(LearningNode, node_id)

    async def update_mastery(self, node_id: int, mastery: str) -> None:
        await self.db.execute(
            update(LearningNode)
            .where(LearningNode.id == node_id)
            .values(mastery_level=mastery)
        )
        await self.db.commit()


class LearningNoteRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, *, topic_id: int | None, title: str, body_md: str,
        source_refs: list | None = None,
    ) -> LearningNote:
        n = LearningNote(
            topic_id=topic_id, title=title, body_md=body_md, source_refs_json=source_refs
        )
        self.db.add(n)
        await self.db.commit()
        await self.db.refresh(n)
        return n

    async def get(self, note_id: int) -> Optional[LearningNote]:
        return await self.db.get(LearningNote, note_id)

    async def list_by_topic(self, topic_id: int | None) -> list[LearningNote]:
        stmt = select(LearningNote).order_by(LearningNote.created_at.desc())
        if topic_id is not None:
            stmt = stmt.where(LearningNote.topic_id == topic_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, note_id: int, *, title: str | None = None, body_md: str | None = None) -> None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if body_md is not None:
            values["body_md"] = body_md
        if not values:
            return
        await self.db.execute(
            update(LearningNote).where(LearningNote.id == note_id).values(**values)
        )
        await self.db.commit()


class LearningCardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_many(self, topic_id: int, cards: list[dict]) -> list[LearningCard]:
        # 新卡 due_at 默认 now（naive UTC，与 created_at 同基准）：立即可复习，
        # 今日复习队列自然包含新生成卡片。
        now = utcnow()
        objs = [
            LearningCard(
                topic_id=topic_id,
                node_id=c.get("node_id"),
                front=c["front"],
                back=c["back"],
                due_at=now,
            )
            for c in cards
        ]
        self.db.add_all(objs)
        await self.db.commit()
        for o in objs:
            await self.db.refresh(o)
        return objs

    async def get(self, card_id: int) -> Optional[LearningCard]:
        return await self.db.get(LearningCard, card_id)

    async def get_fresh(self, card_id: int) -> Optional[LearningCard]:
        """取卡片并强制刷新（UPDATE 后读取 onupdate/调度新值，避免会话缓存陈旧）。"""
        card = await self.db.get(LearningCard, card_id, populate_existing=True)
        return card

    async def update_scheduling(
        self,
        card_id: int,
        *,
        interval_days: int,
        ease_factor: float,
        review_count: int,
        lapse_count: int,
        due_at: datetime,
    ) -> None:
        await self.db.execute(
            update(LearningCard)
            .where(LearningCard.id == card_id)
            .values(
                interval_days=interval_days,
                ease_factor=ease_factor,
                review_count=review_count,
                lapse_count=lapse_count,
                due_at=due_at,
            )
        )
        await self.db.commit()

    async def list_by_topic(self, topic_id: int) -> list[LearningCard]:
        stmt = (
            select(LearningCard)
            .where(LearningCard.topic_id == topic_id)
            .order_by(LearningCard.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_due(
        self, now: datetime, topic_id: int | None = None
    ) -> list[LearningCard]:
        """到期卡片：due_at 为空（旧卡未排期）或 due_at<=now。可按主题过滤。"""
        stmt = select(LearningCard).where(
            or_(LearningCard.due_at.is_(None), LearningCard.due_at <= now)
        )
        if topic_id is not None:
            stmt = stmt.where(LearningCard.topic_id == topic_id)
        stmt = stmt.order_by(LearningCard.due_at.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class LearningReviewRepository:
    """复习记录仓储：每次评分写一条，驱动 SM-2 调度溯源。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        card_id: int,
        topic_id: int,
        rating: str,
        previous_due_at: datetime | None,
        next_due_at: datetime | None,
    ) -> LearningReview:
        r = LearningReview(
            card_id=card_id,
            topic_id=topic_id,
            rating=rating,
            previous_due_at=previous_due_at,
            next_due_at=next_due_at,
        )
        self.db.add(r)
        await self.db.commit()
        await self.db.refresh(r)
        return r

    async def list_by_topic(self, topic_id: int, limit: int = 200) -> list[LearningReview]:
        stmt = (
            select(LearningReview)
            .where(LearningReview.topic_id == topic_id)
            .order_by(LearningReview.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_by_card(self, card_id: int, limit: int = 50) -> list[LearningReview]:
        stmt = (
            select(LearningReview)
            .where(LearningReview.card_id == card_id)
            .order_by(LearningReview.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_since(
        self, topic_id: int, since: datetime
    ) -> list[LearningReview]:
        """主题下自 since 以来的复习记录（周报统计用）。"""
        stmt = (
            select(LearningReview)
            .where(LearningReview.topic_id == topic_id)
            .where(LearningReview.created_at >= since)
            .order_by(LearningReview.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class LearningQuizRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_many(self, topic_id: int, quizzes: list[dict]) -> list[LearningQuiz]:
        objs = [
            LearningQuiz(
                topic_id=topic_id,
                node_id=q.get("node_id"),
                question=q["question"],
                answer=q["answer"],
                explanation=q.get("explanation"),
            )
            for q in quizzes
        ]
        self.db.add_all(objs)
        await self.db.commit()
        for o in objs:
            await self.db.refresh(o)
        return objs

    async def list_by_topic(self, topic_id: int) -> list[LearningQuiz]:
        stmt = (
            select(LearningQuiz)
            .where(LearningQuiz.topic_id == topic_id)
            .order_by(LearningQuiz.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, quiz_id: int) -> Optional[LearningQuiz]:
        return await self.db.get(LearningQuiz, quiz_id)


class LearningAttemptRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, *, quiz_id: int, user_answer: str | None, result: str
    ) -> LearningQuizAttempt:
        a = LearningQuizAttempt(quiz_id=quiz_id, user_answer=user_answer, result=result)
        self.db.add(a)
        await self.db.commit()
        await self.db.refresh(a)
        return a

    async def list_by_quiz(self, quiz_id: int) -> list[LearningQuizAttempt]:
        stmt = (
            select(LearningQuizAttempt)
            .where(LearningQuizAttempt.quiz_id == quiz_id)
            .order_by(LearningQuizAttempt.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_wrong_by_topic(
        self, topic_id: int
    ) -> list[tuple[LearningQuizAttempt, LearningQuiz]]:
        """主题下所有错题（result in wrong/partial），连练习题一起返回供错题本展示。"""
        stmt = (
            select(LearningQuizAttempt, LearningQuiz)
            .join(LearningQuiz, LearningQuizAttempt.quiz_id == LearningQuiz.id)
            .where(LearningQuiz.topic_id == topic_id)
            .where(LearningQuizAttempt.result.in_(["wrong", "partial"]))
            .order_by(LearningQuizAttempt.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return [(a, q) for a, q in result.all()]
