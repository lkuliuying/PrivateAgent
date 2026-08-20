"""Provider-neutral contracts for bounded context assembly."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_assistant.agents.contracts import ModelMessage


class ContextContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextFragmentKind(StrEnum):
    MEMORY = "memory"
    RAG = "rag"
    SUMMARY = "summary"
    # v0.6.0 C2：项目指令 / workspace / Git 摘要（coding run 上下文）
    PROJECT = "project"


class ContextTrust(StrEnum):
    USER_CONFIRMED = "user_confirmed"
    EXTERNAL_UNTRUSTED = "external_untrusted"
    MODEL_GENERATED = "model_generated"


class ContextSelectionReason(StrEnum):
    INCLUDED = "included"
    INCLUDED_TRUNCATED = "included_truncated"
    SENSITIVE_EXCLUDED = "sensitive_excluded"
    SECTION_BUDGET = "section_budget"
    TOTAL_BUDGET = "total_budget"


class ContextFragment(ContextContract):
    id: str = Field(min_length=1, max_length=200)
    kind: ContextFragmentKind
    content: str = Field(min_length=1, max_length=200_000)
    trust: ContextTrust
    source: str = Field(min_length=1, max_length=500)
    score: float = Field(default=0.0, ge=-1_000_000, le=1_000_000)
    sensitive: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextBudget(ContextContract):
    max_total_tokens: int = Field(default=6_000, ge=128, le=1_000_000)
    max_history_tokens: int = Field(default=2_500, ge=0, le=1_000_000)
    max_memory_tokens: int = Field(default=800, ge=0, le=1_000_000)
    max_rag_tokens: int = Field(default=1_600, ge=0, le=1_000_000)
    max_summary_tokens: int = Field(default=800, ge=0, le=1_000_000)
    max_fragment_tokens: int = Field(default=600, ge=32, le=1_000_000)
    # v0.6.0 C2：项目指令/workspace/Git 摘要片段预算
    max_project_tokens: int = Field(default=800, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def section_limits_cannot_exceed_total(self) -> ContextBudget:
        for value in (
            self.max_history_tokens,
            self.max_memory_tokens,
            self.max_rag_tokens,
            self.max_summary_tokens,
            self.max_fragment_tokens,
            self.max_project_tokens,
        ):
            if value > self.max_total_tokens:
                raise ValueError("context section limit cannot exceed total limit")
        return self


class ContextSelection(ContextContract):
    id: str
    kind: str
    included: bool
    reason: ContextSelectionReason
    estimated_tokens: int = Field(ge=0)
    score: float | None = None
    source: str | None = None


class ContextBuildResult(ContextContract):
    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    estimated_tokens: int = Field(ge=1)
    section_tokens: dict[str, int]
    selections: tuple[ContextSelection, ...]
    sensitive_excluded: int = Field(ge=0)
    truncated: bool

