"""Low-cardinality telemetry for compatibility paths awaiting retirement."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_LABELS = {
    "/tools": {
        "modes": frozenset({"legacy_registry"}),
        "outcomes": frozenset({"returned"}),
    },
    "/tools/plan": {
        "modes": frozenset({"legacy_full", "runtime_filtered"}),
        "outcomes": frozenset({"planned", "not_planned", "error"}),
    },
    "/chat/stream": {
        "modes": frozenset(
            {
                "agent_runtime",
                "legacy_runtime_disabled",
                "legacy_tool_result",
                "legacy_rag_tools_disabled",
                "legacy_output_verification_disabled",
            }
        ),
        "outcomes": frozenset({"routed"}),
    },
    "/tool-calls/:id/approve": {
        "modes": frozenset({"legacy_tool_call"}),
        "outcomes": frozenset({"succeeded", "failed", "conflict", "not_found"}),
    },
    "/tool-calls/:id/reject": {
        "modes": frozenset({"legacy_tool_call"}),
        "outcomes": frozenset({"rejected", "conflict", "not_found"}),
    },
    "/tool-calls": {
        "modes": frozenset({"all", "session_filtered"}),
        "outcomes": frozenset({"returned"}),
    },
    "/tool-calls/:id": {
        "modes": frozenset({"legacy_tool_call"}),
        "outcomes": frozenset({"found", "not_found"}),
    },
}


class CompatibilityTelemetry:
    """Track process-lifetime compatibility calls without user-controlled labels."""

    def __init__(self) -> None:
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._lock = Lock()
        self._calls: Counter[str] = Counter()
        self._modes: Counter[tuple[str, str]] = Counter()
        self._outcomes: Counter[tuple[str, str]] = Counter()

    def record(self, *, path: str, mode: str, outcome: str) -> None:
        labels = _LABELS.get(path)
        if labels is None:
            raise ValueError(f"unsupported compatibility path: {path}")
        if mode not in labels["modes"]:
            raise ValueError(f"unsupported compatibility mode: {mode}")
        if outcome not in labels["outcomes"]:
            raise ValueError(f"unsupported compatibility outcome: {outcome}")
        with self._lock:
            self._calls[path] += 1
            self._modes[(path, mode)] += 1
            self._outcomes[(path, outcome)] += 1

    def snapshot(self) -> dict:
        with self._lock:
            calls = self._calls.copy()
            modes = self._modes.copy()
            outcomes = self._outcomes.copy()
        return {
            "scope": "current_process",
            "started_at": self._started_at,
            "paths": {
                path: {
                    "calls": calls[path],
                    "modes": {
                        mode: modes[(path, mode)]
                        for mode in sorted(_LABELS[path]["modes"])
                    },
                    "outcomes": {
                        outcome: outcomes[(path, outcome)]
                        for outcome in sorted(_LABELS[path]["outcomes"])
                    },
                }
                for path in sorted(_LABELS)
            },
        }


class CompatibilityTelemetryPersister:
    """Persist per-window compatibility counts to MySQL (R3 遥测持久化).

    - 每个进程启动 = 一个观察窗口（scope_key = uuid）；定期把自上次 flush 的
      增量写入 ``compatibility_telemetry`` 表（低基数，单写者）；
    - 进程退出（``flush_now(ended=True)``）标记窗口 ``ended_at``；
    - 崩溃最多丢失一个 flush 间隔（默认 60s）的增量；
    - 同一调用会同时产生一条 mode 记录与一条 outcome 记录（各自完整计数，
      数量相等），查询按任一维度聚合即可。
    """

    def __init__(
        self,
        telemetry: CompatibilityTelemetry,
        session_factory: async_sessionmaker,
        *,
        scope: str = "process",
        scope_key: str | None = None,
        flush_interval_seconds: int = 60,
    ) -> None:
        self._telemetry = telemetry
        self._factory = session_factory
        self._scope = scope
        self._scope_key = scope_key or uuid.uuid4().hex[:16]
        self._interval = int(flush_interval_seconds)
        self._last: dict | None = None
        self._stop = asyncio.Event()

    @property
    def scope_key(self) -> str:
        return self._scope_key

    async def run(self) -> None:
        """后台循环：定期 flush 增量，直到 stop()。"""
        while True:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self.flush_now()
            except Exception:  # noqa: BLE001
                # 落库失败不阻断主流程；下个周期重试
                continue

    async def stop(self) -> None:
        self._stop.set()

    async def flush_now(self, *, ended: bool = False) -> list[tuple[str, int]]:
        """把自上次 flush 的增量写入表；ended=True 时标记窗口结束。

        返回 [(label, delta), ...]，label 形如 ``path#mode`` / ``path#outcome``。
        """
        current = self._telemetry.snapshot()
        deltas: list[tuple[str, int]] = []
        for path in sorted(current["paths"]):
            for label, count in current["paths"][path]["modes"].items():
                delta = self._delta(path, label, count)
                if delta > 0:
                    deltas.append((f"{path}#{label}", delta))
            for label, count in current["paths"][path]["outcomes"].items():
                delta = self._delta(path, label, count)
                if delta > 0:
                    deltas.append((f"{path}#{label}", delta))
        self._last = current
        if deltas or ended:
            await self._write(deltas, ended=ended)
        return deltas

    def _delta(self, path: str, label: str, count: int) -> int:
        if self._last is None:
            return count
        prev = 0
        if label in self._last["paths"][path]["modes"]:
            prev = self._last["paths"][path]["modes"][label]
        elif label in self._last["paths"][path]["outcomes"]:
            prev = self._last["paths"][path]["outcomes"][label]
        return max(0, count - prev)

    async def _write(self, deltas: list[tuple[str, int]], *, ended: bool) -> None:
        from .models import CompatibilityTelemetryRow
        from .timeutil import utcnow

        now = utcnow()
        async with self._factory() as db:
            for label, delta in deltas:
                path, _, label_value = label.partition("#")
                row = (
                    await db.execute(
                        select(CompatibilityTelemetryRow).where(
                            CompatibilityTelemetryRow.scope == self._scope,
                            CompatibilityTelemetryRow.scope_key == self._scope_key,
                            CompatibilityTelemetryRow.path == path,
                            CompatibilityTelemetryRow.mode == (
                                label_value if self._is_mode(path, label_value) else "-"
                            ),
                            CompatibilityTelemetryRow.outcome == (
                                label_value if not self._is_mode(path, label_value) else "-"
                            ),
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    db.add(
                        CompatibilityTelemetryRow(
                            scope=self._scope,
                            scope_key=self._scope_key,
                            path=path,
                            mode=(
                                label_value if self._is_mode(path, label_value) else "-"
                            ),
                            outcome=(
                                label_value if not self._is_mode(path, label_value) else "-"
                            ),
                            calls=delta,
                            last_flushed_at=now,
                        )
                    )
                else:
                    row.calls += delta
                    row.last_flushed_at = now
            if ended:
                await db.execute(
                    CompatibilityTelemetryRow.__table__.update()
                    .where(
                        CompatibilityTelemetryRow.scope == self._scope,
                        CompatibilityTelemetryRow.scope_key == self._scope_key,
                    )
                    .values(ended_at=now)
                )
            await db.commit()

    @staticmethod
    def _is_mode(path: str, label: str) -> bool:
        return label in _LABELS[path]["modes"]


async def windowed_telemetry_summary(
    db: AsyncSession, *, since: datetime | None = None
) -> dict[str, Any]:
    """跨窗口聚合兼容遥测（R3 §6.4 观察窗口）。

    按 path 聚合 mode 维度（mode 行与 outcome 行数量相等，取 mode 维度即可）；
    返回窗口列表与各 path 的 legacy 调用总数。``since`` 限定观察起始时间。
    """
    from .models import CompatibilityTelemetryRow

    stmt = select(CompatibilityTelemetryRow)
    if since is not None:
        stmt = stmt.where(CompatibilityTelemetryRow.started_at >= since)
    rows = (await db.execute(stmt)).scalars().all()
    windows: dict[str, dict[str, Any]] = {}
    by_path: Counter[str] = Counter()
    for row in rows:
        window = windows.setdefault(
            row.scope_key,
            {
                "scope": row.scope,
                "scope_key": row.scope_key,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
            },
        )
        if row.mode != "-":
            by_path[row.path] += row.calls
        # 窗口内 path 的 mode 计数用于"legacy 归零"判断（mode 维度完整）
        window.setdefault("paths", {}).setdefault(row.path, 0)
        if row.mode != "-":
            window["paths"][row.path] += row.calls
    return {
        "windows": list(windows.values()),
        "window_count": len(windows),
        "by_path": {path: count for path, count in sorted(by_path.items())},
    }


compatibility_telemetry = CompatibilityTelemetry()
