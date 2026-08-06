"""RAG 证据充分性策略（R2.1 无答案拒答）。

检索层在返回 top-k 前对融合后的最终分数做可解释的"证据不足"判断：

- 不同检索器（Chroma 向量、MySQL FULLTEXT/BM25）的原始分数量纲不同，
  不直接共用阈值；策略只对 **重排后的归一化最终分数** 判阈值
  （``HybridResult.score`` = 0.35 * fusion_norm + 0.65 * semantic_norm，范围 0..1）。
- 只有单一命中渠道（仅向量或仅 BM25）的结果需要更高的分数门槛，
  因为单渠道命中更容易是弱相关或巧合。
- 证据不足时不返回弱结果，由回答层说明"资料不足"，不生成伪引用。
- 重排不可用（如 embedding provider 故障、纯 BM25 模式）时无法归一化分数，
  策略**不拒答**（保持 legacy 行为），但记录 ``rerank_unavailable`` 观察原因，
  避免在降级链路上把所有检索结果都吞掉。

阈值可配置（见 config.py 的 ``PA_RAG_EVIDENCE_*``），版本号随策略变更递增。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

EVIDENCE_POLICY_VERSION = "rag-evidence-v1"

# 结构化原因码（回答层/工具输出可见，便于诊断与测试断言）
REASON_NO_RESULTS = "no_results"
REASON_EVIDENCE_INSUFFICIENT = "evidence_insufficient"
REASON_SINGLE_CHANNEL_WEAK = "single_channel_weak"
REASON_RERANK_UNAVAILABLE = "rerank_unavailable"
REASON_PASSED = "sufficient_evidence"


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    """检索层"证据是否充分"的决策结果。"""

    abstain: bool
    reason_code: str
    policy_version: str
    detail: str = ""
    scores: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RagEvidencePolicy:
    """证据充分性策略参数。``enabled=False`` 时永不拒答（legacy 行为）。"""

    enabled: bool = True
    # 最终归一化分数下限（0..1）。低于该值视为证据不足。
    min_final_score: float = 0.30
    # 单一命中渠道（仅向量或仅 BM25）的更高下限，防止单渠道弱命中填数。
    single_channel_min_final_score: float = 0.45
    version: str = EVIDENCE_POLICY_VERSION

    def decide(self, results: list[Any]) -> EvidenceDecision:
        """对检索结果做证据充分性判断。

        ``results`` 元素须具备 ``score`` / ``matched_via`` 属性
        （``HybridResult``），缺失分数时按未打分处理。
        """
        if not self.enabled:
            return EvidenceDecision(
                abstain=False,
                reason_code=REASON_PASSED,
                policy_version=self.version,
                detail="evidence policy disabled",
            )
        if not results:
            return EvidenceDecision(
                abstain=True,
                reason_code=REASON_NO_RESULTS,
                policy_version=self.version,
                detail="检索未返回任何结果",
            )
        scores = _score_snapshots(results)
        top = results[0]
        top_score = getattr(top, "score", 0.0) or 0.0
        top_rerank = getattr(top, "rerank_score", None)
        if top_rerank is None:
            # 重排未运行（provider 不可用 / 纯 BM25 模式）：无法归一化，不拒答，
            # 只记录观察原因，避免降级链路上误吞全部结果。
            return EvidenceDecision(
                abstain=False,
                reason_code=REASON_RERANK_UNAVAILABLE,
                policy_version=self.version,
                detail="重排不可用，保留 legacy 检索行为（观察项）",
                scores=scores,
            )
        if top_score < self.min_final_score:
            return EvidenceDecision(
                abstain=True,
                reason_code=REASON_EVIDENCE_INSUFFICIENT,
                policy_version=self.version,
                detail=(
                    f"最高命中分数 {top_score:.3f} 低于阈值 "
                    f"{self.min_final_score:.3f}"
                ),
                scores=scores,
            )
        channels = _channels(top)
        if len(channels) == 1 and top_score < self.single_channel_min_final_score:
            return EvidenceDecision(
                abstain=True,
                reason_code=REASON_SINGLE_CHANNEL_WEAK,
                policy_version=self.version,
                detail=(
                    f"单一命中渠道 {channels[0]}，分数 {top_score:.3f} 低于"
                    f"单渠道阈值 {self.single_channel_min_final_score:.3f}"
                ),
                scores=scores,
            )
        return EvidenceDecision(
            abstain=False,
            reason_code=REASON_PASSED,
            policy_version=self.version,
            detail="证据充分",
            scores=scores,
        )


def _channels(result: Any) -> list[str]:
    via = getattr(result, "matched_via", None)
    if isinstance(via, (list, tuple, set)):
        return [str(v) for v in via if str(v)]
    return []


def _score_snapshots(results: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    """提取每条结果的分数快照（用于评测报告；不含正文与查询）。"""
    out: list[dict[str, Any]] = []
    for item in results:
        out.append(
            {
                "doc_id": getattr(item, "doc_id", None),
                "chunk_id": getattr(item, "chunk_id", None),
                "score": getattr(item, "score", None),
                "fusion_score": getattr(item, "fusion_score", None),
                "rerank_score": getattr(item, "rerank_score", None),
                "bm25_score": getattr(item, "bm25_score", None),
                "matched_via": list(_channels(item)),
            }
        )
    return tuple(out)
