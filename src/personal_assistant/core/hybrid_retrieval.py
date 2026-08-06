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

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..logging_setup import get_logger
from .index_versions import DocumentIndexRepository
from .models import (
    DocChunk,
    Document,
    DocumentCollectionItem,
    DocumentIndexChunk,
    DocumentIndexHead,
)
from .rag_evidence import EvidenceDecision, RagEvidencePolicy
from .repo import DocChunkRepository, DocumentRepository
from .store_chroma import chroma_store, versioned_chroma_store

logger = get_logger(__name__)


def policy_from_settings() -> RagEvidencePolicy:
    """从应用配置构建证据充分性策略（R2.1）。"""
    return RagEvidencePolicy(
        enabled=settings.rag_evidence_enabled,
        min_final_score=settings.rag_evidence_min_final_score,
        single_channel_min_final_score=settings.rag_evidence_min_single_channel_score,
    )

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
    index_version_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    heading_path: list[str] = field(default_factory=list)
    source_kind: str | None = None
    parser_version: str | None = None


@dataclass
class RetrievalFilters:
    doc_type: str | None = None
    topic: str | None = None
    tags: list[str] | None = None
    language: str | None = None
    project_id: int | None = None
    collection_id: int | None = None
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
        if not results:
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


def build_bm25_query(query: str) -> str:
    """Prefer explicitly quoted phrases for lexical retrieval.

    Natural-language wrappers around exact identifiers or headings can swamp
    MySQL ngram scoring. Quoted spans are an explicit user signal; unquoted
    queries retain the existing behavior unchanged.
    """
    quoted: list[str] = []
    seen: set[str] = set()
    for left, right in (("“", "”"), ("「", "」"), ('"', '"')):
        pattern = re.escape(left) + r"([^\r\n]{2,128}?)" + re.escape(right)
        for match in re.finditer(pattern, query):
            phrase = match.group(1).strip()
            folded = phrase.casefold()
            if phrase and folded not in seen:
                seen.add(folded)
                quoted.append(phrase)
    return " ".join(quoted) if quoted else query.strip()


def _matched_terms(content: str, terms: list[str]) -> list[str]:
    """按 Unicode 大小写折叠补充可解释的原词命中信息。"""
    normalized = content.casefold()
    return [term for term in terms if term.casefold() in normalized]


def _doc_matches_filters(
    doc: Document,
    filters: RetrievalFilters,
    collection_doc_ids: set[int] | None = None,
) -> bool:
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
    if collection_doc_ids is not None and doc.id not in collection_doc_ids:
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
        use_versioned: bool | None = None,
        enable_vector: bool = True,
    ) -> None:
        self.db = db
        self._provider = provider
        self.reranker = reranker
        self.docs = DocumentRepository(db)
        self.chunk_repo = DocChunkRepository(db)
        self.indexes = DocumentIndexRepository(db)
        self.enable_vector = bool(enable_vector)
        self.use_versioned = (
            settings.versioned_rag_retrieval_enabled
            if use_versioned is None
            else use_versioned
        )

    async def _get_provider(self):
        if not self.enable_vector:
            raise RuntimeError("vector retrieval is disabled")
        if self._provider is not None:
            return self._provider
        from .settings import SettingsService

        s = await SettingsService(self.db).get_all()
        from .provider import ProviderRouter

        self._provider = ProviderRouter(s).embedding_provider()
        return self._provider

    async def require_vector_ready(self, probe: str = "RAG rollout preflight") -> int:
        """Fail fast unless the configured embedding provider returns a vector."""
        provider = await self._get_provider()
        embedding = await provider.embed_one(probe)
        if not embedding or any(not math.isfinite(float(value)) for value in embedding):
            raise RuntimeError("embedding provider returned an invalid vector")
        return len(embedding)

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
        collection_doc_ids: set[int] | None = None
        if filters.collection_id is not None:
            if filters.collection_id <= 0:
                return []
            collection_doc_ids = set(
                await self.db.scalars(
                    select(DocumentCollectionItem.doc_id).where(
                        DocumentCollectionItem.collection_id == filters.collection_id
                    )
                )
            )
            if not collection_doc_ids:
                return []

        provider = None
        if self.enable_vector:
            try:
                provider = await self._get_provider()
            except Exception as exc:  # noqa: BLE001
                logger.warning("embedding provider unavailable", error=str(exc))

        vector_list: list[HybridResult] = []
        query_embedding: list[float] | None = None
        if self.enable_vector and provider is not None:
            try:
                vector_list, query_embedding = await self._vector_recall(
                    query,
                    top_k * VECTOR_OVERFETCH,
                    filters,
                    terms,
                    provider,
                    collection_doc_ids,
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
        if reranker is not None and len(merged) >= 1:
            try:
                merged = await reranker.rerank(query, merged)
            except Exception as exc:  # noqa: BLE001
                logger.warning("embedding rerank failed, keeping rrf order", error=str(exc))
        return merged[:top_k]

    async def retrieve_with_evidence(
        self,
        query: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
        policy: RagEvidencePolicy | None = None,
    ) -> tuple[list[HybridResult], EvidenceDecision]:
        """混合检索 + 证据充分性判断（R2.1）。

        返回 ``(results, decision)``；``decision.abstain=True`` 时 ``results`` 为空，
        回答层应依据 ``decision`` 的结构化原因说明资料不足，不生成伪引用。
        """
        results = await self.retrieve(query, top_k=top_k, filters=filters)
        if policy is None:
            policy = policy_from_settings()
        decision = policy.decide(results)
        if decision.abstain:
            return [], decision
        return results, decision

    async def _vector_recall(
        self,
        query: str,
        top_n: int,
        filters: RetrievalFilters,
        terms: list[str],
        provider: EmbeddingProvider,
        collection_doc_ids: set[int] | None,
    ) -> tuple[list[HybridResult], list[float] | None]:
        try:
            qvec = await provider.embed_one(query)
        except Exception as e:  # noqa: BLE001
            logger.warning("vector recall embed failed", error=str(e))
            return [], None
        active_heads = (
            await self.indexes.list_active_heads() if self.use_versioned else {}
        )
        active_version_ids = list(active_heads.values())
        versioned_ids = (
            await versioned_chroma_store.query_active(
                qvec,
                active_version_ids=active_version_ids,
                top_k=top_n,
            )
            if active_version_ids
            else []
        )
        legacy_ids = await chroma_store.query(qvec, top_k=top_n)

        doc_cache: dict[int, Document | None] = {}
        versioned_out: list[HybridResult] = []
        versioned_map = await self.indexes.get_chunks_by_ids(versioned_ids)
        provenance_map = await self.indexes.get_provenance_by_chunk_ids(versioned_ids)
        for chunk_id in versioned_ids:
            chunk = versioned_map.get(chunk_id)
            provenance = provenance_map.get(chunk_id)
            if chunk is None or provenance is None:
                continue
            if active_heads.get(chunk.doc_id) != chunk.index_version_id:
                continue
            if chunk.doc_id not in doc_cache:
                doc_cache[chunk.doc_id] = await self.docs.get(chunk.doc_id)
            document = doc_cache[chunk.doc_id]
            if document is None or not _doc_matches_filters(
                document, filters, collection_doc_ids
            ):
                continue
            versioned_out.append(
                HybridResult(
                    chunk_id=chunk.id,
                    doc_id=chunk.doc_id,
                    doc_name=document.name,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    heading=chunk.heading,
                    index_version_id=chunk.index_version_id,
                    page_start=provenance.page_start,
                    page_end=provenance.page_end,
                    char_start=provenance.char_start,
                    char_end=provenance.char_end,
                    line_start=provenance.line_start,
                    line_end=provenance.line_end,
                    heading_path=list(provenance.heading_path_json or []),
                    source_kind=provenance.source_kind,
                    parser_version=provenance.parser_version,
                )
            )

        legacy_out: list[HybridResult] = []
        legacy_map = await self.chunk_repo.get_by_ids(legacy_ids)
        for cid in legacy_ids:
            c = legacy_map.get(cid)
            if not c:
                continue
            if c.doc_id in active_heads:
                continue
            if c.doc_id not in doc_cache:
                doc_cache[c.doc_id] = await self.docs.get(c.doc_id)
            doc = doc_cache[c.doc_id]
            if doc is None or not _doc_matches_filters(
                doc, filters, collection_doc_ids
            ):
                continue
            legacy_out.append(
                HybridResult(
                    chunk_id=c.id,
                    doc_id=c.doc_id,
                    doc_name=doc.name,
                    ordinal=c.ordinal,
                    content=c.content,
                    heading=c.heading,
                )
            )
        combined: list[HybridResult] = []
        for rank in range(max(len(versioned_out), len(legacy_out))):
            if rank < len(versioned_out):
                combined.append(versioned_out[rank])
            if rank < len(legacy_out):
                combined.append(legacy_out[rank])
        return combined[:top_n], qvec

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
        lexical_query = build_bm25_query(query)

        def _apply_document_filters(stmt):
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
            if filters.collection_id is not None:
                stmt = stmt.where(
                    exists(
                        select(DocumentCollectionItem.id).where(
                            DocumentCollectionItem.collection_id
                            == filters.collection_id,
                            DocumentCollectionItem.doc_id == Document.id,
                        )
                    )
                )
            if filters.tags:
                for tag in filters.tags:
                    stmt = stmt.where(
                        func.json_contains(
                            Document.tags_json, json.dumps(tag, ensure_ascii=False)
                        )
                        == 1
                    )
            return stmt

        legacy_expr = DocChunk.bm25_text.match(
            lexical_query,
            mysql_boolean_mode=False,
            mysql_natural_language=True,
        )
        legacy_score = legacy_expr.label("bm25_score")
        legacy_stmt = (
            select(DocChunk, Document, legacy_score)
            .join(Document, DocChunk.doc_id == Document.id)
            .where(legacy_expr > 0)
        )
        if self.use_versioned:
            legacy_stmt = legacy_stmt.where(
                ~exists(
                    select(DocumentIndexHead.doc_id).where(
                        DocumentIndexHead.doc_id == DocChunk.doc_id,
                        DocumentIndexHead.active_version_id.is_not(None),
                    )
                )
            )
        legacy_stmt = _apply_document_filters(legacy_stmt)
        legacy_stmt = legacy_stmt.order_by(
            legacy_score.desc(), DocChunk.id.asc()
        ).limit(limit)
        legacy_rows = (await self.db.execute(legacy_stmt)).all()

        versioned_rows = []
        if self.use_versioned:
            versioned_expr = DocumentIndexChunk.bm25_text.match(
                lexical_query,
                mysql_boolean_mode=False,
                mysql_natural_language=True,
            )
            versioned_score = versioned_expr.label("bm25_score")
            versioned_stmt = (
                select(DocumentIndexChunk, Document, versioned_score)
                .join(Document, DocumentIndexChunk.doc_id == Document.id)
                .join(
                    DocumentIndexHead,
                    and_(
                        DocumentIndexHead.doc_id == DocumentIndexChunk.doc_id,
                        DocumentIndexHead.active_version_id
                        == DocumentIndexChunk.index_version_id,
                    ),
                )
                .where(versioned_expr > 0)
            )
            versioned_stmt = _apply_document_filters(versioned_stmt)
            versioned_stmt = versioned_stmt.order_by(
                versioned_score.desc(), DocumentIndexChunk.id.asc()
            ).limit(limit)
            versioned_rows = (await self.db.execute(versioned_stmt)).all()

        versioned_provenance = await self.indexes.get_provenance_by_chunk_ids(
            [
                chunk.id
                for chunk, _, _ in versioned_rows
                if isinstance(chunk, DocumentIndexChunk)
            ]
        )

        recalled: list[HybridResult] = []
        for chunk, doc, raw_score in [*legacy_rows, *versioned_rows]:
            provenance = (
                versioned_provenance.get(chunk.id)
                if isinstance(chunk, DocumentIndexChunk)
                else None
            )
            if isinstance(chunk, DocumentIndexChunk) and provenance is None:
                continue
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
                    index_version_id=(
                        chunk.index_version_id
                        if isinstance(chunk, DocumentIndexChunk)
                        else None
                    ),
                    page_start=provenance.page_start if provenance else None,
                    page_end=provenance.page_end if provenance else None,
                    char_start=provenance.char_start if provenance else None,
                    char_end=provenance.char_end if provenance else None,
                    line_start=provenance.line_start if provenance else None,
                    line_end=provenance.line_end if provenance else None,
                    heading_path=(
                        list(provenance.heading_path_json or [])
                        if provenance
                        else []
                    ),
                    source_kind=(provenance.source_kind if provenance else None),
                    parser_version=(provenance.parser_version if provenance else None),
                )
            )
        recalled.sort(
            key=lambda item: (item.bm25_score or 0.0, -item.chunk_id),
            reverse=True,
        )
        return recalled[:limit]

    def _rrf_merge(
        self,
        vector_list: list[HybridResult],
        bm25_list: list[HybridResult],
        top_k: int,
    ) -> list[HybridResult]:
        scores: dict[tuple[str, int], float] = {}
        results: dict[tuple[str, int], HybridResult] = {}

        def _key(result: HybridResult) -> tuple[str, int]:
            return (result.index_version_id or "legacy", result.chunk_id)

        for rank, r in enumerate(vector_list):
            key = _key(r)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            r.matched_via.append("vector")
            results[key] = r
        for rank, r in enumerate(bm25_list):
            key = _key(r)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            existing = results.get(key)
            if existing is not None:
                existing.matched_via.append("bm25")
                existing.bm25_score = r.bm25_score
                for kw in r.matched_keywords:
                    if kw not in existing.matched_keywords:
                        existing.matched_keywords.append(kw)
            else:
                r.matched_via.append("bm25")
                results[key] = r
        for key, score in scores.items():
            results[key].score = score
            results[key].fusion_score = score
        ranked = sorted(results.values(), key=lambda r: r.score, reverse=True)
        return ranked[:top_k]
