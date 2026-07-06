"""混合检索：向量召回 + 关键词召回 + RRF 融合 + 可插拔 rerank + 命中原因。

设计（docs/phase3-plan.md M2 / requirements §4.5）：
- 向量召回：embed query → ChromaDB top_n → 回查 MySQL 切片与文档。
- 关键词召回：按查询切词后在 doc_chunks.content 上 LIKE 匹配（精确命中函数名/报错/配置项）。
- 融合：RRF（Reciprocal Rank Fusion），score = Σ 1/(k+rank)，k=60。
- rerank：Reranker 协议，默认 IdentityReranker（no-op）；可插拔交叉编码器等。
- 命中原因：每条结果记录 matched_via（vector/keyword）与 matched_keywords。

易维护优先：关键词召回用 MySQL LIKE（无需 FULLTEXT/ngram parser 依赖），
精确子串命中满足 M2 验收；FULLTEXT/BM25 可后续替换 _keyword_recall 实现而不改接口。
禁用文档（enabled=False）在两路召回均被排除。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .models import DocChunk, Document
from .repo import DocChunkRepository, DocumentRepository
from .store_chroma import chroma_store

logger = get_logger(__name__)

RRF_K = 60  # RRF 常数，标准值
VECTOR_OVERFETCH = 4  # 向量过取倍数（过滤禁用/元数据后仍够 top_k）
KEYWORD_CANDIDATE_LIMIT = 200  # 关键词召回候选上限（LIKE 扫描保护）


@dataclass
class HybridResult:
    chunk_id: int
    doc_id: int
    doc_name: str
    ordinal: int
    content: str
    heading: str | None
    score: float = 0.0
    matched_via: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)


@dataclass
class RetrievalFilters:
    doc_type: str | None = None
    topic: str | None = None
    tags: list[str] | None = None
    language: str | None = None
    project_id: int | None = None
    enabled: bool | None = True


class Reranker(Protocol):
    """可插拔重排接口：对融合后的结果按查询相关性重排。"""

    async def rerank(
        self, query: str, results: list[HybridResult]
    ) -> list[HybridResult]: ...


class IdentityReranker:
    """默认 no-op 重排器（保持 RRF 顺序）。"""

    async def rerank(self, query: str, results: list[HybridResult]) -> list[HybridResult]:
        return results


def extract_terms(query: str) -> list[str]:
    """从查询中抽取检索词：完整查询 + 标识符 token + 标识符子词 + CJK 连续段。

    - 完整查询作为强信号（精确子串命中函数名/报错串）。
    - [A-Za-z0-9_]+ 拆出完整标识符（import_document）。
    - [A-Za-z0-9]+ 再拆出子词（import_document → import, document），提升复合标识符召回。
    - CJK 连续段整体作为一个词（中文无空格，按短语命中）。
    过滤掉长度 < 2 的 token。
    """
    q = query.strip()
    if not q:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    # 完整查询
    if len(q) >= 2 and q not in seen:
        terms.append(q)
        seen.add(q)
    # 完整标识符（含下划线）
    for m in re.findall(r"[A-Za-z0-9_]+", q):
        if len(m) >= 2 and m not in seen:
            terms.append(m)
            seen.add(m)
    # 标识符子词（按下划线拆分，import_document → import/document）
    for m in re.findall(r"[A-Za-z0-9]+", q):
        if len(m) >= 2 and m not in seen:
            terms.append(m)
            seen.add(m)
    # CJK 连续段
    for m in re.findall(r"[一-鿿]+", q):
        if len(m) >= 2 and m not in seen:
            terms.append(m)
            seen.add(m)
    return terms


def _escape_like(term: str) -> str:
    """转义 LIKE 元字符（% _ \\），避免用户输入被当通配符。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _doc_matches_filters(doc: Document, filters: RetrievalFilters) -> bool:
    if filters.enabled is not None and doc.enabled != filters.enabled:
        return False
    if filters.doc_type and doc.doc_type != filters.doc_type:
        return False
    if filters.topic and doc.topic != filters.topic:
        return False
    if filters.language and doc.language != filters.language:
        return False
    if filters.project_id is not None and doc.project_id != filters.project_id:
        return False
    if filters.tags:
        doc_tags = doc.tags_json or []
        if not all(t in doc_tags for t in filters.tags):
            return False
    return True


class HybridRetriever:
    def __init__(
        self,
        db: AsyncSession,
        provider=None,
        reranker: Reranker | None = None,
    ) -> None:
        self.db = db
        self._provider = provider
        self.reranker = reranker or IdentityReranker()
        self.docs = DocumentRepository(db)
        self.chunk_repo = DocChunkRepository(db)

    async def _get_provider(self):
        if self._provider is not None:
            return self._provider
        from .settings import SettingsService

        s = await SettingsService(self.db).get_all()
        from .provider import OllamaProvider

        return OllamaProvider(embed_model=s["embed_model"])

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> list[HybridResult]:
        """混合检索：向量 + 关键词 → RRF → rerank → top_k。"""
        filters = filters or RetrievalFilters()
        if not query or not query.strip():
            return []
        terms = extract_terms(query)

        vector_list = await self._vector_recall(query, top_k * VECTOR_OVERFETCH, filters, terms)
        keyword_list = await self._keyword_recall(terms, KEYWORD_CANDIDATE_LIMIT, filters)

        merged = self._rrf_merge(vector_list, keyword_list, top_k * 3)
        # 为每条结果补 matched_keywords（向量召回也按内容子串判定）
        for r in merged:
            if not r.matched_keywords:
                r.matched_keywords = [t for t in terms if t in r.content]
        reranked = await self.reranker.rerank(query, merged)
        return reranked[:top_k]

    async def _vector_recall(
        self,
        query: str,
        top_n: int,
        filters: RetrievalFilters,
        terms: list[str],
    ) -> list[HybridResult]:
        provider = await self._get_provider()
        try:
            qvec = await provider.embed_one(query)
        except Exception as e:  # noqa: BLE001
            logger.warning("vector recall embed failed", error=str(e))
            return []
        chunk_ids = await chroma_store.query(qvec, top_k=top_n)
        if not chunk_ids:
            return []
        chunks_map = await self.chunk_repo.get_by_ids(chunk_ids)
        doc_cache: dict[int, Document | None] = {}
        out: list[HybridResult] = []
        for cid in chunk_ids:
            c = chunks_map.get(cid)
            if not c:
                continue
            if c.doc_id not in doc_cache:
                doc_cache[c.doc_id] = await self.docs.get(c.doc_id)
            doc = doc_cache[c.doc_id]
            if doc is None or not _doc_matches_filters(doc, filters):
                continue
            out.append(
                HybridResult(
                    chunk_id=c.id,
                    doc_id=c.doc_id,
                    doc_name=doc.name,
                    ordinal=c.ordinal,
                    content=c.content,
                    heading=c.heading,
                )
            )
        return out

    async def _keyword_recall(
        self,
        terms: list[str],
        limit: int,
        filters: RetrievalFilters,
    ) -> list[HybridResult]:
        if not terms:
            return []
        # 在 doc_chunks 上 LIKE 任一词命中（转义元字符），JOIN documents 应用 enabled/元数据过滤。
        like_conds = [
            DocChunk.content.like(f"%{_escape_like(t)}%", escape="\\") for t in terms
        ]
        stmt = (
            select(DocChunk, Document)
            .join(Document, DocChunk.doc_id == Document.id)
            .where(or_(*like_conds))
        )
        if filters.enabled is not None:
            stmt = stmt.where(Document.enabled == filters.enabled)
        if filters.doc_type:
            stmt = stmt.where(Document.doc_type == filters.doc_type)
        if filters.topic:
            stmt = stmt.where(Document.topic == filters.topic)
        if filters.language:
            stmt = stmt.where(Document.language == filters.language)
        if filters.project_id is not None:
            stmt = stmt.where(Document.project_id == filters.project_id)
        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        rows = result.all()

        scored: list[tuple[float, HybridResult, list[str]]] = []
        for chunk, doc in rows:
            # SQL 已过滤 enabled/doc_type/topic/language/project_id；这里补 tags 过滤，
            # 与向量召回 _doc_matches_filters 保持一致。
            if not _doc_matches_filters(doc, filters):
                continue
            matched = [t for t in terms if t in chunk.content]
            if not matched:
                continue
            # 完整查询命中加权；命中词数越多分越高
            full_query = terms[0] if terms else ""
            score = len(matched) + (3 if full_query in chunk.content else 0)
            r = HybridResult(
                chunk_id=chunk.id,
                doc_id=doc.id,
                doc_name=doc.name,
                ordinal=chunk.ordinal,
                content=chunk.content,
                heading=chunk.heading,
                matched_keywords=matched,
            )
            scored.append((score, r, matched))
        # 按分数降序得关键词召回排名
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r, _ in scored]

    def _rrf_merge(
        self,
        vector_list: list[HybridResult],
        keyword_list: list[HybridResult],
        top_k: int,
    ) -> list[HybridResult]:
        scores: dict[int, float] = {}
        results: dict[int, HybridResult] = {}

        for rank, r in enumerate(vector_list):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            r.matched_via.append("vector")
            results[r.chunk_id] = r
        for rank, r in enumerate(keyword_list):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            existing = results.get(r.chunk_id)
            if existing is not None:
                existing.matched_via.append("keyword")
                for kw in r.matched_keywords:
                    if kw not in existing.matched_keywords:
                        existing.matched_keywords.append(kw)
            else:
                r.matched_via.append("keyword")
                results[r.chunk_id] = r
        for cid, s in scores.items():
            results[cid].score = s
        ranked = sorted(results.values(), key=lambda r: r.score, reverse=True)
        return ranked[:top_k]
