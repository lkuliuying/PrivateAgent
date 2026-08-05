from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentRunRepository,
    AgentRuntime,
    ModelMessage,
    ModelResponse,
    PersistentAgentRunner,
)
from personal_assistant.context import ContextBudget, ContextBuilder
from personal_assistant.context.sources import (
    context_event_payload,
    prepare_agent_context,
)
from personal_assistant.core.history import MessageRepository, SessionRepository
from personal_assistant.core.memory import MemoryService
from personal_assistant.core.models import (
    AgentRun as AgentRunRecord,
    MemoryEvent,
    MemoryItem,
    MemoryRevision,
)


class CharacterEstimator:
    def estimate_text(self, text: str) -> int:
        return len(text)

    def estimate_message(self, message: ModelMessage) -> int:
        return 4 + len(message.content)


class NoTools:
    async def execute(self, call, *, cancellation):
        raise AssertionError(f"unexpected tool call: {call}; {cancellation}")


class FinalModel:
    def __init__(self) -> None:
        self.request = None

    async def complete(self, request, *, cancellation):
        del cancellation
        self.request = request
        return ModelResponse(text="done")


def _builder() -> ContextBuilder:
    return ContextBuilder(
        budget=ContextBudget(
            max_total_tokens=2_000,
            max_history_tokens=500,
            max_memory_tokens=500,
            max_rag_tokens=500,
            max_summary_tokens=300,
            max_fragment_tokens=400,
        ),
        estimator=CharacterEstimator(),
    )


@pytest.mark.asyncio
async def test_sql_context_source_bounds_history_and_excludes_sensitive_memory(db):
    marker = f"contextmarker{uuid4().hex}"
    session = await SessionRepository(db).create("context test")
    messages = MessageRepository(db)
    await messages.add(session.id, "user", f"old {marker}")
    await messages.add(session.id, "assistant", "old answer")
    memory_service = MemoryService(db)
    safe = await memory_service.create(
        kind="preference",
        title=f"safe {marker}",
        content_md=f"Remember {marker} and concise answers",
        confidence=0.9,
    )
    sensitive = await memory_service.create(
        kind="preference",
        title=f"secret {marker}",
        content_md=f"password={marker}",
        confidence=1.0,
        sensitive=True,
    )
    try:
        result = await prepare_agent_context(
            db,
            system_policy="system policy",
            current_request=f"please use {marker}",
            session_id=session.id,
            knowledge_base=False,
            builder=_builder(),
        )
        prompt = "\n".join(message.content for message in result.messages)
        payload = context_event_payload(result)

        assert "old answer" in prompt
        assert f"Remember {marker}" in prompt
        assert "password=" not in prompt
        assert result.messages[-1].content == f"please use {marker}"
        assert payload["memory_included"] >= 1
        assert marker not in str(payload)
    finally:
        await memory_service.delete(safe.id)
        await memory_service.delete(sensitive.id)
        memory_ids = [safe.id, sensitive.id]
        await db.execute(
            delete(MemoryEvent).where(MemoryEvent.memory_id.in_(memory_ids))
        )
        await db.execute(
            delete(MemoryRevision).where(MemoryRevision.memory_id.in_(memory_ids))
        )
        await db.execute(delete(MemoryItem).where(MemoryItem.id.in_(memory_ids)))
        await db.delete(session)
        await db.commit()


@pytest.mark.asyncio
async def test_context_prepared_event_is_persisted_without_source_content(db):
    run_id = str(uuid4())
    model = FinalModel()
    repository = AgentRunRepository(db)
    metadata = {
        "estimated_tokens": 123,
        "section_tokens": {"required": 100, "history": 23},
        "history_included": 2,
        "memory_included": 1,
        "rag_included": 0,
        "summary_included": 0,
        "sensitive_excluded": 1,
        "truncated": True,
        "decisions": [
            {
                "id": "memory:7",
                "kind": "memory",
                "included": True,
                "reason": "included",
                "estimated_tokens": 20,
            }
        ],
        "decisions_truncated": False,
    }
    try:
        result = await PersistentAgentRunner(
            AgentRuntime(model, NoTools()),
            repository,
        ).run(
            [
                ModelMessage(role="system", content="policy"),
                ModelMessage(role="user", content="question"),
            ],
            run_id=run_id,
            context_metadata=metadata,
        )
        events = await repository.list_events(run_id)

        assert result.status.value == "completed"
        assert [event.event_type for event in events[:2]] == [
            "run.started",
            "context.prepared",
        ]
        assert events[1].payload_json == metadata
        assert "question" not in str(events[1].payload_json)
        assert model.request is not None
    finally:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.commit()
