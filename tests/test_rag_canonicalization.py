from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_assistant.core.rag_canonicalization import (
    CanonicalCandidate,
    choose_canonical,
    load_canonical_document_ids,
)


def test_canonical_selection_prioritizes_recoverable_source() -> None:
    selected = choose_canonical(
        [
            CanonicalCandidate(1, False, True, True, datetime(2026, 8, 2, tzinfo=UTC)),
            CanonicalCandidate(2, True, False, False, datetime(2026, 7, 1, tzinfo=UTC)),
        ]
    )

    assert selected.doc_id == 2


def test_canonical_selection_uses_integrity_then_recency() -> None:
    selected = choose_canonical(
        [
            CanonicalCandidate(1, True, True, False, datetime(2026, 8, 2, tzinfo=UTC)),
            CanonicalCandidate(2, True, True, True, datetime(2026, 7, 1, tzinfo=UTC)),
            CanonicalCandidate(3, True, True, True, datetime(2026, 8, 1, tzinfo=UTC)),
        ]
    )

    assert selected.doc_id == 3


def test_canonical_selection_is_deterministic_for_ties() -> None:
    selected = choose_canonical(
        [
            CanonicalCandidate(20, True, True, True),
            CanonicalCandidate(10, True, True, True),
        ]
    )

    assert selected.doc_id == 10


def test_canonical_selection_rejects_empty_group() -> None:
    with pytest.raises(ValueError, match="at least one"):
        choose_canonical([])


def test_canonical_plan_loader_accepts_source_specific_clone(tmp_path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(
        """{
          "mode": "dry_run",
          "mutations_performed": false,
          "database": {"database_name": "personal_assistant"},
          "summary": {"canonical_documents": 2},
          "groups": [
            {"canonical_doc_id": 10, "canonical_source_available": true},
            {"canonical_doc_id": 20, "canonical_source_available": true}
          ]
        }""",
        encoding="utf-8",
    )

    assert load_canonical_document_ids(
        plan,
        allowed_root=tmp_path,
        target_database="personal_assistant_preupgrade_20260802123456",
    ) == (10, 20)


def test_canonical_plan_loader_rejects_unrelated_database(tmp_path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(
        """{
          "mode": "dry_run",
          "mutations_performed": false,
          "database": {"database_name": "personal_assistant"},
          "groups": [
            {"canonical_doc_id": 10, "canonical_source_available": true}
          ]
        }""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source-specific"):
        load_canonical_document_ids(
            plan,
            allowed_root=tmp_path,
            target_database="unrelated_database",
        )


def test_canonical_plan_loader_requires_recoverable_sources(tmp_path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(
        """{
          "mode": "dry_run",
          "mutations_performed": false,
          "database": {"database_name": "personal_assistant"},
          "groups": [
            {"canonical_doc_id": 10, "canonical_source_available": false}
          ]
        }""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no recoverable source"):
        load_canonical_document_ids(
            plan,
            allowed_root=tmp_path,
            target_database="personal_assistant",
        )
