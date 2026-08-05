from __future__ import annotations

from dataclasses import dataclass

import pytest

from personal_assistant.core.rag_evaluation import (
    RetrievalEvaluationCase,
    RetrievalGate,
    evaluate_retrieval,
)


@dataclass(frozen=True)
class Result:
    doc_id: int
    content: str = ""


@pytest.mark.asyncio
async def test_retrieval_evaluation_computes_recall_mrr_citations_and_empty_rate():
    cases = [
        RetrievalEvaluationCase(
            id="partial",
            query="partial query",
            relevant_doc_ids=frozenset({1, 2}),
            evidence_terms=("grounded",),
        ),
        RetrievalEvaluationCase(
            id="empty",
            query="empty query",
            relevant_doc_ids=frozenset({4}),
        ),
    ]

    async def retrieve(query: str, top_k: int):
        assert top_k == 2
        if query == "partial query":
            return [Result(3, "unrelated"), Result(2, "grounded evidence")]
        return []

    report = await evaluate_retrieval(
        cases,
        retrieve,
        top_k=2,
        gate=RetrievalGate(max_p95_latency_ms=10_000),
    )

    assert report.recall_at_k == pytest.approx(0.25)
    assert report.mrr == pytest.approx(0.25)
    assert report.citation_correctness == pytest.approx(0.5)
    assert report.cases[0].citation_supported is True
    assert report.cases[1].citation_supported is False
    assert report.empty_recall_rate == pytest.approx(0.5)
    assert report.p50_latency_ms >= 0
    assert report.p95_latency_ms >= report.p50_latency_ms
    assert report.passed is False
    assert report.failures == (
        "recall_at_k",
        "mrr",
        "citation_correctness",
        "empty_recall_rate",
    )


@pytest.mark.asyncio
async def test_retrieval_evaluation_gate_passes_a_relevant_first_result():
    cases = [
        RetrievalEvaluationCase(
            id="case-a",
            query="a",
            relevant_doc_ids=frozenset({10}),
        ),
        RetrievalEvaluationCase(
            id="case-b",
            query="b",
            relevant_doc_ids=frozenset({20}),
        ),
    ]

    async def retrieve(query: str, top_k: int):
        del top_k
        return [Result(10 if query == "a" else 20, "support")]

    report = await evaluate_retrieval(
        cases,
        retrieve,
        gate=RetrievalGate(max_p95_latency_ms=10_000),
    )

    assert report.passed is True
    assert report.failures == ()
    assert report.recall_at_k == report.mrr == report.citation_correctness == 1.0
    assert report.empty_recall_rate == 0.0


@pytest.mark.asyncio
async def test_retrieval_evaluation_rejects_empty_or_invalid_cases():
    async def retrieve(query: str, top_k: int):
        del query, top_k
        return []

    with pytest.raises(ValueError, match="at least one"):
        await evaluate_retrieval([], retrieve)
    with pytest.raises(ValueError, match="relevant"):
        RetrievalEvaluationCase(
            id="invalid",
            query="query",
            relevant_doc_ids=frozenset(),
        )


@pytest.mark.asyncio
async def test_citation_correctness_requires_grounded_evidence_terms():
    cases = [
        RetrievalEvaluationCase(
            id="grounded",
            query="query",
            relevant_doc_ids=frozenset({7}),
            evidence_terms=("required phrase",),
        )
    ]

    async def wrong_chunk(query: str, top_k: int):
        del query, top_k
        return [Result(7, "same document but different passage")]

    report = await evaluate_retrieval(
        cases,
        wrong_chunk,
        gate=RetrievalGate(
            min_recall_at_k=0,
            min_mrr=0,
            min_citation_correctness=0.5,
            max_p95_latency_ms=10_000,
        ),
    )
    assert report.recall_at_k == report.mrr == 1.0
    assert report.citation_correctness == 0.0
    assert report.cases[0].citation_supported is False
    assert report.failures == ("citation_correctness",)


@pytest.mark.asyncio
async def test_any_relevance_mode_treats_duplicate_documents_as_alternatives():
    case = RetrievalEvaluationCase(
        id="duplicate-content",
        query="anchor",
        relevant_doc_ids=frozenset({10, 11, 12}),
        evidence_terms=("anchor",),
        relevance_mode="any",
    )

    async def retrieve(query: str, top_k: int):
        del query, top_k
        return [Result(11, "anchor content")]

    report = await evaluate_retrieval(
        [case], retrieve, gate=RetrievalGate(max_p95_latency_ms=10_000)
    )
    assert report.recall_at_k == 1.0
    assert report.mrr == 1.0
    assert report.citation_correctness == 1.0
    assert report.passed is True


@pytest.mark.asyncio
async def test_expect_empty_cases_are_observed_and_excluded_from_quality_gates():
    case = RetrievalEvaluationCase(
        id="no-answer",
        query="query about something absent from the corpus",
        relevant_doc_ids=frozenset(),
        expect_empty=True,
    )
    grounded = RetrievalEvaluationCase(
        id="grounded",
        query="grounded query",
        relevant_doc_ids=frozenset({5}),
    )

    async def retrieve(query: str, top_k: int):
        del top_k
        if "absent" in query:
            return []
        return [Result(5, "support")]

    report = await evaluate_retrieval(
        [case, grounded],
        retrieve,
        top_k=5,
        gate=RetrievalGate(max_p95_latency_ms=10_000),
    )
    assert report.case_count == 2
    assert report.abstention_rate == 1.0
    assert report.recall_at_k == 1.0
    assert report.mrr == 1.0
    assert report.citation_correctness == 1.0
    assert report.empty_recall_rate == 0.0
    assert report.passed is True


@pytest.mark.asyncio
async def test_expect_empty_case_with_false_positive_retrieval_reports_zero_abstention():
    case = RetrievalEvaluationCase(
        id="no-answer-fp",
        query="absent topic",
        relevant_doc_ids=frozenset(),
        expect_empty=True,
    )

    async def retrieve(query: str, top_k: int):
        del query, top_k
        return [Result(3, "unrelated but returned")]

    report = await evaluate_retrieval(
        [case], retrieve, gate=RetrievalGate(max_p95_latency_ms=10_000)
    )
    assert report.abstention_rate == 0.0
    assert report.recall_at_k == 0.0
    assert report.empty_recall_rate == 0.0
    assert report.passed is True


def test_expect_empty_still_rejects_empty_evidence_terms() -> None:
    with pytest.raises(ValueError, match="relevant"):
        RetrievalEvaluationCase(
            id="invalid-empty",
            query="query",
            relevant_doc_ids=frozenset(),
        )
    RetrievalEvaluationCase(
        id="valid-empty",
        query="query",
        relevant_doc_ids=frozenset(),
        expect_empty=True,
    )
