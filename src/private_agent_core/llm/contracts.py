"""Contracts shared by model gateway implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ModelTextDelta:
    """公开消息增量；不允许携带供应商原始条目或推理内容。"""

    message_id: str
    phase: Literal["commentary", "final_answer"] | None
    delta: str

    def __post_init__(self) -> None:
        if not isinstance(self.message_id, str) or not 1 <= len(self.message_id) <= 200:
            raise ValueError("公开消息标识长度无效")
        if self.phase not in {None, "commentary", "final_answer"}:
            raise ValueError("公开消息阶段无效")
        if not isinstance(self.delta, str):
            raise ValueError("公开消息增量必须为字符串")


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    streaming: bool
    native_tool_calls: bool
    structured_output: bool
    usage_reporting: bool
    cancellation: bool
    max_context_tokens: int | None = None
    output_token_limit: bool = False


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 2
    initial_backoff_seconds: float = 0.2
    max_backoff_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_attempts > 10:
            raise ValueError("max_attempts 必须在 1 到 10 之间")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds 不能为负数")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds 不能小于 initial_backoff_seconds")


class ModelGatewayError(RuntimeError):
    """Normalized model failure without provider credentials or response bodies."""

    def __init__(self, message: str, *, code: str, provider: str) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
