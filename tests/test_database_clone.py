from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_assistant.core.database_clone import (
    DatabaseCloneError,
    DatabaseSnapshot,
    build_clone_name,
    compare_snapshots,
    validate_clone_name,
)


def test_clone_name_is_source_specific_bounded_and_deterministic() -> None:
    now = datetime(2026, 8, 2, 9, 10, 11, tzinfo=timezone.utc)
    name = build_clone_name("personal_assistant", now=now)
    assert name == "personal_assistant_preupgrade_20260802091011"
    long_name = build_clone_name("a" * 64, now=now)
    assert len(long_name) == 64
    validate_clone_name("personal_assistant", name)
    validate_clone_name("a" * 64, long_name)


def test_clone_name_rejects_overwrite_and_unrelated_targets() -> None:
    with pytest.raises(DatabaseCloneError, match="source-specific"):
        validate_clone_name("personal_assistant", "personal_assistant")
    with pytest.raises(DatabaseCloneError, match="source-specific"):
        validate_clone_name("personal_assistant", "other_preupgrade_20260802091011")
    with pytest.raises(DatabaseCloneError, match="14-digit"):
        validate_clone_name("personal_assistant", "personal_assistant_preupgrade_latest")


def test_snapshot_comparison_is_exact_without_exposing_rows() -> None:
    source = DatabaseSnapshot(
        database="personal_assistant",
        schema_head="0012",
        table_counts={"documents": 10, "sessions": 4},
    )
    identical = DatabaseSnapshot(
        database="personal_assistant_preupgrade_20260802091011",
        schema_head="0012",
        table_counts={"documents": 10, "sessions": 4},
    )
    changed = DatabaseSnapshot(
        database="personal_assistant_preupgrade_20260802091011",
        schema_head="0011",
        table_counts={"documents": 9, "extra": 1},
    )
    assert compare_snapshots(source, identical) == []
    assert compare_snapshots(source, changed) == [
        "schema head mismatch",
        "table set mismatch",
        "row count mismatch: documents",
    ]
    assert source.total_rows == 14
    assert len(source.counts_sha256) == 64
