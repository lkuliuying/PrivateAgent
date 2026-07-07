"""长期记忆服务：检索 / 候选沉淀 / 事件审计。

照 RagService/LearningService 分层：路由调服务，服务组合 MemoryRepository +
MemoryEventRepository。M1 检索为纯 MySQL + Python 评分（无向量），向量检索留待后续。

两类检索语义不同：
- retrieve_for_context：聊天注入，query 是自然语言问句；用 CJK n-gram 评分召回
  同义不同形的记忆（整串 LIKE 对长问句过严，会漏）。只取 confirmed+enabled+非敏感。
- search：管理视图，query 是用户键入的搜索词；走 MySQL LIKE 精确子串匹配。
"""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .models import MemoryItem
from .repo_memories import MemoryEventRepository, MemoryRepository

logger = get_logger(__name__)

# 聊天上下文注入的记忆段落总长上限（字符），防止 num_ctx 膨胀。
MEMORY_CONTEXT_CHAR_LIMIT = 2000


def _extract_terms(text: str) -> list[str]:
    """从查询文本提取匹配词：CJK 整段 + CJK 2-gram + 拉丁标识符。

    整段精度高、2-gram 召回高（解决同义不同形），二者并集用于评分。
    """
    terms: set[str] = set()
    for run in re.findall(r"[一-鿿]+", text or ""):
        if len(run) >= 2:
            terms.add(run)
            for i in range(len(run) - 1):
                terms.add(run[i : i + 2])
    for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or ""):
        terms.add(m)
    return list(terms)


class MemoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = MemoryRepository(db)
        self.events = MemoryEventRepository(db)

    # ---------------- 检索 ----------------
    async def retrieve_for_context(
        self, query: str, top_k: int = 5
    ) -> list[MemoryItem]:
        """聊天上下文检索：取已确认、启用、非敏感的记忆，按 query 评分召回。

        失败容错降级为空，不阻断聊天（仿 rag.retrieve try/except）。
        """
        try:
            items = await self.repo.list(status="confirmed", enabled=True)
        except Exception:  # noqa: BLE001
            logger.exception("memory retrieve_for_context failed, fallback empty")
            return []
        # 敏感记忆绝不进 prompt（DB 层未过滤，在此兜底）
        items = [m for m in items if not m.sensitive]
        if not items or not query:
            return []
        terms = _extract_terms(query)
        if not terms:
            return []

        def score(m: MemoryItem) -> int:
            hay = f"{m.title} {m.summary or ''} {m.content_md or ''}"
            return sum(1 for t in terms if t in hay)

        scored = [(m, score(m)) for m in items]
        scored = [s for s in scored if s[1] > 0]
        scored.sort(key=lambda s: s[1], reverse=True)
        return [m for m, _ in scored[:top_k]]

    async def search(
        self,
        query: str | None = None,
        *,
        kind: str | None = None,
        status: str | None = None,
        enabled: bool | None = None,
        project_id: int | None = None,
        topic_id: int | None = None,
    ) -> list[MemoryItem]:
        """记忆搜索（管理视图）：尊重调用方过滤，query 走 LIKE 精确子串。"""
        return await self.repo.list(
            kind=kind,
            status=status,
            enabled=enabled,
            project_id=project_id,
            topic_id=topic_id,
            search=query or None,
        )

    @staticmethod
    def format_sources(mems: list[MemoryItem]) -> list[dict]:
        """生成前端「使用了哪些记忆」展示列表。"""
        return [
            {"id": m.id, "title": m.title, "kind": m.kind, "summary": m.summary}
            for m in mems
        ]

    @staticmethod
    def format_memory_context(mems: list[MemoryItem]) -> str:
        """把记忆格式化为注入 system prompt 的上下文片段（带截断保护）。"""
        lines: list[str] = []
        total = 0
        for m in mems:
            body = m.summary or m.content_md or ""
            frag = f"[记忆：{m.title}]（{m.kind}）\n{body}"
            if total + len(frag) > MEMORY_CONTEXT_CHAR_LIMIT:
                frag = frag[: max(0, MEMORY_CONTEXT_CHAR_LIMIT - total)] + "…（截断）"
                lines.append(frag)
                break
            lines.append(frag)
            total += len(frag) + 2
        return "\n\n".join(lines)

    # ---------------- 使用审计 ----------------
    async def record_usage(
        self,
        memory_ids: list[int],
        *,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> None:
        """记录记忆被使用的审计事件（如聊天引用）。失败容错（best-effort）。"""
        if not memory_ids:
            return
        try:
            await self.events.create_many(
                memory_ids=memory_ids,
                event_type="used",
                ref_type=ref_type,
                ref_id=ref_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("memory record_usage failed (best-effort)")

    # ---------------- CRUD（带事件审计） ----------------
    async def create(self, **kwargs) -> MemoryItem:
        item = await self.repo.create(**kwargs)
        try:
            await self.events.create(
                memory_id=item.id,
                event_type="created",
                ref_type=item.source_type,
                ref_id=item.source_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("memory created-event write failed (best-effort)")
        return item

    async def update(self, memory_id: int, **kwargs) -> MemoryItem | None:
        old = await self.repo.get(memory_id)
        if old is None:
            return None
        await self.repo.update(memory_id, **kwargs)
        # 事件类型：启用->禁用记 disabled，其余编辑记 edited
        new_enabled = kwargs.get("enabled")
        if new_enabled is not None and old.enabled and not new_enabled:
            etype = "disabled"
        else:
            etype = "edited"
        try:
            await self.events.create(memory_id=memory_id, event_type=etype)
        except Exception:  # noqa: BLE001
            logger.exception("memory edited-event write failed (best-effort)")
        return await self.repo.get_fresh(memory_id)

    async def delete(self, memory_id: int) -> bool:
        old = await self.repo.get(memory_id)
        if old is None:
            return False
        # memory_events 对 memory_id 有 ON DELETE CASCADE：删记忆会级联删全部事件，
        # 故 'deleted' 事件无法持久化（写后即被级联删除）。删除审计留待后续活动流。
        await self.repo.delete(memory_id)
        return True

    async def get(self, memory_id: int) -> MemoryItem | None:
        return await self.repo.get(memory_id)

    async def list_events(self, memory_id: int):
        return await self.events.list_by_memory(memory_id)
