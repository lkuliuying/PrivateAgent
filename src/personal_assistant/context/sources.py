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
        max_project_tokens=min(800, total),
    )


async def prepare_agent_context(
    db: AsyncSession,
    *,
    system_policy: str,
    current_request: str,
    session_id: int | None,
    knowledge_base: bool,
    builder: ContextBuilder | None = None,
    # v0.6.0 C2：项目指令 / workspace / Git 摘要（coding run 上下文）
    project_id: int | None = None,
    workspace_id: int | None = None,
    git_snapshot: tuple[str | None, str | None, bool | None] | None = None,
) -> ContextBuildResult:
    """Load bounded sources and build context without mutating source records."""

    project_fragments: list[ContextFragment] = []
    if project_id is not None:
        project_fragments = await _load_project_fragments(
            db, project_id, workspace_id, git_snapshot
        )

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
        project_fragments=project_fragments,
    )


async def _load_project_fragments(
    db: AsyncSession,
    project_id: int,
    workspace_id: int | None,
    git_snapshot: tuple[str | None, str | None, bool | None] | None,
) -> list[ContextFragment]:
    """v0.6.0 C2：项目指令、workspace 与 Git 摘要片段（有界、无秘密）。"""

    from personal_assistant.core.models import Project, ProjectWorkspace

    project = await db.get(Project, project_id)
    if project is None:
        return []
    workspace = None
    if workspace_id is not None:
        workspace = await db.get(ProjectWorkspace, workspace_id)

    lines = [
        f"项目名称: {project.name}",
        f"项目根目录: {project.root_path}",
    ]
    if project.language:
        lines.append(f"语言: {project.language}")
    if project.framework:
        lines.append(f"框架: {project.framework}")
    if workspace is not None:
        lines.append(f"工作区状态: {workspace.status}")
    if git_snapshot is not None:
        head_sha, branch, dirty = git_snapshot
        git_desc = f"分支: {branch}" if branch else "HEAD: 分离"
        if head_sha:
            git_desc += f" @ {head_sha[:12]}"
        git_desc += "（有未提交改动）" if dirty else "（工作区干净）"
        lines.append(f"Git: {git_desc}")

    fragment = ContextFragment(
        id=f"project:{project_id}",
        kind=ContextFragmentKind.PROJECT,
        content="\n".join(lines),
        trust=ContextTrust.USER_CONFIRMED,
        source=f"project:{project_id}",
        score=1_000_000.0,
        metadata={
            "project_id": project_id,
            "workspace_id": workspace_id,
            "workspace_status": workspace.status if workspace is not None else None,
        },
    )
    return [fragment]


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
