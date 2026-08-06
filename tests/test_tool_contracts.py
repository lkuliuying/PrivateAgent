from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.agents import (
    CancellationToken,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolDispatchCancelled,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    ValidatedToolDispatcher,
    VersionedToolRegistry,
    build_tool_idempotency_key,
)
from personal_assistant.core.tool_adapter import build_read_only_tool_registry

Executor = Callable[[dict[str, Any], CancellationToken], Awaitable[Any]]


async def _echo(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
    del cancellation
    return {"value": arguments["value"]}


def _spec(
    *,
    executor: Executor = _echo,
    risk_level: ToolRiskLevel = ToolRiskLevel.SAFE,
    idempotency: ToolIdempotency = ToolIdempotency.IDEMPOTENT,
    timeout_ms: int = 1_000,
    max_output_bytes: int = 1_024,
    output_schema: dict[str, Any] | None = None,
    version: str = "1.0.0",
) -> ToolSpec:
    return ToolSpec(
        name="echo",
        version=version,
        description="Echo a value",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema=output_schema
        or {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        risk_level=risk_level,
        required_capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
        timeout_ms=timeout_ms,
        max_output_bytes=max_output_bytes,
        idempotency=idempotency,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=executor,
    )


def _dispatcher(
    spec: ToolSpec,
    *,
    granted: frozenset[ToolCapability] | None = None,
    approval_requester=None,
) -> ValidatedToolDispatcher:
    registry = VersionedToolRegistry()
    registry.register(spec)
    return ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=granted
            if granted is not None
            else frozenset({ToolCapability.FILESYSTEM_READ})
        ),
        approval_requester=approval_requester,
    )


def test_tool_spec_rejects_invalid_or_remote_schemas() -> None:
    with pytest.raises(ValueError, match="input_schema"):
        replace(_spec(), input_schema={"type": "string"})

    with pytest.raises(ValueError, match="远程引用"):
        ToolSpec(
            name="remote",
            version="1.0.0",
            description="Remote schema",
            input_schema={
                "type": "object",
                "properties": {"value": {"$ref": "https://example.test/schema"}},
            },
            output_schema={"type": "object"},
            risk_level=ToolRiskLevel.SAFE,
            required_capabilities=frozenset(),
            timeout_ms=100,
            max_output_bytes=128,
            idempotency=ToolIdempotency.IDEMPOTENT,
            supports_cancellation=True,
            redaction_policy=ToolRedactionPolicy.NONE,
            executor=_echo,
        )


def test_registry_rejects_implicit_version_replacement() -> None:
    registry = VersionedToolRegistry()
    registry.register(_spec())
    with pytest.raises(ValueError, match="不能隐式替换"):
        registry.register(_spec(version="1.1.0"))


@pytest.mark.asyncio
async def test_dispatcher_validates_input_before_executor() -> None:
    calls = 0

    async def executor(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
        nonlocal calls
        del arguments, cancellation
        calls += 1
        return {"value": "unused"}

    dispatcher = _dispatcher(_spec(executor=executor))
    result = await dispatcher.execute(
        ToolCall(id="call-1", name="echo", arguments={"value": 1}),
        cancellation=CancellationToken(),
    )

    assert result.success is False
    assert result.error_code == "input_schema_invalid"
    assert "$['value']" not in (result.error or "")
    assert "$.value" in (result.error or "")
    assert calls == 0


@pytest.mark.asyncio
async def test_dispatcher_validates_output_and_never_wraps_it_as_success() -> None:
    async def invalid_output(
        arguments: dict[str, Any], cancellation: CancellationToken
    ) -> dict:
        del arguments, cancellation
        return {"value": 42}

    result = await _dispatcher(_spec(executor=invalid_output)).execute(
        ToolCall(id="call-1", name="echo", arguments={"value": "ok"}),
        cancellation=CancellationToken(),
    )

    assert result.success is False
    assert result.output is None
    assert result.error_code == "output_schema_invalid"


@pytest.mark.asyncio
async def test_dispatcher_redacts_sensitive_keys_and_reuses_idempotent_success() -> None:
    calls = 0

    async def executor(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
        nonlocal calls
        del cancellation
        calls += 1
        return {
            "value": arguments["value"],
            "token": "do-not-expose",
            "nested": {"api-key": "also-secret"},
        }

    spec = _spec(
        executor=executor,
        output_schema={
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "token": {"type": "string"},
                "nested": {"type": "object"},
            },
            "required": ["value", "token", "nested"],
        },
    )
    dispatcher = _dispatcher(spec)

    first = await dispatcher.execute(
        ToolCall(id="call-1", name="echo", arguments={"value": "ok"}),
        cancellation=CancellationToken(),
    )
    second = await dispatcher.execute(
        ToolCall(id="call-2", name="echo", arguments={"value": "ok"}),
        cancellation=CancellationToken(),
    )

    assert first.success is True and second.success is True
    assert first.output["token"] == "[REDACTED]"
    assert first.output["nested"]["api-key"] == "[REDACTED]"
    assert second.tool_call_id == "call-2"
    assert calls == 1


@pytest.mark.asyncio
async def test_dispatcher_enforces_timeout_and_output_limit() -> None:
    async def slow(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
        del arguments, cancellation
        await asyncio.sleep(1)
        return {"value": "late"}

    timed_out = await _dispatcher(_spec(executor=slow, timeout_ms=10)).execute(
        ToolCall(id="call-timeout", name="echo", arguments={"value": "x"}),
        cancellation=CancellationToken(),
    )
    assert timed_out.error_code == "timeout"

    async def large(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
        del arguments, cancellation
        return {"value": "x" * 500}

    too_large = await _dispatcher(
        _spec(executor=large, max_output_bytes=128)
    ).execute(
        ToolCall(id="call-large", name="echo", arguments={"value": "x"}),
        cancellation=CancellationToken(),
    )
    assert too_large.error_code == "output_too_large"


@pytest.mark.asyncio
async def test_dispatcher_cancellation_stops_publish() -> None:
    started = asyncio.Event()

    async def slow(arguments: dict[str, Any], cancellation: CancellationToken) -> dict:
        del arguments, cancellation
        started.set()
        await asyncio.sleep(30)
        return {"value": "late"}

    token = CancellationToken()
    task = asyncio.create_task(
        _dispatcher(_spec(executor=slow)).execute(
            ToolCall(id="call-1", name="echo", arguments={"value": "x"}),
            cancellation=token,
        )
    )
    await started.wait()
    token.cancel()

    with pytest.raises(ToolDispatchCancelled):
        await task


@pytest.mark.asyncio
async def test_capability_and_risk_policy_are_default_deny() -> None:
    no_capability = _dispatcher(_spec(), granted=frozenset())
    denied = await no_capability.execute(
        ToolCall(id="call-1", name="echo", arguments={"value": "x"}),
        cancellation=CancellationToken(),
    )
    assert denied.error_code == "permission_denied"
    assert no_capability.model_definitions() == ()

    confirm = _dispatcher(_spec(risk_level=ToolRiskLevel.CONFIRM))
    awaiting = await confirm.execute(
        ToolCall(id="call-2", name="echo", arguments={"value": "x"}),
        cancellation=CancellationToken(),
    )
    assert awaiting.error_code == "approval_unavailable"
    assert confirm.model_definitions() == ()

    class Requester:
        def __init__(self) -> None:
            self.calls = []

        async def request(self, spec, call, arguments) -> str:
            self.calls.append((spec.name, call.id, arguments))
            return "approval-1"

    requester = Requester()
    confirm_with_broker = _dispatcher(
        _spec(risk_level=ToolRiskLevel.CONFIRM),
        approval_requester=requester,
    )
    pending = await confirm_with_broker.execute(
        ToolCall(id="call-3", name="echo", arguments={"value": "x"}),
        cancellation=CancellationToken(),
    )
    assert pending.error_code == "approval_required"
    assert pending.approval_id == "approval-1"
    assert [tool.name for tool in confirm_with_broker.model_definitions()] == ["echo"]
    assert requester.calls == [("echo", "call-3", {"value": "x"})]


def test_idempotency_key_is_canonical_and_versioned() -> None:
    spec = _spec()
    assert build_tool_idempotency_key(spec, {"b": 2, "a": 1}) == (
        build_tool_idempotency_key(spec, {"a": 1, "b": 2})
    )
    assert build_tool_idempotency_key(spec, {"a": 1}) != build_tool_idempotency_key(
        _spec(version="1.0.1"), {"a": 1}
    )


def test_legacy_adapter_exposes_only_audited_read_only_tools() -> None:
    registry = build_read_only_tool_registry(cast(AsyncSession, object()))
    specs = {spec.name: spec for spec in registry.list()}

    assert set(specs) == {
        "read_file",
        "search_files",
        "grep_code",
        "read_code_file",
        "get_git_status",
        "get_git_diff",
        "propose_patch",
    }
    assert all(spec.version == "1.0.0" for spec in specs.values())
    assert {
        name for name, spec in specs.items() if spec.risk_level == ToolRiskLevel.SAFE
    } == {
        "search_files",
        "grep_code",
        "get_git_status",
        "get_git_diff",
        "propose_patch",
    }
    assert {
        name
        for name, spec in specs.items()
        if spec.risk_level == ToolRiskLevel.CONFIRM
    } == {"read_file", "read_code_file"}
    assert all(
        spec.idempotency == ToolIdempotency.IDEMPOTENT for spec in specs.values()
    )
    assert "apply_patch_to_workspace" not in specs
    assert "run_whitelisted_command" not in specs
