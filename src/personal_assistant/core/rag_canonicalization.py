"""Build a non-mutating canonicalization plan for repeated legacy RAG rows."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ..config import settings
from .database_clone import DatabaseCloneError, validate_clone_name
from .rag_benchmark import resolve_document_source_path


@dataclass(frozen=True)
class CanonicalCandidate:
    doc_id: int
    source_available: bool
    bm25_complete: bool
    chunk_count_matches: bool
    indexed_at: datetime | None = None


def load_canonical_document_ids(
    path: Path,
    *,
    allowed_root: Path,
    target_database: str,
) -> tuple[int, ...]:
    """Load a bounded dry-run plan for its source DB or a verified-name clone."""
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("canonicalization plan must stay inside the allowed data root")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if payload.get("mode") != "dry_run" or payload.get("mutations_performed") is not False:
        raise ValueError("canonicalization plan must be a non-mutating dry run")
    source_database = str(payload.get("database", {}).get("database_name") or "")
    if not source_database:
        raise ValueError("canonicalization plan does not name its source database")
    if target_database != source_database:
        try:
            validate_clone_name(source_database, target_database)
        except DatabaseCloneError as exc:
            raise ValueError(
                "target database is not a source-specific pre-upgrade clone"
            ) from exc

    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError("canonicalization plan must contain at least one group")
    if len(raw_groups) > 1_000:
        raise ValueError("canonicalization plan exceeds the 1000-group limit")
    document_ids: list[int] = []
    for index, group in enumerate(raw_groups, start=1):
        if not isinstance(group, dict):
            raise TypeError(f"canonicalization group #{index} must be an object")
        if group.get("canonical_source_available") is not True:
            raise ValueError(f"canonicalization group #{index} has no recoverable source")
        doc_id = group.get("canonical_doc_id")
        if not isinstance(doc_id, int) or isinstance(doc_id, bool) or doc_id <= 0:
            raise ValueError(f"canonicalization group #{index} has an invalid document id")
        document_ids.append(doc_id)
    if len(set(document_ids)) != len(document_ids):
        raise ValueError("canonicalization plan repeats a canonical document id")
    expected = payload.get("summary", {}).get("canonical_documents")
    if expected is not None and expected != len(document_ids):
        raise ValueError("canonicalization plan summary does not match its groups")
    return tuple(document_ids)


def choose_canonical(candidates: Iterable[CanonicalCandidate]) -> CanonicalCandidate:
    """Prefer recoverability and integrity, then the newest stable row."""
    values = list(candidates)
    if not values:
        raise ValueError("at least one canonicalization candidate is required")
    return max(
        values,
        key=lambda item: (
            item.source_available,
            item.bm25_complete,
            item.chunk_count_matches,
            item.indexed_at.isoformat() if item.indexed_at is not None else "",
            -item.doc_id,
        ),
    )


def build_rag_canonicalization_plan(
    db_url: str,
    *,
    data_dir: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Return a reviewable plan without changing database or vector state."""
    data_dir = (data_dir or settings.data_dir).resolve()
    project_root = (project_root or Path.cwd()).resolve()
    sync_url = make_url(db_url).set(drivername="mysql+pymysql")
    engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            schema_revision = connection.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            documents = list(
                connection.execute(
                    text(
                        "SELECT id, name, source_path, chunk_count, indexed_at "
                        "FROM documents "
                        "WHERE status = 'ready' AND enabled = 1 "
                        "ORDER BY id"
                    )
                ).mappings()
            )
            chunks = list(
                connection.execute(
                    text(
                        "SELECT id, doc_id, ordinal, content, bm25_text "
                        "FROM doc_chunks ORDER BY doc_id, ordinal, id"
                    )
                ).mappings()
            )
    finally:
        engine.dispose()

    chunks_by_doc: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in chunks:
        chunks_by_doc[int(row["doc_id"])].append(dict(row))

    groups: dict[str, list[CanonicalCandidate]] = defaultdict(list)
    for document in documents:
        doc_id = int(document["id"])
        doc_chunks = chunks_by_doc.get(doc_id, [])
        if not doc_chunks:
            continue
        manifest = "\0".join(str(chunk["content"] or "") for chunk in doc_chunks)
        manifest_hash = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        source_available = (
            resolve_document_source_path(
                doc_id=doc_id,
                name=str(document["name"]),
                source_path=(
                    str(document["source_path"])
                    if document["source_path"]
                    else None
                ),
                data_dir=data_dir,
                project_root=project_root,
            )
            is not None
        )
        groups[manifest_hash].append(
            CanonicalCandidate(
                doc_id=doc_id,
                source_available=source_available,
                bm25_complete=all(
                    bool(str(chunk["bm25_text"] or "").strip())
                    for chunk in doc_chunks
                ),
                chunk_count_matches=int(document["chunk_count"] or 0)
                == len(doc_chunks),
                indexed_at=document["indexed_at"],
            )
        )

    ranked_groups: list[dict[str, Any]] = []
    for candidates in groups.values():
        canonical = choose_canonical(candidates)
        ranked_groups.append(
            {
                "member_count": len(candidates),
                "canonical_doc_id": canonical.doc_id,
                "canonical_source_available": canonical.source_available,
                "canonical_bm25_complete": canonical.bm25_complete,
                "canonical_chunk_count_matches": canonical.chunk_count_matches,
                "source_available_member_count": sum(
                    item.source_available for item in candidates
                ),
                "member_doc_ids": sorted(item.doc_id for item in candidates),
                "duplicate_doc_ids": sorted(
                    item.doc_id
                    for item in candidates
                    if item.doc_id != canonical.doc_id
                ),
            }
        )
    ranked_groups.sort(
        key=lambda item: (-item["member_count"], item["canonical_doc_id"])
    )
    for rank, item in enumerate(ranked_groups, start=1):
        item["group_rank"] = rank

    candidate_documents = sum(item["member_count"] for item in ranked_groups)
    return {
        "as_of_utc": datetime.now(UTC).isoformat(),
        "database": {
            "database_name": sync_url.database,
            "schema_revision": (
                str(schema_revision) if schema_revision is not None else None
            ),
        },
        "mode": "dry_run",
        "mutations_performed": False,
        "cleanup_authorized": False,
        "summary": {
            "candidate_documents": candidate_documents,
            "logical_content_groups": len(ranked_groups),
            "canonical_documents": len(ranked_groups),
            "duplicate_documents": candidate_documents - len(ranked_groups),
            "canonical_groups_with_source": sum(
                item["canonical_source_available"] for item in ranked_groups
            ),
            "canonical_groups_with_complete_bm25": sum(
                item["canonical_bm25_complete"] for item in ranked_groups
            ),
            "canonical_groups_with_matching_chunk_count": sum(
                item["canonical_chunk_count_matches"] for item in ranked_groups
            ),
        },
        "selection_policy": [
            "prefer a currently resolvable source file",
            "then prefer complete BM25 text",
            "then prefer matching declared and actual chunk counts",
            "then prefer the most recently indexed row",
            "then prefer the lowest document id for deterministic ties",
        ],
        "groups": ranked_groups,
        "privacy": {
            "document_names_emitted": False,
            "source_paths_emitted": False,
            "content_emitted": False,
            "content_hashes_emitted": False,
        },
    }
