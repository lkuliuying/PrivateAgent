from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunCheckpoint,
    AgentRunProjectionError,
    AgentRunRepository,
    AgentRunSequenceError,
    AgentRuntime,
    ModelMessage,
    ModelResponse,
    ModelToolDefinition,
    PersistentAgentRunner,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from personal_assistant.core.models import AgentRun as AgentRunRecord


class ScriptedModel:
    def __init__(self, *responses: ModelResponse) -> None:
        self._responses = list(responses)

    async def complete(self, request, *, cancellation):
        del request, cancellation
        return self._responses.pop(0)


class EchoTool:
    async def execute(self, call, *, cancellation):
        del cancellation
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            success=True,
            output={"value": call.arguments["value"]},
        )


class ApprovalTool:
    async def execute(self, call, *, cancellation):
        del cancellation
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            success=False,
            error="approval required",
            error_code="approval_required",
            approval_id="approval-1",
        )


def _tool_definition() -> ModelToolDefinition:
    return ModelToolDefinition(
        name="echo",
        description="Return the supplied value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )


async def _delete_run(db, run_id: str) -> None:
    await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    await db.commit()


@pytest.mark.asyncio
async def test_persistent_runner_projects_run_steps_usage_and_events(db):
    run_id = str(uuid4())
    model = ScriptedModel(
        ModelResponse(
            tool_calls=(
                ToolCall(id="call-1", name="echo", arguments={"value": "hello"}),
            ),
            usage=TokenUsage(
                input_tokens=7,
                output_tokens=3,
                cached_tokens=2,
                cost_usd=0.01,
            ),
            provider="openai-compatible",
            model="test-model",
            request_id="req-1",
            latency_ms=12.5,
        ),
        ModelResponse(
            text="done",
            usage=TokenUsage(
                input_tokens=11,
                output_tokens=5,
                cached_tokens=1,
                cost_usd=0.02,
            ),
            provider="openai-compatible",
            model="test-model",
            request_id="req-2",
            latency_ms=9.5,
        ),
    )
    repository = AgentRunRepository(db)
    runner = PersistentAgentRunner(AgentRuntime(model, EchoTool()), repository)

    try:
        result = await runner.run(
            [ModelMessage(role="user", content="echo hello")],
            run_id=run_id,
            trace_id=f"trace-{run_id}",
            tool_definitions=[_tool_definition()],
        )

        run = await repository.get_run(run_id)
        steps = await repository.list_steps(run_id)
        events = await repository.list_events(run_id)
        checkpoint = await repository.load_checkpoint(run_id)

        assert result.output == "done"
        assert run is not None
        assert run.status == "completed"
        assert run.output == "done"
        assert run.provider == "openai-compatible"
        assert run.model == "test-model"
        assert run.tool_call_count == 1
        assert (run.input_tokens, run.output_tokens, run.cached_tokens) == (18, 8, 3)
        assert run.cost_usd == Decimal("0.03000000")
        assert checkpoint is None
        assert run.last_event_sequence == len(events) == len(result.events)
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert [step.ordinal for step in steps] == [1, 2, 3]
        assert [step.kind for step in steps] == ["model", "tool", "model"]
        assert [step.status for step in steps] == [
            "succeeded",
            "succeeded",
            "succeeded",
        ]
        assert steps[0].provider_request_id == "req-1"
        assert steps[2].provider_request_id == "req-2"
        replay = await repository.list_events(run_id, after_sequence=3)
        assert [event.sequence for event in replay] == list(
            range(4, len(events) + 1)
        )
    finally:
        await _delete_run(db, run_id)


@pytest.mark.asyncio
async def test_persistent_runner_projects_waiting_approval_without_terminal_event(db):
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    runner = PersistentAgentRunner(
        AgentRuntime(
            ScriptedModel(
                ModelResponse(
                    tool_calls=(
                        ToolCall(id="call-1", name="echo", arguments={"value": "x"}),
                    )
                )
            ),
            ApprovalTool(),
        ),
        repository,
    )
    try:
        result = await runner.run(
            [ModelMessage(role="user", content="echo")],
            run_id=run_id,
            tool_definitions=[_tool_definition()],
        )

        run = await repository.get_run(run_id)
        steps = await repository.list_steps(run_id)
        events = await repository.list_events(run_id)
        checkpoint = await repository.load_checkpoint(run_id)

        assert result.status.value == "waiting_approval"
        assert run is not None
        assert run.status == "waiting_approval"
        assert run.completed_at is None
        assert run.tool_call_count == 1
        assert [step.status for step in steps] == ["succeeded", "waiting_approval"]
        assert steps[-1].completed_at is None
        assert events[-1].event_type == "tool.approval_required"
        assert all(not event.event_type.startswith("run.") for event in events[1:])
        assert checkpoint is not None
        assert checkpoint.event_sequence == events[-1].sequence
        assert checkpoint.tool_call_count == 1
        assert checkpoint.pending_tool_calls == (
            ToolCall(id="call-1", name="echo", arguments={"value": "x"}),
        )
        assert checkpoint.conversation[-1].role == "assistant"
        assert checkpoint.conversation[-1].tool_calls == checkpoint.pending_tool_calls
    finally:
        await _delete_run(db, run_id)


@pytest.mark.asyncio
async def test_committed_partial_run_is_visible_from_another_session(db, fresh_session):
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    try:
        await repository.create_run(run_id=run_id, limits=AgentRunLimits())
        await repository.record_event(
            AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
        )
        await repository.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=2,
                type=AgentEventType.MODEL_STARTED,
                step_id=str(uuid4()),
                payload={"ordinal": 1, "kind": "model", "name": "model"},
            )
        )

        other_repository = AgentRunRepository(fresh_session)
        persisted = await other_repository.get_run(run_id)
        persisted_steps = await other_repository.list_steps(run_id)
        persisted_events = await other_repository.list_events(run_id)

        assert persisted is not None
        assert persisted.status == "running"
        assert persisted.last_event_sequence == 2
        assert len(persisted_steps) == 1
        assert persisted_steps[0].status == "running"
        assert [event.event_type for event in persisted_events] == [
            "run.started",
            "model.started",
        ]
        await fresh_session.rollback()
    finally:
        await _delete_run(db, run_id)


@pytest.mark.asyncio
async def test_event_replay_is_idempotent_but_conflicting_or_gapped_sequences_fail(db):
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    started = AgentEvent(
        run_id=run_id,
        sequence=1,
        type=AgentEventType.RUN_STARTED,
        payload={"max_steps": 12},
    )
    try:
        await repository.create_run(run_id=run_id, limits=AgentRunLimits())
        first = await repository.record_event(started)
        replayed = await repository.record_event(started)

        assert replayed.id == first.id
        assert len(await repository.list_events(run_id)) == 1

        with pytest.raises(AgentRunSequenceError, match="already bound"):
            await repository.record_event(
                AgentEvent(
                    run_id=run_id,
                    sequence=1,
                    type=AgentEventType.RUN_STARTED,
                    payload={"max_steps": 99},
                )
            )

        with pytest.raises(AgentRunSequenceError, match="Expected event sequence 2"):
            await repository.record_event(
                AgentEvent(
                    run_id=run_id,
                    sequence=3,
                    type=AgentEventType.RUN_COMPLETED,
                )
            )
    finally:
        await _delete_run(db, run_id)


@pytest.mark.asyncio
async def test_approval_event_and_checkpoint_are_atomic_and_idempotent(db):
    run_id = str(uuid4())
    step_id = str(uuid4())
    call = ToolCall(id="call-1", name="echo", arguments={"value": "x"})
    repository = AgentRunRepository(db)
    approval_event = AgentEvent(
        run_id=run_id,
        sequence=4,
        type=AgentEventType.TOOL_APPROVAL_REQUIRED,
        step_id=step_id,
        payload={
            "tool_call_id": call.id,
            "name": call.name,
            "approval_id": "approval-1",
            "tool_call_count": 1,
        },
    )
    checkpoint = AgentRunCheckpoint(
        run_id=run_id,
        event_sequence=4,
        conversation=(
            ModelMessage(role="user", content="echo"),
            ModelMessage(role="assistant", tool_calls=(call,)),
        ),
        pending_tool_calls=(call,),
        tool_call_count=1,
        usage=TokenUsage(input_tokens=2, output_tokens=1),
    )
    try:
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
                    "tool_call_id": call.id,
                    "name": call.name,
                },
            )
        )
        await repository.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=3,
                type=AgentEventType.TOOL_STARTED,
                step_id=step_id,
                payload={"tool_call_id": call.id, "name": call.name},
            )
        )

        first = await repository.record_event(approval_event, checkpoint=checkpoint)
        replayed = await repository.record_event(approval_event, checkpoint=checkpoint)

        assert replayed.id == first.id
        assert await repository.load_checkpoint(run_id) == checkpoint
        assert len(await repository.list_events(run_id)) == 4

        with pytest.raises(AgentRunProjectionError, match="different continuation"):
            await repository.record_event(
                approval_event,
                checkpoint=checkpoint.model_copy(
                    update={"conversation": (ModelMessage(role="user", content="changed"),)}
                ),
            )
    finally:
        await _delete_run(db, run_id)
