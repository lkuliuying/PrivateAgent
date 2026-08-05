from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_assistant.core.rag_benchmark import (
    BenchmarkChunk,
    build_benchmark_candidates,
    load_benchmark_case_rows,
    resolve_document_source_path,
)


def test_candidate_generation_is_grounded_deterministic_and_redacted() -> None:
    chunks = [
        BenchmarkChunk(
            doc_id=2,
            chunk_id=20,
            ordinal=0,
            heading="Approval checkpoint",
            keywords=("checkpoint", "approval"),
            content="Approval checkpoint recovery uses a durable checkpoint token.",
        ),
        BenchmarkChunk(
            doc_id=1,
            chunk_id=10,
            ordinal=0,
            heading="版本化索引",
            keywords=("版本化索引", "原子切换"),
            content="版本化索引通过原子切换保持旧索引可查询。",
        ),
        BenchmarkChunk(
            doc_id=101,
            chunk_id=1010,
            ordinal=0,
            heading="版本化索引",
            keywords=("版本化索引", "原子切换"),
            content="版本化索引通过原子切换保持旧索引可查询。",
        ),
    ]

    candidates = build_benchmark_candidates(
        chunks,
        limit=10,
        equivalent_doc_ids={1: (1, 101), 2: (2,)},
    )

    assert [candidate["id"] for candidate in candidates] == [
        "doc-1-chunk-10",
        "doc-2-chunk-20",
    ]
    assert all(candidate["review_status"] == "generated" for candidate in candidates)
    assert candidates[0]["relevant_doc_ids"] == [1, 101]
    assert all(candidate["relevance_mode"] == "any" for candidate in candidates)
    for candidate, chunk in zip(candidates, [chunks[1], chunks[0]], strict=True):
        assert all(term.casefold() in chunk.content.casefold() for term in candidate["evidence_terms"])
        assert "content" not in candidate["provenance"]
        assert len(candidate["provenance"]["content_sha256"]) == 64


def test_case_loader_refuses_unreviewed_candidates_by_default(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "review_status": "generated",
                "cases": [
                    {
                        "id": "case-a",
                        "query": "query",
                        "relevant_doc_ids": [1],
                        "evidence_terms": ["anchor"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not reviewed"):
        load_benchmark_case_rows(path)
    rows = load_benchmark_case_rows(path, allow_unreviewed=True)
    assert rows[0]["relevant_doc_ids"] == [1]
    assert rows[0]["evidence_terms"] == ["anchor"]


def test_case_loader_accepts_reviewed_expect_empty_without_documents(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "review_status": "reviewed",
                "cases": [
                    {
                        "id": "case-empty",
                        "query": "absent topic",
                        "expect_empty": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = load_benchmark_case_rows(path)
    assert rows[0]["id"] == "case-empty"
    assert rows[0]["expect_empty"] is True
    assert rows[0]["relevant_doc_ids"] == []
    assert rows[0]["relevant_doc_names"] == []


def test_case_loader_rejects_expect_empty_with_relevant_documents(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "review_status": "reviewed",
                "cases": [
                    {
                        "id": "case-conflict",
                        "query": "query",
                        "relevant_doc_ids": [1],
                        "expect_empty": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expect_empty"):
        load_benchmark_case_rows(path)


def test_source_resolution_prefers_existing_explicit_path(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    resolved = resolve_document_source_path(
        doc_id=1,
        name="document.md",
        source_path=str(source),
        data_dir=tmp_path / "data",
        project_root=tmp_path / "project",
    )
    assert resolved == source.resolve()
