#!/usr/bin/env python3
"""Independently reconcile the RAG profile with aggregate-only SQL."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from personal_assistant.config import settings  # noqa: E402

MANIFEST_SQL = """
SELECT
    d.id AS document_id,
    COUNT(c.id) AS chunk_rows,
    SHA2(
        GROUP_CONCAT(
            COALESCE(c.content, '')
            ORDER BY c.ordinal, c.id
            SEPARATOR '\\0'
        ),
        256
    ) AS manifest_hash
FROM documents AS d
JOIN doc_chunks AS c ON c.doc_id = d.id
WHERE d.status = 'ready' AND d.enabled = 1
GROUP BY d.id
ORDER BY d.id
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    allowed_root = settings.data_dir.resolve()
    profile_path = args.profile.resolve()
    output_path = args.output.resolve()
    for label, path in (("profile", profile_path), ("output", output_path)):
        if path != allowed_root and allowed_root not in path.parents:
            print(f"{label} must stay inside the configured data directory", file=sys.stderr)
            return 2
    if output_path.exists():
        print("validation output already exists; refusing to overwrite", file=sys.stderr)
        return 2

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    sync_url = make_url(settings.db_url).set(drivername="mysql+pymysql")
    engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET SESSION group_concat_max_len = 16777216"))
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM documents) AS document_rows,
                        (SELECT COUNT(*) FROM doc_chunks) AS legacy_chunk_rows,
                        (
                            SELECT COUNT(*) FROM documents
                            WHERE status = 'ready' AND enabled = 1
                        ) AS ready_enabled_documents,
                        (
                            SELECT COUNT(DISTINCT d.id)
                            FROM documents AS d
                            JOIN doc_chunks AS c ON c.doc_id = d.id
                            WHERE d.status = 'ready' AND d.enabled = 1
                        ) AS ready_enabled_with_chunks
                    """
                )
            ).mappings().one()
            manifest_rows = list(connection.execute(text(MANIFEST_SQL)).mappings())
            declared_length_rows = list(
                connection.execute(
                    text(
                        """
                        SELECT CHAR_LENGTH(TRIM(content_hash)) AS hash_length,
                               EXISTS(
                                   SELECT 1 FROM doc_chunks AS c
                                   WHERE c.doc_id = documents.id
                               ) AS has_chunks,
                               COUNT(*) AS documents
                        FROM documents
                        WHERE status = 'ready' AND enabled = 1
                          AND content_hash IS NOT NULL
                          AND TRIM(content_hash) <> ''
                        GROUP BY CHAR_LENGTH(TRIM(content_hash)), has_chunks
                        ORDER BY hash_length, has_chunks
                        """
                    )
                ).mappings()
            )
    finally:
        engine.dispose()

    manifest_sizes = Counter(str(row["manifest_hash"]) for row in manifest_rows)
    sql_results = {
        "document_rows": int(counts["document_rows"]),
        "legacy_chunk_rows": int(counts["legacy_chunk_rows"]),
        "ready_enabled_documents": int(counts["ready_enabled_documents"]),
        "ready_enabled_with_chunks": int(counts["ready_enabled_with_chunks"]),
        "chunk_manifest_groups": len(manifest_sizes),
        "single_chunk_documents": sum(
            int(row["chunk_rows"] == 1) for row in manifest_rows
        ),
        "multi_chunk_documents": sum(
            int(row["chunk_rows"] > 1) for row in manifest_rows
        ),
        "manifest_group_sizes": sorted(manifest_sizes.values(), reverse=True),
        "declared_hash_length_distribution": [
            {
                "hash_length": int(row["hash_length"]),
                "has_chunks": bool(row["has_chunks"]),
                "documents": int(row["documents"]),
            }
            for row in declared_length_rows
        ],
    }
    expected = {
        "document_rows": profile["grain"]["document_rows"],
        "legacy_chunk_rows": profile["grain"]["legacy_chunk_rows"],
        "ready_enabled_documents": profile["grain"]["ready_enabled_documents"],
        "ready_enabled_with_chunks": profile["grain"]["ready_enabled_with_chunks"],
        "chunk_manifest_groups": profile["uniqueness"]["hash_reconciliation"][
            "chunk_manifest_groups"
        ],
    }
    checks = {
        key: {"profile": int(expected[key]), "sql": int(sql_results[key]), "matches": int(expected[key]) == int(sql_results[key])}
        for key in expected
    }
    payload = {
        "as_of_utc": datetime.now(UTC).isoformat(),
        "database_name": sync_url.database,
        "method": "independent aggregate SQL with database-side ordered chunk manifests",
        "checks": checks,
        "all_checks_match": all(item["matches"] for item in checks.values()),
        "sql_results": sql_results,
        "privacy": {
            "document_names_emitted": False,
            "source_paths_emitted": False,
            "content_emitted": False,
            "opaque_hashes_emitted": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "all_checks_match": payload["all_checks_match"],
                "chunk_manifest_groups": sql_results["chunk_manifest_groups"],
                "raw_values_printed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["all_checks_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
