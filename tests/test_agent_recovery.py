from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from personal_assistant.agents import recovery as recovery_module
from personal_assistant.agents.contracts import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
)
from personal_assistant.agents.recovery import (
    AgentRecoveryResult,
    AgentRuntimeOwnershipError,
    AgentRuntimeProcessGuard,
    agent_runtime_process_guard,
    reconcile_orphaned_agent_runs,
    schema_supports_agent_recovery,
)
from personal_assistant.agents.repository import AgentRunRepository
from personal_assistant.api.routes_agent_runs import require_agent_runtime_owner
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import AgentToolExecution, RunStep


async def _create_running_tool_run(
    db,
    *,
    cancellation_requested: bool,
    idempotent: bool,
) -> tuple[str, str, str]:
    run_id = str(uuid4())
    step_id = str(uuid4())
    call_id = f"call-{uuid4()}"
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
            step_id=step_id,
            payload={
                "ordinal": 1,
                "kind": "tool",
                "tool_call_id": call_id,
                "name": "test_tool",
            },
        )
    )
    if cancellation_requested:
        await repository.request_cancellation(run_id)
    now = datetime.now(UTC).replace(tzinfo=None)
    execution_id = str(uuid4())
    db.add(
        AgentToolExecution(
            id=execution_id,
            run_id=run_id,
            step_id=step_id,
            tool_call_id=call_id,
            tool_name="test_tool",
            tool_version="1",
            arguments_json={"value": "bounded"},
            arguments_sha256="a" * 64,
            execution_key_sha256=("b" * 64 if idempotent else None),
            risk_level="safe",
            required_capabilities_json=[],
            approval_id=None,
            status="running",
            attempt_count=1,
            claim_token_sha256="c" * 64,
            lease_expires_at=now + timedelta(minutes=5),
            started_at=now,
        )
    )
    await db.commit()
    return run_id, step_id, execution_id


async def _delete_runs(db, *run_ids: str) -> None:
    await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id.in_(run_ids)))
    await db.commit()


@pytest.mark.asyncio
async def test_recovery_terminalizes_orphans_and_preserves_created_runs(db):
    failed_id, failed_step_id, failed_execution_id = await _create_running_tool_run(
        db,
        cancellation_requested=False,
        idempotent=True,
    )
    cancelled_id, cancelled_step_id, unknown_execution_id = (
        await _create_running_tool_run(
            db,
            cancellation_requested=True,
            idempotent=False,
        )
    )
    created_id = str(uuid4())
    await AgentRunRepository(db).create_run(
        run_id=created_id,
        limits=AgentRunLimits(),
    )
    try:
        result = await reconcile_orphaned_agent_runs(db)

        assert result.failed_runs == 1
        assert result.cancelled_runs == 1
        assert result.failed_executions == 1
        assert result.unknown_executions == 1

        failed = await db.get(AgentRunRecord, failed_id)
        cancelled = await db.get(AgentRunRecord, cancelled_id)
        created = await db.get(AgentRunRecord, created_id)
        assert failed is not None and failed.status == "failed"
        assert failed.error_code == "process_restarted"
        assert cancelled is not None and cancelled.status == "cancelled"
        assert cancelled.error_code == "process_restarted_after_cancel"
        assert created is not None and created.status == "created"

        failed_step = await db.get(RunStep, failed_step_id)
        cancelled_step = await db.get(RunStep, cancelled_step_id)
        assert failed_step is not None and failed_step.status == "failed"
        assert cancelled_step is not None and cancelled_step.status == "cancelled"

        failed_execution = await db.get(AgentToolExecution, failed_execution_id)
        unknown_execution = await db.get(AgentToolExecution, unknown_execution_id)
        assert failed_execution is not None
        assert failed_execution.status == "failed"
        assert failed_execution.claim_token_sha256 is None
        assert failed_execution.lease_expires_at is None
        assert unknown_execution is not None
        assert unknown_execution.status == "unknown"
        assert unknown_execution.error_code == "state_unknown"

        assert await reconcile_orphaned_agent_runs(db) == type(result)()
    finally:
        await _delete_runs(db, failed_id, cancelled_id, created_id)


@pytest.mark.parametrize(
    ("revision", "expected"),
    [
        (None, False),
        ("0015", False),
        ("0016", True),
        ("0019", True),
        ("0020", True),
        ("invalid", False),
    ],
)
def test_agent_recovery_requires_execution_lease_schema(revision, expected):
    assert schema_supports_agent_recovery(revision) is expected


def test_agent_run_start_is_blocked_after_process_ownership_is_lost(monkeypatch):
    monkeypatch.setattr(agent_runtime_process_guard, "required", True)
    monkeypatch.setattr(agent_runtime_process_guard, "is_held", False)

    with pytest.raises(HTTPException) as exc_info:
        require_agent_runtime_owner()

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_mysql_process_guard_allows_only_one_owner(db, monkeypatch):
    class NoopSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def no_orphans(_db):
        return AgentRecoveryResult()

    test_engine = db.bind
    assert test_engine is not None
    monkeypatch.setattr(recovery_module, "engine", test_engine)
    monkeypatch.setattr(
        recovery_module,
        "async_session_factory",
        lambda: NoopSessionContext(),
    )
    monkeypatch.setattr(
        recovery_module,
        "reconcile_orphaned_agent_runs",
        no_orphans,
    )
    first = AgentRuntimeProcessGuard()
    second = AgentRuntimeProcessGuard()
    db_url = str(test_engine.url)
    try:
        assert await first.acquire(db_url) == AgentRecoveryResult()
        assert first.is_held is True
        assert await first.verify() is True
        with pytest.raises(AgentRuntimeOwnershipError, match="already owns"):
            await second.acquire(db_url)

        await first.release()
        assert await second.acquire(db_url) == AgentRecoveryResult()
        assert second.is_held is True
    finally:
        await first.release()
        await second.release()
