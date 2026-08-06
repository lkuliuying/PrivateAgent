"""R2.1 无答案拒答：证据充分性策略测试。

覆盖：
- 策略单元：空结果 / 分数过低 / 单渠道弱命中 / 多渠道达标 / 重排不可用 / 策略关闭；
- retrieve_with_evidence 集成：拒答返回空结果 + 结构化原因；
- build_system_prompt：拒答时不注入任何资料、明确说明资料不足；
- search_knowledge_base 工具：拒答输出结构化证据字段；
- 评测门禁：min_abstention_rate 生效与分数快照采集。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from personal_assistant.core.rag_evidence import (
    REASON_EVIDENCE_INSUFFICIENT,
    REASON_NO_RESULTS,
    REASON_PASSED,
    REASON_RERANK_UNAVAILABLE,
    REASON_SINGLE_CHANNEL_WEAK,
    EvidenceDecision,
    RagEvidencePolicy,
)


def _hit(score: float, via: list[str] | None = None, rerank: float | None = 0.8) -> SimpleNamespace:
    return SimpleNamespace(
        doc_id=1,
        chunk_id=1,
        score=score,
        fusion_score=0.5,
        rerank_score=rerank,
        bm25_score=2.0,
        matched_via=via or ["vector", "bm25"],
    )


class TestEvidencePolicyUnit:
    def test_disabled_policy_never_abstains(self) -> None:
        policy = RagEvidencePolicy(enabled=False)
        decision = policy.decide([])
        assert decision.abstain is False
        assert decision.reason_code == REASON_PASSED

    def test_no_results_abstains(self) -> None:
        decision = RagEvidencePolicy().decide([])
        assert decision.abstain is True
        assert decision.reason_code == REASON_NO_RESULTS

    def test_low_final_score_abstains(self) -> None:
        decision = RagEvidencePolicy(min_final_score=0.30).decide([_hit(0.10)])
        assert decision.abstain is True
        assert decision.reason_code == REASON_EVIDENCE_INSUFFICIENT
        assert decision.scores and decision.scores[0]["score"] == 0.10

    def test_single_channel_weak_abstains(self) -> None:
        policy = RagEvidencePolicy(min_final_score=0.20, single_channel_min_final_score=0.45)
        decision = policy.decide([_hit(0.40, via=["bm25"])])
        assert decision.abstain is True
        assert decision.reason_code == REASON_SINGLE_CHANNEL_WEAK

    def test_single_channel_strong_passes(self) -> None:
        policy = RagEvidencePolicy(min_final_score=0.20, single_channel_min_final_score=0.45)
        decision = policy.decide([_hit(0.60, via=["bm25"])])
        assert decision.abstain is False
        assert decision.reason_code == REASON_PASSED

    def test_multi_channel_above_min_passes(self) -> None:
        policy = RagEvidencePolicy(min_final_score=0.30, single_channel_min_final_score=0.45)
        decision = policy.decide([_hit(0.35, via=["vector", "bm25"])])
        assert decision.abstain is False

    def test_rerank_unavailable_passes_through_with_reason(self) -> None:
        decision = RagEvidencePolicy().decide([_hit(0.05, rerank=None)])
        assert decision.abstain is False
        assert decision.reason_code == REASON_RERANK_UNAVAILABLE

    def test_policy_version_is_recorded(self) -> None:
        decision = RagEvidencePolicy().decide([_hit(0.9)])
        assert decision.policy_version == "rag-evidence-v1"


class TestRetrieveWithEvidence:
    @pytest.mark.asyncio
    async def test_retrieve_with_evidence_abstains_and_returns_empty(self, monkeypatch):
        from personal_assistant.core.hybrid_retrieval import HybridRetriever

        policy = RagEvidencePolicy(min_final_score=0.30)
        retriever = HybridRetriever(object())

        async def fake_retrieve(query, top_k=5, filters=None):
            del top_k, filters
            return [
                _hit(0.10, via=["bm25"], rerank=0.15),
                _hit(0.05, via=["vector"], rerank=0.10),
            ]

        monkeypatch.setattr(retriever, "retrieve", fake_retrieve)
        results, decision = await retriever.retrieve_with_evidence(
            "查不到的问题", top_k=5, policy=policy
        )
        assert results == []
        assert decision.abstain is True
        assert decision.reason_code == REASON_EVIDENCE_INSUFFICIENT

    @pytest.mark.asyncio
    async def test_retrieve_with_evidence_keeps_strong_results(self, monkeypatch):
        from personal_assistant.core.hybrid_retrieval import HybridRetriever

        policy = RagEvidencePolicy(min_final_score=0.30)
        retriever = HybridRetriever(object())
        strong = _hit(0.80, via=["vector", "bm25"], rerank=0.82)

        async def fake_retrieve(query, top_k=5, filters=None):
            del top_k, filters
            return [strong]

        monkeypatch.setattr(retriever, "retrieve", fake_retrieve)
        results, decision = await retriever.retrieve_with_evidence(
            "有答案的问题", top_k=5, policy=policy
        )
        assert results == [strong]
        assert decision.abstain is False

    @pytest.mark.asyncio
    async def test_rag_service_abstention_prompt_has_no_references(self, db):
        from personal_assistant.core.rag import RagService

        class StubRetriever:
            def __init__(self, db, provider=None) -> None:
                del db, provider

            async def retrieve_with_evidence(self, query, top_k=5, filters=None, policy=None):
                del query, top_k, filters, policy
                return [], EvidenceDecision(
                    abstain=True,
                    reason_code=REASON_EVIDENCE_INSUFFICIENT,
                    policy_version="rag-evidence-v1",
                    detail="分数过低",
                )

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            "personal_assistant.core.hybrid_retrieval.HybridRetriever", StubRetriever
        )
        try:
            svc = RagService(db)
            chunks, decision = await svc.retrieve_with_evidence("问题")
            assert chunks == []
            assert decision.abstain is True
            prompt = RagService.build_system_prompt(chunks, evidence=decision)
            assert "evidence_insufficient" in prompt
            assert "未在知识库中找到相关资料" in prompt
            assert "<reference_material>" not in prompt
        finally:
            monkeypatch.undo()

    @pytest.mark.asyncio
    async def test_rag_service_keeps_normal_prompt_when_no_decision(self, db):
        from personal_assistant.core.rag import RagService

        del db
        prompt = RagService.build_system_prompt([], evidence=None)
        assert "未在知识库中找到相关资料" in prompt
        assert "evidence_insufficient" not in prompt


class TestSearchToolAbstention:
    @pytest.mark.asyncio
    async def test_search_tool_returns_structured_insufficient_evidence(self, db, monkeypatch):
        from personal_assistant.agents import CancellationToken
        from personal_assistant.core.rag import RagService
        from personal_assistant.core.rag_tool_adapter import build_rag_tool_registry

        async def fake_retrieve_with_evidence(
            self, query, top_k=5, filters=None, policy=None
        ):
            del self, query, top_k, filters, policy
            return [], EvidenceDecision(
                abstain=True,
                reason_code=REASON_EVIDENCE_INSUFFICIENT,
                policy_version="rag-evidence-v1",
                detail="最高命中分数低于阈值",
            )

        monkeypatch.setattr(RagService, "retrieve_with_evidence", fake_retrieve_with_evidence)
        spec = build_rag_tool_registry(db).get("search_knowledge_base")
        assert spec is not None
        output = await spec.executor(
            {"query": "不存在的问题"},
            CancellationToken(),
        )
        assert output["count"] == 0
        assert output["results"] == []
        assert output["evidence_insufficient"] is True
        assert output["evidence"]["reason_code"] == REASON_EVIDENCE_INSUFFICIENT
        assert output["evidence"]["policy_version"] == "rag-evidence-v1"
        spec._output_validator.validate(output)


class TestEvaluationAbstentionGate:
    @pytest.mark.asyncio
    async def test_min_abstention_gate_fails_when_no_answer_returns_results(self):
        from personal_assistant.core.rag_evaluation import (
            RetrievalEvaluationCase,
            RetrievalGate,
            evaluate_retrieval,
        )

        case = RetrievalEvaluationCase(
            id="no-answer",
            query="absent topic",
            relevant_doc_ids=frozenset(),
            expect_empty=True,
        )

        async def retrieve(query: str, top_k: int):
            del query, top_k
            return [SimpleNamespace(doc_id=3, content="unrelated but returned")]

        report = await evaluate_retrieval(
            [case],
            retrieve,
            gate=RetrievalGate(
                min_abstention_rate=0.8, max_p95_latency_ms=10_000
            ),
        )
        assert report.abstention_rate == 0.0
        assert report.passed is False
        assert "abstention_rate" in report.failures

    @pytest.mark.asyncio
    async def test_abstention_gate_not_enforced_by_default(self):
        from personal_assistant.core.rag_evaluation import (
            RetrievalEvaluationCase,
            RetrievalGate,
            evaluate_retrieval,
        )

        case = RetrievalEvaluationCase(
            id="no-answer",
            query="absent topic",
            relevant_doc_ids=frozenset(),
            expect_empty=True,
        )

        async def retrieve(query: str, top_k: int):
            del query, top_k
            return [SimpleNamespace(doc_id=3, content="unrelated")]

        report = await evaluate_retrieval(
            [case],
            retrieve,
            gate=RetrievalGate(max_p95_latency_ms=10_000),
        )
        assert report.abstention_rate == 0.0
        assert report.passed is True

    @pytest.mark.asyncio
    async def test_evaluation_snapshots_scores_for_distribution(self):
        from personal_assistant.core.rag_evaluation import (
            RetrievalEvaluationCase,
            RetrievalGate,
            evaluate_retrieval,
        )

        case = RetrievalEvaluationCase(
            id="known",
            query="query",
            relevant_doc_ids=frozenset({1}),
        )

        async def retrieve(query: str, top_k: int):
            del query, top_k
            return [
                SimpleNamespace(
                    doc_id=1,
                    content="support",
                    score=0.72,
                    fusion_score=0.5,
                    rerank_score=0.8,
                    bm25_score=3.0,
                    matched_via=["vector", "bm25"],
                )
            ]

        report = await evaluate_retrieval(
            [case], retrieve, gate=RetrievalGate(max_p95_latency_ms=10_000)
        )
        scores = report.cases[0].scores
        assert len(scores) == 1
        assert scores[0]["score"] == 0.72
        assert scores[0]["matched_via"] == ["vector", "bm25"]
        assert "content" not in scores[0]
