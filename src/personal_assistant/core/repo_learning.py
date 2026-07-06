"""学习系统异步仓储层：主题 / 节点 / 笔记 / 卡片 / 练习 / 答题记录。

照 core/repo.py 模式：每仓储持 AsyncSession，方法内自带 commit。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    LearningCard,
    LearningNode,
    LearningNote,
    LearningQuiz,
    LearningQuizAttempt,
    LearningTopic,
)


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
        objs = [
            LearningCard(
                topic_id=topic_id,
                node_id=c.get("node_id"),
                front=c["front"],
                back=c["back"],
            )
            for c in cards
        ]
        self.db.add_all(objs)
        await self.db.commit()
        for o in objs:
            await self.db.refresh(o)
        return objs

    async def list_by_topic(self, topic_id: int) -> list[LearningCard]:
        stmt = (
            select(LearningCard)
            .where(LearningCard.topic_id == topic_id)
            .order_by(LearningCard.created_at.desc())
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
