"""v0.9.0 H0 §7：上下文 budget / compaction DTO 契约。

红线（计划 §5.4/§11）：用量只来自 provider usage、受验证 tokenizer 或
Runtime 统一计数；不按字符数/消息数伪造百分比。无法准确计量时
``source=unavailable`` + 原因，不显示虚假百分比；``usage_percent`` 域
0..100，超限封顶 100 并携带错误码，禁止负数/超过 100 的裸数值。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UsageSource(StrEnum):
    """用量来源（冻结词汇；H0 §7.1）。"""

    PROVIDER_USAGE = "provider_usage"
    TOKENIZER = "tokenizer"
    RUNTIME_COUNT = "runtime_count"
    UNAVAILABLE = "unavailable"


# 压缩状态集合（冻结；H0 §7.2）
COMPACTION_STATES = frozenset({"idle", "compacting", "compacted", "failed"})


class ContextBudget(BaseModel):
    """typed context budget（H0 §7.1 字段集合）。"""

    model_config = ConfigDict(extra="forbid")

    used_tokens: int = Field(ge=0)
    max_context_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=0)
    # 会话内所有模型请求按 input token 加权的缓存命中率；Provider 未报告
    # 或尚无可计量输入时为 None，前端显示“--”，不伪造为 0%。
    cache_hit_percent: float | None = Field(default=None, ge=0, le=100)
    source: UsageSource
    compaction_state: str
    last_compacted_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_state(self) -> "ContextBudget":
        if self.compaction_state not in COMPACTION_STATES:
            raise ValueError(
                f"compaction_state must be one of {sorted(COMPACTION_STATES)}"
            )
        return self

    @property
    def usage_percent(self) -> int | None:
        """0..100 整数；不可用（无窗口/无计量来源）时返回 None。"""
        if self.source is UsageSource.UNAVAILABLE or self.max_context_tokens <= 0:
            return None
        percent = round(self.used_tokens * 100 / self.max_context_tokens)
        return min(max(percent, 0), 100)

    def to_response(self) -> dict:
        """API 响应体（字段与 H0 §7.1 示例一致）。"""
        from .timeutil import format_rfc3339_utc

        return {
            "used_tokens": self.used_tokens,
            "max_context_tokens": self.max_context_tokens,
            "reserved_output_tokens": self.reserved_output_tokens,
            "cache_hit_percent": self.cache_hit_percent,
            "usage_percent": self.usage_percent,
            "source": str(self.source.value),
            "compaction_state": self.compaction_state,
            "last_compacted_at": format_rfc3339_utc(self.last_compacted_at),
            "error_code": self.error_code,
            "error_reason": self.error_reason,
        }
