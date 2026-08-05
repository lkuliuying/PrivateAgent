from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    CancellationToken,
    ToolApprovalRepository,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolDispatchCancelled,
    ToolExecutionClaimAction,
    ToolExecutionClaimError,
    ToolExecutionConflictError,
    ToolExecutionRepository,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    ValidatedToolDispatcher,
    VersionedToolRegistry,
)
from personal_assistant.config import settings
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import AgentToolExecution as ExecutionRecord


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


async def _executor(
    arguments: dict[str, Any], cancellation: CancellationToken
) -> dict[str, Any]:
    del cancellation
    return {"value": arguments["value"]}


def _spec(
    *,
    idempotency: ToolIdempotency = ToolIdempotency.IDEMPOTENT,
    risk_level: ToolRiskLevel = ToolRiskLevel.SAFE,
) -> ToolSpec:
    return ToolSpec(
        name="echo",
        version="1.0.0",
        description="Echo one value",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        risk_level=risk_level,
        required_capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
        timeout_ms=1_000,
        max_output_bytes=1_024,
        idempotency=idempotency,
        supports_cancellation=False,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=_executor,
    )


async def _create_run_and_tool_step(
    db,
    *,
    tool_call_id: str = "call-1",
) -> str:
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(run_id=run_id, limits=AgentRunLimits())
    await repository.record_event(
        AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
    )
    await repository.record_event(
        AgentEvent(
            run_id=run_id,
            sequence=2,
            type=AgentEventType.TOOL_REQUESTED,
            step_id=str(uuid4()),
            payload={
                "ordinal": 1,
                "kind": "tool",
                "tool_call_id": tool_call_id,
                "name": "echo",
            },
        )
    )
    return run_id


async def _cleanup(db, run_id: str) -> None:
    await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    await db.commit()


@pytest.mark.asyncio
async def test_claim_hashes_token_and_success_is_replayed_without_reexecution(db):
    run_id = await _create_run_and_tool_step(db)
    raw_token = "execution-token-0123456789abcdef0123456789abcdef"
    repository = ToolExecutionRepository(
        db,
        run_id=run_id,
        token_factory=lambda: raw_token,
    )
    spec = _spec()
    call = ToolCall(id="call-1", name="echo", arguments={"value": "hello"})
    try:
        claim = await repository.claim(
            spec=spec,
            call=call,
            arguments=call.arguments,
        )
        stored = await repository.get(claim.execution_id)

        assert claim.action == ToolExecutionClaimAction.EXECUTE
        assert claim.claim_token == raw_token
        assert stored is not None
        assert stored.status == "running"
        assert stored.claim_token_sha256 != raw_token
        assert len(stored.claim_token_sha256 or "") == 64

        with pytest.raises(ToolExecutionClaimError, match="invalid"):
            await repository.complete_success(
                claim.execution_id,
                claim_token="wrong-token-0123456789abcdef0123456789abcdef",
                output={"value": "hello"},
                max_output_bytes=spec.max_output_bytes,
            )

        completed = await repository.complete_success(
            claim.execution_id,
            claim_token=raw_token,
            output={"value": "hello"},
            max_output_bytes=spec.max_output_bytes,
        )
        replay = await repository.claim(
            spec=spec,
            call=call,
            arguments=call.arguments,
        )

        assert completed.status == "succeeded"
        assert completed.output_json == {"value": "hello"}
        assert completed.output_size_bytes == len(b'{"value":"hello"}')
        assert len(completed.output_sha256 or "") == 64
        assert completed.claim_token_sha256 is None
        assert replay.action == ToolExecutionClaimAction.CACHED
        assert replay.output == {"value": "hello"}
        assert replay.attempt_count == 1
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_same_call_id_cannot_be_rebound_to_changed_arguments(db):
    run_id = await _create_run_and_tool_step(db)
    repository = ToolExecutionRepository(db, run_id=run_id)
    spec = _spec()
    try:
        await repository.claim(
            spec=spec,
            call=ToolCall(id="call-1", name="echo", arguments={"value": "first"}),
            arguments={"value": "first"},
        )

        with pytest.raises(ToolExecutionConflictError, match="different immutable"):
            await repository.claim(
                spec=spec,
                call=ToolCall(
                    id="call-1",
                    name="echo",
                    arguments={"value": "replaced"},
                ),
                arguments={"value": "replaced"},
            )
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_concurrent_first_claim_has_one_executor_and_one_active_lease(db):
    run_id = await _create_run_and_tool_step(db)
    spec = _spec()
    call = ToolCall(id="call-1", name="echo", arguments={"value": "hello"})
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async def claim_once():
            async with factory() as session:
                return await ToolExecutionRepository(
                    session,
                    run_id=run_id,
                ).claim(spec=spec, call=call, arguments=call.arguments)

        claims = await asyncio.gather(claim_once(), claim_once())

        assert sorted(claim.action for claim in claims) == [
            ToolExecutionClaimAction.EXECUTE,
            ToolExecutionClaimAction.IN_PROGRESS,
        ]
        assert len({claim.execution_id for claim in claims}) == 1
        await db.rollback()
        executions = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert len(executions) == 1
    finally:
        await engine.dispose()
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_expired_idempotent_lease_is_reclaimed_with_new_token(db):
    run_id = await _create_run_and_tool_step(db)
    clock = MutableClock()
    tokens = iter(
        [
            "execution-token-11111111111111111111111111111111",
            "execution-token-22222222222222222222222222222222",
        ]
    )
    repository = ToolExecutionRepository(
        db,
        run_id=run_id,
        clock=clock,
        token_factory=lambda: next(tokens),
    )
    spec = _spec()
    call = ToolCall(id="call-1", name="echo", arguments={"value": "hello"})
    try:
        first = await repository.claim(spec=spec, call=call, arguments=call.arguments)
        clock.now += timedelta(seconds=7)
        reclaimed = await repository.claim(
            spec=spec,
            call=call,
            arguments=call.arguments,
        )

        assert reclaimed.execution_id == first.execution_id
        assert reclaimed.action == ToolExecutionClaimAction.EXECUTE
        assert reclaimed.claim_token != first.claim_token
        assert reclaimed.attempt_count == 2
        with pytest.raises(ToolExecutionClaimError):
            await repository.complete_success(
                first.execution_id,
                claim_token=first.claim_token or "",
                output={"value": "stale"},
                max_output_bytes=spec.max_output_bytes,
            )
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_non_idempotent_uncertain_execution_is_never_retried(db):
    run_id = await _create_run_and_tool_step(db)
    clock = MutableClock()
    repository = ToolExecutionRepository(db, run_id=run_id, clock=clock)
    spec = _spec(idempotency=ToolIdempotency.NON_IDEMPOTENT)
    call = ToolCall(id="call-1", name="echo", arguments={"value": "hello"})
    try:
        first = await repository.claim(spec=spec, call=call, arguments=call.arguments)
        clock.now += timedelta(seconds=7)
        uncertain = await repository.claim(
            spec=spec,
            call=call,
            arguments=call.arguments,
        )
        stored = await repository.get(first.execution_id)

        assert uncertain.action == ToolExecutionClaimAction.UNKNOWN
        assert uncertain.claim_token is None
        assert stored is not None and stored.status == "unknown"
        assert stored.error_code == "state_unknown"
        assert stored.attempt_count == 1
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_confirm_execution_requires_exact_consumed_approval(db):
    run_id = await _create_run_and_tool_step(db)
    run_repository = AgentRunRepository(db)
    steps = await run_repository.list_steps(run_id)
    step_id = steps[-1].id
    spec = _spec(risk_level=ToolRiskLevel.CONFIRM)
    call = ToolCall(id="call-1", name="echo", arguments={"value": "approved"})
    approval_repository = ToolApprovalRepository(
        db,
        token_factory=lambda: "approval-token-0123456789abcdef0123456789abcdef",
    )
    execution_repository = ToolExecutionRepository(db, run_id=run_id)
    try:
        with pytest.raises(ToolExecutionConflictError, match="requires"):
            await execution_repository.claim(
                spec=spec,
                call=call,
                arguments=call.arguments,
            )

        approval = await approval_repository.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id=call.id,
            spec=spec,
            arguments=call.arguments,
        )
        approved = await approval_repository.approve(approval.id)
        await approval_repository.consume(
            approval.id,
            token=approved.token,
            spec=spec,
            arguments=call.arguments,
        )
        claim = await execution_repository.claim(
            spec=spec,
            call=call,
            arguments=call.arguments,
            approval_id=approval.id,
        )
        stored = await execution_repository.get(claim.execution_id)

        assert claim.action == ToolExecutionClaimAction.EXECUTE
        assert stored is not None and stored.approval_id == approval.id
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_run_delete_cascades_execution_audit(db):
    run_id = await _create_run_and_tool_step(db)
    call = ToolCall(id="call-1", name="echo", arguments={"value": "hello"})
    repository = ToolExecutionRepository(db, run_id=run_id)
    claim = await repository.claim(spec=_spec(), call=call, arguments=call.arguments)

    await _cleanup(db, run_id)

    assert await db.scalar(
        select(ExecutionRecord.id).where(ExecutionRecord.id == claim.execution_id)
    ) is None


@pytest.mark.asyncio
async def test_dispatcher_persists_redacted_success_before_return_and_replays_it(db):
    run_id = await _create_run_and_tool_step(db)
    executions = 0

    async def sensitive_executor(arguments, cancellation):
        nonlocal executions
        del cancellation
        executions += 1
        return {"value": arguments["value"], "token": "raw-secret-token"}

    spec = ToolSpec(
        name="echo",
        version="1.0.0",
        description="Echo with a sensitive field",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "token": {"type": "string"},
            },
            "required": ["value", "token"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.SAFE,
        required_capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
        timeout_ms=1_000,
        max_output_bytes=1_024,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=False,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=sensitive_executor,
    )
    registry = VersionedToolRegistry()
    registry.register(spec)
    repository = ToolExecutionRepository(db, run_id=run_id)
    dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
        ),
        execution_store=repository,
    )
    call = ToolCall(id="call-1", name="echo", arguments={"value": "hello"})
    try:
        first = await dispatcher.execute(call, cancellation=CancellationToken())
        replay = await dispatcher.execute(call, cancellation=CancellationToken())
        records = await repository.list_for_run()

        assert executions == 1
        assert first.success and replay.success
        assert first.output == replay.output == {
            "value": "hello",
            "token": "[REDACTED]",
        }
        assert len(records) == 1
        assert records[0].status == "succeeded"
        assert records[0].output_json == first.output
        assert "raw-secret-token" not in str(records[0].output_json)
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_dispatcher_persists_timeout_and_redacted_executor_failure(db):
    async def timeout_executor(arguments, cancellation):
        del arguments, cancellation
        await asyncio.sleep(0.05)
        return {"value": "late"}

    async def failing_executor(arguments, cancellation):
        del arguments, cancellation
        raise RuntimeError("token=super-secret-value")

    for call_id, executor, expected_code, expected_status in [
        ("call-timeout", timeout_executor, "timeout", "timed_out"),
        ("call-failure", failing_executor, "executor_error", "failed"),
    ]:
        run_id = await _create_run_and_tool_step(db, tool_call_id=call_id)
        base = _spec()
        spec = ToolSpec(
            name=base.name,
            version=base.version,
            description=base.description,
            input_schema=base.input_schema,
            output_schema=base.output_schema,
            risk_level=base.risk_level,
            required_capabilities=base.required_capabilities,
            timeout_ms=1 if call_id == "call-timeout" else base.timeout_ms,
            max_output_bytes=base.max_output_bytes,
            idempotency=base.idempotency,
            supports_cancellation=base.supports_cancellation,
            redaction_policy=base.redaction_policy,
            executor=executor,
        )
        registry = VersionedToolRegistry()
        registry.register(spec)
        repository = ToolExecutionRepository(db, run_id=run_id)
        dispatcher = ValidatedToolDispatcher(
            registry,
            policy=ToolCapabilityPolicy(
                granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
            ),
            execution_store=repository,
        )
        try:
            result = await dispatcher.execute(
                ToolCall(id=call_id, name="echo", arguments={"value": "hello"}),
                cancellation=CancellationToken(),
            )
            records = await repository.list_for_run()

            assert not result.success and result.error_code == expected_code
            assert len(records) == 1 and records[0].status == expected_status
            assert records[0].error_code == expected_code
            assert "super-secret-value" not in (records[0].error_message or "")
        finally:
            await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_dispatcher_persists_cooperative_cancellation(db):
    run_id = await _create_run_and_tool_step(db)
    spec = _spec()
    registry = VersionedToolRegistry()
    registry.register(spec)
    repository = ToolExecutionRepository(db, run_id=run_id)
    dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
        ),
        execution_store=repository,
    )
    cancellation = CancellationToken()
    cancellation.cancel()
    try:
        with pytest.raises(ToolDispatchCancelled):
            await dispatcher.execute(
                ToolCall(id="call-1", name="echo", arguments={"value": "hello"}),
                cancellation=cancellation,
            )
        records = await repository.list_for_run()

        assert len(records) == 1
        assert records[0].status == "cancelled"
        assert records[0].error_code == "cancelled"
    finally:
        await _cleanup(db, run_id)
