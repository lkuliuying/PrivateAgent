#!/usr/bin/env python3
"""Generate grounded, local-only RAG benchmark candidates from existing chunks.

The output belongs under the ignored ``data/`` tree because queries and
document IDs may reveal private knowledge.  Generated cases are deliberately
``review_status=generated`` and cannot pass the production rollout gate until
they are explicitly reviewed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.models import DocChunk, Document  # noqa: E402
from personal_assistant.core.rag_benchmark import (  # noqa: E402
    BenchmarkChunk,
    build_benchmark_candidates,
    resolve_document_source_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--include-missing-source",
        action="store_true",
        help="也生成只能用于 legacy 基线、不能旁路重建的文档候选",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    limit = max(1, min(int(args.limit), 500))
    output = args.output or (
        settings.data_dir
        / "benchmarks"
        / f"rag-candidates-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    )
    output = output.resolve()
    allowed_root = settings.data_dir.resolve()
    if output != allowed_root and allowed_root not in output.parents:
        raise ValueError("benchmark output must stay inside the configured data directory")
    if output.exists():
        raise FileExistsError("benchmark output already exists; refusing to overwrite")

    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            rows = (
                await db.execute(
                    select(Document, DocChunk)
                    .join(DocChunk, DocChunk.doc_id == Document.id)
                    .where(Document.status == "ready", Document.enabled.is_(True))
                    .order_by(Document.id.asc(), DocChunk.ordinal.asc())
                )
            ).all()
    finally:
        await engine.dispose()

    source_available: dict[int, bool] = {}
    source_documents = 0
    benchmark_chunks: list[BenchmarkChunk] = []
    chunks_by_doc: dict[int, list[tuple[int, str]]] = {}
    declared_hash_by_doc: dict[int, str | None] = {}
    for document, chunk in rows:
        chunks_by_doc.setdefault(document.id, []).append((chunk.ordinal, chunk.content))
        declared_hash_by_doc[document.id] = document.content_hash
        if document.id not in source_available:
            source_available[document.id] = (
                resolve_document_source_path(
                    doc_id=document.id,
                    name=document.name,
                    source_path=document.source_path,
                    data_dir=settings.data_dir,
                    project_root=PROJECT_ROOT,
                )
                is not None
            )
            source_documents += int(source_available[document.id])
        if not args.include_missing_source and not source_available[document.id]:
            continue
        keywords = tuple(
            str(item) for item in (chunk.keywords_json or []) if str(item).strip()
        )
        benchmark_chunks.append(
            BenchmarkChunk(
                doc_id=document.id,
                chunk_id=chunk.id,
                ordinal=chunk.ordinal,
                content=chunk.content,
                heading=chunk.heading,
                keywords=keywords,
            )
        )
    docs_by_hash: dict[str, list[int]] = {}
    for doc_id, chunks in chunks_by_doc.items():
        content_hash = declared_hash_by_doc.get(doc_id)
        if not content_hash:
            canonical = "\0".join(
                content for _, content in sorted(chunks, key=lambda item: item[0])
            )
            content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        docs_by_hash.setdefault(content_hash, []).append(doc_id)
    equivalent_doc_ids = {
        doc_id: tuple(sorted(group))
        for group in docs_by_hash.values()
        for doc_id in group
    }
    cases = build_benchmark_candidates(
        benchmark_chunks,
        limit=limit,
        equivalent_doc_ids=equivalent_doc_ids,
    )
    if not cases:
        raise ValueError("no grounded benchmark candidates could be generated")
    payload = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "review_status": "generated",
        "privacy": "local-only; do not commit",
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "candidate_cases": len(cases),
                "eligible_documents": len({chunk.doc_id for chunk in benchmark_chunks}),
                "documents_with_source": source_documents,
                "duplicate_equivalence_groups": sum(
                    len(group) > 1 for group in docs_by_hash.values()
                ),
                "review_status": "generated",
                "queries_printed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except (OSError, ValueError) as exc:
        print(f"RAG benchmark generation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
