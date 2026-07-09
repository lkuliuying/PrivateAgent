"""全局搜索服务（第七阶段 M2）。

初版使用 MySQL LIKE 跨表检索，返回统一结构 {type,id,title,snippet,source,updated_at,action,meta}。
初版限定对象、分表 LIMIT、总结果上限，避免无界返回（phase7 §5.8 性能边界）。

性能说明（第八阶段审查）：LIKE '%q%' 前缀通配无法走普通索引，大表为全表扫。
MySQL FULLTEXT 可加速，但默认分词器不支持 CJK 子串（中文需 ngram parser，
且需迁移加索引 + 环境配置 ngram_token_size），而本项目搜索含大量中文内容
（如「第七阶段」子串匹配），贸然切 FULLTEXT 会破坏中文搜索。故当前保留 LIKE，
后续可在确认 ngram 可用后对 latin/CJK 混合列加 ngram FULLTEXT 索引优化。

搜索对象（对齐 docs/phase7-requirements.md §5.2）：
会话/消息、文档/切片、文档集合、项目、学习主题/笔记、Agent 任务/证据、
记忆、收件箱、提醒、目标、简报。

trusted_paths 边界：搜索只查 DB 元数据与切片文本，不读取未授权文件内容（§9）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AgentEvidence,
    AgentTask,
    Briefing,
    ChatSession,
    Document,
    DocumentCollection,
    DocChunk,
    InboxItem,
    LearningNote,
    LearningTopic,
    MemoryItem,
    Message,
    PersonalGoal,
    Project,
    Reminder,
)

_TRUNCATE = 200


def _snippet(text: str | None, query: str, limit: int = _TRUNCATE) -> str | None:
    """围绕命中位置截取片段；找不到命中则取开头。"""
    if not text:
        return None
    if len(text) <= limit:
        return text
    ql = query.lower()
    idx = text.lower().find(ql)
    if idx < 0:
        return text[:limit] + "…"
    half = limit // 2
    start = max(0, idx - half)
    end = min(len(text), idx + len(query) + half)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class SearchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(
        self,
        query: str,
        *,
        types: list[str] | None = None,
        limit: int = 30,
    ) -> list[dict]:
        """全局搜索。query 为空或过短返回空列表。types 限定返回类型。"""
        q = (query or "").strip()
        if len(q) < 1:
            return []
        like = f"%{q}%"
        per_table = max(5, limit)

        searchers: list[tuple[str, Callable]] = [
            ("session", self._search_sessions),
            ("message", self._search_messages),
            ("document", self._search_documents),
            ("chunk", self._search_chunks),
            ("collection", self._search_collections),
            ("project", self._search_projects),
            ("learning_topic", self._search_topics),
            ("learning_note", self._search_notes),
            ("agent_task", self._search_tasks),
            ("agent_evidence", self._search_evidence),
            ("memory", self._search_memories),
            ("inbox", self._search_inbox),
            ("reminder", self._search_reminders),
            ("goal", self._search_goals),
            ("briefing", self._search_briefings),
        ]

        results: list[dict] = []
        for t, fn in searchers:
            if types and t not in types:
                continue
            try:
                results.extend(await fn(like, per_table))
            except Exception:  # noqa: BLE001
                # 单表搜索失败不阻塞其他表
                continue

        # 按 updated_at/created_at 倒序，截断到 limit
        results.sort(key=lambda r: r.get("_sort") or "", reverse=True)
        for r in results:
            r.pop("_sort", None)
        return results[:limit]

    # ---- 各表搜索 ----

    async def _search_sessions(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.title.like(like))
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "session",
                "id": s.id,
                "title": s.title,
                "snippet": None,
                "source": "对话",
                "updated_at": _iso(s.updated_at),
                "action": "open_chat",
                "meta": {"session_id": s.id},
                "_sort": _iso(s.updated_at) or "",
            }
            for s in rows
        ]

    async def _search_messages(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(Message)
            .where(Message.content.like(like))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "message",
                "id": m.id,
                "title": (m.content[:60] + "…") if len(m.content) > 60 else m.content,
                "snippet": _snippet(m.content, like.strip("%")),
                "source": "对话消息",
                "updated_at": _iso(m.created_at),
                "action": "open_chat",
                "meta": {"session_id": m.session_id, "message_id": m.id},
                "_sort": _iso(m.created_at) or "",
            }
            for m in rows
        ]

    async def _search_documents(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(Document)
            .where(Document.name.like(like))
            .order_by(Document.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "document",
                "id": d.id,
                "title": d.name,
                "snippet": d.doc_type,
                "source": "知识库",
                "updated_at": _iso(d.updated_at),
                "action": "open_kb",
                "meta": {"doc_id": d.id},
                "_sort": _iso(d.updated_at) or "",
            }
            for d in rows
        ]

    async def _search_chunks(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(DocChunk)
            .where(DocChunk.content.like(like))
            .order_by(DocChunk.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "chunk",
                "id": c.id,
                "title": c.heading or f"切片 #{c.id}",
                "snippet": _snippet(c.content, like.strip("%")),
                "source": "文档切片",
                "updated_at": _iso(c.created_at),
                "action": "open_kb",
                "meta": {"doc_id": c.doc_id, "chunk_id": c.id},
                "_sort": _iso(c.created_at) or "",
            }
            for c in rows
        ]

    async def _search_collections(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(DocumentCollection)
            .where(DocumentCollection.title.like(like))
            .order_by(DocumentCollection.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "collection",
                "id": c.id,
                "title": c.title,
                "snippet": None,
                "source": "文档集合",
                "updated_at": _iso(c.updated_at),
                "action": "open_kb",
                "meta": {"collection_id": c.id},
                "_sort": _iso(c.updated_at) or "",
            }
            for c in rows
        ]

    async def _search_projects(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(Project)
            .where(Project.name.like(like))
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "project",
                "id": p.id,
                "title": p.name,
                "snippet": p.language,
                "source": "项目",
                "updated_at": _iso(p.updated_at),
                "action": "open_projects",
                "meta": {"project_id": p.id},
                "_sort": _iso(p.updated_at) or "",
            }
            for p in rows
        ]

    async def _search_topics(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(LearningTopic)
            .where(LearningTopic.title.like(like))
            .order_by(LearningTopic.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "learning_topic",
                "id": t.id,
                "title": t.title,
                "snippet": t.goal,
                "source": "学习主题",
                "updated_at": _iso(t.updated_at),
                "action": "open_learning",
                "meta": {"topic_id": t.id},
                "_sort": _iso(t.updated_at) or "",
            }
            for t in rows
        ]

    async def _search_notes(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(LearningNote)
            .where(LearningNote.title.like(like) | LearningNote.body_md.like(like))
            .order_by(LearningNote.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "learning_note",
                "id": n.id,
                "title": n.title,
                "snippet": _snippet(n.body_md, like.strip("%")),
                "source": "学习笔记",
                "updated_at": _iso(n.updated_at),
                "action": "open_learning",
                "meta": {"topic_id": n.topic_id, "note_id": n.id},
                "_sort": _iso(n.updated_at) or "",
            }
            for n in rows
        ]

    async def _search_tasks(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(AgentTask)
            .where(AgentTask.title.like(like))
            .order_by(AgentTask.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "agent_task",
                "id": t.id,
                "title": t.title,
                "snippet": t.status,
                "source": "Agent 任务",
                "updated_at": _iso(t.updated_at),
                "action": "open_tasks",
                "meta": {"task_id": t.id},
                "_sort": _iso(t.updated_at) or "",
            }
            for t in rows
        ]

    async def _search_evidence(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(AgentEvidence)
            .where(AgentEvidence.title.like(like) | AgentEvidence.content_md.like(like))
            .order_by(AgentEvidence.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "agent_evidence",
                "id": e.id,
                "title": e.title,
                "snippet": _snippet(e.content_md, like.strip("%")),
                "source": "任务证据",
                "updated_at": _iso(e.created_at),
                "action": "open_tasks",
                "meta": {"task_id": e.task_id, "evidence_id": e.id},
                "_sort": _iso(e.created_at) or "",
            }
            for e in rows
        ]

    async def _search_memories(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(MemoryItem)
            .where(MemoryItem.title.like(like) | MemoryItem.content_md.like(like))
            .order_by(MemoryItem.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "memory",
                "id": m.id,
                "title": m.title,
                "snippet": _snippet(m.summary or m.content_md, like.strip("%")),
                "source": "记忆",
                "updated_at": _iso(m.updated_at),
                "action": "open_memory",
                "meta": {"memory_id": m.id},
                "_sort": _iso(m.updated_at) or "",
            }
            for m in rows
        ]

    async def _search_inbox(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(InboxItem)
            .where(InboxItem.title.like(like))
            .order_by(InboxItem.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "inbox",
                "id": i.id,
                "title": i.title,
                "snippet": i.item_type,
                "source": "收件箱",
                "updated_at": _iso(i.updated_at),
                "action": "open_today",
                "meta": {"inbox_id": i.id},
                "_sort": _iso(i.updated_at) or "",
            }
            for i in rows
        ]

    async def _search_reminders(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(Reminder)
            .where(Reminder.title.like(like))
            .order_by(Reminder.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "reminder",
                "id": r.id,
                "title": r.title,
                "snippet": _iso(r.due_at),
                "source": "提醒",
                "updated_at": _iso(r.updated_at),
                "action": "open_today",
                "meta": {"reminder_id": r.id},
                "_sort": _iso(r.updated_at) or "",
            }
            for r in rows
        ]

    async def _search_goals(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(PersonalGoal)
            .where(PersonalGoal.title.like(like))
            .order_by(PersonalGoal.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "goal",
                "id": g.id,
                "title": g.title,
                "snippet": g.status,
                "source": "目标",
                "updated_at": _iso(g.updated_at),
                "action": "open_today",
                "meta": {"goal_id": g.id},
                "_sort": _iso(g.updated_at) or "",
            }
            for g in rows
        ]

    async def _search_briefings(self, like: str, limit: int) -> list[dict]:
        stmt = (
            select(Briefing)
            .where(Briefing.title.like(like) | Briefing.body_md.like(like))
            .order_by(Briefing.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "type": "briefing",
                "id": b.id,
                "title": b.title,
                "snippet": _snippet(b.body_md, like.strip("%")),
                "source": "简报",
                "updated_at": _iso(b.created_at),
                "action": "open_today",
                "meta": {"briefing_id": b.id},
                "_sort": _iso(b.created_at) or "",
            }
            for b in rows
        ]
