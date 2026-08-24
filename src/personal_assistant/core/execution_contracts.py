"""v0.9.0 H0 §8：公开执行链契约——逐轮公开决策摘要（decision.summary）。

红线（计划 §2.2/§5.5）：本模块只定义**结构化公开摘要**（目标/方法/判断/
依据/下一步/风险/验证），不得读取、持久化或展示模型隐藏
chain-of-thought；payload 有界、可审计。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# decision.summary 事件 payload 键（冻结；H0 §8）
DECISION_SUMMARY_PAYLOAD_KEYS = frozenset(
    {
        "goal",
        "method",
        "key_judgments",
        "rationale",
        "next_steps",
        "risks",
        "verification",
    }
)

_MAX_TEXT = 1000
_MAX_LIST_ITEMS = 12
_MAX_ITEM_LEN = 300


class DecisionSummary(BaseModel):
    """一轮执行的公开决策摘要（有界、可公开、可审计）。"""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(max_length=_MAX_TEXT)
    method: str = Field(default="", max_length=_MAX_TEXT)
    key_judgments: list[str] = Field(
        default_factory=list, max_length=_MAX_LIST_ITEMS
    )
    rationale: str = Field(default="", max_length=_MAX_TEXT)
    next_steps: list[str] = Field(
        default_factory=list, max_length=_MAX_LIST_ITEMS
    )
    risks: list[str] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    verification: str = Field(default="", max_length=_MAX_TEXT)

    @classmethod
    def from_payload(cls, payload: dict) -> "DecisionSummary | None":
        """从事件 payload 解析；非法/缺 goal 返回 None（不伪造摘要）。"""
        if not isinstance(payload, dict) or not payload.get("goal"):
            return None
        try:
            return cls(
                goal=str(payload.get("goal", "")),
                method=str(payload.get("method", "") or ""),
                key_judgments=[
                    str(item) for item in (payload.get("key_judgments") or [])
                ],
                rationale=str(payload.get("rationale", "") or ""),
                next_steps=[
                    str(item) for item in (payload.get("next_steps") or [])
                ],
                risks=[str(item) for item in (payload.get("risks") or [])],
                verification=str(payload.get("verification", "") or ""),
            )
        except Exception:
            return None

    def to_payload(self) -> dict:
        payload: dict = {
            "goal": self.goal,
            "method": self.method,
            "key_judgments": [
                item[:_MAX_ITEM_LEN] for item in self.key_judgments
            ],
            "rationale": self.rationale,
            "next_steps": [item[:_MAX_ITEM_LEN] for item in self.next_steps],
            "risks": [item[:_MAX_ITEM_LEN] for item in self.risks],
            "verification": self.verification,
        }
        return payload
