"""Privacy-bounded data-quality profiling for the legacy RAG corpus."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ..config import settings
from .rag_benchmark import resolve_document_source_path
from .store_chroma import chroma_store


def profile_rag_data_quality(
    db_url: str,
    *,
    data_dir: Path | None = None,
    project_root: Path | None = None,
    include_chroma: bool = True,
    embedding_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return aggregates only; document names, paths and contents never leave memory."""
    data_dir = (data_dir or settings.data_dir).resolve()
    project_root = (project_root or Path.cwd()).resolve()
    sync_url = make_url(db_url).set(drivername="mysql+pymysql")
    engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            schema_head = connection.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            document_rows = list(
                connection.execute(
                    text(
                        "SELECT id, name, source_path, status, enabled, content_hash, "
                        "mime_type, doc_type, language, embedding_model, chunk_count, "
                        "indexed_at, created_at FROM documents ORDER BY id"
                    )
                ).mappings()
            )
            chunk_rows = list(
                connection.execute(
                    text(
                        "SELECT id, doc_id, ordinal, content, bm25_text "
                        "FROM doc_chunks ORDER BY doc_id, ordinal, id"
                    )
                ).mappings()
            )
    finally:
        engine.dispose()

    documents_by_id = {int(row["id"]): row for row in document_rows}
    chunks_by_doc: dict[int, list[dict]] = defaultdict(list)
    mysql_chunk_ids: set[int] = set()
    empty_chunk_ids = 0
    bm25_missing = 0
    for row in chunk_rows:
        doc_id = int(row["doc_id"])
        chunks_by_doc[doc_id].append(row)
        mysql_chunk_ids.add(int(row["id"]))
        empty_chunk_ids += int(not str(row["content"] or "").strip())
        bm25_missing += int(not str(row["bm25_text"] or "").strip())

    status_counts = Counter(str(row["status"]) for row in document_rows)
    ready_enabled = [
        row for row in document_rows if row["status"] == "ready" and bool(row["enabled"])
    ]
    ready_with_chunks = [row for row in ready_enabled if int(row["id"]) in chunks_by_doc]
    ready_without_chunks = [row for row in ready_enabled if int(row["id"]) not in chunks_by_doc]
    actual_chunk_counts = {
        doc_id: len(rows) for doc_id, rows in chunks_by_doc.items()
    }
    chunk_count_mismatches = sum(
        int(row["chunk_count"] or 0) != actual_chunk_counts.get(int(row["id"]), 0)
        for row in document_rows
    )

    logical_key_by_doc: dict[int, str] = {}
    declared_hash_by_doc: dict[int, str] = {}
    manifest_hash_by_doc: dict[int, str] = {}
    logical_groups: dict[str, list[int]] = defaultdict(list)
    for row in ready_with_chunks:
        doc_id = int(row["id"])
        declared_hash = _normalize_sha256(row["content_hash"])
        canonical = "\0".join(
            str(chunk["content"] or "")
            for chunk in sorted(
                chunks_by_doc[doc_id],
                key=lambda item: (int(item["ordinal"]), int(item["id"])),
            )
        )
        manifest_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        manifest_hash_by_doc[doc_id] = manifest_hash
        if declared_hash is not None:
            declared_hash_by_doc[doc_id] = declared_hash
            logical_key = declared_hash
        else:
            logical_key = manifest_hash
        logical_key_by_doc[doc_id] = logical_key
        logical_groups[logical_key].append(doc_id)

    hash_reconciliation = _reconcile_content_hashes(
        declared_hash_by_doc,
        manifest_hash_by_doc,
    )

    duplicate_groups = [group for group in logical_groups.values() if len(group) > 1]
    duplicate_documents = sum(len(group) for group in duplicate_groups)
    excess_duplicate_documents = sum(len(group) - 1 for group in duplicate_groups)
    group_size_buckets = Counter()
    for group in logical_groups.values():
        size = len(group)
        label = (
            "1"
            if size == 1
            else "2-9"
            if size <= 9
            else "10-49"
            if size <= 49
            else "50+"
        )
        group_size_buckets[label] += 1

    accessible_source_ids: set[int] = set()
    for row in ready_enabled:
        doc_id = int(row["id"])
        if (
            resolve_document_source_path(
                doc_id=doc_id,
                name=str(row["name"]),
                source_path=str(row["source_path"]) if row["source_path"] else None,
                data_dir=data_dir,
                project_root=project_root,
            )
            is not None
        ):
            accessible_source_ids.add(doc_id)

    normalized_name_counts = Counter(
        " ".join(str(row["name"]).casefold().split()) for row in ready_enabled
    )
    duplicate_name_documents = sum(
        count for count in normalized_name_counts.values() if count > 1
    )

    chunk_counts = sorted(actual_chunk_counts.get(int(row["id"]), 0) for row in ready_enabled)
    percentile_95 = _percentile(chunk_counts, 0.95)
    source_content_groups = {
        logical_key_by_doc[doc_id]
        for doc_id in accessible_source_ids
        if doc_id in logical_key_by_doc
    }

    monthly: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"documents": 0, "documents_with_chunks": 0, "logical_keys": set()}
    )
    for row in ready_enabled:
        created_at = row["created_at"]
        month = created_at.strftime("%Y-%m") if created_at else "unknown"
        doc_id = int(row["id"])
        monthly[month]["documents"] += 1
        if doc_id in chunks_by_doc:
            monthly[month]["documents_with_chunks"] += 1
        if doc_id in logical_key_by_doc:
            monthly[month]["logical_keys"].add(logical_key_by_doc[doc_id])
    monthly_rows = [
        {
            "month": month,
            "documents": values["documents"],
            "documents_with_chunks": values["documents_with_chunks"],
            "logical_content_groups": len(values["logical_keys"]),
        }
        for month, values in sorted(monthly.items())
    ]

    chroma_summary: dict[str, Any]
    if include_chroma:
        vector_ids = set(chroma_store.list_ids_sync())
        missing_vectors = mysql_chunk_ids - vector_ids
        orphan_vectors = vector_ids - mysql_chunk_ids
        chroma_summary = {
            "mysql_chunks": len(mysql_chunk_ids),
            "legacy_vectors": len(vector_ids),
            "missing_vector_count": len(missing_vectors),
            "orphan_vector_count": len(orphan_vectors),
            "coverage_rate": (
                (len(mysql_chunk_ids) - len(missing_vectors)) / len(mysql_chunk_ids)
                if mysql_chunk_ids
                else 1.0
            ),
        }
    else:
        chroma_summary = {"checked": False}

    latest_created = max(
        (row["created_at"] for row in document_rows if row["created_at"] is not None),
        default=None,
    )
    latest_indexed = max(
        (row["indexed_at"] for row in document_rows if row["indexed_at"] is not None),
        default=None,
    )
    ready_count = len(ready_enabled)
    with_chunks_count = len(ready_with_chunks)
    logical_count = len(logical_groups)
    return {
        "as_of_utc": datetime.now(UTC).isoformat(),
        "database": {
            "schema_head": str(schema_head) if schema_head is not None else None,
            "database_name": sync_url.database,
        },
        "grain": {
            "document_rows": len(document_rows),
            "legacy_chunk_rows": len(chunk_rows),
            "ready_enabled_documents": ready_count,
            "ready_enabled_with_chunks": with_chunks_count,
            "ready_enabled_without_chunks": len(ready_without_chunks),
            "logical_content_groups": logical_count,
        },
        "status_distribution": [
            {"status": status, "documents": count}
            for status, count in sorted(status_counts.items())
        ],
        "completeness": {
            "ready_with_chunks_rate": _rate(with_chunks_count, ready_count),
            "source_file_available_documents": len(accessible_source_ids),
            "source_file_available_rate": _rate(len(accessible_source_ids), ready_count),
            "source_file_available_with_chunks_rate": _rate(
                len(accessible_source_ids & set(chunks_by_doc)), with_chunks_count
            ),
            "source_backed_logical_content_groups": len(source_content_groups),
            "content_hash_present_rate": _rate(
                sum(bool(str(row["content_hash"] or "").strip()) for row in ready_enabled),
                ready_count,
            ),
            "valid_content_hash_rate": _rate(
                sum(_normalize_sha256(row["content_hash"]) is not None for row in ready_enabled),
                ready_count,
            ),
            "valid_content_hash_with_chunks_rate": _rate(
                sum(
                    _normalize_sha256(row["content_hash"]) is not None
                    for row in ready_with_chunks
                ),
                with_chunks_count,
            ),
            "mime_type_present_rate": _rate(
                sum(bool(str(row["mime_type"] or "").strip()) for row in ready_enabled),
                ready_count,
            ),
            "doc_type_present_rate": _rate(
                sum(bool(str(row["doc_type"] or "").strip()) for row in ready_enabled),
                ready_count,
            ),
            "language_present_rate": _rate(
                sum(bool(str(row["language"] or "").strip()) for row in ready_enabled),
                ready_count,
            ),
            "embedding_model_present_rate": _rate(
                sum(bool(str(row["embedding_model"] or "").strip()) for row in ready_enabled),
                ready_count,
            ),
        },
        "uniqueness": {
            "logical_content_groups": logical_count,
            "duplicate_content_groups": len(duplicate_groups),
            "documents_in_duplicate_groups": duplicate_documents,
            "duplicate_document_rate_among_chunked": _rate(
                duplicate_documents, with_chunks_count
            ),
            "excess_duplicate_documents": excess_duplicate_documents,
            "max_content_group_size": max((len(group) for group in logical_groups.values()), default=0),
            "duplicate_name_documents": duplicate_name_documents,
            "content_group_size_distribution": [
                {"bucket": bucket, "groups": group_size_buckets.get(bucket, 0)}
                for bucket in ("1", "2-9", "10-49", "50+")
            ],
            "hash_reconciliation": hash_reconciliation,
        },
        "integrity": {
            "orphan_chunks": sum(
                int(int(row["doc_id"]) not in documents_by_id) for row in chunk_rows
            ),
            "empty_chunks": empty_chunk_ids,
            "bm25_missing_chunks": bm25_missing,
            "chunk_count_mismatch_documents": chunk_count_mismatches,
            "chunk_count_min": min(chunk_counts, default=0),
            "chunk_count_median": median(chunk_counts) if chunk_counts else 0,
            "chunk_count_p95": percentile_95,
            "chunk_count_max": max(chunk_counts, default=0),
        },
        "vector_integrity": chroma_summary,
        "freshness": {
            "latest_document_created_at": _iso(latest_created),
            "latest_document_indexed_at": _iso(latest_indexed),
            "monthly_imports": monthly_rows,
        },
        "rollout_readiness": {
            "reviewable_logical_cases": logical_count,
            "source_rebuildable_logical_cases": len(source_content_groups),
            "hybrid_embedding_ready": bool(
                embedding_preflight
                and embedding_preflight.get("status") != "dependency_unavailable"
            ),
            "hybrid_embedding_error_code": (
                embedding_preflight.get("error_code")
                if embedding_preflight
                and embedding_preflight.get("status") == "dependency_unavailable"
                else None
            ),
            "hybrid_embedding_preflight_recorded": embedding_preflight is not None,
            "production_schema_ready": str(schema_head) == "0020",
        },
    }


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _normalize_sha256(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            candidate = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    else:
        candidate = str(value)
    candidate = candidate.strip().casefold()
    return candidate if re.fullmatch(r"[0-9a-f]{64}", candidate) else None


def _reconcile_content_hashes(
    declared_hash_by_doc: dict[int, str],
    manifest_hash_by_doc: dict[int, str],
) -> dict[str, int | bool | None]:
    """Compare independent document- and chunk-level content partitions."""
    declared_to_manifests: dict[str, set[str]] = defaultdict(set)
    manifest_to_declared: dict[str, set[str]] = defaultdict(set)
    conflicting_documents: set[int] = set()

    for doc_id, manifest_hash in manifest_hash_by_doc.items():
        declared_hash = declared_hash_by_doc.get(doc_id)
        if declared_hash is None:
            continue
        declared_to_manifests[declared_hash].add(manifest_hash)
        manifest_to_declared[manifest_hash].add(declared_hash)

    conflicting_declared = {
        value for value, manifests in declared_to_manifests.items() if len(manifests) > 1
    }
    conflicting_manifests = {
        value for value, declared in manifest_to_declared.items() if len(declared) > 1
    }
    for doc_id, manifest_hash in manifest_hash_by_doc.items():
        declared_hash = declared_hash_by_doc.get(doc_id)
        if (
            declared_hash in conflicting_declared
            or manifest_hash in conflicting_manifests
        ):
            conflicting_documents.add(doc_id)

    comparable_documents = len(set(declared_hash_by_doc) & set(manifest_hash_by_doc))
    return {
        "documents_with_valid_declared_hash": len(declared_hash_by_doc),
        "documents_with_chunk_manifest_hash": len(manifest_hash_by_doc),
        "comparable_documents": comparable_documents,
        "declared_content_hash_groups": len(set(declared_hash_by_doc.values())),
        "chunk_manifest_groups": len(set(manifest_hash_by_doc.values())),
        "declared_groups_with_multiple_manifests": len(conflicting_declared),
        "manifest_groups_with_multiple_declared_hashes": len(conflicting_manifests),
        "documents_in_partition_conflicts": len(conflicting_documents),
        "partitions_comparable": comparable_documents > 0,
        "partitions_agree": (
            not conflicting_declared and not conflicting_manifests
            if comparable_documents > 0
            else None
        ),
    }


def _percentile(values: list[int], quantile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
