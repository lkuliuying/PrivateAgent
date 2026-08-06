"""Deterministic retrieval quality and latency gates for RAG rollouts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from time import perf_counter
from typing import Awaitable, Callable, Protocol, Sequence


class RetrievalResult(Protocol):
    doc_id: int
    content: str


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationCase:
    id: str
    query: str
    relevant_doc_ids: frozenset[int]
    evidence_terms: tuple[str, ...] = ()
    relevance_mode: str = "all"
    expect_empty: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.query.strip():
            raise ValueError("evaluation case id and query are required")
        if not self.relevant_doc_ids and not self.expect_empty:
            raise ValueError("evaluation case must declare relevant documents")
        if any(not term.strip() for term in self.evidence_terms):
            raise ValueError("evaluation evidence terms cannot be empty")
        if self.relevance_mode not in {"all", "any"}:
            raise ValueError("evaluation relevance mode must be all or any")


@dataclass(frozen=True, slots=True)
class RetrievalGate:
    min_recall_at_k: float = 0.8
    min_mrr: float = 0.7
    min_citation_correctness: float = 0.8
    max_empty_recall_rate: float = 0.1
    max_p95_latency_ms: float = 2_000.0
    # R2.1：无答案 case 的最低拒答率。None 表示只观察不计门禁（默认，向后兼容）；
    # 正式发布门禁由 evaluate_rag.py 显式传入（--min-abstention）。
    min_abstention_rate: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalCaseResult:
    id: str
    recall_at_k: float
    reciprocal_rank: float
    retrieved_doc_ids: tuple[int, ...]
    citation_supported: bool
    latency_ms: float
    scores: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationReport:
    top_k: int
    case_count: int
    recall_at_k: float
    mrr: float
    citation_correctness: float
    empty_recall_rate: float
    abstention_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    passed: bool
    failures: tuple[str, ...] = field(default_factory=tuple)
    cases: tuple[RetrievalCaseResult, ...] = field(default_factory=tuple)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _score_snapshot(results: Sequence[RetrievalResult]) -> tuple[dict, ...]:
    """提取每条结果的分数快照（R2.1 分数分布报告；不含查询与正文）。"""
    out: list[dict] = []
    for result in results:
        via = getattr(result, "matched_via", None)
        channels = [str(v) for v in via] if isinstance(via, (list, tuple)) else []
        out.append(
            {
                "doc_id": int(getattr(result, "doc_id", 0)),
                "chunk_id": getattr(result, "chunk_id", None),
                "score": getattr(result, "score", None),
                "fusion_score": getattr(result, "fusion_score", None),
                "rerank_score": getattr(result, "rerank_score", None),
                "bm25_score": getattr(result, "bm25_score", None),
                "matched_via": channels,
            }
        )
    return tuple(out)


async def evaluate_retrieval(
    cases: Sequence[RetrievalEvaluationCase],
    retrieve: Callable[[str, int], Awaitable[Sequence[RetrievalResult]]],
    *,
    top_k: int = 5,
    gate: RetrievalGate | None = None,
) -> RetrievalEvaluationReport:
    if not cases:
        raise ValueError("at least one evaluation case is required")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    gate = gate or RetrievalGate()
    case_results: list[RetrievalCaseResult] = []
    expect_empty_count = 0
    absten_expect_empty = 0

    for case in cases:
        started = perf_counter()
        results = list(await retrieve(case.query, top_k))[:top_k]
        latency_ms = (perf_counter() - started) * 1_000.0
        retrieved_doc_ids = tuple(int(result.doc_id) for result in results)
        if case.expect_empty:
            expect_empty_count += 1
            if not retrieved_doc_ids:
                absten_expect_empty += 1
            recall = 0.0
            reciprocal_rank = 0.0
            citation_supported = False
        else:
            retrieved_relevant = case.relevant_doc_ids.intersection(retrieved_doc_ids)
            recall = (
                float(bool(retrieved_relevant))
                if case.relevance_mode == "any"
                else len(retrieved_relevant) / len(case.relevant_doc_ids)
            )
            reciprocal_rank = 0.0
            for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
                if doc_id in case.relevant_doc_ids:
                    reciprocal_rank = 1.0 / rank
                    break
            normalized_terms = tuple(term.casefold() for term in case.evidence_terms)
            citation_supported = any(
                int(result.doc_id) in case.relevant_doc_ids
                and (
                    not normalized_terms
                    or all(
                        term in str(getattr(result, "content", "")).casefold()
                        for term in normalized_terms
                    )
                )
                for result in results
            )
        case_results.append(
            RetrievalCaseResult(
                id=case.id,
                recall_at_k=recall,
                reciprocal_rank=reciprocal_rank,
                retrieved_doc_ids=retrieved_doc_ids,
                citation_supported=citation_supported,
                latency_ms=latency_ms,
                scores=_score_snapshot(results),
            )
        )

    count = len(case_results)
    graded = sum(not case.expect_empty for case in cases)
    if graded == 0:
        recall_at_k = 0.0
        mrr = 0.0
        citation_correctness = 0.0
        empty_recall_rate = 0.0
    else:
        recall_at_k = sum(
            result.recall_at_k
            for case, result in zip(cases, case_results, strict=True)
            if not case.expect_empty
        ) / graded
        mrr = sum(
            result.reciprocal_rank
            for case, result in zip(cases, case_results, strict=True)
            if not case.expect_empty
        ) / graded
        citation_correctness = sum(
            int(result.citation_supported)
            for case, result in zip(cases, case_results, strict=True)
            if not case.expect_empty
        ) / graded
        empty_recall_rate = sum(
            not result.retrieved_doc_ids
            for case, result in zip(cases, case_results, strict=True)
            if not case.expect_empty
        ) / graded
    abstention_rate = (
        (absten_expect_empty / expect_empty_count) if expect_empty_count else 0.0
    )
    latencies = [item.latency_ms for item in case_results]
    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    failures: list[str] = []
    if graded and recall_at_k < gate.min_recall_at_k:
        failures.append("recall_at_k")
    if graded and mrr < gate.min_mrr:
        failures.append("mrr")
    if graded and citation_correctness < gate.min_citation_correctness:
        failures.append("citation_correctness")
    if graded and empty_recall_rate > gate.max_empty_recall_rate:
        failures.append("empty_recall_rate")
    if p95 > gate.max_p95_latency_ms:
        failures.append("p95_latency_ms")
    if (
        gate.min_abstention_rate is not None
        and expect_empty_count > 0
        and abstention_rate < gate.min_abstention_rate
    ):
        failures.append("abstention_rate")
    return RetrievalEvaluationReport(
        top_k=top_k,
        case_count=count,
        recall_at_k=recall_at_k,
        mrr=mrr,
        citation_correctness=citation_correctness,
        empty_recall_rate=empty_recall_rate,
        abstention_rate=abstention_rate,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        passed=not failures,
        failures=tuple(failures),
        cases=tuple(case_results),
    )
