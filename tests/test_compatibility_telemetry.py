"""R3 遥测持久化测试：跨进程观察窗口（compatibility_telemetry 表）。

覆盖：
- 增量 flush 落库（mode/outcome 双行，数量相等）；
- 重复 flush 只写增量（幂等）；
- flush(ended=True) 标记窗口 ended_at；
- 跨窗口聚合 windowed_telemetry_summary；
- 现有内存 snapshot 行为不变。
0.3.0 M1 增强：
- 新标签：agent_runtime_rag（知识库聊天）、/chat/agent-runs/:id/stream
  （断线重连）、/agent-runs（显式 Agent Runs API）；
- telemetry_scope：scope 带 <origin>:<version>，QA 与生产区分；
- 聚合过滤：since/until 时间范围、scope_origins、version，及 by_mode 明细。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_assistant.core.compatibility import (
    CompatibilityTelemetry,
    CompatibilityTelemetryPersister,
    telemetry_scope,
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


# ============ 0.3.0 M1：新标签 ============


def test_m1_labels_are_registered_for_ordinary_rag_and_api_routes():
    telemetry = CompatibilityTelemetry()
    telemetry.record(
        path="/chat/stream", mode="agent_runtime_rag", outcome="routed"
    )
    telemetry.record(
        path="/chat/agent-runs/:id/stream",
        mode="agent_runtime",
        outcome="reconnected",
    )
    telemetry.record(
        path="/chat/agent-runs/:id/stream",
        mode="agent_runtime",
        outcome="not_found",
    )
    telemetry.record(path="/agent-runs", mode="agent_runs_api", outcome="created")
    snapshot = telemetry.snapshot()
    assert snapshot["paths"]["/chat/stream"]["modes"]["agent_runtime_rag"] == 1
    assert (
        snapshot["paths"]["/chat/agent-runs/:id/stream"]["modes"]["agent_runtime"] == 2
    )
    assert (
        snapshot["paths"]["/chat/agent-runs/:id/stream"]["outcomes"]["reconnected"]
        == 1
    )
    assert snapshot["paths"]["/agent-runs"]["modes"]["agent_runs_api"] == 1


def test_unknown_m1_label_is_still_rejected():
    telemetry = CompatibilityTelemetry()
    with pytest.raises(ValueError):
        telemetry.record(
            path="/chat/stream", mode="not_a_mode", outcome="routed"
        )


# ============ 0.3.0 M1：scope 标签与聚合过滤 ============


def test_telemetry_scope_carries_origin_and_version(monkeypatch):
    monkeypatch.delenv("PA_QA_STATIC_TOKEN", raising=False)
    assert telemetry_scope() == "process:0.3.0-alpha.2"
    monkeypatch.setenv("PA_QA_STATIC_TOKEN", "qa-token-0123456789abcdef0123456789")
    assert telemetry_scope() == "qa:0.3.0-alpha.2"
    assert telemetry_scope(origin="process", version="0.3.0") == "process:0.3.0"


@pytest.mark.asyncio
async def test_summary_filters_by_time_origin_and_version(db):
    telemetry = CompatibilityTelemetry()
    telemetry.record(path="/chat/stream", mode="agent_runtime", outcome="routed")
    prod = CompatibilityTelemetryPersister(
        telemetry,
        _factory(db),
        scope="process:0.2.1",
        scope_key="window-prod",
    )
    qa_telemetry = CompatibilityTelemetry()
    qa_telemetry.record(
        path="/chat/stream", mode="agent_runtime_rag", outcome="routed"
    )
    qa = CompatibilityTelemetryPersister(
        qa_telemetry,
        _factory(db),
        scope="qa:0.2.1",
        scope_key="window-qa",
    )
    try:
        await prod.flush_now(ended=True)
        await qa.flush_now()

        summary = await windowed_telemetry_summary(db)
        assert summary["window_count"] == 2
        assert summary["ended_window_count"] == 1
        assert summary["open_window_count"] == 1
        assert summary["origins"] == {"process": 1, "qa": 1}
        assert summary["by_mode"]["/chat/stream"]["agent_runtime"] == 1
        assert summary["by_mode"]["/chat/stream"]["agent_runtime_rag"] == 1
        assert summary["windows"][0]["origin"] in {"process", "qa"}
        assert summary["windows"][0]["version"] == "0.2.1"

        only_process = await windowed_telemetry_summary(
            db, scope_origins={"process"}
        )
        assert only_process["window_count"] == 1
        assert only_process["origins"] == {"process": 1}
        assert only_process["by_mode"]["/chat/stream"]["agent_runtime"] == 1
        assert "agent_runtime_rag" not in only_process["by_mode"]["/chat/stream"]

        only_version = await windowed_telemetry_summary(db, version="0.3.0")
        assert only_version["window_count"] == 0
        only_021 = await windowed_telemetry_summary(db, version="0.2.1")
        assert only_021["window_count"] == 2

        since = utcnow() + timedelta(hours=1)
        after = await windowed_telemetry_summary(db, since=since)
        assert after["window_count"] == 0
        before = utcnow() + timedelta(hours=1)
        until = await windowed_telemetry_summary(db, until=before)
        assert until["window_count"] == 2
        early_until = await windowed_telemetry_summary(
            db, until=utcnow() - timedelta(hours=1)
        )
        assert early_until["window_count"] == 0
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_legacy_scope_without_version_is_kept_but_excluded_from_version_filter(
    db,
):
    """0.2.1 及更早的历史窗口 scope 为纯 process（无版本段）。"""
    telemetry = CompatibilityTelemetry()
    telemetry.record(path="/tools/plan", mode="legacy_full", outcome="planned")
    persister = CompatibilityTelemetryPersister(
        telemetry,
        _factory(db),
        scope="process",
        scope_key="window-legacy-format",
    )
    try:
        await persister.flush_now(ended=True)
        summary = await windowed_telemetry_summary(db)
        assert summary["window_count"] == 1
        assert summary["origins"] == {"process": 1}
        assert summary["windows"][0]["version"] is None
        assert summary["by_mode"]["/tools/plan"]["legacy_full"] == 1

        with_version = await windowed_telemetry_summary(db, version="0.2.1")
        assert with_version["window_count"] == 0
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


# ============ 0.3.0 M1/M0：启动 reconcile 陈旧窗口 ============


@pytest.mark.asyncio
async def test_reconcile_closes_only_stale_open_windows_of_previous_processes(db):
    """M0 §5.3：异常退出窗口在下次启动被 reconcile，当前窗口与近期窗口不受影响。"""
    stale_telemetry = CompatibilityTelemetry()
    stale_telemetry.record(path="/tools", mode="legacy_registry", outcome="returned")
    stale = CompatibilityTelemetryPersister(
        stale_telemetry,
        _factory(db),
        scope_key="window-stale",
    )
    recent_telemetry = CompatibilityTelemetry()
    recent = CompatibilityTelemetryPersister(
        recent_telemetry,
        _factory(db),
        scope_key="window-recent",
    )
    try:
        await stale.flush_now()
        await recent.flush_now()
        # 把 stale 窗口的 started_at 改到宽限期之前，模拟上次会话被强杀
        old = utcnow() - timedelta(hours=24)
        await db.execute(
            CompatibilityTelemetryRow.__table__.update()
            .where(CompatibilityTelemetryRow.scope_key == "window-stale")
            .values(started_at=old)
        )
        await db.commit()

        current = CompatibilityTelemetryPersister(
            CompatibilityTelemetry(),
            _factory(db),
            scope_key="window-current",
            reconcile_grace_seconds=7_200,
        )
        reconciled = await current.reconcile_stale_windows()
        assert reconciled == 1

        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        by_scope: dict[str, list] = {}
        for row in rows:
            by_scope.setdefault(row.scope_key, []).append(row)
        assert all(
            row.ended_at is not None for row in by_scope["window-stale"]
        )
        assert all(
            row.ended_at is None for row in by_scope["window-recent"]
        )
        # 当前进程窗口由首次 flush 才写基线行，reconcile 不创建、不关闭它
        assert "window-current" not in by_scope
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_reconcile_does_not_touch_grace_period_windows(db):
    telemetry = CompatibilityTelemetry()
    persister = CompatibilityTelemetryPersister(
        telemetry,
        _factory(db),
        scope_key="window-fresh-enough",
    )
    try:
        await persister.flush_now()
        # 窗口 started_at 距现在小于宽限期（7_200s 用 60s 小窗口模拟）
        recent = CompatibilityTelemetryPersister(
            CompatibilityTelemetry(),
            _factory(db),
            scope_key="window-reconciler",
            reconcile_grace_seconds=60,
        )
        reconciled = await recent.reconcile_stale_windows()
        assert reconciled == 0
        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        assert all(row.ended_at is None for row in rows)
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


# ============ 0.3.0 M1：停机 flush 竞态修复 ============


@pytest.mark.asyncio
async def test_first_flush_with_ended_writes_ended_at_on_baseline(db):
    """停机 flush 是首次 flush 时，基线行必须直接带 ended_at。"""
    telemetry = CompatibilityTelemetry()
    persister = CompatibilityTelemetryPersister(
        telemetry,
        _factory(db),
        scope_key="window-first-ended",
    )
    try:
        await persister.flush_now(ended=True)
        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        assert len(rows) == 1
        assert rows[0].path == "__window__"
        assert rows[0].ended_at is not None
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_ended_flush_recovers_when_window_row_is_not_committed_yet(db):
    """竞态回归：run 循环 flush 已 snapshot 但窗口行未提交时，停机 flush
    （first_flush=False 且窗口行不存在）仍必须写入带 ended_at 的基线行。"""
    telemetry = CompatibilityTelemetry()
    persister = CompatibilityTelemetryPersister(
        telemetry,
        _factory(db),
        scope_key="window-race",
    )
    try:
        # 模拟 run 循环已执行 snapshot（first_flush=False），
        # 但基线行插入尚未提交（并发交错）。
        persister._last = telemetry.snapshot()
        deltas = await persister.flush_now(ended=True)
        assert deltas == []
        rows = (
            (await db.execute(select(CompatibilityTelemetryRow))).scalars().all()
        )
        assert len(rows) == 1
        assert rows[0].path == "__window__"
        assert rows[0].ended_at is not None
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()


@pytest.mark.asyncio
async def test_ended_flush_updates_existing_delta_rows(db):
    """已有调用行的窗口：停机 flush 应把窗口内所有行 ended_at 置位。"""
    telemetry = CompatibilityTelemetry()
    telemetry.record(path="/tools", mode="legacy_registry", outcome="returned")
    persister = CompatibilityTelemetryPersister(
        telemetry,
        _factory(db),
        scope_key="window-with-calls",
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
async def test_ended_at_never_precedes_started_at(db):
    """负时长窗口回归：任何 flush 路径下 ended_at 都必须 >= started_at。"""

    cases = [
        ("window-neg-a", False, False),  # 首次 flush（不结束）
        ("window-neg-b", True, False),  # 首次 flush 即结束（短生命周期进程）
        ("window-neg-c", False, True),  # 先周期 flush 再结束 flush
    ]
    try:
        for scope_key, first_ended, second_ended in cases:
            telemetry = CompatibilityTelemetry()
            persister = CompatibilityTelemetryPersister(
                telemetry,
                _factory(db),
                scope_key=scope_key,
            )
            await persister.flush_now(ended=first_ended)
            if second_ended:
                await persister.flush_now(ended=True)
            # 刷新 fixture session 的快照（REPEATABLE READ 下同一事务读不到
            # 其他 session 之后提交的行）
            await db.rollback()
            rows = (
                (
                    await db.execute(
                        select(CompatibilityTelemetryRow).where(
                            CompatibilityTelemetryRow.scope_key == scope_key
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert rows
            for row in rows:
                if row.ended_at is not None:
                    assert row.ended_at >= row.started_at, (
                        f"{scope_key} 出现负时长窗口: "
                        f"started={row.started_at} ended={row.ended_at}"
                    )
    finally:
        await db.execute(delete(CompatibilityTelemetryRow))
        await db.commit()
