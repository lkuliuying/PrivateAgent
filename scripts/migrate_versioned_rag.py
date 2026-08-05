#!/usr/bin/env python3
"""Plan or execute a bounded migration from legacy to versioned RAG indexes.

The command is dry-run by default. Execution builds one side-by-side version at
a time and never enables versioned retrieval automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.index_versions import DocumentIndexRepository  # noqa: E402
from personal_assistant.core.models import Document, DocumentIndexHead  # noqa: E402
from personal_assistant.core.rag_benchmark import (  # noqa: E402
    resolve_document_source_path,
)
from personal_assistant.core.rag_canonicalization import (  # noqa: E402
    load_canonical_document_ids,
)
from personal_assistant.workers.importer import import_document  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="执行有界迁移；省略则只预览")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument(
        "--source-data-dir",
        type=Path,
        help="源文件解析根目录；用于 PA_DATA_DIR 指向隔离 Chroma 的演练",
    )
    parser.add_argument(
        "--canonicalization-plan",
        type=Path,
        help="仅迁移 data/ 下经过校验的 canonical dry-run 计划",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="可选：把逐项计划写入 data/；控制台只打印聚合摘要",
    )
    parser.add_argument(
        "--rebuild-active",
        action="store_true",
        help="也为已有 active head 的文档创建新版本",
    )
    return parser.parse_args()


def source_path_for(
    document: Document,
    *,
    source_data_dir: Path | None = None,
) -> Path | None:
    return resolve_document_source_path(
        doc_id=document.id,
        name=document.name,
        source_path=document.source_path,
        data_dir=source_data_dir or settings.data_dir,
        project_root=PROJECT_ROOT,
    )


async def run(args: argparse.Namespace) -> int:
    limit = max(1, min(int(args.limit), 1_000))
    target = make_url(settings.db_url)
    target_database = target.database or ""
    project_data_root = (PROJECT_ROOT / "data").resolve()
    source_data_dir = (args.source_data_dir or settings.data_dir).resolve()
    if source_data_dir != project_data_root and project_data_root not in source_data_dir.parents:
        print("source data directory must stay inside the project data root", file=sys.stderr)
        return 2
    canonical_ids: tuple[int, ...] = ()
    if args.canonicalization_plan:
        if int(args.after_id) != 0:
            print("--after-id cannot be combined with --canonicalization-plan", file=sys.stderr)
            return 2
        canonical_ids = load_canonical_document_ids(
            args.canonicalization_plan,
            allowed_root=project_data_root,
            target_database=target_database,
        )
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            schema_revision = await db.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            if str(schema_revision) != "0020":
                target = make_url(settings.db_url)
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "reason": "schema_revision_not_ready",
                            "database": f"{target.host or 'localhost'}:{target.port or 3306}/{target.database}",
                            "observed_revision": str(schema_revision),
                            "required_revision": "0020",
                            "mutations_performed": False,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 2
            stmt = select(Document).where(
                Document.status == "ready",
                Document.enabled.is_(True),
            )
            if canonical_ids:
                stmt = stmt.where(Document.id.in_(canonical_ids))
            else:
                stmt = stmt.where(
                    Document.id > max(0, int(args.after_id))
                ).limit(limit)
            stmt = stmt.order_by(Document.id.asc())
            if not args.rebuild_active:
                stmt = stmt.outerjoin(
                    DocumentIndexHead,
                    DocumentIndexHead.doc_id == Document.id,
                ).where(DocumentIndexHead.active_version_id.is_(None))
            documents = list((await db.execute(stmt)).scalars().all())
        if canonical_ids:
            found_ids = {document.id for document in documents}
            missing_ids = sorted(set(canonical_ids) - found_ids)
            if missing_ids:
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "reason": "canonical_documents_unavailable_or_already_active",
                            "missing_document_ids": missing_ids,
                            "mutations_performed": False,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 2
        plan = [
            {
                "doc_id": document.id,
                "source_available": source_path_for(
                    document,
                    source_data_dir=source_data_dir,
                )
                is not None,
            }
            for document in documents
        ]
        summary = {
            "mode": "execute" if args.yes else "dry_run",
            "database": f"{target.host or 'localhost'}:{target.port or 3306}/{target.database}",
            "retrieval_enabled": settings.versioned_rag_retrieval_enabled,
            "planned": len(plan),
            "source_available": sum(item["source_available"] for item in plan),
            "canonical_plan": bool(canonical_ids),
            "private_values_printed": False,
        }
        if not args.yes:
            if args.report:
                report_path = _write_report(args.report, {**summary, "items": plan})
                summary["report"] = str(report_path)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        results: list[dict] = []
        for document in documents:
            path = source_path_for(document, source_data_dir=source_data_dir)
            if path is None:
                results.append(
                    {
                        "doc_id": document.id,
                        "status": "skipped",
                        "reason": "source_missing",
                    }
                )
                continue
            async with factory() as db:
                before = await DocumentIndexRepository(db).get_head(document.id)
                before_id = before.active_version_id if before else None
            await import_document(
                document.id,
                str(path),
                activity_kind="reindex",
                use_versioned=True,
            )
            async with factory() as db:
                repository = DocumentIndexRepository(db)
                head = await repository.get_head(document.id)
                active_id = head.active_version_id if head else None
                active = (
                    await repository.get_version(active_id) if active_id else None
                )
            succeeded = bool(
                active is not None
                and active.status == "active"
                and active_id != before_id
            )
            results.append(
                {
                    "doc_id": document.id,
                    "status": "migrated" if succeeded else "failed",
                    "active_version_id": active_id,
                }
            )
        summary["results"] = results
        summary["migrated"] = sum(
            result["status"] == "migrated" for result in results
        )
        summary["failed"] = sum(result["status"] == "failed" for result in results)
        summary["skipped"] = sum(
            result["status"] == "skipped" for result in results
        )
        if args.report:
            report_path = _write_report(args.report, summary)
            summary["report"] = str(report_path)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["failed"] == 0 else 2
    finally:
        await engine.dispose()


def _write_report(path: Path, payload: dict) -> Path:
    report_path = path.resolve()
    allowed_root = settings.data_dir.resolve()
    if report_path != allowed_root and allowed_root not in report_path.parents:
        raise ValueError("report must stay inside the configured data directory")
    if report_path.exists():
        raise FileExistsError("report already exists; refusing to overwrite")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except Exception as exc:  # noqa: BLE001
        print(f"versioned RAG migration failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
