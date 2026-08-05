#!/usr/bin/env python3
"""Build a bounded MCP report artifact from aggregate RAG audit evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    validation_path = args.validation.resolve()
    output_path = args.output.resolve()
    data_root = (PROJECT_ROOT / "data").resolve()
    docs_root = (PROJECT_ROOT / "docs" / "analysis").resolve()
    for label, path in (("profile", profile_path), ("validation", validation_path)):
        if path != data_root and data_root not in path.parents:
            raise SystemExit(f"{label} must stay inside {data_root}")
    if output_path != docs_root and docs_root not in output_path.parents:
        raise SystemExit(f"output must stay inside {docs_root}")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["all_checks_match"] is True

    grain = profile["grain"]
    completeness = profile["completeness"]
    uniqueness = profile["uniqueness"]
    integrity = profile["integrity"]
    vectors = profile["vector_integrity"]
    readiness = profile["rollout_readiness"]
    source_with_chunks = round(
        grain["ready_enabled_with_chunks"]
        * completeness["source_file_available_with_chunks_rate"]
    )
    generated_at = profile["as_of_utc"]

    sources = [
        {
            "id": "corpus_profile",
            "label": "Aggregate RAG corpus profile",
            "path": profile_path.relative_to(PROJECT_ROOT).as_posix(),
            "query": {
                "engine": "python-sqlalchemy",
                "language": "python",
                "description": "Profiles retrieval eligibility, completeness, duplicates, chunk integrity, vector coverage, and rollout readiness without emitting private corpus values.",
                "sql": "SELECT d.id AS document_id, d.status, d.enabled, d.content_hash, d.chunk_count AS declared_chunk_count, d.created_at, d.indexed_at, c.id AS chunk_id, c.ordinal, c.content, c.bm25_text FROM personal_assistant.documents AS d LEFT JOIN personal_assistant.doc_chunks AS c ON c.doc_id = d.id ORDER BY d.id, c.ordinal, c.id",
                "tables_used": [
                    "personal_assistant.documents",
                    "personal_assistant.doc_chunks",
                    "chroma.knowledge",
                ],
                "filters": [
                    "Retrieval-eligible population: documents.status = 'ready' AND documents.enabled = 1",
                    "No document names, source paths, contents, or opaque hashes are emitted",
                ],
                "metric_definitions": [
                    "Logical content groups = distinct SHA-256 values of each document's chunk contents ordered by ordinal and chunk id.",
                    "Duplicate rate = ready/enabled documents with chunks that belong to a content group larger than one divided by all ready/enabled documents with chunks.",
                    "Vector coverage = MySQL legacy chunk ids found in the legacy Chroma collection divided by MySQL legacy chunk ids.",
                    "Source-resolvable with chunks = ready/enabled documents with chunks whose original source file resolves inside the allowed project/data roots.",
                ],
                "executed_at": generated_at,
            },
        },
        {
            "id": "independent_sql",
            "label": "Independent aggregate SQL reconciliation",
            "path": validation_path.relative_to(PROJECT_ROOT).as_posix(),
            "query": {
                "engine": "mysql",
                "language": "sql",
                "description": "Recomputes the decision-critical row and logical-group counts in MySQL using ordered database-side chunk manifests.",
                "sql": "SELECT d.id AS document_id, COUNT(c.id) AS chunk_rows, SHA2(GROUP_CONCAT(COALESCE(c.content, '') ORDER BY c.ordinal, c.id SEPARATOR '\\0'), 256) AS manifest_hash FROM personal_assistant.documents AS d JOIN personal_assistant.doc_chunks AS c ON c.doc_id = d.id WHERE d.status = 'ready' AND d.enabled = 1 GROUP BY d.id ORDER BY d.id",
                "tables_used": [
                    "personal_assistant.documents",
                    "personal_assistant.doc_chunks",
                ],
                "filters": [
                    "documents.status = 'ready'",
                    "documents.enabled = 1",
                ],
                "metric_definitions": [
                    "Chunk manifest groups = count of distinct database-side ordered manifest hashes.",
                    "Match = the application-profile count exactly equals the independently computed SQL count.",
                ],
                "executed_at": validation["as_of_utc"],
            },
        },
        {
            "id": "audit_notebook",
            "label": "Executed RAG data-quality audit notebook",
            "path": "docs/analysis/rag-data-quality-audit-20260802.ipynb",
            "query": {
                "engine": "python",
                "language": "python",
                "description": "Loads the two aggregate evidence files, asserts reconciliation, and derives the report tables.",
                "sql": "SELECT version_num AS schema_revision FROM personal_assistant.alembic_version LIMIT 1",
                "tables_used": [
                    "data.analysis.rag_data_quality_profile",
                    "data.analysis.rag_data_quality_validation",
                ],
                "filters": ["Aggregate-only evidence; no private corpus values"],
                "metric_definitions": [
                    "Gate status is blocked when the observed production prerequisite is absent or cannot be reviewed.",
                ],
                "executed_at": validation["as_of_utc"],
            },
        },
    ]

    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "RAG Corpus Data Quality and Rollout Readiness",
            "description": "Decision report for the PrivateAgent versioned RAG production rollout.",
            "generatedAt": generated_at,
            "sources": sources,
            "cards": [
                {
                    "id": "logical_groups",
                    "description": "Distinct ordered chunk-content manifests among ready/enabled documents with chunks.",
                    "dataset": "summary",
                    "sourceId": "corpus_profile",
                    "metrics": [
                        {"label": "Logical content groups", "field": "logical_groups", "format": "number"}
                    ],
                },
                {
                    "id": "duplicate_rate",
                    "description": "Share of retrieval-eligible chunked document rows that belong to a repeated content group.",
                    "dataset": "summary",
                    "sourceId": "corpus_profile",
                    "metrics": [
                        {"label": "Duplicate rate", "field": "duplicate_rate", "format": "percent"}
                    ],
                },
                {
                    "id": "vector_coverage",
                    "description": "Share of MySQL legacy chunks currently represented in the legacy Chroma collection.",
                    "dataset": "summary",
                    "sourceId": "corpus_profile",
                    "metrics": [
                        {"label": "Legacy vector coverage", "field": "vector_coverage", "format": "percent"}
                    ],
                },
                {
                    "id": "source_chunked",
                    "description": "Ready/enabled document rows that have chunks and a currently resolvable original source file.",
                    "dataset": "summary",
                    "sourceId": "corpus_profile",
                    "metrics": [
                        {"label": "Source-resolvable rows", "field": "source_with_chunks", "format": "number"}
                    ],
                },
            ],
            "charts": [
                {
                    "id": "corpus_funnel",
                    "title": "Retrieval-eligible document rows",
                    "subtitle": "Only 32 rows have both chunks and a currently resolvable source file.",
                    "type": "bar",
                    "dataset": "corpus_funnel",
                    "sourceId": "corpus_profile",
                    "encodings": {
                        "x": {"field": "stage", "type": "nominal", "label": "Corpus stage"},
                        "y": {"field": "documents", "type": "quantitative", "label": "Document rows", "format": "number"},
                    },
                    "options": {"orientation": "horizontal", "grouping": "grouped"},
                    "valueFormat": "number",
                    "layout": "full",
                },
                {
                    "id": "logical_group_sizes",
                    "title": "Document rows per logical content group",
                    "subtitle": "One group contains 180 rows; each of the other three contains 59.",
                    "type": "bar",
                    "dataset": "logical_group_sizes",
                    "sourceId": "independent_sql",
                    "encodings": {
                        "x": {"field": "group_rank", "type": "ordinal", "label": "Logical group rank"},
                        "y": {"field": "documents", "type": "quantitative", "label": "Document rows", "format": "number"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                },
            ],
            "tables": [
                {
                    "id": "quality_gates",
                    "title": "Production rollout prerequisites",
                    "subtitle": "All four prerequisites are currently blocking promotion.",
                    "dataset": "quality_gates",
                    "sourceId": "audit_notebook",
                    "defaultSort": {"field": "gate_order", "direction": "asc"},
                    "columns": [
                        {"field": "gate_order", "label": "#", "type": "number"},
                        {"field": "gate", "label": "Gate", "type": "text"},
                        {"field": "observed", "label": "Observed", "type": "text"},
                        {"field": "required", "label": "Required", "type": "text"},
                        {"field": "status", "label": "Status", "type": "text"},
                    ],
                },
                {
                    "id": "reconciliation",
                    "title": "Independent count reconciliation",
                    "subtitle": "Application-side and database-side aggregates match on every decision-critical count.",
                    "dataset": "reconciliation",
                    "sourceId": "independent_sql",
                    "defaultSort": {"field": "check_order", "direction": "asc"},
                    "columns": [
                        {"field": "check_order", "label": "#", "type": "number"},
                        {"field": "metric", "label": "Metric", "type": "text"},
                        {"field": "profile", "label": "Application profile", "type": "number", "format": "number"},
                        {"field": "sql", "label": "Independent SQL", "type": "number", "format": "number"},
                        {"field": "match", "label": "Match", "type": "text"},
                    ],
                },
            ],
            "blocks": [
                {"id": "title", "type": "markdown", "body": "# RAG Corpus Data Quality and Rollout Readiness"},
                {
                    "id": "executive_summary",
                    "type": "markdown",
                    "sourceId": "corpus_profile",
                    "body": "## Executive Summary\n\n**Decision: hold the production versioned-hybrid-RAG rollout.** The local corpus has 1,117 document rows, but only 357 ready/enabled rows with chunks and just 4 logical content groups. All 357 chunked rows are duplicates at the logical-content grain, legacy vector coverage is 0%, the embedding preflight is unavailable, and the production schema remains at revision 0012. The safe next move is an isolated canonicalization and rebuild rehearsal—not a production migration.",
                },
                {"id": "metrics", "type": "metric-strip", "cardIds": ["logical_groups", "duplicate_rate", "vector_coverage", "source_chunked"]},
                {
                    "id": "corpus_collapse_finding",
                    "type": "markdown",
                    "sourceId": "corpus_profile",
                    "body": "## Most document rows are not rebuildable retrieval evidence\n\nOnly 383 rows are ready and enabled. Of those, 357 have chunks, but only 32 combine chunks with a currently resolvable source file. Source recovery—not indexing throughput—is the main constraint on a clean rebuild.",
                },
                {"id": "corpus_funnel_block", "type": "chart", "chartId": "corpus_funnel", "layout": "full"},
                {
                    "id": "duplicate_finding",
                    "type": "markdown",
                    "sourceId": "independent_sql",
                    "body": "## Four repeated payloads account for every chunked document\n\nIndependent aggregate SQL reproduces 4 ordered chunk-content manifests across 357 retrieval-eligible rows. Their group sizes are 180, 59, 59, and 59, leaving 353 excess duplicate rows beyond one canonical row per group.",
                },
                {"id": "logical_groups_block", "type": "chart", "chartId": "logical_group_sizes", "layout": "full"},
                {
                    "id": "rollout_gates_heading",
                    "type": "markdown",
                    "body": "## Production rollout gates remain closed\n\nThe database rehearsal proved migration reversibility on an isolated clone, but corpus readiness is a separate gate. Every current prerequisite below blocks production promotion."
                },
                {"id": "quality_gates_block", "type": "table", "tableId": "quality_gates", "layout": "full"},
                {
                    "id": "validation_heading",
                    "type": "markdown",
                    "sourceId": "independent_sql",
                    "body": "## Independent validation supports the no-go decision\n\nA second database-side aggregation matches all five decision-critical application-profile counts exactly. The result is ready to share as a data-quality audit, while the underlying RAG rollout remains blocked."
                },
                {"id": "reconciliation_block", "type": "table", "tableId": "reconciliation", "layout": "full"},
                {
                    "id": "recommendations",
                    "type": "markdown",
                    "body": "## Recommendations\n\n1. Preserve the verified pre-upgrade clone and keep production at revision 0012 until explicit migration approval.\n2. On an isolated clone, select one canonical row per chunk manifest; do not delete production duplicates.\n3. Repair chunk-count metadata and missing BM25 text, then rebuild source-backed logical groups into an isolated versioned index.\n4. Restore the embedding dependency and require complete vector-count/hash/manifest validation before activation.\n5. Replace generated cases with a human-reviewed, representative benchmark before comparing legacy and versioned retrieval."
                },
                {
                    "id": "questions",
                    "type": "markdown",
                    "body": "## Questions to Resolve\n\n- Are the four repeated content groups expected fixtures, accidental repeated imports, or evidence that this is not the intended production corpus?\n- Should documents without resolvable source files be exported, quarantined as legacy-only evidence, or retired after review?\n- What minimum benchmark breadth represents the user's real knowledge tasks before a rollout can pass?"
                },
                {
                    "id": "caveats",
                    "type": "markdown",
                    "sourceId": "corpus_profile",
                    "body": "## Caveats\n\nThe 357 chunked documents have no valid declared content hash, so declared hashes cannot independently validate the chunk-manifest partition. Nineteen valid declared hashes belong only to ready/enabled documents without chunks. The audit exposes aggregate counts only and does not inspect or reveal private document contents. No production database rows were changed."
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "summary": [
                    {
                        "logical_groups": grain["logical_content_groups"],
                        "duplicate_rate": uniqueness["duplicate_document_rate_among_chunked"],
                        "vector_coverage": vectors["coverage_rate"],
                        "source_with_chunks": source_with_chunks,
                        "ready_enabled": grain["ready_enabled_documents"],
                        "ready_with_chunks": grain["ready_enabled_with_chunks"],
                        "document_rows": grain["document_rows"],
                    }
                ],
                "corpus_funnel": [
                    {"stage_order": 1, "stage": "All document rows", "documents": grain["document_rows"], "share_of_all": 1.0, "excluded_from_previous": 0},
                    {"stage_order": 2, "stage": "Ready and enabled", "documents": grain["ready_enabled_documents"], "share_of_all": grain["ready_enabled_documents"] / grain["document_rows"], "excluded_from_previous": grain["document_rows"] - grain["ready_enabled_documents"]},
                    {"stage_order": 3, "stage": "With chunks", "documents": grain["ready_enabled_with_chunks"], "share_of_all": grain["ready_enabled_with_chunks"] / grain["document_rows"], "excluded_from_previous": grain["ready_enabled_documents"] - grain["ready_enabled_with_chunks"]},
                    {"stage_order": 4, "stage": "Chunks + source file", "documents": source_with_chunks, "share_of_all": source_with_chunks / grain["document_rows"], "excluded_from_previous": grain["ready_enabled_with_chunks"] - source_with_chunks},
                ],
                "logical_group_sizes": [
                    {"group_rank": f"Group {rank}", "documents": size, "share_of_chunked": size / grain["ready_enabled_with_chunks"], "excess_rows": size - 1}
                    for rank, size in enumerate(validation["sql_results"]["manifest_group_sizes"], start=1)
                ],
                "quality_gates": [
                    {"gate_order": 1, "gate": "Production schema", "observed": str(profile["database"]["schema_head"]), "required": "0020 after explicit approval", "status": "BLOCKED"},
                    {"gate_order": 2, "gate": "Embedding dependency", "observed": readiness["hybrid_embedding_error_code"] or "unavailable", "required": "Preflight succeeds", "status": "BLOCKED"},
                    {"gate_order": 3, "gate": "Legacy vector coverage", "observed": f"{vectors['coverage_rate']:.0%}", "required": "Complete and reconciled", "status": "BLOCKED"},
                    {"gate_order": 4, "gate": "Benchmark breadth", "observed": f"{readiness['reviewable_logical_cases']} generated logical cases", "required": "Human-reviewed representative set", "status": "BLOCKED"},
                ],
                "reconciliation": [
                    {"check_order": index, "metric": key.replace("_", " ").title(), "profile": values["profile"], "sql": values["sql"], "match": "Yes" if values["matches"] else "No"}
                    for index, (key, values) in enumerate(validation["checks"].items(), start=1)
                ],
                "integrity_detail": [
                    {"metric": "BM25 missing chunks", "value": integrity["bm25_missing_chunks"], "denominator": grain["legacy_chunk_rows"]},
                    {"metric": "Chunk-count mismatch documents", "value": integrity["chunk_count_mismatch_documents"], "denominator": grain["document_rows"]},
                    {"metric": "Missing vectors", "value": vectors["missing_vector_count"], "denominator": vectors["mysql_chunks"]},
                ],
            },
        },
        "sources": sources,
        "package_info": {
            "root": "docs/analysis",
            "manifestPath": "rag-data-quality-report-artifact.json",
            "snapshotPath": "rag-data-quality-report-artifact.json",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
