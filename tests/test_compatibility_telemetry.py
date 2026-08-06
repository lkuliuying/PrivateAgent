"""R3 遥测持久化测试：跨进程观察窗口（compatibility_telemetry 表）。

覆盖：
- 增量 flush 落库（mode/outcome 双行，数量相等）；
- 重复 flush 只写增量（幂等）；
- flush(ended=True) 标记窗口 ended_at；
- 跨窗口聚合 windowed_telemetry_summary；
- 现有内存 snapshot 行为不变。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_assistant.core.compatibility import (
    CompatibilityTelemetry,
    CompatibilityTelemetryPersister,
    windowed_telemetry_summary,
)
from personal_assistant.core.models import CompatibilityTelemetryRow
from personal_assistant.core.timeutil import utcnow


def _factory(db):
    return async_sessionmaker(db.bind, expire_on_commit=False)


def _recording_telemetry() -> CompatibilityTelemetry:
    telemetry = CompatibilityTelemetry()
    telemetry.record(path="/chat/stream", mode="agent_runtime", outcome="routed")
    telemetry.record(path="/chat/stream", mode="legacy_runtime_disabled", outcome="routed")
    telemetry.record(path="/tools/plan", mode="legacy_full", outcome="planned")
    return telemetry


@pytest.mark.asyncio
async def test_persister_flushes_increments_to_db(db):
    telemetry = _recording_telemetry()
    persister = CompatibilityTelemetryPersister(
        telemetry, _factory(db), scope_key="window-a"
    )
    try:
        deltas = await persister.flush_now()
        # 3 条调用 → 3 条 mode 增量 + 2 条 outcome 增量（routed 被共享计数为 2）
        assert len(deltas) == 5
        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        assert len(rows) == 6  # 5 增量行 + 1 窗口基线行
        by_mode = {
            (row.path, row.mode): row.calls
            for row in rows
            if row.mode != "-"
        }
        assert by_mode[("/chat/stream", "agent_runtime")] == 1
        assert by_mode[("/chat/stream", "legacy_runtime_disabled")] == 1
        assert by_mode[("/tools/plan", "legacy_full")] == 1
        # mode 维度与 outcome 维度各自完整计数（同一调用两者都计）
        mode_total = sum(row.calls for row in rows if row.mode != "-")
        outcome_total = sum(row.calls for row in rows if row.outcome != "-")
        assert mode_total == outcome_total == 3
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_persister_flush_is_incremental(db):
    telemetry = _recording_telemetry()
    persister = CompatibilityTelemetryPersister(
        telemetry, _factory(db), scope_key="window-b"
    )
    try:
        first = await persister.flush_now()
        assert len(first) == 5
        # 无新调用 → 第二次 flush 空增量（不重复写入）
        second = await persister.flush_now()
        assert second == []
        # 新调用只写增量
        telemetry.record(path="/tools", mode="legacy_registry", outcome="returned")
        third = await persister.flush_now()
        assert len(third) == 2
        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        by_label = {
            (row.path, row.mode, row.outcome): row.calls for row in rows
        }
        assert by_label[("/tools", "legacy_registry", "-")] == 1
        assert by_label[("/chat/stream", "agent_runtime", "-")] == 1
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_persister_marks_window_ended(db):
    telemetry = _recording_telemetry()
    persister = CompatibilityTelemetryPersister(
        telemetry, _factory(db), scope_key="window-c"
    )
    try:
        await persister.flush_now()
        await persister.flush_now(ended=True)
        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        assert rows
        for row in rows:
            assert row.ended_at is not None
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_zero_call_window_still_records_baseline_row(db):
    """零调用窗口也必须产生基线行，才能证明"窗口存在且 legacy 为 0"。"""
    telemetry = CompatibilityTelemetry()  # 没有任何调用
    persister = CompatibilityTelemetryPersister(
        telemetry, _factory(db), scope_key="window-empty"
    )
    try:
        deltas = await persister.flush_now()
        assert deltas == []
        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        assert len(rows) == 1
        assert rows[0].path == "__window__"
        assert rows[0].calls == 0
        summary = await windowed_telemetry_summary(db)
        assert summary["window_count"] == 1
        assert summary["by_path"] == {}
        assert "legacy_zero" not in summary  # 归零判定由报告脚本基于 by_path 计算
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_windowed_summary_aggregates_across_windows(db):
    telemetry_a = _recording_telemetry()
    persister_a = CompatibilityTelemetryPersister(
        telemetry_a, _factory(db), scope_key="window-1"
    )
    telemetry_b = CompatibilityTelemetry()
    telemetry_b.record(path="/chat/stream", mode="agent_runtime", outcome="routed")
    telemetry_b.record(path="/tools/plan", mode="legacy_full", outcome="planned")
    persister_b = CompatibilityTelemetryPersister(
        telemetry_b, _factory(db), scope_key="window-2"
    )
    try:
        await persister_a.flush_now(ended=True)
        await persister_b.flush_now(ended=True)
        summary = await windowed_telemetry_summary(db)
        assert summary["window_count"] == 2
        assert summary["by_path"]["/chat/stream"] == 3  # window-1 两条 + window-2 一条
        assert summary["by_path"]["/tools/plan"] == 2
        ended = [w for w in summary["windows"] if w["ended_at"] is not None]
        assert len(ended) == 2

        since = utcnow() + timedelta(hours=1)
        empty = await windowed_telemetry_summary(db, since=since)
        assert empty["window_count"] == 0
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()
