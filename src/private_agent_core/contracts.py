"""桌面与服务端共用、独立于模型供应商的有界运行契约。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class AgentRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    LIMIT_EXCEEDED = "limit_exceeded"


class AgentStepKind(StrEnum):
    MODEL = "model"
    TOOL = "tool"


class AgentStepStatus(StrEnum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class AgentEventType(StrEnum):
    RUN_STARTED = "run.started"
    CONTEXT_PREPARED = "context.prepared"
    MODEL_STARTED = "model.started"
    MODEL_COMPLETED = "model.completed"
    OUTPUT_VALIDATION_STARTED = "output.validation_started"
    OUTPUT_VALIDATION_PASSED = "output.validation_passed"
    OUTPUT_VALIDATION_FAILED = "output.validation_failed"
    TOOL_REQUESTED = "tool.requested"
    TOOL_STARTED = "tool.started"
    TOOL_APPROVAL_REQUIRED = "tool.approval_required"
    TOOL_APPROVAL_RESOLVED = "tool.approval_resolved"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_TIMED_OUT = "run.timed_out"
    RUN_LIMIT_EXCEEDED = "run.limit_exceeded"
    CHAT_OUTPUT_PERSISTED = "chat.output_persisted"
    # v0.6.0 C0 §4.5：稳定事件（plan/artifact）
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"
    PLAN_ITEM_CHANGED = "plan.item_changed"
    ARTIFACT_CREATED = "artifact.created"
    # v0.7.0 E0 §1：PatchSet durable 事件（additive，payload 脱敏有界）
    PATCH_SET_PREVIEW_CREATED = "patch_set.preview_created"
    PATCH_SET_APPLIED = "patch_set.applied"
    PATCH_SET_ROLLED_BACK = "patch_set.rolled_back"
    PATCH_SET_FAILED = "patch_set.failed"
    PATCH_SET_UNKNOWN = "patch_set.unknown"
    # v0.9.0 H0 §7.2/§8：公开决策摘要与上下文压缩 durable 事件（additive）。
    # decision.summary payload 只含结构化公开摘要（目标/方法/判断/依据/
    # 下一步/风险/验证），不含隐藏 chain-of-thought。
    DECISION_SUMMARY = "decision.summary"
    CONTEXT_COMPACTION_STARTED = "context.compaction_started"
    CONTEXT_COMPACTION_COMPLETED = "context.compaction_completed"
    CONTEXT_COMPACTION_FAILED = "context.compaction_failed"
    PERMISSION_DOWNGRADED = "permission.downgraded"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolCall(ContractModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelToolDefinition(ContractModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str = Field(min_length=1, max_length=8_000)
    input_schema: dict[str, Any]

    @model_validator(mode="after")
    def require_object_schema(self) -> ModelToolDefinition:
        if self.input_schema.get("type") != "object":
            raise ValueError("工具 input_schema 的根类型必须是 object")
        return self


class ToolResult(ContractModel):
    tool_call_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    success: bool
    output: Any = None
    error: str | None = Field(default=None, max_length=4_000)
    error_code: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9_]{1,64}$",
    )
    approval_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def require_error_for_failure(self) -> ToolResult:
        if not self.success and not self.error:
            raise ValueError("失败的工具结果必须包含 error")
        if self.success and (self.error or self.error_code):
            raise ValueError("成功的工具结果不能包含 error 或 error_code")
        if self.success and self.approval_id:
            raise ValueError("成功的工具结果不能包含 approval_id")
        if self.error_code == "approval_required" and not self.approval_id:
            raise ValueError("approval_required 工具结果必须包含 approval_id")
        if self.approval_id and self.error_code != "approval_required":
            raise ValueError("approval_id 只能用于 approval_required 工具结果")
        return self


class TokenUsage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ProviderState(ContractModel):
    """供应商原生输出仅用于同一路由续接，不进入公开正文或工具结果。"""

    api_format: Literal["responses"] = "responses"
    route: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_json: str = Field(min_length=2, max_length=1_500_000, repr=False)


class ModelMessage(ContractModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    name: str | None = Field(default=None, max_length=200)
    tool_call_id: str | None = Field(default=None, max_length=200)
    tool_calls: tuple[ToolCall, ...] = ()
    phase: Literal["commentary", "final_answer"] | None = None
    provider_state: ProviderState | None = Field(default=None, repr=False)

    @model_serializer(mode="wrap")
    def serialize_message(self, handler):
        data = handler(self)
        # 旧协议不增加空字段，保持既有小窗口预算和持久化兼容性。
        for key in ("phase", "provider_state"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def validate_role_fields(self) -> ModelMessage:
        if self.role == "tool" and (not self.name or not self.tool_call_id):
            raise ValueError("tool 消息必须包含 name 和 tool_call_id")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("只有 assistant 消息可以携带 tool_calls")
        if self.role != "assistant" and (self.phase is not None or self.provider_state is not None):
            raise ValueError("只有 assistant 消息可以携带供应商续接状态")
        return self


def _validate_local_schema_references(
    value: Any,
    *,
    depth: int = 0,
    node_count: list[int] | None = None,
) -> None:
    if depth > 32:
        raise ValueError("model output schema nesting exceeds 32")
    counter = node_count if node_count is not None else [0]
    counter[0] += 1
    if counter[0] > 2_048:
        raise ValueError("model output schema exceeds 2048 nodes")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ValueError("model output schema forbids remote references")
            _validate_local_schema_references(
                child,
                depth=depth + 1,
                node_count=counter,
            )
    elif isinstance(value, list):
        for child in value:
            _validate_local_schema_references(
                child,
                depth=depth + 1,
                node_count=counter,
            )


class ModelOutputFormat(ContractModel):
    """Provider-neutral strict JSON output request."""

    name: str = Field(default="agent_output", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str | None = Field(default=None, max_length=1_024)
    json_schema: dict[str, Any]
    strict: Literal[True] = True

    @model_validator(mode="after")
    def validate_json_schema(self) -> ModelOutputFormat:
        if self.json_schema.get("type") != "object":
            raise ValueError("model output schema root type must be object")
        try:
            encoded = json.dumps(
                self.json_schema,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("model output schema must be JSON serializable") from exc
        if len(encoded) > 64 * 1024:
            raise ValueError("model output schema exceeds 64 KiB")
        _validate_local_schema_references(self.json_schema)
        try:
            Draft202012Validator.check_schema(self.json_schema)
        except SchemaError as exc:
            raise ValueError("model output schema is invalid") from exc
        return self


class AgentRunCheckpoint(ContractModel):
    checkpoint_version: Literal[1] = 1
    run_id: str = Field(min_length=1, max_length=36)
    event_sequence: int = Field(ge=1)
    conversation: tuple[ModelMessage, ...] = Field(min_length=1)
    pending_tool_calls: tuple[ToolCall, ...] = Field(min_length=1)
    tool_call_count: int = Field(ge=1)
    usage: TokenUsage


class ModelRequest(ContractModel):
    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    tools: tuple[ModelToolDefinition, ...] = ()
    output_format: ModelOutputFormat | None = None
    # v0.7.0 验收修复（P0-1）：run 的 reasoning_effort 透传到模型请求
    # （additive；OpenAI 系请求体透传，Ollama/Claude 由 adapter 自行决定）。
    reasoning_effort: str | None = Field(default=None, max_length=32)
    max_output_tokens: int | None = Field(default=None, ge=1, le=131072, strict=True)

    @model_validator(mode="after")
    def require_unique_tool_names(self) -> ModelRequest:
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("模型请求中的工具名必须唯一")
        return self


class ModelResponse(ContractModel):
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = Field(default=None, max_length=200)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    request_id: str | None = Field(default=None, max_length=300)
    latency_ms: float | None = Field(default=None, ge=0)
    phase: Literal["commentary", "final_answer"] | None = None
    provider_state: ProviderState | None = Field(default=None, repr=False)

    @model_serializer(mode="wrap")
    def serialize_response(self, handler):
        data = handler(self)
        for key in ("phase", "provider_state"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    def as_message(self) -> ModelMessage:
        return ModelMessage(role="assistant", content=self.text, tool_calls=self.tool_calls,
                            phase=self.phase, provider_state=self.provider_state)

    def require_complete(self) -> None:
        """部分响应不能成为工具执行请求或最终验收候选。"""
        if self.finish_reason in {"length", "max_tokens", "max_output_tokens", "incomplete", "failed", "cancelled", "content_filter"}:
            raise ValueError("模型响应未完整结束，不能执行工具或确认完成")
        if self.phase == "final_answer" and self.tool_calls:
            raise ValueError("最终回答不能同时包含尚待执行的工具")

    @model_validator(mode="after")
    def require_unique_tool_call_ids(self) -> ModelResponse:
        call_ids = [call.id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("单次模型响应中的 tool_call id 必须唯一")
        return self


class AgentRunLimits(ContractModel):
    max_steps: int = Field(default=12, ge=1, le=1_000)
    max_tool_calls: int = Field(default=8, ge=0, le=1_000)
    max_wall_time_seconds: float = Field(default=120.0, ge=0.01, le=86_400)


class AgentStep(ContractModel):
    id: str
    ordinal: int = Field(ge=1)
    kind: AgentStepKind
    status: AgentStepStatus
    started_at: datetime
    completed_at: datetime | None = None
    tool_call_id: str | None = None
    name: str | None = None
    error: str | None = None


class AgentEvent(ContractModel):
    run_id: str
    sequence: int = Field(ge=1)
    type: AgentEventType
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    step_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(ContractModel):
    run_id: str
    status: AgentRunStatus
    output: str | None = None
    error: str | None = None
    steps: tuple[AgentStep, ...]
    tool_call_count: int = Field(ge=0)
    usage: TokenUsage
    events: tuple[AgentEvent, ...]
