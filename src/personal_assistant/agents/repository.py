"""Durable persistence and projection for AgentRuntime public events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.core.models import (
    AgentRun as AgentRunRecord,
)
from personal_assistant.core.models import (
    AgentRunCheckpoint as AgentRunCheckpointRecord,
)
from personal_assistant.core.models import (
    AgentRunEvent as AgentRunEventRecord,
)
from personal_assistant.core.models import ChatSession, Message
from personal_assistant.core.models import (
    RunStep as RunStepRecord,
)

from .contracts import (
    AgentEvent,
    AgentEventType,
    AgentRunCheckpoint,
    AgentRunLimits,
    AgentRunResult,
    AgentStep,
    AgentStepKind,
    AgentStepStatus,
    ModelMessage,
    ModelToolDefinition,
    TokenUsage,
    ToolCall,
)
from .runtime import AgentRuntime, CancellationToken, EventSink


class AgentRunPersistenceError(RuntimeError):
    """Base error for durable run persistence failures."""


class AgentRunNotFoundError(AgentRunPersistenceError):
    pass


class AgentRunSequenceError(AgentRunPersistenceError):
    pass


class AgentRunProjectionError(AgentRunPersistenceError):
    pass


class ClientRequestConflictError(AgentRunPersistenceError):
    """C0 §5.2.4：相同幂等键对应不同请求 payload，拒绝复用与新建。"""


_TERMINAL_RUN_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "limit_exceeded",
}

_TERMINAL_EVENT_STATUS = {
    AgentEventType.RUN_COMPLETED: "completed",
    AgentEventType.RUN_FAILED: "failed",
    AgentEventType.RUN_CANCELLED: "cancelled",
    AgentEventType.RUN_TIMED_OUT: "timed_out",
    AgentEventType.RUN_LIMIT_EXCEEDED: "limit_exceeded",
}


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _event_payload(event: AgentEvent) -> dict[str, Any]:
    dumped = event.model_dump(mode="json")
    return dict(dumped["payload"])


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return str(value)


def _non_negative_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key, 0)
    if isinstance(value, bool):
        raise AgentRunProjectionError(f"{key} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AgentRunProjectionError(
            f"{key} must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise AgentRunProjectionError(f"{key} must be a non-negative integer")
    return parsed


class AgentRunRepository:
    """Store each event and its read-model projection in one transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(
        self,
        *,
        run_id: str,
        limits: AgentRunLimits,
        session_id: int | None = None,
        trace_id: str | None = None,
        knowledge_base: bool = False,
        completion_conditions: dict | None = None,
        # v0.6.0 Coding Agent
        project_id: int | None = None,
        workspace_id: int | None = None,
        base_head_sha: str | None = None,
        base_branch_name: str | None = None,
        base_git_dirty: bool | None = None,
        model_profile_id: str | None = None,
        reasoning_effort: str | None = None,
        permission_mode: str | None = None,
        permission_snapshot_json: dict | None = None,
        client_request_id: str | None = None,
        request_payload_sha256: str | None = None,
    ) -> AgentRunRecord:
        if not run_id or len(run_id) > 36:
            raise ValueError("run_id must contain 1-36 characters")
        effective_trace_id = trace_id or str(uuid4())
        if len(effective_trace_id) > 64:
            raise ValueError("trace_id must contain at most 64 characters")

        # v0.6.0：client_request_id 幂等——重复请求返回原 run；payload 不一致时冲突
        if client_request_id is not None:
            existing = await self.get_run_by_client_request_id(client_request_id)
            if existing is not None:
                if (
                    existing.request_payload_sha256 is not None
                    and request_payload_sha256 is not None
                    and existing.request_payload_sha256 != request_payload_sha256
                ):
                    raise ClientRequestConflictError(
                        "client_request_id is bound to a different request payload"
                    )
                return existing

        record = AgentRunRecord(
            id=run_id,
            session_id=session_id,
            trace_id=effective_trace_id,
            knowledge_base=knowledge_base,
            completion_conditions_json=completion_conditions,
            project_id=project_id,
            workspace_id=workspace_id,
            base_head_sha=base_head_sha,
            base_branch_name=base_branch_name,
            base_git_dirty=base_git_dirty,
            model_profile_id=model_profile_id,
            reasoning_effort=reasoning_effort,
            permission_mode=permission_mode,
            permission_snapshot_json=permission_snapshot_json,
            client_request_id=client_request_id,
            request_payload_sha256=request_payload_sha256,
            status="created",
            max_steps=limits.max_steps,
            max_tool_calls=limits.max_tool_calls,
            max_wall_time_ms=max(1, round(limits.max_wall_time_seconds * 1_000)),
        )
        self.db.add(record)
        try:
            await self.db.commit()
            await self.db.refresh(record)
        except Exception:
            await self.db.rollback()
            raise
        return record

    async def get_run_by_client_request_id(
        self, client_request_id: str
    ) -> AgentRunRecord | None:
        stmt = select(AgentRunRecord).where(
            AgentRunRecord.client_request_id == client_request_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_run(self, run_id: str) -> AgentRunRecord | None:
        return await self.db.get(AgentRunRecord, run_id)

    async def persist_chat_output_message_once(
        self,
        run_id: str,
        *,
        session_id: int,
        content: str,
    ) -> Message:
        """Atomically bind one completed run to one immutable chat message.

        The marker is a post-terminal public event in the existing durable event
        stream. Locking the run serializes the initial SSE delivery and every
        continuation request without adding another nullable projection column.
        """

        try:
            run = (
                await self.db.execute(
                    select(AgentRunRecord)
                    .where(AgentRunRecord.id == run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if run is None:
                raise AgentRunNotFoundError(f"Agent run not found: {run_id}")
            if run.status != "completed" or run.session_id != session_id:
                raise AgentRunProjectionError(
                    "Only a completed run bound to this session can persist chat output"
                )

            existing_records = list(
                (
                    await self.db.execute(
                        select(AgentRunEventRecord).where(
                            AgentRunEventRecord.run_id == run_id,
                            AgentRunEventRecord.event_type
                            == AgentEventType.CHAT_OUTPUT_PERSISTED.value,
                        )
                    )
                ).scalars()
            )
            if len(existing_records) > 1:
                raise AgentRunProjectionError(
                    "Run has conflicting chat output persistence events"
                )
            if existing_records:
                message_id = existing_records[0].payload_json.get("message_id")
                if (
                    not isinstance(message_id, int)
                    or isinstance(message_id, bool)
                    or message_id <= 0
                ):
                    raise AgentRunProjectionError(
                        "Chat output persistence event has an invalid message id"
                    )
                message = await self.db.get(Message, message_id)
                if (
                    message is None
                    or message.session_id != session_id
                    or message.role != "assistant"
                    or message.content != content
                ):
                    raise AgentRunProjectionError(
                        "Persisted chat output does not match the completed run projection"
                    )
                await self.db.commit()
                return message

            message = Message(
                session_id=session_id,
                role="assistant",
                content=content,
            )
            self.db.add(message)
            await self.db.flush()
            occurred_at = datetime.now(timezone.utc).replace(tzinfo=None)
            event = AgentEvent(
                run_id=run_id,
                sequence=run.last_event_sequence + 1,
                type=AgentEventType.CHAT_OUTPUT_PERSISTED,
                created_at=occurred_at,
                payload={"message_id": message.id},
            )
            self.db.add(
                AgentRunEventRecord(
                    run_id=run_id,
                    sequence=event.sequence,
                    event_type=event.type.value,
                    step_id=None,
                    payload_json=_event_payload(event),
                    created_at=occurred_at,
                )
            )
            run.last_event_sequence = event.sequence
            run.updated_at = occurred_at
            await self.db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(updated_at=func.now())
            )
            await self.db.commit()
            await self.db.refresh(message)
            return message
        except Exception:
            await self.db.rollback()
            raise

    async def list_steps(self, run_id: str) -> list[RunStepRecord]:
        result = await self.db.execute(
            select(RunStepRecord)
            .where(RunStepRecord.run_id == run_id)
            .order_by(RunStepRecord.ordinal.asc())
        )
        return list(result.scalars().all())

    async def load_step_contracts(self, run_id: str) -> tuple[AgentStep, ...]:
        records = await self.list_steps(run_id)
        return tuple(
            AgentStep(
                id=record.id,
                ordinal=record.ordinal,
                kind=AgentStepKind(record.kind),
                status=AgentStepStatus(record.status),
                started_at=record.started_at.replace(tzinfo=timezone.utc),
                completed_at=(
                    record.completed_at.replace(tzinfo=timezone.utc)
                    if record.completed_at is not None
                    else None
                ),
                tool_call_id=record.tool_call_id,
                name=record.name,
                error=record.error_message,
            )
            for record in records
        )

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1_000,
    ) -> list[AgentRunEventRecord]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        result = await self.db.execute(
            select(AgentRunEventRecord)
            .where(
                AgentRunEventRecord.run_id == run_id,
                AgentRunEventRecord.sequence > after_sequence,
            )
            .order_by(AgentRunEventRecord.sequence.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def request_cancellation(self, run_id: str) -> bool:
        """Persist cancellation intent without inventing a terminal event."""

        try:
            run = (
                await self.db.execute(
                    select(AgentRunRecord)
                    .where(AgentRunRecord.id == run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if run is None:
                raise AgentRunNotFoundError(f"Agent run not found: {run_id}")
            if run.status in _TERMINAL_RUN_STATUSES:
                await self.db.commit()
                return False
            run.cancel_requested_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self.db.commit()
            return True
        except Exception:
            await self.db.rollback()
            raise

    async def cancel_waiting_approval(
        self,
        run_id: str,
        *,
        error: str = "tool approval rejected",
        error_code: str = "approval_rejected",
    ) -> bool:
        """Finish an inactive approval checkpoint as a durable cancellation."""

        run = await self.get_run(run_id)
        if run is None:
            raise AgentRunNotFoundError(f"Agent run not found: {run_id}")
        if run.status != "waiting_approval":
            return False
        await self.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=run.last_event_sequence + 1,
                type=AgentEventType.RUN_CANCELLED,
                payload={
                    "error": error,
                    "error_code": error_code,
                    "tool_call_count": run.tool_call_count,
                    "input_tokens": run.input_tokens,
                    "output_tokens": run.output_tokens,
                    "cached_tokens": run.cached_tokens,
                    "cost_usd": (
                        float(run.cost_usd) if run.cost_usd is not None else None
                    ),
                },
            )
        )
        return True

    async def load_checkpoint(self, run_id: str) -> AgentRunCheckpoint | None:
        record = await self.db.get(AgentRunCheckpointRecord, run_id)
        if record is None:
            return None
        return AgentRunCheckpoint(
            checkpoint_version=record.checkpoint_version,
            run_id=record.run_id,
            event_sequence=record.event_sequence,
            conversation=tuple(
                ModelMessage.model_validate(message)
                for message in record.conversation_json
            ),
            pending_tool_calls=tuple(
                ToolCall.model_validate(call)
                for call in record.pending_tool_calls_json
            ),
            tool_call_count=record.tool_call_count,
            usage=TokenUsage(
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cached_tokens=record.cached_tokens,
                cost_usd=(float(record.cost_usd) if record.cost_usd is not None else None),
            ),
        )

    async def record_event(
        self,
        event: AgentEvent,
        *,
        checkpoint: AgentRunCheckpoint | None = None,
    ) -> AgentRunEventRecord:
        payload = _event_payload(event)
        try:
            run = (
                await self.db.execute(
                    select(AgentRunRecord)
                    .where(AgentRunRecord.id == event.run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if run is None:
                raise AgentRunNotFoundError(f"Agent run not found: {event.run_id}")

            existing = (
                await self.db.execute(
                    select(AgentRunEventRecord).where(
                        AgentRunEventRecord.run_id == event.run_id,
                        AgentRunEventRecord.sequence == event.sequence,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if (
                    existing.event_type == event.type.value
                    and existing.step_id == event.step_id
                    and existing.payload_json == payload
                ):
                    if checkpoint is not None:
                        await self._verify_checkpoint(checkpoint, event)
                    await self.db.commit()
                    return existing
                raise AgentRunSequenceError(
                    f"Sequence {event.sequence} is already bound to another event"
                )

            expected = run.last_event_sequence + 1
            if event.sequence != expected:
                raise AgentRunSequenceError(
                    f"Expected event sequence {expected}, received {event.sequence}"
                )
            if run.status in _TERMINAL_RUN_STATUSES:
                raise AgentRunProjectionError(
                    f"Run {event.run_id} is already terminal: {run.status}"
                )
            if event.sequence == 1 and event.type != AgentEventType.RUN_STARTED:
                raise AgentRunProjectionError("The first event must be run.started")

            occurred_at = _utc_naive(event.created_at)
            await self._project(run, event, payload, occurred_at)
            # A step-start event references the step row created by the same
            # projection. Flush the projection first so MySQL can enforce the
            # step foreign key while both writes remain in one transaction.
            await self.db.flush()
            if checkpoint is not None:
                await self._store_checkpoint(checkpoint, event)
            record = AgentRunEventRecord(
                run_id=event.run_id,
                sequence=event.sequence,
                event_type=event.type.value,
                step_id=event.step_id,
                payload_json=payload,
                created_at=occurred_at,
            )
            self.db.add(record)
            run.last_event_sequence = event.sequence
            run.updated_at = occurred_at
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except Exception:
            await self.db.rollback()
            raise

    async def _store_checkpoint(
        self,
        checkpoint: AgentRunCheckpoint,
        event: AgentEvent,
    ) -> None:
        self._validate_checkpoint_binding(checkpoint, event)
        existing = await self.db.get(AgentRunCheckpointRecord, checkpoint.run_id)
        values = {
            "checkpoint_version": checkpoint.checkpoint_version,
            "event_sequence": checkpoint.event_sequence,
            "conversation_json": [
                message.model_dump(mode="json") for message in checkpoint.conversation
            ],
            "pending_tool_calls_json": [
                call.model_dump(mode="json") for call in checkpoint.pending_tool_calls
            ],
            "tool_call_count": checkpoint.tool_call_count,
            "input_tokens": checkpoint.usage.input_tokens,
            "output_tokens": checkpoint.usage.output_tokens,
            "cached_tokens": checkpoint.usage.cached_tokens,
            "cost_usd": checkpoint.usage.cost_usd,
            "updated_at": _utc_naive(event.created_at),
        }
        if existing is None:
            self.db.add(AgentRunCheckpointRecord(run_id=checkpoint.run_id, **values))
            return
        if existing.event_sequence >= checkpoint.event_sequence:
            raise AgentRunProjectionError(
                "checkpoint sequence must advance monotonically"
            )
        for key, value in values.items():
            setattr(existing, key, value)

    async def _verify_checkpoint(
        self,
        checkpoint: AgentRunCheckpoint,
        event: AgentEvent,
    ) -> None:
        self._validate_checkpoint_binding(checkpoint, event)
        existing = await self.db.get(AgentRunCheckpointRecord, checkpoint.run_id)
        if existing is None or existing.event_sequence != checkpoint.event_sequence:
            raise AgentRunProjectionError(
                "idempotent approval event is missing its matching checkpoint"
            )
        loaded = await self.load_checkpoint(checkpoint.run_id)
        if loaded != checkpoint:
            raise AgentRunProjectionError(
                "checkpoint sequence is already bound to different continuation state"
            )

    @staticmethod
    def _validate_checkpoint_binding(
        checkpoint: AgentRunCheckpoint,
        event: AgentEvent,
    ) -> None:
        if event.type != AgentEventType.TOOL_APPROVAL_REQUIRED:
            raise AgentRunProjectionError(
                "checkpoints can only accompany tool.approval_required"
            )
        if (
            checkpoint.run_id != event.run_id
            or checkpoint.event_sequence != event.sequence
        ):
            raise AgentRunProjectionError(
                "checkpoint run and sequence must match its event"
            )

    async def _project(
        self,
        run: AgentRunRecord,
        event: AgentEvent,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        if event.type == AgentEventType.RUN_STARTED:
            if event.sequence != 1 or run.status != "created":
                raise AgentRunProjectionError("run.started is only valid for a new run")
            run.status = "running"
            run.started_at = occurred_at
            return

        if event.type == AgentEventType.CONTEXT_PREPARED:
            if run.status != "running" or event.step_id is not None:
                raise AgentRunProjectionError(
                    "context.prepared requires a running run and no step"
                )
            estimated_tokens = _non_negative_int(payload, "estimated_tokens")
            if estimated_tokens < 1:
                raise AgentRunProjectionError(
                    "context.prepared requires estimated_tokens >= 1"
                )
            for key in (
                "history_included",
                "memory_included",
                "rag_included",
                "summary_included",
                "sensitive_excluded",
            ):
                _non_negative_int(payload, key)
            if not isinstance(payload.get("truncated"), bool):
                raise AgentRunProjectionError(
                    "context.prepared requires boolean truncated"
                )
            return

        if event.type in {
            AgentEventType.MODEL_STARTED,
            AgentEventType.TOOL_REQUESTED,
        }:
            if event.step_id is None:
                raise AgentRunProjectionError(f"{event.type.value} requires step_id")
            ordinal = _non_negative_int(payload, "ordinal")
            if ordinal < 1:
                raise AgentRunProjectionError("ordinal must be at least 1")
            kind = _optional_str(payload, "kind")
            expected_kind = (
                "model"
                if event.type == AgentEventType.MODEL_STARTED
                else "tool"
            )
            if kind != expected_kind:
                raise AgentRunProjectionError(
                    f"{event.type.value} requires kind={expected_kind}"
                )
            self.db.add(
                RunStepRecord(
                    id=event.step_id,
                    run_id=event.run_id,
                    ordinal=ordinal,
                    kind=expected_kind,
                    status="running",
                    tool_call_id=_optional_str(payload, "tool_call_id"),
                    name=_optional_str(payload, "name"),
                    started_at=occurred_at,
                )
            )
            return

        if event.type == AgentEventType.TOOL_STARTED:
            step = await self._require_step(event)
            if step.kind != "tool" or step.status != "running":
                raise AgentRunProjectionError("tool.started requires a running tool step")
            return

        if event.type == AgentEventType.TOOL_APPROVAL_REQUIRED:
            step = await self._require_step(event)
            if step.kind != "tool" or step.status != "running":
                raise AgentRunProjectionError(
                    "tool.approval_required requires a running tool step"
                )
            approval_id = _optional_str(payload, "approval_id")
            if not approval_id:
                raise AgentRunProjectionError(
                    "tool.approval_required requires approval_id"
                )
            step.status = "waiting_approval"
            run.status = "waiting_approval"
            tool_call_count = _non_negative_int(payload, "tool_call_count")
            if tool_call_count < 1:
                raise AgentRunProjectionError(
                    "tool.approval_required requires tool_call_count >= 1"
                )
            run.tool_call_count = tool_call_count
            return

        if event.type == AgentEventType.TOOL_APPROVAL_RESOLVED:
            step = await self._require_step(event)
            if step.kind != "tool" or step.status != "waiting_approval":
                raise AgentRunProjectionError(
                    "tool.approval_resolved requires a waiting tool step"
                )
            approval_id = _optional_str(payload, "approval_id")
            if not approval_id:
                raise AgentRunProjectionError(
                    "tool.approval_resolved requires approval_id"
                )
            step.status = "running"
            run.status = "running"
            return

        if event.type == AgentEventType.MODEL_COMPLETED:
            step = await self._require_step(event)
            if step.kind != "model" or step.status != "running":
                raise AgentRunProjectionError(
                    "model.completed requires a running model step"
                )
            step.status = "succeeded"
            step.completed_at = occurred_at
            step.provider = _optional_str(payload, "provider")
            step.model = _optional_str(payload, "model")
            step.provider_request_id = _optional_str(payload, "request_id")
            latency = payload.get("latency_ms")
            step.latency_ms = float(latency) if latency is not None else None
            run.provider = step.provider or run.provider
            run.model = step.model or run.model
            run.input_tokens += _non_negative_int(payload, "input_tokens")
            run.output_tokens += _non_negative_int(payload, "output_tokens")
            run.cached_tokens += _non_negative_int(payload, "cached_tokens")
            cost = payload.get("cost_usd")
            if cost is not None:
                run.cost_usd = (run.cost_usd or Decimal("0")) + Decimal(str(cost))
            return

        if event.type in {
            AgentEventType.OUTPUT_VALIDATION_STARTED,
            AgentEventType.OUTPUT_VALIDATION_PASSED,
            AgentEventType.OUTPUT_VALIDATION_FAILED,
        }:
            step = await self._require_step(event)
            if step.kind != "model" or step.status != "succeeded":
                raise AgentRunProjectionError(
                    f"{event.type.value} requires a succeeded model step"
                )
            verifier = _optional_str(payload, "verifier")
            if not verifier or len(verifier) > 200:
                raise AgentRunProjectionError(
                    f"{event.type.value} requires a bounded verifier name"
                )
            attempt = _non_negative_int(payload, "attempt")
            retry_count = _non_negative_int(payload, "retry_count")
            max_retries = _non_negative_int(payload, "max_retries")
            if (
                attempt < 1
                or retry_count != attempt - 1
                or max_retries > 2
                or retry_count > max_retries
            ):
                raise AgentRunProjectionError(
                    f"{event.type.value} contains invalid retry counters"
                )
            if event.type == AgentEventType.OUTPUT_VALIDATION_STARTED:
                return
            code = _optional_str(payload, "code")
            message = _optional_str(payload, "message")
            if not code or len(code) > 64 or not message or len(message) > 2_000:
                raise AgentRunProjectionError(
                    f"{event.type.value} requires bounded code and message"
                )
            if event.type == AgentEventType.OUTPUT_VALIDATION_FAILED:
                correction = _optional_str(payload, "correction")
                if correction is not None and len(correction) > 4_000:
                    raise AgentRunProjectionError(
                        "output.validation_failed correction exceeds its limit"
                    )
                will_retry = payload.get("will_retry")
                if not isinstance(will_retry, bool) or will_retry != (
                    retry_count < max_retries
                ):
                    raise AgentRunProjectionError(
                        "output.validation_failed has an invalid retry decision"
                    )
            return

        if event.type in {
            AgentEventType.TOOL_COMPLETED,
            AgentEventType.TOOL_FAILED,
        }:
            step = await self._require_step(event)
            if step.kind != "tool" or step.status != "running":
                raise AgentRunProjectionError(
                    f"{event.type.value} requires a running tool step"
                )
            step.status = (
                "succeeded"
                if event.type == AgentEventType.TOOL_COMPLETED
                else "failed"
            )
            step.completed_at = occurred_at
            step.error_message = _optional_str(payload, "error")
            return

        terminal_status = _TERMINAL_EVENT_STATUS.get(event.type)
        if terminal_status is not None:
            run.status = terminal_status
            run.completed_at = occurred_at
            run.output = _optional_str(payload, "output")
            run.error_code = _optional_str(payload, "error_code")
            run.error_message = _optional_str(payload, "error")
            run.tool_call_count = _non_negative_int(payload, "tool_call_count")
            self._validate_terminal_usage(run, payload)
            await self._finish_running_step(event.type, run.id, occurred_at, payload)
            await self.db.execute(
                delete(AgentRunCheckpointRecord).where(
                    AgentRunCheckpointRecord.run_id == run.id
                )
            )
            return

        # v0.6.0 C0 §4.5：plan/artifact 稳定事件只推进 sequence，不改变 run 状态。
        # payload 必须脱敏且有界（禁止完整命令输出、API key、审批 token）。
        if event.type in {
            AgentEventType.PLAN_CREATED,
            AgentEventType.PLAN_UPDATED,
            AgentEventType.PLAN_ITEM_CHANGED,
            AgentEventType.ARTIFACT_CREATED,
        }:
            if run.status not in {"created", "running", "waiting_approval"}:
                raise AgentRunProjectionError(
                    f"{event.type.value} requires a non-terminal run"
                )
            if event.step_id is not None:
                raise AgentRunProjectionError(
                    f"{event.type.value} must not carry step_id"
                )
            self._validate_stable_event_payload(event.type, payload)
            return

        raise AgentRunProjectionError(f"Unsupported event type: {event.type.value}")

    @staticmethod
    def _validate_stable_event_payload(
        event_type: AgentEventType, payload: dict[str, Any]
    ) -> None:
        """plan/artifact 事件 payload 校验：必需字段存在且有界。"""
        if event_type == AgentEventType.PLAN_CREATED:
            plan_version = payload.get("plan_version")
            items = payload.get("items")
            if not isinstance(plan_version, int) or plan_version < 1:
                raise AgentRunProjectionError(
                    "plan.created requires a positive plan_version"
                )
            if not isinstance(items, list) or not items or len(items) > 32:
                raise AgentRunProjectionError(
                    "plan.created requires 1..32 items"
                )
            return
        if event_type == AgentEventType.PLAN_UPDATED:
            previous = payload.get("previous_version")
            plan_version = payload.get("plan_version")
            if not isinstance(previous, int) or not isinstance(plan_version, int):
                raise AgentRunProjectionError(
                    "plan.updated requires previous_version and plan_version"
                )
            if previous < 1 or plan_version <= previous:
                raise AgentRunProjectionError(
                    "plan.updated requires plan_version > previous_version"
                )
            return
        if event_type == AgentEventType.PLAN_ITEM_CHANGED:
            plan_version = payload.get("plan_version")
            item_key = payload.get("item_key")
            previous_status = payload.get("previous_status")
            status = payload.get("status")
            for name, value in (
                ("plan_version", plan_version),
                ("item_key", item_key),
                ("previous_status", previous_status),
                ("status", status),
            ):
                if not isinstance(value, str) and not isinstance(value, int):
                    raise AgentRunProjectionError(
                        f"plan.item_changed requires a bounded {name}"
                    )
            if not isinstance(plan_version, int) or plan_version < 1:
                raise AgentRunProjectionError(
                    "plan.item_changed requires a positive plan_version"
                )
            if not isinstance(item_key, str) or not 1 <= len(item_key) <= 128:
                raise AgentRunProjectionError(
                    "plan.item_changed requires a bounded item_key"
                )
            if (
                not isinstance(previous_status, str)
                or not isinstance(status, str)
                or len(previous_status) > 32
                or len(status) > 32
            ):
                raise AgentRunProjectionError(
                    "plan.item_changed requires bounded status values"
                )
            return
        if event_type == AgentEventType.ARTIFACT_CREATED:
            for key in ("artifact_id", "kind", "title"):
                value = payload.get(key)
                if not isinstance(value, str) or not 1 <= len(value) <= 512:
                    raise AgentRunProjectionError(
                        f"artifact.created requires a bounded {key}"
                    )
            step_id = payload.get("step_id")
            if step_id is not None and (
                not isinstance(step_id, str) or len(step_id) > 36
            ):
                raise AgentRunProjectionError(
                    "artifact.created requires a bounded step_id"
                )
            return
        raise AgentRunProjectionError(f"Unsupported stable event: {event_type.value}")

    async def _require_step(self, event: AgentEvent) -> RunStepRecord:
        if event.step_id is None:
            raise AgentRunProjectionError(f"{event.type.value} requires step_id")
        step = await self.db.get(RunStepRecord, event.step_id)
        if step is None or step.run_id != event.run_id:
            raise AgentRunProjectionError(
                f"Step {event.step_id} does not belong to run {event.run_id}"
            )
        return step

    @staticmethod
    def _validate_terminal_usage(
        run: AgentRunRecord, payload: dict[str, Any]
    ) -> None:
        expected = {
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "cached_tokens": run.cached_tokens,
        }
        for key, projected in expected.items():
            terminal_value = _non_negative_int(payload, key)
            if terminal_value != projected:
                raise AgentRunProjectionError(
                    f"Terminal {key}={terminal_value} does not match projected {projected}"
                )
        terminal_cost = payload.get("cost_usd")
        projected_cost = run.cost_usd
        if terminal_cost is None and projected_cost is None:
            return
        if terminal_cost is None or projected_cost is None:
            raise AgentRunProjectionError("Terminal cost does not match projected cost")
        if Decimal(str(terminal_cost)) != projected_cost:
            raise AgentRunProjectionError("Terminal cost does not match projected cost")

    async def _finish_running_step(
        self,
        event_type: AgentEventType,
        run_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        result = await self.db.execute(
            select(RunStepRecord)
            .where(
                RunStepRecord.run_id == run_id,
                RunStepRecord.status.in_(("running", "waiting_approval")),
            )
            .order_by(RunStepRecord.ordinal.desc())
            .limit(1)
        )
        step = result.scalar_one_or_none()
        if step is None:
            return
        status_by_event = {
            AgentEventType.RUN_FAILED: AgentStepStatus.FAILED.value,
            AgentEventType.RUN_CANCELLED: AgentStepStatus.CANCELLED.value,
            AgentEventType.RUN_TIMED_OUT: AgentStepStatus.TIMED_OUT.value,
            AgentEventType.RUN_LIMIT_EXCEEDED: AgentStepStatus.FAILED.value,
        }
        status = status_by_event.get(event_type)
        if status is None:
            raise AgentRunProjectionError(
                "A completed run cannot contain a running step"
            )
        step.status = status
        step.completed_at = occurred_at
        step.error_message = _optional_str(payload, "error")


class SqlAgentRunEventSink(EventSink):
    """Persist one immutable public event and its projection per commit."""

    def __init__(self, repository: AgentRunRepository) -> None:
        self._repository = repository

    async def emit(self, event: AgentEvent) -> None:
        await self._repository.record_event(event)

    async def emit_with_checkpoint(
        self,
        event: AgentEvent,
        checkpoint: AgentRunCheckpoint,
    ) -> None:
        await self._repository.record_event(event, checkpoint=checkpoint)


class PersistentAgentRunner:
    """Create a durable run before delegating execution to AgentRuntime."""

    def __init__(
        self,
        runtime: AgentRuntime,
        repository: AgentRunRepository,
    ) -> None:
        self._runtime = runtime
        self._repository = repository

    async def run(
        self,
        messages: list[ModelMessage] | tuple[ModelMessage, ...],
        *,
        limits: AgentRunLimits | None = None,
        cancellation: CancellationToken | None = None,
        tool_definitions: list[ModelToolDefinition]
        | tuple[ModelToolDefinition, ...] = (),
        run_id: str | None = None,
        trace_id: str | None = None,
        session_id: int | None = None,
        context_metadata: Mapping[str, Any] | None = None,
    ) -> AgentRunResult:
        effective_limits = limits or AgentRunLimits()
        effective_run_id = run_id or str(uuid4())
        await self._repository.create_run(
            run_id=effective_run_id,
            limits=effective_limits,
            session_id=session_id,
            trace_id=trace_id,
        )
        return await self._runtime.run(
            messages,
            limits=effective_limits,
            cancellation=cancellation,
            tool_definitions=tool_definitions,
            run_id=effective_run_id,
            event_sink=SqlAgentRunEventSink(self._repository),
            context_metadata=context_metadata,
        )

    async def resume(
        self,
        *,
        run_id: str,
        approval_id: str,
        cancellation: CancellationToken | None = None,
        tool_definitions: list[ModelToolDefinition]
        | tuple[ModelToolDefinition, ...] = (),
    ) -> AgentRunResult:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise AgentRunNotFoundError(f"Agent run not found: {run_id}")
        if run.status != "waiting_approval":
            raise AgentRunProjectionError(
                f"Run {run_id} cannot resume from status {run.status}"
            )
        checkpoint = await self._repository.load_checkpoint(run_id)
        if checkpoint is None or checkpoint.event_sequence != run.last_event_sequence:
            raise AgentRunProjectionError(
                "waiting Agent run has no checkpoint at its latest event"
            )
        steps = await self._repository.load_step_contracts(run_id)
        original_wall_seconds = run.max_wall_time_ms / 1_000
        limits = AgentRunLimits(
            max_steps=run.max_steps,
            max_tool_calls=run.max_tool_calls,
            # Human approval wait is governed by approval expiry, not active
            # model/tool wall time. Each resumed execution segment is bounded.
            max_wall_time_seconds=original_wall_seconds,
        )
        return await self._runtime.resume(
            checkpoint,
            steps=steps,
            approval_id=approval_id,
            limits=limits,
            cancellation=cancellation,
            tool_definitions=tool_definitions,
            event_sink=SqlAgentRunEventSink(self._repository),
        )
