"""SQL-backed context sources for the feature-gated AgentRun path."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.agents.contracts import ModelMessage
from personal_assistant.config import settings
from personal_assistant.core.context_summaries import ConversationSummaryRepository
from personal_assistant.core.history import MessageRepository
from personal_assistant.core.memory import MemoryService
from personal_assistant.core.rag import RagService

from .builder import ContextBuilder
from .contracts import (
    ContextBudget,
    ContextBuildResult,
    ContextFragment,
    ContextFragmentKind,
    ContextTrust,
)


def _default_budget() -> ContextBudget:
    total = min(settings.agent_context_max_tokens, settings.llm_context_length)
    return ContextBudget(
        max_total_tokens=total,
        max_history_tokens=min(2_500, total),
        max_memory_tokens=min(800, total),
        max_rag_tokens=min(1_600, total),
        max_summary_tokens=min(800, total),
        max_fragment_tokens=min(600, total),
    )


async def prepare_agent_context(
    db: AsyncSession,
    *,
    system_policy: str,
    current_request: str,
    session_id: int | None,
    knowledge_base: bool,
    builder: ContextBuilder | None = None,
) -> ContextBuildResult:
    """Load bounded sources and build context without mutating source records."""

    history: list[ModelMessage] = []
    summary_fragments: list[ContextFragment] = []
    if session_id is not None:
        stored_messages = await MessageRepository(db).list_recent_by_session(
            session_id,
            limit=200,
        )
        active_summaries = await ConversationSummaryRepository(db).list_active(
            session_id
        )
        covered_ranges = [
            (summary.first_message_id, summary.last_message_id)
            for summary in active_summaries
            if summary.first_message_id is not None
            and summary.last_message_id is not None
        ]
        history = [
            ModelMessage(role=message.role, content=message.content)
            for message in stored_messages
            if message.role in {"user", "assistant"}
            and not any(
                first <= message.id <= last for first, last in covered_ranges
            )
        ]
        summary_fragments = [
            ContextFragment(
                id=f"summary:{summary.id}",
                kind=ContextFragmentKind.SUMMARY,
                content=summary.summary_text,
                trust=ContextTrust.MODEL_GENERATED,
                source=f"conversation_summary:{summary.id}",
                score=float(summary.last_message_id or 0),
                sensitive=summary.sensitive,
                metadata={
                    "summary_id": summary.id,
                    "first_message_id": summary.first_message_id,
                    "last_message_id": summary.last_message_id,
                    "source_sha256": summary.source_sha256,
                    "summary_version": summary.summary_version,
                },
            )
            for summary in active_summaries
        ]

    memory_service = MemoryService(db)
    memories = await memory_service.retrieve_for_context(current_request, top_k=8)
    memory_fragments = [
        ContextFragment(
            id=f"memory:{memory.id}",
            kind=ContextFragmentKind.MEMORY,
            content=memory.summary or memory.content_md,
            trust=ContextTrust.USER_CONFIRMED,
            source=f"memory:{memory.id}",
            score=float(memory.confidence or 0.0),
            sensitive=bool(memory.sensitive),
            metadata={"memory_id": memory.id, "kind": memory.kind},
        )
        for memory in memories
    ]

    rag_fragments: list[ContextFragment] = []
    if knowledge_base:
        chunks = await RagService(db).retrieve(current_request, top_k=8)
        rag_fragments = [
            ContextFragment(
                id=(
                    f"rag:{chunk.index_version_id or 'legacy'}:{chunk.chunk_id}"
                ),
                kind=ContextFragmentKind.RAG,
                content=chunk.content,
                trust=ContextTrust.EXTERNAL_UNTRUSTED,
                source=(
                    f"document:{chunk.doc_id}:index:"
                    f"{chunk.index_version_id or 'legacy'}:chunk:{chunk.chunk_id}"
                ),
                score=float(chunk.score),
                metadata={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "doc_name": chunk.doc_name,
                    "ordinal": chunk.ordinal,
                    "heading": chunk.heading,
                    "index_version_id": chunk.index_version_id,
                },
            )
            for chunk in chunks
        ]

    return (builder or ContextBuilder(budget=_default_budget())).build(
        system_policies=[system_policy],
        current_request=ModelMessage(role="user", content=current_request),
        recent_history=history,
        memories=memory_fragments,
        rag_fragments=rag_fragments,
        summaries=summary_fragments,
    )


def context_event_payload(result: ContextBuildResult) -> dict[str, object]:
    """Return bounded observability metadata with no selected source content."""

    included_by_kind = {
        kind: sum(
            selection.included and selection.kind == kind
            for selection in result.selections
        )
        for kind in ("history", "memory", "rag", "summary")
    }
    return {
        "estimated_tokens": result.estimated_tokens,
        "section_tokens": dict(result.section_tokens),
        "history_included": included_by_kind["history"],
        "memory_included": included_by_kind["memory"],
        "rag_included": included_by_kind["rag"],
        "summary_included": included_by_kind["summary"],
        "sensitive_excluded": result.sensitive_excluded,
        "truncated": result.truncated,
        "decisions": [
            {
                "id": selection.id,
                "kind": selection.kind,
                "included": selection.included,
                "reason": selection.reason.value,
                "estimated_tokens": selection.estimated_tokens,
            }
            for selection in result.selections[:200]
        ],
        "decisions_truncated": len(result.selections) > 200,
    }
