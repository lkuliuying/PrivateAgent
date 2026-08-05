#!/usr/bin/env python3
"""Run a read-only RAG rollout gate against a fixed JSON query set.

Case format::

    [{"id": "auth", "query": "How is auth configured?",
      "relevant_doc_names": ["security.md"]}]

Optional per-case fields: ``relevant_doc_ids``, ``evidence_terms``,
``relevance_mode`` (``all``/``any``), ``expect_empty`` (no-answer case;
must not carry relevant documents, only observed via abstention_rate),
and ``review_status`` (top-level ``review_status`` applies globally).
Top-level ``review_status`` other than ``reviewed`` requires
``--allow-unreviewed``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.hybrid_retrieval import HybridRetriever  # noqa: E402
from personal_assistant.core.models import Document  # noqa: E402
from personal_assistant.core.rag_benchmark import load_benchmark_case_rows  # noqa: E402
from personal_assistant.core.rag_evaluation import (  # noqa: E402
    RetrievalEvaluationCase,
    RetrievalGate,
    evaluate_retrieval,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--retrieval",
        choices=("config", "legacy", "versioned"),
        default="config",
    )
    parser.add_argument(
        "--mode",
        choices=("hybrid", "bm25"),
        default="hybrid",
        help="正式 gate 使用 hybrid；bm25 仅用于依赖离线时的词法基线",
    )
    parser.add_argument("--min-recall", type=float, default=0.8)
    parser.add_argument("--min-mrr", type=float, default=0.7)
    parser.add_argument("--min-citation-correctness", type=float, default=0.8)
    parser.add_argument("--max-empty-rate", type=float, default=0.1)
    parser.add_argument("--max-p95-ms", type=float, default=2_000.0)
    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="仅做候选集特征化；生产 rollout gate 默认拒绝未审阅 case",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="将不含查询和正文的完整 JSON 结果写入 data 目录",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    rows = load_benchmark_case_rows(
        args.cases.resolve(), allow_unreviewed=args.allow_unreviewed
    )
    required_names = {
        name for row in rows for name in row["relevant_doc_names"]
    }
    required_ids = {doc_id for row in rows for doc_id in row["relevant_doc_ids"]}
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            filters = []
            if required_names:
                filters.append(Document.name.in_(required_names))
            if required_ids:
                filters.append(Document.id.in_(required_ids))
            from sqlalchemy import or_

            documents = list(
                (await db.execute(select(Document).where(or_(*filters))))
                .scalars()
                .all()
            )
            ids_by_name: dict[str, set[int]] = {}
            for document in documents:
                ids_by_name.setdefault(document.name, set()).add(document.id)
            missing = sorted(required_names - ids_by_name.keys())
            if missing:
                raise ValueError(
                    "evaluation documents are missing: " + ", ".join(missing)
                )
            found_ids = {document.id for document in documents}
            missing_ids = sorted(required_ids - found_ids)
            if missing_ids:
                raise ValueError(
                    "evaluation document ids are missing: "
                    + ", ".join(map(str, missing_ids))
                )
            unavailable_ids = sorted(
                document.id
                for document in documents
                if document.status != "ready" or not document.enabled
            )
            if unavailable_ids:
                raise ValueError(
                    "evaluation documents are not ready and enabled: "
                    + ", ".join(map(str, unavailable_ids))
                )
            cases = [
                RetrievalEvaluationCase(
                    id=row["id"],
                    query=row["query"],
                    relevant_doc_ids=frozenset(
                        [
                            *row["relevant_doc_ids"],
                            *(
                                doc_id
                                for name in row["relevant_doc_names"]
                                for doc_id in ids_by_name[name]
                            ),
                        ]
                    ),
                    evidence_terms=tuple(row["evidence_terms"]),
                    relevance_mode=row["relevance_mode"],
                    expect_empty=row["expect_empty"],
                )
                for row in rows
            ]
            use_versioned = {
                "config": None,
                "legacy": False,
                "versioned": True,
            }[args.retrieval]
            retriever = HybridRetriever(
                db,
                use_versioned=use_versioned,
                enable_vector=args.mode == "hybrid",
            )
            vector_dimension = None
            if args.mode == "hybrid":
                try:
                    vector_dimension = await retriever.require_vector_ready()
                except Exception as exc:  # noqa: BLE001
                    dependency_report = {
                        "status": "dependency_unavailable",
                        "error_code": "embedding_preflight_failed",
                        "error_type": type(exc).__name__,
                        "retrieval": args.retrieval,
                        "mode": args.mode,
                        "case_count": len(cases),
                        "reviewed": all(
                            row["review_status"] == "reviewed" for row in rows
                        ),
                    }
                    _write_report(args.report, dependency_report)
                    print(json.dumps(dependency_report, ensure_ascii=False, indent=2))
                    return 4

            async def retrieve(query: str, top_k: int):
                return await retriever.retrieve(query, top_k=top_k)

            report = await evaluate_retrieval(
                cases,
                retrieve,
                top_k=args.top_k,
                gate=RetrievalGate(
                    min_recall_at_k=args.min_recall,
                    min_mrr=args.min_mrr,
                    min_citation_correctness=args.min_citation_correctness,
                    max_empty_recall_rate=args.max_empty_rate,
                    max_p95_latency_ms=args.max_p95_ms,
                ),
            )
    finally:
        await engine.dispose()
    payload = {
        "status": "passed" if report.passed else "gate_failed",
        "retrieval": args.retrieval,
        "mode": args.mode,
        "reviewed": all(row["review_status"] == "reviewed" for row in rows),
        "vector_dimension": vector_dimension,
        "report": asdict(report),
    }
    _write_report(args.report, payload)
    summary = {
        "status": payload["status"],
        "retrieval": args.retrieval,
        "mode": args.mode,
        "reviewed": payload["reviewed"],
        "case_count": report.case_count,
        "recall_at_k": report.recall_at_k,
        "mrr": report.mrr,
        "citation_correctness": report.citation_correctness,
        "empty_recall_rate": report.empty_recall_rate,
        "abstention_rate": report.abstention_rate,
        "p50_latency_ms": report.p50_latency_ms,
        "p95_latency_ms": report.p95_latency_ms,
        "failures": report.failures,
        "report_path": str(args.report.resolve()) if args.report else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report.passed else 2


def _write_report(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    resolved = path.resolve()
    allowed_root = settings.data_dir.resolve()
    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise ValueError("evaluation report must stay inside the configured data directory")
    if resolved.exists():
        raise FileExistsError("evaluation report already exists; refusing to overwrite")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RAG evaluation configuration error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
