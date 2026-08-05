"""Single-process ownership and fail-closed recovery for durable Agent runs."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from personal_assistant.core.db import async_session_factory, engine
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import AgentToolExecution as ExecutionRecord

from .contracts import AgentEvent, AgentEventType
from .repository import AgentRunRepository

_MINIMUM_RECOVERY_SCHEMA_REVISION = 16


class AgentRuntimeOwnershipError(RuntimeError):
    """Raised when safe single-process Agent ownership cannot be established."""


@dataclass(frozen=True, slots=True)
class AgentRecoveryResult:
    failed_runs: int = 0
    cancelled_runs: int = 0
    failed_executions: int = 0
    unknown_executions: int = 0


def schema_supports_agent_recovery(revision: str | None) -> bool:
    if revision is None or len(revision) != 4 or not revision.isdigit():
        return False
    return int(revision) >= _MINIMUM_RECOVERY_SCHEMA_REVISION


def _lock_name(db_url: str) -> str:
    parsed = make_url(db_url)
    identity = f"{parsed.host or ''}:{parsed.port or ''}:{parsed.database or ''}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"private-agent:agent-owner:{digest}"


def _usage_payload(run: AgentRunRecord) -> dict[str, int | float | None]:
    return {
        "tool_call_count": run.tool_call_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cached_tokens": run.cached_tokens,
        "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
    }


async def reconcile_orphaned_agent_runs(db: AsyncSession) -> AgentRecoveryResult:
    """Terminalize only non-resumable running work left by a dead owner.

    ``waiting_approval`` runs retain their durable checkpoint and remain manually
    resumable. ``created`` runs never began execution and remain auditable. The
    process ownership lock guarantees that a live process cannot be reconciled by
    a second supported API instance.
    """

    run_ids = list(
        (
            await db.execute(
                select(AgentRunRecord.id)
                .where(AgentRunRecord.status == "running")
                .order_by(AgentRunRecord.created_at.asc())
            )
        ).scalars()
    )
    failed_runs = 0
    cancelled_runs = 0
    for run_id in run_ids:
        run = await AgentRunRepository(db).get_run(run_id)
        if run is None or run.status != "running":
            continue
        cancellation_was_requested = run.cancel_requested_at is not None
        event_type = (
            AgentEventType.RUN_CANCELLED
            if cancellation_was_requested
            else AgentEventType.RUN_FAILED
        )
        error_code = (
            "process_restarted_after_cancel"
            if cancellation_was_requested
            else "process_restarted"
        )
        await AgentRunRepository(db).record_event(
            AgentEvent(
                run_id=run.id,
                sequence=run.last_event_sequence + 1,
                type=event_type,
                payload={
                    **_usage_payload(run),
                    "error": "Agent runtime process exited before the run completed",
                    "error_code": error_code,
                },
            )
        )
        if cancellation_was_requested:
            cancelled_runs += 1
        else:
            failed_runs += 1

    terminal_statuses = {
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "limit_exceeded",
    }
    executions = list(
        (
            await db.execute(
                select(ExecutionRecord)
                .join(AgentRunRecord, AgentRunRecord.id == ExecutionRecord.run_id)
                .where(
                    ExecutionRecord.status == "running",
                    AgentRunRecord.status.in_(terminal_statuses),
                )
                .with_for_update()
            )
        ).scalars()
    )
    failed_executions = 0
    unknown_executions = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    for execution in executions:
        if execution.execution_key_sha256 is None:
            execution.status = "unknown"
            execution.error_code = "state_unknown"
            execution.error_message = (
                "Non-idempotent tool state is unknown after process restart"
            )
            unknown_executions += 1
        else:
            execution.status = "failed"
            execution.error_code = "process_restarted"
            execution.error_message = "Tool execution stopped when its process exited"
            failed_executions += 1
        execution.claim_token_sha256 = None
        execution.lease_expires_at = None
        execution.completed_at = now
        execution.updated_at = now
    if executions:
        await db.commit()
    else:
        await db.rollback()

    return AgentRecoveryResult(
        failed_runs=failed_runs,
        cancelled_runs=cancelled_runs,
        failed_executions=failed_executions,
        unknown_executions=unknown_executions,
    )


class AgentRuntimeProcessGuard:
    """Hold one MySQL named lock for the Agent-enabled API process lifetime."""

    def __init__(self) -> None:
        self._connection: AsyncConnection | None = None
        self._connection_id: int | None = None
        self._lock_name: str | None = None
        self._mutex = asyncio.Lock()
        self.required = False
        self.is_held = False

    async def acquire(self, db_url: str) -> AgentRecoveryResult:
        async with self._mutex:
            if self._connection is not None:
                raise AgentRuntimeOwnershipError("Agent runtime ownership already held")
            self.required = True
            connection = await engine.connect()
            lock_name = _lock_name(db_url)
            try:
                revision = await connection.scalar(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
                if not schema_supports_agent_recovery(
                    str(revision) if revision is not None else None
                ):
                    raise AgentRuntimeOwnershipError(
                        "Agent runtime requires database schema revision 0016 or later"
                    )
                acquired = await connection.scalar(
                    text("SELECT GET_LOCK(:lock_name, 0)"),
                    {"lock_name": lock_name},
                )
                if int(acquired or 0) != 1:
                    raise AgentRuntimeOwnershipError(
                        "Another Agent-enabled API process already owns this database"
                    )
                connection_id = await connection.scalar(text("SELECT CONNECTION_ID()"))
                self._connection = connection
                self._connection_id = int(connection_id or 0)
                self._lock_name = lock_name
                self.is_held = True
            except Exception:
                await connection.close()
                self.is_held = False
                raise

        try:
            async with async_session_factory() as db:
                return await reconcile_orphaned_agent_runs(db)
        except Exception:
            await self.release()
            raise

    async def verify(self) -> bool:
        async with self._mutex:
            if (
                self._connection is None
                or self._connection_id is None
                or self._lock_name is None
            ):
                self.is_held = False
                return False
            try:
                owner = await self._connection.scalar(
                    text("SELECT IS_USED_LOCK(:lock_name)"),
                    {"lock_name": self._lock_name},
                )
                self.is_held = int(owner or 0) == self._connection_id
            except Exception:  # noqa: BLE001
                self.is_held = False
            return self.is_held

    async def release(self) -> None:
        async with self._mutex:
            connection = self._connection
            lock_name = self._lock_name
            self._connection = None
            self._connection_id = None
            self._lock_name = None
            self.is_held = False
            if connection is None:
                self.required = False
                return
            try:
                if lock_name is not None:
                    await connection.scalar(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": lock_name},
                    )
            finally:
                await connection.close()
                self.required = False


agent_runtime_process_guard = AgentRuntimeProcessGuard()
