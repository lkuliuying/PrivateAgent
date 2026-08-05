#!/usr/bin/env python3
"""Rehearse canonical versioned RAG on a disposable verified database clone."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chromadb
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from alembic import command  # noqa: E402
from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.database_clone import (  # noqa: E402
    DatabaseCloneError,
    build_clone_name,
    create_verified_database_clone,
    snapshot_database,
    validate_clone_name,
)
from personal_assistant.core.rag_canonicalization import (  # noqa: E402
    load_canonical_document_ids,
)
from personal_assistant.core.store_chroma import (  # noqa: E402
    VERSIONED_COLLECTION_NAME,
)


def parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--canonicalization-plan", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--ollama-base-url", default="http://127.0.0.1:11435")
    parser.add_argument("--base-revision", default="0012")
    parser.add_argument("--max-p95-ms", type=float, default=2_000.0)
    parser.add_argument("--drop-clone-after-success", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/rehearsals") / f"versioned-rag-{stamp}.json",
    )
    return parser.parse_args()


def _bounded_path(path: Path, *, root: Path, label: str) -> Path:
    resolved = path.resolve()
    allowed = root.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ValueError(f"{label} must stay inside {allowed}")
    return resolved


def _run_private_subprocess(args: list[str], *, env: dict[str, str]) -> int:
    completed = subprocess.run(  # noqa: S603 - fixed Python executable and scripts.
        args,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=900,
    )
    return int(completed.returncode)


async def _versioned_state(db_url: URL) -> dict[str, Any]:
    engine = create_async_engine(db_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            active_rows = list(
                (
                    await connection.execute(
                        text(
                            "SELECT h.doc_id, h.active_version_id, v.status, "
                            "v.chunk_count, v.vector_count, v.manifest_sha256 "
                            "FROM document_index_heads AS h "
                            "JOIN document_index_versions AS v "
                            "ON v.id = h.active_version_id "
                            "ORDER BY h.doc_id"
                        )
                    )
                ).mappings()
            )
            version_count = int(
                await connection.scalar(
                    text("SELECT COUNT(*) FROM document_index_versions")
                )
                or 0
            )
            chunk_count = int(
                await connection.scalar(
                    text("SELECT COUNT(*) FROM document_index_chunks")
                )
                or 0
            )
    finally:
        await engine.dispose()
    return {
        "active_document_ids": [int(row["doc_id"]) for row in active_rows],
        "active_version_ids": [str(row["active_version_id"]) for row in active_rows],
        "active_statuses": sorted({str(row["status"]) for row in active_rows}),
        "active_chunk_count": sum(int(row["chunk_count"]) for row in active_rows),
        "active_vector_count": sum(int(row["vector_count"]) for row in active_rows),
        "active_manifests_present": all(
            bool(str(row["manifest_sha256"] or "")) for row in active_rows
        ),
        "version_count": version_count,
        "chunk_count": chunk_count,
    }


def _isolated_vector_state(
    isolated_data_dir: Path,
    *,
    active_version_ids: list[str],
) -> dict[str, Any]:
    client = chromadb.PersistentClient(path=str(isolated_data_dir / "chroma"))
    collection = client.get_collection(VERSIONED_COLLECTION_NAME)
    per_version: dict[str, int] = {}
    for version_id in active_version_ids:
        result = collection.get(
            where={"index_version_id": version_id},
            include=[],
            limit=1_000_000,
        )
        per_version[version_id] = len(result.get("ids", []))
    return {
        "collection": VERSIONED_COLLECTION_NAME,
        "total_vectors": int(collection.count()),
        "vectors_per_active_version": per_version,
    }


async def _drop_created_clone(source_url: URL, clone_database: str) -> None:
    validate_clone_name(source_url.database or "", clone_database)
    engine = create_async_engine(
        source_url.set(database="mysql"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as connection:
            exists = int(
                await connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM information_schema.schemata "
                        "WHERE schema_name = :database"
                    ),
                    {"database": clone_database},
                )
                or 0
            )
            if exists != 1:
                raise DatabaseCloneError("created rehearsal clone no longer exists uniquely")
            await connection.execute(  # noqa: S608 - validated source-specific clone.
                text(f"DROP DATABASE `{clone_database}`")
            )
            exists_after = int(
                await connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM information_schema.schemata "
                        "WHERE schema_name = :database"
                    ),
                    {"database": clone_database},
                )
                or 0
            )
            if exists_after != 0:
                raise DatabaseCloneError("created rehearsal clone still exists after drop")
    finally:
        await engine.dispose()


def run(args: argparse.Namespace) -> int:
    data_root = (PROJECT_ROOT / "data").resolve()
    rehearsal_root = (data_root / "rehearsals").resolve()
    plan_path = _bounded_path(
        args.canonicalization_plan,
        root=data_root,
        label="canonicalization plan",
    )
    cases_path = _bounded_path(args.cases, root=data_root, label="evaluation cases")
    output_path = _bounded_path(args.output, root=rehearsal_root, label="output")
    if output_path.exists():
        raise FileExistsError("rehearsal output already exists; refusing to overwrite")

    source_url = make_url(settings.db_url)
    source_database = source_url.database or ""
    clone_database = build_clone_name(source_database)
    canonical_ids = load_canonical_document_ids(
        plan_path,
        allowed_root=data_root,
        target_database=clone_database,
    )
    isolated_data_dir = output_path.with_suffix("")
    if isolated_data_dir.exists():
        raise FileExistsError("isolated rehearsal data directory already exists")

    preview = {
        "mode": "execute" if args.yes else "preview",
        "source_database": source_database,
        "clone_database": clone_database,
        "canonical_documents": len(canonical_ids),
        "isolated_data_dir": str(isolated_data_dir),
        "drop_clone_after_success": bool(args.drop_clone_after_success),
        "primary_database_modified": False,
    }
    if not args.yes:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    isolated_data_dir.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        **preview,
        "started_at": datetime.now(UTC).isoformat(),
        "base_revision": args.base_revision,
        "head_revision": None,
        "migration_exit_code": None,
        "evaluation_exit_code": None,
        "rehearsal_passed": False,
        "rollout_ready": False,
        "clone_dropped": False,
        "primary_database_modified": False,
    }
    original_settings_url = settings.db_url
    clone_created = False
    upgraded = False
    integrity_ok = False
    try:
        clone_result = asyncio.run(
            create_verified_database_clone(
                source_url,
                clone_database=clone_database,
            )
        )
        clone_created = True
        report["clone_verified"] = clone_result.verified
        report["primary_database_revision_before"] = clone_result.source.schema_head
        report["source_counts_sha256"] = clone_result.source.counts_sha256
        report["clone_counts_sha256"] = clone_result.clone.counts_sha256
        if clone_result.clone.schema_head != args.base_revision:
            raise DatabaseCloneError("rehearsal clone started at the wrong revision")

        clone_url = source_url.set(database=clone_database)
        settings.db_url = clone_url.render_as_string(hide_password=False)
        alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
        command.upgrade(alembic_config, "head")
        upgraded = True
        upgraded_snapshot = asyncio.run(snapshot_database(clone_url))
        report["head_revision"] = upgraded_snapshot.schema_head
        if upgraded_snapshot.schema_head != "0020":
            raise DatabaseCloneError("rehearsal clone did not reach revision 0020")
        for table, count in clone_result.source.table_counts.items():
            if upgraded_snapshot.table_counts.get(table) != count:
                raise DatabaseCloneError(
                    f"source table row count changed during upgrade: {table}"
                )

        migration_report = isolated_data_dir / "migration-report.json"
        evaluation_report = isolated_data_dir / "evaluation-report.json"
        child_env = os.environ.copy()
        child_env.update(
            {
                "PA_DB_URL": clone_url.render_as_string(hide_password=False),
                "PA_DATA_DIR": str(isolated_data_dir),
                "PA_OLLAMA_BASE_URL": str(args.ollama_base_url),
                "PA_VERSIONED_RAG_INDEXING_ENABLED": "true",
                "PA_VERSIONED_RAG_RETRIEVAL_ENABLED": "true",
                "NO_PROXY": "localhost,127.0.0.1,::1",
            }
        )
        report["migration_exit_code"] = _run_private_subprocess(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "migrate_versioned_rag.py"),
                "--yes",
                "--canonicalization-plan",
                str(plan_path),
                "--source-data-dir",
                str(data_root),
                "--report",
                str(migration_report),
            ],
            env=child_env,
        )
        if report["migration_exit_code"] != 0 or not migration_report.is_file():
            raise RuntimeError("canonical versioned RAG migration subprocess failed")
        migration = json.loads(migration_report.read_text(encoding="utf-8"))
        report["migration"] = {
            "planned": migration.get("planned"),
            "migrated": migration.get("migrated"),
            "failed": migration.get("failed"),
            "skipped": migration.get("skipped"),
            "canonical_plan": migration.get("canonical_plan"),
        }
        if (
            migration.get("migrated") != len(canonical_ids)
            or migration.get("failed") != 0
            or migration.get("skipped") != 0
        ):
            raise RuntimeError("canonical migration counts did not match the plan")

        versioned_state = asyncio.run(_versioned_state(clone_url))
        vector_state = _isolated_vector_state(
            isolated_data_dir,
            active_version_ids=versioned_state["active_version_ids"],
        )
        report["versioned_state"] = versioned_state
        report["vector_state"] = {
            "collection": vector_state["collection"],
            "total_vectors": vector_state["total_vectors"],
            "active_version_count": len(vector_state["vectors_per_active_version"]),
            "all_active_versions_have_vectors": all(
                count > 0
                for count in vector_state["vectors_per_active_version"].values()
            ),
        }
        if set(versioned_state["active_document_ids"]) != set(canonical_ids):
            raise RuntimeError("active versioned documents do not match canonical plan")
        if versioned_state["active_statuses"] != ["active"]:
            raise RuntimeError("versioned index contains a non-active head")
        if (
            versioned_state["active_chunk_count"]
            != versioned_state["active_vector_count"]
            or versioned_state["active_vector_count"]
            != vector_state["total_vectors"]
        ):
            raise RuntimeError("versioned chunk and vector counts do not reconcile")
        if not versioned_state["active_manifests_present"]:
            raise RuntimeError("an active version is missing its manifest")

        report["evaluation_exit_code"] = _run_private_subprocess(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "evaluate_rag.py"),
                "--cases",
                str(cases_path),
                "--retrieval",
                "versioned",
                "--mode",
                "hybrid",
                "--allow-unreviewed",
                "--max-p95-ms",
                str(float(args.max_p95_ms)),
                "--report",
                str(evaluation_report),
            ],
            env=child_env,
        )
        if report["evaluation_exit_code"] not in {0, 2} or not evaluation_report.is_file():
            raise RuntimeError("versioned retrieval evaluation did not complete")
        evaluation = json.loads(evaluation_report.read_text(encoding="utf-8"))
        evaluation_result = evaluation.get("report", {})
        report["evaluation"] = {
            "status": evaluation.get("status"),
            "reviewed": evaluation.get("reviewed"),
            "vector_dimension": evaluation.get("vector_dimension"),
            "case_count": evaluation_result.get("case_count"),
            "recall_at_k": evaluation_result.get("recall_at_k"),
            "mrr": evaluation_result.get("mrr"),
            "citation_correctness": evaluation_result.get("citation_correctness"),
            "empty_recall_rate": evaluation_result.get("empty_recall_rate"),
            "abstention_rate": evaluation_result.get("abstention_rate"),
            "p95_latency_ms": evaluation_result.get("p95_latency_ms"),
            "failures": evaluation_result.get("failures"),
        }
        if not evaluation.get("vector_dimension") or evaluation.get("status") not in {
            "passed",
            "gate_failed",
        }:
            raise RuntimeError("versioned retrieval did not produce a hybrid evaluation")
        integrity_ok = True
        report["rollout_ready"] = bool(
            evaluation.get("status") == "passed" and evaluation.get("reviewed") is True
        )
    except Exception as exc:  # noqa: BLE001
        report["error_type"] = type(exc).__name__
    finally:
        if clone_created and upgraded:
            try:
                command.downgrade(
                    Config(str(PROJECT_ROOT / "alembic.ini")),
                    args.base_revision,
                )
                report["clone_rollback_revision"] = asyncio.run(
                    snapshot_database(source_url.set(database=clone_database))
                ).schema_head
            except Exception as exc:  # noqa: BLE001
                report["rollback_error_type"] = type(exc).__name__
                integrity_ok = False
        settings.db_url = original_settings_url

        source_after = asyncio.run(snapshot_database(source_url))
        source_before = report.get("source_counts_sha256")
        report["primary_database_counts_sha256_after"] = source_after.counts_sha256
        report["primary_database_revision_after"] = source_after.schema_head
        if (
            source_before
            and (
                source_after.counts_sha256 != source_before
                or source_after.schema_head
                != report.get("primary_database_revision_before")
            )
        ):
            report["primary_database_modified"] = True
            integrity_ok = False

        rollback_ok = report.get("clone_rollback_revision") == args.base_revision
        report["rehearsal_passed"] = bool(integrity_ok and rollback_ok)
        if (
            report["rehearsal_passed"]
            and clone_created
            and args.drop_clone_after_success
        ):
            try:
                asyncio.run(_drop_created_clone(source_url, clone_database))
                report["clone_dropped"] = True
            except Exception as exc:  # noqa: BLE001
                report["drop_clone_error_type"] = type(exc).__name__
                report["rehearsal_passed"] = False
        report["finished_at"] = datetime.now(UTC).isoformat()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "output": str(output_path),
        "rehearsal_passed": report["rehearsal_passed"],
        "rollout_ready": report["rollout_ready"],
        "quality_gate_status": report.get("evaluation", {}).get("status"),
        "clone_dropped": report["clone_dropped"],
        "primary_database_modified": report["primary_database_modified"],
        "private_values_printed": False,
        "error_type": report.get("error_type"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["rehearsal_passed"] else 2


def main() -> int:
    try:
        return run(parse_args())
    except (DatabaseCloneError, FileExistsError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "error_type": type(exc).__name__,
                    "primary_database_modified": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
