from __future__ import annotations

import pytest

from personal_assistant.core.rag_data_quality import (
    _normalize_sha256,
    _percentile,
    _rate,
    _reconcile_content_hashes,
)


def test_data_quality_rate_and_percentile_helpers_are_bounded() -> None:
    assert _rate(1, 4) == 0.25
    assert _rate(0, 0) == 0.0
    assert _percentile([], 0.95) == 0.0
    assert _percentile([0, 1, 2, 3, 4], 0.5) == 2.0
    assert _percentile([0, 10], 0.95) == pytest.approx(9.5)


def test_content_hash_reconciliation_accepts_equivalent_partitions() -> None:
    result = _reconcile_content_hashes(
        {1: "declared-a", 2: "declared-a", 3: "declared-b"},
        {1: "manifest-a", 2: "manifest-a", 3: "manifest-b"},
    )

    assert result["declared_content_hash_groups"] == 2
    assert result["chunk_manifest_groups"] == 2
    assert result["documents_in_partition_conflicts"] == 0
    assert result["partitions_agree"] is True


def test_content_hash_reconciliation_exposes_partition_conflicts() -> None:
    result = _reconcile_content_hashes(
        {1: "declared-a", 2: "declared-a", 3: "declared-b"},
        {1: "manifest-a", 2: "manifest-b", 3: "manifest-b"},
    )

    assert result["declared_groups_with_multiple_manifests"] == 1
    assert result["manifest_groups_with_multiple_declared_hashes"] == 1
    assert result["documents_in_partition_conflicts"] == 3
    assert result["partitions_agree"] is False


def test_sha256_normalization_handles_database_bytes() -> None:
    value = "a" * 64

    assert _normalize_sha256(value) == value
    assert _normalize_sha256(value.encode("ascii")) == value
    assert _normalize_sha256("not-a-hash") is None
    assert _normalize_sha256(b"\xff" * 32) is None


def test_content_hash_reconciliation_does_not_claim_agreement_without_overlap() -> None:
    result = _reconcile_content_hashes({}, {1: "manifest-a"})

    assert result["partitions_comparable"] is False
    assert result["partitions_agree"] is None
