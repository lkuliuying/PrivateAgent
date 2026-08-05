from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    AgentRuntime,
    CancellationToken,
    ModelMessage,
    ModelResponse,
    PersistentAgentRunner,
    SqlToolApprovalRequester,
    SqlToolApprovalConsumer,
    ToolCall,
    ToolApprovalConflictError,
    ToolApprovalExpiredError,
    ToolApprovalRepository,
    ToolApprovalTokenError,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    ValidatedToolDispatcher,
    VersionedToolRegistry,
)
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.config import settings


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


async def _executor(
    arguments: dict[str, Any], cancellation: CancellationToken
) -> dict[str, Any]:
    del cancellation
    return {"path": arguments["path"], "content": "safe"}


def _confirm_spec(*, version: str = "1.0.0") -> ToolSpec:
    return ToolSpec(
        name="read_file",
        version=version,
        description="Read one approved file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
        timeout_ms=5_000,
        max_output_bytes=64 * 1024,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=False,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=_executor,
    )


async def _create_run_and_tool_step(db) -> tuple[str, str]:
    run_id = str(uuid4())
    step_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(run_id=run_id, limits=AgentRunLimits())
    await repository.record_event(
        AgentEvent(
            run_id=run_id,
            sequence=1,
            type=AgentEventType.RUN_STARTED,
        )
    )
    await repository.record_event(
        AgentEvent(
            run_id=run_id,
            sequence=2,
            type=AgentEventType.TOOL_REQUESTED,
            step_id=step_id,
            payload={
                "ordinal": 1,
                "kind": "tool",
                "tool_call_id": "call-1",
                "name": "read_file",
            },
        )
    )
    return run_id, step_id


async def _cleanup(db, run_id: str) -> None:
    await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    await db.commit()


@pytest.mark.asyncio
async def test_pending_approval_binds_run_step_version_arguments_and_capabilities(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    repo = ToolApprovalRepository(db)
    spec = _confirm_spec()
    try:
        approval = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=spec,
            arguments={"path": "C:/notes/a.md"},
        )
        duplicate = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=spec,
            arguments={"path": "C:/notes/a.md"},
        )

        assert duplicate.id == approval.id
        assert approval.status == "pending"
        assert approval.run_id == run_id
        assert approval.step_id == step_id
        assert approval.tool_version == "1.0.0"
        assert approval.arguments_json == {"path": "C:/notes/a.md"}
        assert len(approval.arguments_sha256) == 64
        assert approval.required_capabilities_json == ["filesystem.read"]

        with pytest.raises(ToolApprovalConflictError, match="different"):
            await repo.create_pending(
                run_id=run_id,
                step_id=step_id,
                tool_call_id="call-1",
                spec=spec,
                arguments={"path": "C:/notes/replaced.md"},
            )
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_approved_token_is_hashed_consumed_once_and_cannot_be_replayed(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    clock = MutableClock()
    raw_token = "approval-token-0123456789abcdef0123456789abcdef"
    repo = ToolApprovalRepository(
        db,
        clock=clock,
        token_factory=lambda: raw_token,
    )
    spec = _confirm_spec()
    arguments = {"path": "C:/notes/a.md"}
    try:
        pending = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=spec,
            arguments=arguments,
        )
        approval_id = pending.id
        approved = await repo.approve(approval_id)
        stored = await repo.get(approval_id)

        assert approved.token == raw_token
        assert stored is not None
        assert stored.status == "approved"
        assert stored.approval_token_sha256 != raw_token
        assert len(stored.approval_token_sha256 or "") == 64

        with pytest.raises(ToolApprovalTokenError):
            await repo.consume(
                approval_id,
                token="wrong-token",
                spec=spec,
                arguments=arguments,
            )
        assert (await repo.get(approval_id)).status == "approved"

        consumed = await repo.consume(
            approval_id,
            token=raw_token,
            spec=spec,
            arguments=arguments,
        )
        assert consumed.status == "consumed"
        assert consumed.consumed_at == clock.now.replace(tzinfo=None)

        with pytest.raises(ToolApprovalConflictError, match="consumed"):
            await repo.consume(
                approval_id,
                token=raw_token,
                spec=spec,
                arguments=arguments,
            )
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_unconsumed_approval_token_can_be_rotated_after_process_restart(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    tokens = iter(
        (
            "first-approval-token-0123456789abcdef0123456789",
            "second-approval-token-0123456789abcdef01234567",
        )
    )
    repo = ToolApprovalRepository(db, token_factory=lambda: next(tokens))
    spec = _confirm_spec()
    arguments = {"path": "C:/notes/recovery.md"}
    try:
        pending = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=spec,
            arguments=arguments,
        )
        approval_id = pending.id
        first = await repo.approve(approval_id)
        second = await repo.reissue_approved(approval_id)

        with pytest.raises(ToolApprovalTokenError):
            await repo.consume(
                approval_id,
                token=first.token,
                spec=spec,
                arguments=arguments,
            )
        consumed = await repo.consume(
            approval_id,
            token=second.token,
            spec=spec,
            arguments=arguments,
        )
        assert consumed.status == "consumed"
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_concurrent_consumers_allow_exactly_one_execution_claim(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    raw_token = "approval-token-0123456789abcdef0123456789abcdef"
    spec = _confirm_spec()
    arguments = {"path": "C:/notes/a.md"}
    setup_repo = ToolApprovalRepository(db, token_factory=lambda: raw_token)
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        pending = await setup_repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=spec,
            arguments=arguments,
        )
        approval_id = pending.id
        await setup_repo.approve(approval_id)

        async def consume_once():
            async with factory() as session:
                return await ToolApprovalRepository(session).consume(
                    approval_id,
                    token=raw_token,
                    spec=spec,
                    arguments=arguments,
                )

        results = await asyncio.gather(
            consume_once(),
            consume_once(),
            return_exceptions=True,
        )

        successes = [result for result in results if not isinstance(result, Exception)]
        conflicts = [
            result for result in results if isinstance(result, ToolApprovalConflictError)
        ]
        assert len(successes) == 1
        assert successes[0].status == "consumed"
        assert len(conflicts) == 1
    finally:
        await engine.dispose()
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_consumed_approval_can_reauthorize_exact_crash_recovery_without_token(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    raw_token = "approval-token-0123456789abcdef0123456789abcdef"
    spec = _confirm_spec()
    call = ToolCall(
        id="call-1",
        name="read_file",
        arguments={"path": "C:/notes/a.md"},
    )
    repository = ToolApprovalRepository(db, token_factory=lambda: raw_token)
    try:
        pending = await repository.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id=call.id,
            spec=spec,
            arguments=call.arguments,
        )
        approved = await repository.approve(pending.id)
        await repository.consume(
            pending.id,
            token=approved.token,
            spec=spec,
            arguments=call.arguments,
        )

        consumer = SqlToolApprovalConsumer(
            db,
            approval_id=pending.id,
            token=None,
        )
        assert await consumer.consume(spec, call, call.arguments) == pending.id
        assert await consumer.consume(spec, call, call.arguments) is None

        changed_call = ToolCall(
            id=call.id,
            name=call.name,
            arguments={"path": "C:/notes/changed.md"},
        )
        with pytest.raises(ToolApprovalConflictError, match="exact"):
            await SqlToolApprovalConsumer(
                db,
                approval_id=pending.id,
                token=None,
            ).consume(spec, changed_call, changed_call.arguments)
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_approval_rejects_changed_arguments_or_tool_version(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    raw_token = "approval-token-0123456789abcdef0123456789abcdef"
    repo = ToolApprovalRepository(db, token_factory=lambda: raw_token)
    spec = _confirm_spec()
    try:
        pending = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=spec,
            arguments={"path": "C:/notes/a.md"},
        )
        approval_id = pending.id
        await repo.approve(approval_id)

        for changed_spec, changed_arguments in [
            (spec, {"path": "C:/notes/other.md"}),
            (_confirm_spec(version="1.0.1"), {"path": "C:/notes/a.md"}),
        ]:
            with pytest.raises(ToolApprovalConflictError, match="no longer match"):
                await repo.consume(
                    approval_id,
                    token=raw_token,
                    spec=changed_spec,
                    arguments=changed_arguments,
                )
        assert (await repo.get(approval_id)).status == "approved"
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_expiry_is_persisted_and_prevents_late_approval(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    clock = MutableClock()
    repo = ToolApprovalRepository(db, clock=clock)
    try:
        pending = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=_confirm_spec(),
            arguments={"path": "C:/notes/a.md"},
            ttl_seconds=30,
        )
        clock.now += timedelta(seconds=31)

        with pytest.raises(ToolApprovalExpiredError):
            await repo.approve(pending.id)
        stored = await repo.get(pending.id)
        assert stored is not None
        assert stored.status == "expired"
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_reject_cancel_and_bulk_expiry_are_terminal(db):
    run_id, step_id = await _create_run_and_tool_step(db)
    clock = MutableClock()
    repo = ToolApprovalRepository(db, clock=clock)
    try:
        first = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-1",
            spec=_confirm_spec(),
            arguments={"path": "C:/notes/a.md"},
            ttl_seconds=30,
        )
        rejected = await repo.reject(first.id)
        assert rejected.status == "rejected"
        with pytest.raises(ToolApprovalConflictError, match="rejected"):
            await repo.approve(first.id)

        second = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-2",
            spec=_confirm_spec(),
            arguments={"path": "C:/notes/b.md"},
            ttl_seconds=30,
        )
        assert await repo.cancel_for_run(run_id) == 1
        assert (await repo.get(second.id)).status == "cancelled"

        third = await repo.create_pending(
            run_id=run_id,
            step_id=step_id,
            tool_call_id="call-3",
            spec=_confirm_spec(),
            arguments={"path": "C:/notes/c.md"},
            ttl_seconds=30,
        )
        clock.now += timedelta(seconds=31)
        assert await repo.expire_due() >= 1
        assert (await repo.get(third.id)).status == "expired"
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_approval_rejects_step_from_another_run(db):
    run_id, _ = await _create_run_and_tool_step(db)
    other_run_id, other_step_id = await _create_run_and_tool_step(db)
    try:
        with pytest.raises(ToolApprovalConflictError, match="does not belong"):
            await ToolApprovalRepository(db).create_pending(
                run_id=run_id,
                step_id=other_step_id,
                tool_call_id="call-1",
                spec=_confirm_spec(),
                arguments={"path": "C:/notes/a.md"},
            )
    finally:
        await _cleanup(db, run_id)
        await _cleanup(db, other_run_id)


@pytest.mark.asyncio
async def test_sql_requester_persists_exact_approval_before_runtime_pauses(db):
    run_id = str(uuid4())
    spec = _confirm_spec()
    registry = VersionedToolRegistry()
    registry.register(spec)
    dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
        ),
        approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
        execution_store=ToolExecutionRepository(db, run_id=run_id),
    )

    class ToolCallingModel:
        async def complete(self, request, *, cancellation):
            del request, cancellation
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="call-approval",
                        name="read_file",
                        arguments={"path": "C:/notes/a.md"},
                    ),
                )
            )

    repository = AgentRunRepository(db)
    runner = PersistentAgentRunner(
        AgentRuntime(ToolCallingModel(), dispatcher),
        repository,
    )
    try:
        result = await runner.run(
            [ModelMessage(role="user", content="read file")],
            run_id=run_id,
            tool_definitions=dispatcher.model_definitions(),
        )
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        steps = await repository.list_steps(run_id)

        assert result.status.value == "waiting_approval"
        assert len(approvals) == 1
        assert approvals[0].status == "pending"
        assert approvals[0].tool_call_id == "call-approval"
        assert approvals[0].arguments_json == {"path": "C:/notes/a.md"}
        assert approvals[0].step_id == steps[-1].id
        assert result.events[-1].payload["approval_id"] == approvals[0].id

        approved = await ToolApprovalRepository(db).approve(approvals[0].id)
        resume_dispatcher = ValidatedToolDispatcher(
            registry,
            policy=ToolCapabilityPolicy(
                granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
            ),
            approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
            approval_consumer=SqlToolApprovalConsumer(
                db,
                approval_id=approved.approval_id,
                token=approved.token,
            ),
            execution_store=ToolExecutionRepository(db, run_id=run_id),
        )

        class FinalModel:
            async def complete(self, request, *, cancellation):
                del cancellation
                assert request.messages[-1].role == "tool"
                return ModelResponse(text="approved tool completed")

        resumed = await PersistentAgentRunner(
            AgentRuntime(FinalModel(), resume_dispatcher),
            repository,
        ).resume(
            run_id=run_id,
            approval_id=approved.approval_id,
            tool_definitions=resume_dispatcher.model_definitions(),
        )
        stored_run = await repository.get_run(run_id)
        stored_approval = await ToolApprovalRepository(db).get(approvals[0].id)
        stored_events = await repository.list_events(run_id)
        stored_executions = await ToolExecutionRepository(
            db,
            run_id=run_id,
        ).list_for_run()

        assert resumed.status.value == "completed"
        assert resumed.output == "approved tool completed"
        assert stored_run is not None and stored_run.status == "completed"
        assert stored_approval is not None and stored_approval.status == "consumed"
        assert len(stored_executions) == 1
        assert stored_executions[0].status == "succeeded"
        assert stored_executions[0].approval_id == approved.approval_id
        assert stored_executions[0].claim_token_sha256 is None
        assert await repository.load_checkpoint(run_id) is None
        assert "tool.approval_resolved" in [event.event_type for event in stored_events]
        assert stored_events[-1].event_type == "run.completed"
    finally:
        await _cleanup(db, run_id)


@pytest.mark.asyncio
async def test_resume_replays_result_after_crash_between_execution_and_event_commit(db):
    run_id = str(uuid4())
    spec = _confirm_spec()
    registry = VersionedToolRegistry()
    registry.register(spec)

    class ToolCallingModel:
        async def complete(self, request, *, cancellation):
            del request, cancellation
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="call-crash-window",
                        name="read_file",
                        arguments={"path": "C:/notes/a.md"},
                    ),
                )
            )

    repository = AgentRunRepository(db)
    initial_dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
        ),
        approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
        execution_store=ToolExecutionRepository(db, run_id=run_id),
    )
    try:
        waiting = await PersistentAgentRunner(
            AgentRuntime(ToolCallingModel(), initial_dispatcher),
            repository,
        ).run(
            [ModelMessage(role="user", content="read file")],
            run_id=run_id,
            tool_definitions=initial_dispatcher.model_definitions(),
        )
        approval = (await ToolApprovalRepository(db).list_for_run(run_id))[0]
        approved = await ToolApprovalRepository(db).approve(approval.id)
        await ToolApprovalRepository(db).consume(
            approval.id,
            token=approved.token,
            spec=spec,
            arguments={"path": "C:/notes/a.md"},
        )

        # Simulate a worker that durably finished the tool, then exited before
        # the runtime could append approval-resolved/tool-completed events.
        execution_repository = ToolExecutionRepository(db, run_id=run_id)
        checkpoint = await repository.load_checkpoint(run_id)
        assert waiting.status.value == "waiting_approval"
        assert checkpoint is not None
        call = checkpoint.pending_tool_calls[0]
        claim = await execution_repository.claim(
            spec=spec,
            call=call,
            arguments=call.arguments,
            approval_id=approval.id,
        )
        await execution_repository.complete_success(
            claim.execution_id,
            claim_token=claim.claim_token or "",
            output={"path": "C:/notes/a.md", "content": "safe"},
            max_output_bytes=spec.max_output_bytes,
        )

        resumed_dispatcher = ValidatedToolDispatcher(
            registry,
            policy=ToolCapabilityPolicy(
                granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
            ),
            approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
            approval_consumer=SqlToolApprovalConsumer(
                db,
                approval_id=approval.id,
                token=None,
            ),
            execution_store=execution_repository,
        )

        class FinalModel:
            async def complete(self, request, *, cancellation):
                del cancellation
                assert json.loads(request.messages[-1].content)["output"] == {
                    "path": "C:/notes/a.md",
                    "content": "safe",
                }
                return ModelResponse(text="recovered")

        resumed = await PersistentAgentRunner(
            AgentRuntime(FinalModel(), resumed_dispatcher),
            repository,
        ).resume(
            run_id=run_id,
            approval_id=approval.id,
            tool_definitions=resumed_dispatcher.model_definitions(),
        )
        executions = await execution_repository.list_for_run()

        assert resumed.status.value == "completed"
        assert resumed.output == "recovered"
        assert len(executions) == 1
        assert executions[0].status == "succeeded"
        assert executions[0].attempt_count == 1
        assert (await ToolApprovalRepository(db).get(approval.id)).status == "consumed"
        assert await repository.load_checkpoint(run_id) is None
    finally:
        await _cleanup(db, run_id)
