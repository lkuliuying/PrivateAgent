"""混合检索：向量召回 + MySQL FULLTEXT/BM25 + RRF + embedding 重排。

设计（docs/phase3-plan.md M2 / requirements §4.5）：
- 向量召回：embed query → ChromaDB top_n → 回查 MySQL 切片与文档。
- 词法召回：MySQL FULLTEXT ngram 索引 + 自然语言相关性（BM25）。
- 融合：RRF（Reciprocal Rank Fusion），score = Σ 1/(k+rank)，k=60。
- rerank：默认复用本地 embedding 模型批量计算 query/chunk 语义相似度。
- 命中原因：每条结果记录 matched_via（vector/bm25）与 matched_keywords。

FULLTEXT 索引由 Alembic 0012 创建；ngram parser 同时覆盖中文短语、函数名和错误串。
模型或某一路召回失败时保留另一路结果并记录结构化日志，不让 RAG 整体失效。
禁用文档（enabled=False）在两路召回均被排除。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .models import DocChunk, Document
from .repo import DocChunkRepository, DocumentRepository
from .store_chroma import chroma_store

logger = get_logger(__name__)

RRF_K = 60  # RRF 常数，标准值
VECTOR_OVERFETCH = 4  # 向量过取倍数（过滤禁用/元数据后仍够 top_k）
BM25_CANDIDATE_LIMIT = 200
RERANK_CANDIDATE_LIMIT = 64
RERANK_BATCH_SIZE = 16
FUSION_WEIGHT = 0.35
SEMANTIC_WEIGHT = 0.65


@dataclass
class HybridResult:
    chunk_id: int
    doc_id: int
    doc_name: str
    ordinal: int
    content: str
    heading: str | None
    score: float = 0.0
    fusion_score: float = 0.0
    bm25_score: float | None = None
    rerank_score: float | None = None
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


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_one(self, text: str) -> list[float]: ...


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("embedding 维度不一致")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


class EmbeddingReranker:
    """使用配置的本地 embedding 模型对 RRF 候选做批量语义重排。"""

    def __init__(
        self,
        provider: EmbeddingProvider,
        query_embedding: list[float],
        *,
        batch_size: int = RERANK_BATCH_SIZE,
    ) -> None:
        self.provider = provider
        self.query_embedding = query_embedding
        self.batch_size = max(1, batch_size)

    async def rerank(self, query: str, results: list[HybridResult]) -> list[HybridResult]:
        if len(results) <= 1:
            return results

        inputs = [
            "\n".join(part for part in (item.doc_name, item.heading, item.content) if part)[
                :2000
            ]
            for item in results
        ]
        embeddings: list[list[float]] = []
        for start in range(0, len(inputs), self.batch_size):
            batch = inputs[start : start + self.batch_size]
            batch_embeddings = await self.provider.embed(batch)
            if len(batch_embeddings) != len(batch):
                raise ValueError("重排 embedding 数量与候选数量不一致")
            embeddings.extend(batch_embeddings)

        fusion_scores = [item.fusion_score for item in results]
        low, high = min(fusion_scores), max(fusion_scores)
        for item, embedding in zip(results, embeddings, strict=True):
            semantic = (_cosine_similarity(self.query_embedding, embedding) + 1.0) / 2.0
            fusion = (
                1.0 if high == low else (item.fusion_score - low) / (high - low)
            )
            item.rerank_score = semantic
            item.score = FUSION_WEIGHT * fusion + SEMANTIC_WEIGHT * semantic
        return sorted(results, key=lambda item: item.score, reverse=True)


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


def _matched_terms(content: str, terms: list[str]) -> list[str]:
    """按 Unicode 大小写折叠补充可解释的原词命中信息。"""
    normalized = content.casefold()
    return [term for term in terms if term.casefold() in normalized]


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
        self.reranker = reranker
        self.docs = DocumentRepository(db)
        self.chunk_repo = DocChunkRepository(db)

    async def _get_provider(self):
        if self._provider is not None:
            return self._provider
        from .settings import SettingsService

        s = await SettingsService(self.db).get_all()
        from .provider import ProviderRouter

        return ProviderRouter(s).embedding_provider()

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> list[HybridResult]:
        """混合检索：向量 + 关键词 → RRF → rerank → top_k。"""
        filters = filters or RetrievalFilters()
        if not query or not query.strip() or top_k <= 0:
            return []
        # 防止内部调用方误传超大值，放大向量查询和数据库候选集。
        top_k = min(top_k, 50)
        terms = extract_terms(query)

        provider = None
        try:
            provider = await self._get_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning("embedding provider unavailable", error=str(exc))

        vector_list: list[HybridResult] = []
        query_embedding: list[float] | None = None
        if provider is not None:
            try:
                vector_list, query_embedding = await self._vector_recall(
                    query,
                    top_k * VECTOR_OVERFETCH,
                    filters,
                    terms,
                    provider,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("vector recall failed", error=str(exc))

        try:
            bm25_list = await self._bm25_recall(
                query, terms, BM25_CANDIDATE_LIMIT, filters
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("bm25 recall failed", error=str(exc))
            bm25_list = []

        candidate_limit = min(max(top_k * 3, top_k), RERANK_CANDIDATE_LIMIT)
        merged = self._rrf_merge(vector_list, bm25_list, candidate_limit)
        # 为每条结果补 matched_keywords（向量召回也按内容子串判定）
        for r in merged:
            if not r.matched_keywords:
                r.matched_keywords = _matched_terms(r.content, terms)
        reranker = self.reranker
        if reranker is None and provider is not None and query_embedding is not None:
            reranker = EmbeddingReranker(provider, query_embedding)
        if reranker is not None and len(merged) > 1:
            try:
                merged = await reranker.rerank(query, merged)
            except Exception as exc:  # noqa: BLE001
                logger.warning("embedding rerank failed, keeping rrf order", error=str(exc))
        return merged[:top_k]

    async def _vector_recall(
        self,
        query: str,
        top_n: int,
        filters: RetrievalFilters,
        terms: list[str],
        provider: EmbeddingProvider,
    ) -> tuple[list[HybridResult], list[float] | None]:
        try:
            qvec = await provider.embed_one(query)
        except Exception as e:  # noqa: BLE001
            logger.warning("vector recall embed failed", error=str(e))
            return [], None
        chunk_ids = await chroma_store.query(qvec, top_k=top_n)
        if not chunk_ids:
            return [], qvec
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
        return out, qvec

    async def _bm25_recall(
        self,
        query: str,
        terms: list[str],
        limit: int,
        filters: RetrievalFilters,
    ) -> list[HybridResult]:
        if not query.strip():
            return []
        if self.db.get_bind().dialect.name not in {
            "mysql",
            "mariadb",
        }:
            raise RuntimeError("FULLTEXT/BM25 召回仅支持 MySQL/MariaDB")

        bm25_expr = DocChunk.bm25_text.match(
            query,
            mysql_boolean_mode=False,
            mysql_natural_language=True,
        )
        bm25_score = bm25_expr.label("bm25_score")
        stmt = (
            select(DocChunk, Document, bm25_score)
            .join(Document, DocChunk.doc_id == Document.id)
            .where(bm25_expr > 0)
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
        if filters.tags:
            for tag in filters.tags:
                stmt = stmt.where(
                    func.json_contains(
                        Document.tags_json, json.dumps(tag, ensure_ascii=False)
                    )
                    == 1
                )
        stmt = stmt.order_by(bm25_score.desc(), DocChunk.id.asc()).limit(limit)
        result = await self.db.execute(stmt)
        rows = result.all()

        recalled: list[HybridResult] = []
        for chunk, doc, raw_score in rows:
            matched = _matched_terms(chunk.content, terms)
            recalled.append(
                HybridResult(
                    chunk_id=chunk.id,
                    doc_id=doc.id,
                    doc_name=doc.name,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    heading=chunk.heading,
                    bm25_score=float(raw_score),
                    matched_keywords=matched,
                )
            )
        return recalled

    def _rrf_merge(
        self,
        vector_list: list[HybridResult],
        bm25_list: list[HybridResult],
        top_k: int,
    ) -> list[HybridResult]:
        scores: dict[int, float] = {}
        results: dict[int, HybridResult] = {}

        for rank, r in enumerate(vector_list):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            r.matched_via.append("vector")
            results[r.chunk_id] = r
        for rank, r in enumerate(bm25_list):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            existing = results.get(r.chunk_id)
            if existing is not None:
                existing.matched_via.append("bm25")
                existing.bm25_score = r.bm25_score
                for kw in r.matched_keywords:
                    if kw not in existing.matched_keywords:
                        existing.matched_keywords.append(kw)
            else:
                r.matched_via.append("bm25")
                results[r.chunk_id] = r
        for cid, s in scores.items():
            results[cid].score = s
            results[cid].fusion_score = s
        ranked = sorted(results.values(), key=lambda r: r.score, reverse=True)
        return ranked[:top_k]
