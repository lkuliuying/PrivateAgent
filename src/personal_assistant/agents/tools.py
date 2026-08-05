"""Versioned tool contracts and the provider-neutral validated dispatcher."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .contracts import ModelToolDefinition, ToolCall, ToolResult
from .runtime import CancellationToken


class ToolRiskLevel(StrEnum):
    SAFE = "safe"
    CONFIRM = "confirm"
    RESTRICTED = "restricted"


class ToolCapability(StrEnum):
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    PROCESS_EXECUTE = "process.execute"
    NETWORK_FETCH = "network.fetch"
    DATABASE_QUERY = "database.query"
    EXTERNAL_MCP = "external.mcp"


class ToolIdempotency(StrEnum):
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


class ToolRedactionPolicy(StrEnum):
    NONE = "none"
    SENSITIVE_KEYS = "sensitive_keys"


class ToolPolicyDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ToolDispatchCancelled(RuntimeError):
    """Raised when cancellation wins before a tool can publish a result."""


ToolExecutor = Callable[
    [dict[str, Any], CancellationToken],
    Awaitable[Any],
]


class ToolApprovalRequester(Protocol):
    async def request(
        self,
        spec: ToolSpec,
        call: ToolCall,
        arguments: Mapping[str, Any],
    ) -> str: ...


class ToolApprovalConsumer(Protocol):
    async def consume(
        self,
        spec: ToolSpec,
        call: ToolCall,
        arguments: Mapping[str, Any],
    ) -> str | None: ...


class ToolExecutionClaimView(Protocol):
    execution_id: str
    action: str
    claim_token: str | None
    output: Any


class ToolExecutionStore(Protocol):
    async def claim(
        self,
        *,
        spec: ToolSpec,
        call: ToolCall,
        arguments: Mapping[str, Any],
        approval_id: str | None = None,
    ) -> ToolExecutionClaimView: ...

    async def complete_success(
        self,
        execution_id: str,
        *,
        claim_token: str,
        output: Any,
        max_output_bytes: int,
    ) -> Any: ...

    async def complete_failure(
        self,
        execution_id: str,
        *,
        claim_token: str,
        status: str,
        error_code: str,
        error_message: str,
    ) -> Any: ...

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    }
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(
        r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"
    ),
)
_MAX_ERROR_CHARS = 2_000


def _json_clone(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )


def _reject_remote_references(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ValueError(
                    f"工具 schema 禁止远程引用：{child_path} 必须是本地片段引用"
                )
            _reject_remote_references(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_remote_references(child, path=f"{path}[{index}]")


def _compile_schema(schema: Mapping[str, Any], *, label: str) -> Draft202012Validator:
    copied = deepcopy(dict(schema))
    if copied.get("type") != "object":
        raise ValueError(f"{label} 根类型必须是 object")
    _reject_remote_references(copied)
    try:
        Draft202012Validator.check_schema(copied)
    except SchemaError as exc:
        raise ValueError(f"{label} 不是有效的 JSON Schema") from exc
    return Draft202012Validator(copied)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Immutable metadata plus an executor for one active tool version."""

    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    risk_level: ToolRiskLevel
    required_capabilities: frozenset[ToolCapability]
    timeout_ms: int
    max_output_bytes: int
    idempotency: ToolIdempotency
    supports_cancellation: bool
    redaction_policy: ToolRedactionPolicy
    executor: ToolExecutor
    sensitive_keys: frozenset[str] = _DEFAULT_SENSITIVE_KEYS
    max_input_bytes: int = 64 * 1024
    _input_validator: Draft202012Validator = field(init=False, repr=False, compare=False)
    _output_validator: Draft202012Validator = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.fullmatch(self.name):
            raise ValueError("工具名必须匹配 [a-zA-Z0-9_-]{1,64}")
        if not _VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("工具版本必须使用三段式数字版本，例如 1.0.0")
        if not self.description or len(self.description) > 8_000:
            raise ValueError("工具描述长度必须为 1..8000")
        if not 1 <= self.timeout_ms <= 600_000:
            raise ValueError("工具 timeout_ms 必须为 1..600000")
        if not 128 <= self.max_output_bytes <= 10 * 1024 * 1024:
            raise ValueError("工具 max_output_bytes 必须为 128..10485760")
        if not 128 <= self.max_input_bytes <= 1024 * 1024:
            raise ValueError("工具 max_input_bytes 必须为 128..1048576")
        if not callable(self.executor):
            raise ValueError("工具 executor 必须可调用")

        input_validator = _compile_schema(self.input_schema, label="input_schema")
        output_validator = _compile_schema(self.output_schema, label="output_schema")
        risk_level = ToolRiskLevel(self.risk_level)
        idempotency = ToolIdempotency(self.idempotency)
        redaction_policy = ToolRedactionPolicy(self.redaction_policy)
        capabilities = frozenset(
            ToolCapability(capability) for capability in self.required_capabilities
        )
        sensitive_keys = frozenset(
            key.casefold().replace("-", "_") for key in self.sensitive_keys
        )
        object.__setattr__(self, "input_schema", input_validator.schema)
        object.__setattr__(self, "output_schema", output_validator.schema)
        object.__setattr__(self, "risk_level", risk_level)
        object.__setattr__(self, "required_capabilities", capabilities)
        object.__setattr__(self, "idempotency", idempotency)
        object.__setattr__(self, "redaction_policy", redaction_policy)
        object.__setattr__(self, "sensitive_keys", sensitive_keys)
        object.__setattr__(self, "_input_validator", input_validator)
        object.__setattr__(self, "_output_validator", output_validator)

    def to_model_definition(self) -> ModelToolDefinition:
        return ModelToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
        )


class VersionedToolRegistry:
    """Holds one explicitly versioned active spec for each provider-visible name."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            current = self._specs[spec.name]
            raise ValueError(
                f"工具已注册：{spec.name}@{current.version}，不能隐式替换为 {spec.version}"
            )
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def list(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())


@dataclass(frozen=True, slots=True)
class ToolCapabilityPolicy:
    """Default-deny capability policy for the first unified-tool migration slice."""

    granted_capabilities: frozenset[ToolCapability] = frozenset()

    def evaluate(self, spec: ToolSpec) -> ToolPolicyDecision:
        if not spec.required_capabilities.issubset(self.granted_capabilities):
            return ToolPolicyDecision.DENY
        if spec.risk_level == ToolRiskLevel.RESTRICTED:
            return ToolPolicyDecision.DENY
        if spec.risk_level == ToolRiskLevel.CONFIRM:
            return ToolPolicyDecision.REQUIRE_APPROVAL
        return ToolPolicyDecision.ALLOW


def build_tool_idempotency_key(spec: ToolSpec, arguments: Mapping[str, Any]) -> str:
    """Hash the version and canonical arguments without storing their clear text."""

    canonical = json.dumps(
        {
            "name": spec.name,
            "version": spec.version,
            "arguments": arguments,
        },
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validation_error(label: str, error: ValidationError) -> str:
    path = "$"
    for component in error.absolute_path:
        path += f"[{component}]" if isinstance(component, int) else f".{component}"
    keyword = str(error.validator or "schema")
    return f"{label}不符合 JSON Schema：{path} ({keyword})"


def _redact_text(value: str, *, max_chars: int | None = _MAX_ERROR_CHARS) -> str:
    redacted = value
    for pattern in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted if max_chars is None else redacted[:max_chars]


def _redact_value(value: Any, sensitive_keys: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.casefold().replace("-", "_")
            if normalized in sensitive_keys:
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_value(child, sensitive_keys)
        return redacted
    if isinstance(value, list):
        return [_redact_value(child, sensitive_keys) for child in value]
    if isinstance(value, str):
        return _redact_text(value, max_chars=None)
    return value


class ValidatedToolDispatcher:
    """Validate, authorize, bound, redact and deduplicate every tool execution."""

    def __init__(
        self,
        registry: VersionedToolRegistry,
        *,
        policy: ToolCapabilityPolicy | None = None,
        approval_requester: ToolApprovalRequester | None = None,
        approval_consumer: ToolApprovalConsumer | None = None,
        execution_store: ToolExecutionStore | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy or ToolCapabilityPolicy()
        self._approval_requester = approval_requester
        self._approval_consumer = approval_consumer
        self._execution_store = execution_store
        self._success_cache: dict[str, Any] = {}

    def model_definitions(self) -> tuple[ModelToolDefinition, ...]:
        return tuple(
            spec.to_model_definition()
            for spec in self._registry.list()
            if self._policy.evaluate(spec) == ToolPolicyDecision.ALLOW
            or (
                self._policy.evaluate(spec) == ToolPolicyDecision.REQUIRE_APPROVAL
                and (
                    self._approval_requester is not None
                    or self._approval_consumer is not None
                )
            )
        )

    async def execute(
        self,
        call: ToolCall,
        *,
        cancellation: CancellationToken,
    ) -> ToolResult:
        spec = self._registry.get(call.name)
        if spec is None:
            return self._failure(call, "unknown_tool", "工具未注册")

        decision = self._policy.evaluate(spec)
        if decision == ToolPolicyDecision.DENY:
            return self._failure(call, "permission_denied", "工具能力未获授权")

        try:
            canonical_arguments = _json_clone(call.arguments)
            input_size = len(
                json.dumps(
                    canonical_arguments,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            return self._failure(call, "input_not_json", "工具参数必须是有效 JSON")
        if input_size > spec.max_input_bytes:
            return self._failure(call, "input_too_large", "工具参数超过大小上限")

        input_error = next(spec._input_validator.iter_errors(canonical_arguments), None)
        if input_error is not None:
            return self._failure(
                call,
                "input_schema_invalid",
                _validation_error("工具参数", input_error),
            )

        consumed_approval_id: str | None = None
        if decision == ToolPolicyDecision.REQUIRE_APPROVAL:
            if self._approval_consumer is not None:
                try:
                    consumed = await self._approval_consumer.consume(
                        spec,
                        call,
                        canonical_arguments,
                    )
                    if consumed is not None:
                        if not isinstance(consumed, str) or not 1 <= len(consumed) <= 36:
                            raise ValueError("approval consumer returned an invalid id")
                        consumed_approval_id = consumed
                        decision = ToolPolicyDecision.ALLOW
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    return self._failure(
                        call,
                        "approval_consume_failed",
                        _redact_text(str(exc) or type(exc).__name__),
                    )
        if decision == ToolPolicyDecision.REQUIRE_APPROVAL:
            if self._approval_requester is None:
                return self._failure(
                    call,
                    "approval_unavailable",
                    "工具需要审批，但当前运行未配置安全审批通道",
                )
            try:
                approval_id = await self._approval_requester.request(
                    spec,
                    call,
                    canonical_arguments,
                )
                if not isinstance(approval_id, str) or not 1 <= len(approval_id) <= 36:
                    raise ValueError("approval requester returned an invalid id")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._failure(
                    call,
                    "approval_persistence_failed",
                    _redact_text(str(exc) or type(exc).__name__),
                )
            return self._failure(
                call,
                "approval_required",
                "工具需要用户审批",
                approval_id=approval_id,
            )

        execution_claim: ToolExecutionClaimView | None = None
        if self._execution_store is not None:
            try:
                execution_claim = await self._execution_store.claim(
                    spec=spec,
                    call=call,
                    arguments=canonical_arguments,
                    approval_id=consumed_approval_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._failure(
                    call,
                    "execution_claim_failed",
                    _redact_text(str(exc) or type(exc).__name__),
                )
            if execution_claim.action == "cached":
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    success=True,
                    output=deepcopy(execution_claim.output),
                )
            if execution_claim.action == "in_progress":
                return self._failure(
                    call,
                    "execution_in_progress",
                    "工具调用已有活动执行租约",
                )
            if execution_claim.action == "unknown":
                return self._failure(
                    call,
                    "execution_state_unknown",
                    "工具执行状态不确定，已拒绝自动重试",
                )
            if execution_claim.action != "execute" or not execution_claim.claim_token:
                return self._failure(
                    call,
                    "execution_claim_invalid",
                    "工具执行仓储返回了无效 claim",
                )

        cache_key: str | None = None
        if (
            self._execution_store is None
            and spec.idempotency == ToolIdempotency.IDEMPOTENT
        ):
            cache_key = build_tool_idempotency_key(spec, canonical_arguments)
            if cache_key in self._success_cache:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    success=True,
                    output=deepcopy(self._success_cache[cache_key]),
                )

        try:
            raw_output = await self._execute_with_bounds(
                spec,
                canonical_arguments,
                cancellation,
            )
        except ToolDispatchCancelled:
            await self._persist_cancelled(execution_claim)
            raise
        except TimeoutError:
            return await self._terminal_failure(
                call,
                execution_claim,
                code="timeout",
                message="工具执行超时",
                status="timed_out",
            )
        except asyncio.CancelledError:
            await self._persist_cancelled(execution_claim)
            raise
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or type(exc).__name__
            return await self._terminal_failure(
                call,
                execution_claim,
                code="executor_error",
                message=_redact_text(message),
            )

        try:
            canonical_output = _json_clone(raw_output)
        except (TypeError, ValueError, RecursionError):
            return await self._terminal_failure(
                call,
                execution_claim,
                code="output_not_json",
                message="工具输出必须是有效 JSON",
            )

        output_error = next(spec._output_validator.iter_errors(canonical_output), None)
        if output_error is not None:
            return await self._terminal_failure(
                call,
                execution_claim,
                code="output_schema_invalid",
                message=_validation_error("工具输出", output_error),
            )

        if spec.redaction_policy == ToolRedactionPolicy.SENSITIVE_KEYS:
            output = _redact_value(canonical_output, spec.sensitive_keys)
        else:
            output = canonical_output
        try:
            serialized = json.dumps(
                output,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            return await self._terminal_failure(
                call,
                execution_claim,
                code="output_not_json",
                message="工具输出必须是有效 JSON",
            )
        if len(serialized) > spec.max_output_bytes:
            return await self._terminal_failure(
                call,
                execution_claim,
                code="output_too_large",
                message="工具输出超过大小上限",
            )

        safe_output = json.loads(serialized)
        if execution_claim is not None:
            try:
                await self._execution_store.complete_success(
                    execution_claim.execution_id,
                    claim_token=execution_claim.claim_token or "",
                    output=safe_output,
                    max_output_bytes=spec.max_output_bytes,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._failure(
                    call,
                    "execution_persistence_failed",
                    _redact_text(str(exc) or type(exc).__name__),
                )
        if cache_key is not None:
            self._success_cache[cache_key] = safe_output
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            success=True,
            output=deepcopy(safe_output),
        )

    async def _terminal_failure(
        self,
        call: ToolCall,
        claim: ToolExecutionClaimView | None,
        *,
        code: str,
        message: str,
        status: str = "failed",
    ) -> ToolResult:
        if claim is not None and self._execution_store is not None:
            try:
                await self._execution_store.complete_failure(
                    claim.execution_id,
                    claim_token=claim.claim_token or "",
                    status=status,
                    error_code=code,
                    error_message=_redact_text(message),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._failure(
                    call,
                    "execution_persistence_failed",
                    _redact_text(str(exc) or type(exc).__name__),
                )
        return self._failure(call, code, message)

    async def _persist_cancelled(
        self,
        claim: ToolExecutionClaimView | None,
    ) -> None:
        if claim is None or self._execution_store is None:
            return
        with suppress(Exception):
            await asyncio.shield(
                self._execution_store.complete_failure(
                    claim.execution_id,
                    claim_token=claim.claim_token or "",
                    status="cancelled",
                    error_code="cancelled",
                    error_message="工具执行已取消",
                )
            )

    @staticmethod
    async def _execute_with_bounds(
        spec: ToolSpec,
        arguments: dict[str, Any],
        cancellation: CancellationToken,
    ) -> Any:
        if cancellation.is_cancelled:
            raise ToolDispatchCancelled("工具执行已取消")
        operation = asyncio.create_task(spec.executor(arguments, cancellation))
        cancelled = asyncio.create_task(cancellation.wait())
        try:
            async with asyncio.timeout(spec.timeout_ms / 1_000):
                done, _ = await asyncio.wait(
                    {operation, cancelled},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancelled in done:
                    operation.cancel()
                    with suppress(asyncio.CancelledError):
                        await operation
                    raise ToolDispatchCancelled("工具执行已取消")
                return await operation
        finally:
            cancelled.cancel()
            with suppress(asyncio.CancelledError):
                await cancelled
            if not operation.done():
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation

    @staticmethod
    def _failure(
        call: ToolCall,
        code: str,
        message: str,
        *,
        approval_id: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            success=False,
            error=_redact_text(message),
            error_code=code,
            approval_id=approval_id,
        )
