from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from personal_assistant.context import ContextBudget, ContextBuilder
from personal_assistant.context.sources import prepare_agent_context
from personal_assistant.core.context_summaries import (
    ConversationSummaryRangeError,
    ConversationSummaryRepository,
)
from personal_assistant.core.history import MessageRepository, SessionRepository
from personal_assistant.core.memory import MemoryService
from personal_assistant.core.models import (
    ChatSession,
    MemoryConflict,
    MemoryEvent,
    MemoryItem,
    MemoryRevision,
)
from personal_assistant.core.repo_memories import (
    MemoryConflictRepository,
    MemoryRepository,
    MemoryRevisionRepository,
)
from personal_assistant.core.timeutil import utcnow


async def _purge_memories(db, *memory_ids: int) -> None:
    if not memory_ids:
        return
    await db.execute(
        delete(MemoryConflict).where(
            (MemoryConflict.left_memory_id.in_(memory_ids))
            | (MemoryConflict.right_memory_id.in_(memory_ids))
        )
    )
    await db.execute(delete(MemoryEvent).where(MemoryEvent.memory_id.in_(memory_ids)))
    await db.execute(
        delete(MemoryRevision).where(MemoryRevision.memory_id.in_(memory_ids))
    )
    await db.execute(delete(MemoryItem).where(MemoryItem.id.in_(memory_ids)))
    await db.commit()


@pytest.mark.asyncio
async def test_memory_create_edit_and_soft_delete_preserve_immutable_revisions(db):
    repository = MemoryRepository(db)
    revisions = MemoryRevisionRepository(db)
    item = await repository.create(
        kind="preference",
        title="Editor preference",
        content_md="Use short answers",
        confidence=0.9,
    )
    try:
        created_revisions = await revisions.list_by_memory(item.id)
        assert len(item.stable_key) == 32
        assert item.memory_version == 1
        assert item.content_sha256 == hashlib.sha256(
            b"Use short answers"
        ).hexdigest()
        assert [(revision.memory_version, revision.change_type) for revision in created_revisions] == [
            (1, "created")
        ]

        updated = await repository.update(
            item.id,
            content_md="Use concise, evidence-backed answers",
            importance=0.8,
        )
        assert updated is not None
        assert updated.memory_version == 2
        assert updated.stable_key == item.stable_key
        assert updated.content_sha256 != created_revisions[0].content_sha256

        assert await repository.delete(item.id)
        assert await repository.get(item.id) is None
        tombstone = await repository.get_including_deleted(item.id)
        all_revisions = await revisions.list_by_memory(item.id)
        deleted_events = await db.scalars(
            select(MemoryEvent).where(
                MemoryEvent.memory_id == item.id,
                MemoryEvent.event_type == "deleted",
            )
        )

        assert tombstone is not None
        assert tombstone.deleted_at is not None
        assert tombstone.enabled is False
        assert tombstone.status == "archived"
        assert [(revision.memory_version, revision.change_type) for revision in all_revisions] == [
            (1, "created"),
            (2, "edited"),
            (3, "deleted"),
        ]
        assert len(list(deleted_events)) == 1
    finally:
        await _purge_memories(db, item.id)


@pytest.mark.asyncio
async def test_context_retrieval_excludes_expired_and_non_normal_memories(db):
    service = MemoryService(db)
    marker = "memory-expiry-boundary"
    active = await service.create(
        kind="note",
        title=marker,
        content_md=f"active {marker}",
    )
    expired = await service.create(
        kind="note",
        title=marker,
        content_md=f"expired {marker}",
        expires_at=utcnow() - timedelta(seconds=1),
    )
    restricted = await service.create(
        kind="note",
        title=marker,
        content_md=f"restricted {marker}",
        sensitivity_level="restricted",
    )
    try:
        recalled = await service.retrieve_for_context(marker, top_k=10)

        assert [memory.id for memory in recalled] == [active.id]
        assert expired.id not in {memory.id for memory in recalled}
        assert restricted.id not in {memory.id for memory in recalled}
    finally:
        await _purge_memories(db, active.id, expired.id, restricted.id)


@pytest.mark.asyncio
async def test_memory_conflicts_are_normalized_idempotent_and_explicitly_resolved(db):
    repository = MemoryRepository(db)
    left = await repository.create(
        kind="project",
        title="Deployment region",
        content_md="Deploy to region A",
    )
    right = await repository.create(
        kind="project",
        title="Deployment region",
        content_md="Deploy to region B",
    )
    conflicts = MemoryConflictRepository(db)
    try:
        conflict = await conflicts.create(
            right.id,
            left.id,
            reason="Contradictory deployment decisions",
        )
        duplicate = await conflicts.create(
            left.id,
            right.id,
            reason="same pair",
        )

        assert duplicate.id == conflict.id
        assert conflict.left_memory_id == min(left.id, right.id)
        assert conflict.right_memory_id == max(left.id, right.id)
        assert len(await conflicts.list_open()) >= 1

        resolved = await conflicts.resolve(
            conflict.id,
            resolution={"winner_memory_id": right.id, "reason": "newer decision"},
        )
        assert resolved is not None and resolved.status == "resolved"
        assert resolved.resolution_json["winner_memory_id"] == right.id

        with pytest.raises(ValueError, match="itself"):
            await conflicts.create(left.id, left.id, reason="invalid")
    finally:
        await _purge_memories(db, left.id, right.id)


@pytest.mark.asyncio
async def test_summary_versions_bind_exact_source_and_replace_overlapping_context(db):
    session = await SessionRepository(db).create("summary facts")
    session_id = session.id
    messages = MessageRepository(db)
    first = await messages.add(session_id, "user", "question one")
    second = await messages.add(session_id, "assistant", "answer one")
    third = await messages.add(session_id, "user", "question two")
    summaries = ConversationSummaryRepository(db)
    try:
        original = await summaries.create(
            session_id=session_id,
            first_message_id=first.id,
            last_message_id=second.id,
            summary_text="The first exchange established fact A.",
            prompt_version="summary-v1",
            provider="local",
            model="fake",
            input_tokens=10,
            output_tokens=5,
        )
        replay = await summaries.create(
            session_id=session_id,
            first_message_id=first.id,
            last_message_id=second.id,
            summary_text="The first exchange established fact A.",
            prompt_version="summary-v1",
            provider="local",
            model="fake",
            input_tokens=10,
            output_tokens=5,
        )
        corrected = await summaries.create(
            session_id=session_id,
            first_message_id=first.id,
            last_message_id=second.id,
            summary_text="The first exchange established corrected fact A.",
            prompt_version="summary-v1",
        )
        overlapping = await summaries.create(
            session_id=session_id,
            first_message_id=second.id,
            last_message_id=third.id,
            summary_text="The transition from answer one to question two.",
            prompt_version="summary-v1",
        )
        all_records = await summaries.list_all(session_id)
        active = await summaries.list_active(session_id)

        assert replay.id == original.id
        assert corrected.summary_version == 2
        assert len(corrected.source_sha256) == 64
        assert corrected.source_message_count == 2
        assert [record.id for record in active] == [overlapping.id]
        assert [record.status for record in all_records] == [
            "superseded",
            "superseded",
            "active",
        ]

        with pytest.raises(ConversationSummaryRangeError, match="endpoints"):
            await summaries.create(
                session_id=session_id,
                first_message_id=first.id,
                last_message_id=third.id + 99_999,
                summary_text="invalid range",
                prompt_version="summary-v1",
            )
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
        await db.commit()


@pytest.mark.asyncio
async def test_active_summary_replaces_covered_history_in_context(db):
    session = await SessionRepository(db).create("summary context")
    messages = MessageRepository(db)
    first = await messages.add(session.id, "user", "covered old question")
    second = await messages.add(session.id, "assistant", "covered old answer")
    await messages.add(session.id, "user", "recent uncovered question")
    summary = await ConversationSummaryRepository(db).create(
        session_id=session.id,
        first_message_id=first.id,
        last_message_id=second.id,
        summary_text="Traceable summary of the old exchange.",
        prompt_version="summary-v1",
    )
    try:
        result = await prepare_agent_context(
            db,
            system_policy="policy",
            current_request="current request",
            session_id=session.id,
            knowledge_base=False,
            builder=ContextBuilder(
                budget=ContextBudget(
                    max_total_tokens=2_000,
                    max_history_tokens=500,
                    max_memory_tokens=200,
                    max_rag_tokens=200,
                    max_summary_tokens=500,
                    max_fragment_tokens=400,
                )
            ),
        )
        prompt = "\n".join(message.content for message in result.messages)

        assert f"summary:{summary.id}" in prompt
        assert "Traceable summary of the old exchange." in prompt
        assert "covered old question" not in prompt
        assert "covered old answer" not in prompt
        assert "recent uncovered question" in prompt
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
        await db.commit()
