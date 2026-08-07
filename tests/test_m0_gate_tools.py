"""M0 观察工具的自动化测试（m0_gate_common / m0_gate_runner / m0_gate_aggregate）。

覆盖：有效 run 判定、分位数、观察天数、gate 判定、二进制 SHA256、
窗口 ended_at 校验（含负时长与陈旧窗口统计）。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import delete

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from m0_gate_common import (  # noqa: E402
    count_valid_runs,
    gate_verdict,
    latency_percentiles,
    observation_days,
    runs_by_status,
)
from m0_gate_runner import _sha256, _windows_status  # noqa: E402

from personal_assistant.core.models import CompatibilityTelemetryRow  # noqa: E402


def _run(status: str, validation_passed: bool = True, latency: float = 10.0) -> dict:
    return {
        "status": status,
        "validation_passed": validation_passed,
        "latency_s": latency,
        "prompt_id": "daily:01",
    }


def test_valid_completed_run_requires_completed_and_validation():
    assert count_valid_runs(
        [_run("completed", True), _run("completed", False), _run("failed", True)]
    ) == 1
    assert count_valid_runs([]) == 0


def test_runs_by_status_groups_and_sorts():
    assert runs_by_status(
        [_run("completed"), _run("cancelled"), _run("completed")]
    ) == {"cancelled": 1, "completed": 2}


def test_latency_percentiles_only_use_completed_runs():
    values = latency_percentiles(
        [
            _run("completed", latency=1.0),
            _run("completed", latency=2.0),
            _run("completed", latency=3.0),
            _run("failed", latency=99.0),
        ]
    )
    assert values["p50"] == 2.0
    assert values["p95"] == 3.0
    assert latency_percentiles([_run("failed", latency=9.0)])["p95"] is None


def test_observation_days_span():
    days = observation_days(
        ["2026-08-07T00:00:00Z", "2026-08-14T00:00:00Z"]
    )
    assert days == 7.0
    assert observation_days([]) is None
    assert observation_days(["not-a-date"]) is None


def test_gate_verdict_all_criteria():
    aggregate = {
        "valid_completed_runs": 100,
        "observation_days": 7.0,
        "rag_runs": 1,
        "cancel_sample": True,
        "approval_sample": True,
        "ollama_outage_sample": True,
        "windows_ended_cycles": 3,
        "stale_open_windows": 0,
        "negative_duration_windows": 0,
        "stuck_runs_over_10min": 0,
        "p0p1_blockers": [],
    }
    verdict = gate_verdict(aggregate=aggregate)
    assert verdict["gate_pass"] is True
    assert all(check["passed"] for check in verdict["checks"])


@pytest.mark.parametrize(
    ("override", "failed_key"),
    [
        ({"valid_completed_runs": 99}, "valid_completed_runs"),
        ({"observation_days": 6.5}, "observation_days"),
        ({"stale_open_windows": 1}, "stale_open_windows"),
        ({"negative_duration_windows": 1}, "negative_duration_windows"),
        ({"p0p1_blockers": ["issue-1"]}, "p0p1_blockers"),
    ],
)
def test_gate_verdict_fails_on_each_criterion(override, failed_key):
    aggregate = {
        "valid_completed_runs": 100,
        "observation_days": 7.0,
        "rag_runs": 1,
        "cancel_sample": True,
        "approval_sample": True,
        "ollama_outage_sample": True,
        "windows_ended_cycles": 3,
        "stale_open_windows": 0,
        "negative_duration_windows": 0,
        "stuck_runs_over_10min": 0,
        "p0p1_blockers": [],
    }
    aggregate.update(override)
    verdict = gate_verdict(aggregate=aggregate)
    assert verdict["gate_pass"] is False
    failed = [c["key"] for c in verdict["checks"] if not c["passed"]]
    assert failed_key in failed


def test_sha256_matches_hashing_utility(tmp_path):
    target = tmp_path / "binary.bin"
    target.write_bytes(b"m0-gate-test-bytes")
    assert _sha256(target) == hashlib.sha256(b"m0-gate-test-bytes").hexdigest()


@pytest.mark.asyncio
async def test_windows_status_counts_closed_open_negative_and_stale(db):
    """runner 的窗口校验：ended>=started 判定、负时长与陈旧窗口统计。"""
    from datetime import timedelta

    from personal_assistant.core.timeutil import utcnow

    now = utcnow()
    try:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()
        base = dict(scope="process", path="__window__", mode="-", outcome="-", calls=0)
        await db.execute(
            CompatibilityTelemetryRow.__table__.insert(),
            [
                {**base, "scope_key": "w-closed", "started_at": now - timedelta(hours=2), "ended_at": now - timedelta(hours=1)},
                {**base, "scope_key": "w-open", "started_at": now - timedelta(hours=5), "ended_at": None},
                {**base, "scope_key": "w-neg", "started_at": now - timedelta(hours=2), "ended_at": now - timedelta(hours=3)},
            ],
        )
        await db.commit()

        status = await _windows_status(db.bind, ["w-closed", "w-open", "w-neg"])
        # w-closed 与 w-neg 都有 ended_at（后者被 negative 单独标记），w-open 无
        assert status["closed"] == 2
        assert status["open"] == 1
        assert status["negative"] == 1
        assert status["stale_open"] == 1
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()
