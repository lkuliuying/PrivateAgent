"""Load integrity-checked RAG citation evidence from durable tool executions."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.verification import RagCitationSource
from .models import AgentToolExecution

_RAG_SOURCE_TOOLS = frozenset({"search_knowledge_base", "get_document_chunk"})
_MAX_SOURCES = 128
_MAX_SOURCE_CHARS = 2 * 1024 * 1024


class RagCitationEvidenceError(RuntimeError):
    """Durable retrieval evidence is missing, corrupt, or outside bounds."""


def _verified_output(record: AgentToolExecution) -> dict[str, Any]:
    output = record.output_json
    if not isinstance(output, dict):
        raise RagCitationEvidenceError("RAG execution output is not an object")
    try:
        encoded = json.dumps(
            output,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise RagCitationEvidenceError(
            "RAG execution output is not canonical JSON"
        ) from exc
    if (
        record.output_size_bytes != len(encoded)
        or not record.output_sha256
        or not hmac.compare_digest(
            record.output_sha256,
            hashlib.sha256(encoded).hexdigest(),
        )
    ):
        raise RagCitationEvidenceError("RAG execution output integrity check failed")
    return output


def _source_from_payload(payload: object, *, content_key: str) -> RagCitationSource:
    if not isinstance(payload, dict):
        raise RagCitationEvidenceError("RAG source payload is not an object")
    content = payload.get(content_key)
    chunk_id = payload.get("chunk_id")
    index_version_id = payload.get("index_version_id")
    if (
        not isinstance(content, str)
        or not content
        or not isinstance(chunk_id, int)
        or isinstance(chunk_id, bool)
        or chunk_id <= 0
        or (
            index_version_id is not None
            and not isinstance(index_version_id, str)
        )
    ):
        raise RagCitationEvidenceError(
            "RAG source payload has invalid identity or content"
        )
    try:
        return RagCitationSource(
            chunk_id=chunk_id,
            index_version_id=index_version_id,
            content=content,
            doc_name=payload.get("doc_name"),
            ordinal=payload.get("ordinal"),
            heading=payload.get("heading"),
            score=payload.get("score"),
            fusion_score=payload.get("fusion_score"),
            bm25_score=payload.get("bm25_score"),
            rerank_score=payload.get("rerank_score"),
            matched_via=tuple(payload.get("matched_via") or ()),
            matched_keywords=tuple(payload.get("matched_keywords") or ()),
        )
    except ValueError as exc:
        raise RagCitationEvidenceError("RAG source payload is outside bounds") from exc


def _merge_source(
    sources: dict[tuple[str | None, int], RagCitationSource],
    source: RagCitationSource,
) -> None:
    key = (source.index_version_id, source.chunk_id)
    existing = sources.get(key)
    if existing is None:
        sources[key] = source
        return
    if existing.content in source.content:
        content = source.content
    elif source.content in existing.content:
        content = existing.content
    else:
        raise RagCitationEvidenceError("RAG source identity has conflicting content")

    updates: dict[str, Any] = {"content": content}
    optional_fields = (
        "doc_name",
        "ordinal",
        "heading",
        "score",
        "fusion_score",
        "bm25_score",
        "rerank_score",
    )
    for field_name in optional_fields:
        existing_value = getattr(existing, field_name)
        source_value = getattr(source, field_name)
        if (
            existing_value is not None
            and source_value is not None
            and existing_value != source_value
        ):
            raise RagCitationEvidenceError(
                "RAG source identity has conflicting metadata"
            )
        updates[field_name] = (
            existing_value if existing_value is not None else source_value
        )
    for field_name in ("matched_via", "matched_keywords"):
        existing_value = getattr(existing, field_name)
        source_value = getattr(source, field_name)
        if existing_value and source_value and existing_value != source_value:
            raise RagCitationEvidenceError(
                "RAG source identity has conflicting metadata"
            )
        updates[field_name] = existing_value or source_value
    sources[key] = existing.model_copy(update=updates)


async def load_durable_rag_citation_sources(
    db: AsyncSession,
    *,
    run_id: str,
) -> tuple[RagCitationSource, ...]:
    """Return only RAG text actually exposed by successful tools in this run."""

    records = list(
        (
            await db.execute(
                select(AgentToolExecution)
                .where(
                    AgentToolExecution.run_id == run_id,
                    AgentToolExecution.status == "succeeded",
                    AgentToolExecution.tool_name.in_(_RAG_SOURCE_TOOLS),
                )
                .order_by(AgentToolExecution.created_at, AgentToolExecution.id)
            )
        ).scalars()
    )
    sources: dict[tuple[str | None, int], RagCitationSource] = {}
    for record in records:
        output = _verified_output(record)
        if record.tool_name == "search_knowledge_base":
            results = output.get("results")
            if not isinstance(results, list):
                raise RagCitationEvidenceError("RAG search output has no result list")
            for result in results:
                _merge_source(
                    sources,
                    _source_from_payload(result, content_key="content_excerpt"),
                )
        else:
            if output.get("found") is False:
                continue
            _merge_source(
                sources,
                _source_from_payload(output.get("chunk"), content_key="content"),
            )
        if len(sources) > _MAX_SOURCES:
            raise RagCitationEvidenceError("RAG citation source count exceeds limit")
        if sum(len(source.content) for source in sources.values()) > _MAX_SOURCE_CHARS:
            raise RagCitationEvidenceError("RAG citation source content exceeds limit")
    return tuple(sources.values())
