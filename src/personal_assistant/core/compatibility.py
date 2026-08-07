"""Low-cardinality telemetry for compatibility paths awaiting retirement."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .. import __version__
from ..logging_setup import get_logger

logger = get_logger(__name__)

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
                "agent_runtime_rag",
                "legacy_runtime_disabled",
                "legacy_tool_result",
                "legacy_rag_tools_disabled",
                "legacy_output_verification_disabled",
            }
        ),
        "outcomes": frozenset({"routed"}),
    },
    "/chat/agent-runs/:id/stream": {
        "modes": frozenset({"agent_runtime"}),
        "outcomes": frozenset({"reconnected", "not_found"}),
    },
    "/agent-runs": {
        "modes": frozenset({"agent_runs_api"}),
        "outcomes": frozenset({"created"}),
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

# 窗口基线行保留 path：证明窗口存在（即使零调用），不计入 legacy 分路径计数。
WINDOW_BASELINE_PATH = "__window__"


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
        reconcile_grace_seconds: int = 7_200,
    ) -> None:
        self._telemetry = telemetry
        self._factory = session_factory
        self._scope = scope
        self._scope_key = scope_key or uuid.uuid4().hex[:16]
        self._interval = int(flush_interval_seconds)
        self._reconcile_grace = int(reconcile_grace_seconds)
        self._last: dict | None = None
        self._stop = asyncio.Event()

    @property
    def scope_key(self) -> str:
        return self._scope_key

    async def run(self) -> None:
        """后台循环：定期 flush 增量，直到 stop()。

        启动时先 reconcile 陈旧窗口（M0 §5.3：异常退出在下次启动被 reconcile），
        失败不阻断启动。
        """
        try:
            reconciled = await self.reconcile_stale_windows()
            if reconciled:
                logger.info(
                    "compatibility telemetry stale windows reconciled",
                    windows=reconciled,
                )
        except Exception:  # noqa: BLE001
            logger.warning("compatibility telemetry reconcile failed at startup")
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

    async def reconcile_stale_windows(self) -> int:
        """关闭上次启动前未写入 ended_at 的陈旧窗口。

        强杀/崩溃的进程不会执行 ``flush_now(ended=True)``，窗口会永远保持
        open；本方法在下次启动时把 ``started_at`` 早于宽限期的 open 窗口
        标记为结束。本地单实例应用下，早于宽限期仍 open 的窗口可安全认为
        属于已死亡进程。返回受影响的窗口数（同一窗口的多行计为一个）。
        """
        from .models import CompatibilityTelemetryRow
        from .timeutil import utcnow

        cutoff = utcnow() - timedelta(seconds=self._reconcile_grace)
        now = utcnow()
        async with self._factory() as db:
            stale = (
                await db.execute(
                    select(CompatibilityTelemetryRow.scope_key)
                    .where(
                        CompatibilityTelemetryRow.scope_key != self._scope_key,
                        CompatibilityTelemetryRow.ended_at.is_(None),
                        CompatibilityTelemetryRow.started_at < cutoff,
                    )
                    .distinct()
                )
            ).scalars().all()
            if stale:
                await db.execute(
                    CompatibilityTelemetryRow.__table__.update()
                    .where(
                        CompatibilityTelemetryRow.scope_key.in_(stale),
                        CompatibilityTelemetryRow.ended_at.is_(None),
                    )
                    .values(ended_at=now)
                )
                await db.commit()
        return len(stale)

    async def stop(self) -> None:
        self._stop.set()

    async def flush_now(self, *, ended: bool = False) -> list[tuple[str, int]]:
        """把自上次 flush 的增量写入表；ended=True 时标记窗口结束。

        首次 flush（窗口开始）总是写一条基线行（path="__window__"），保证
        "窗口存在且 legacy 调用为 0"可以被证明（§6.4 归零观察需要能区分
        "没有窗口"与"有窗口但零调用"）。
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
        first_flush = self._last is None
        self._last = current
        if deltas or ended or first_flush:
            await self._write(deltas, ended=ended, ensure_window=first_flush)
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

    async def _write(
        self, deltas: list[tuple[str, int]], *, ended: bool, ensure_window: bool = False
    ) -> None:
        from .models import CompatibilityTelemetryRow
        from .timeutil import utcnow

        now = utcnow()
        async with self._factory() as db:
            # 0.3.0 M1 修复：停机 flush 与 run 循环 flush 可能并发（后者把窗口
            # 基线行挂起未提交）。先执行 ended UPDATE，若匹配 0 行（窗口行尚未
            # 落库）则由 ended 路径直接插入带 ended_at 的基线行，保证任何交错
            # 顺序下 ended_at 都不会丢失。
            if ended:
                result = await db.execute(
                    CompatibilityTelemetryRow.__table__.update()
                    .where(
                        CompatibilityTelemetryRow.scope == self._scope,
                        CompatibilityTelemetryRow.scope_key == self._scope_key,
                    )
                    .values(ended_at=now)
                )
            else:
                result = None
            if ensure_window or (ended and result is not None and result.rowcount == 0):
                existing = (
                    await db.execute(
                        select(CompatibilityTelemetryRow).where(
                            CompatibilityTelemetryRow.scope == self._scope,
                            CompatibilityTelemetryRow.scope_key == self._scope_key,
                            CompatibilityTelemetryRow.path == WINDOW_BASELINE_PATH,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    db.add(
                        CompatibilityTelemetryRow(
                            scope=self._scope,
                            scope_key=self._scope_key,
                            path=WINDOW_BASELINE_PATH,
                            mode="-",
                            outcome="-",
                            calls=0,
                            # ended 路径直接写 ended_at，避免与并发 flush 竞态；
                            # started_at 显式取同一 now，保证 ended_at >= started_at
                            # （服务端默认时间戳可能晚于 Python 侧 now，产生负时长）。
                            started_at=now,
                            ended_at=now if ended else None,
                            last_flushed_at=now,
                        )
                    )
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
                            started_at=now,
                            ended_at=now if ended else None,
                            last_flushed_at=now,
                        )
                    )
                else:
                    row.calls += delta
                    row.last_flushed_at = now
                    if ended:
                        row.ended_at = now
            await db.commit()

    @staticmethod
    def _is_mode(path: str, label: str) -> bool:
        return label in _LABELS[path]["modes"]


def telemetry_scope(*, origin: str | None = None, version: str | None = None) -> str:
    """观察窗口 scope 标签：``<origin>:<version>``（0.3.0 M1 遥测增强）。

    - origin：真实用户窗口 ``process``；QA smoke 窗口 ``qa``。QA 由桌面
      进程环境里的 ``PA_QA_STATIC_TOKEN`` 识别（sidecar 继承父进程环境），
      报告可据此把测试调用排除在生产归零结论之外。
    - version：应用版本（``personal_assistant.__version__``）。
    0.2.1 及更早的历史窗口 scope 为纯 ``process``（无版本段），观察脚本
    视为未知版本：不参与 ``--version`` 过滤，但计入总量与 legacy 判定。
    """
    origin = origin or ("qa" if os.environ.get("PA_QA_STATIC_TOKEN") else "process")
    version = version or __version__
    return f"{origin}:{version}"


async def windowed_telemetry_summary(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    scope_origins: set[str] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """跨窗口聚合兼容遥测（R3 §6.4 观察窗口，0.3.0 M1 增强）。

    按 path 聚合 mode 维度（mode 行与 outcome 行数量相等，取 mode 维度即可）；
    返回窗口列表、各 path 与各 mode 的调用总数。

    - ``since`` / ``until``：按窗口 ``started_at`` 限定时间范围
      （``since <= started_at < until``）；
    - ``scope_origins``：只保留指定 origin（如 ``{"process"}``）的窗口；
    - ``version``：只保留 scope 版本段等于该值的窗口（历史窗口无版本段，会被排除）。
    """
    from .models import CompatibilityTelemetryRow

    stmt = select(CompatibilityTelemetryRow)
    if since is not None:
        stmt = stmt.where(CompatibilityTelemetryRow.started_at >= since)
    if until is not None:
        stmt = stmt.where(CompatibilityTelemetryRow.started_at < until)
    rows = (await db.execute(stmt)).scalars().all()
    windows: dict[str, dict[str, Any]] = {}
    by_path: Counter[str] = Counter()
    by_mode: Counter[tuple[str, str]] = Counter()
    origins: Counter[str] = Counter()
    for row in rows:
        scope_origin = row.scope.partition(":")[0]
        scope_version = row.scope.partition(":")[2]
        if scope_origins is not None and scope_origin not in scope_origins:
            continue
        if version is not None and scope_version != version:
            continue
        is_new_window = row.scope_key not in windows
        window = windows.setdefault(
            row.scope_key,
            {
                "scope": row.scope,
                "origin": scope_origin,
                "version": scope_version or None,
                "scope_key": row.scope_key,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
            },
        )
        if is_new_window:
            origins[scope_origin] += 1
        if row.path == WINDOW_BASELINE_PATH:
            continue
        if row.mode != "-":
            by_path[row.path] += row.calls
            by_mode[(row.path, row.mode)] += row.calls
        # 窗口内 path 的 mode 计数用于"legacy 归零"判断（mode 维度完整）
        window.setdefault("paths", {}).setdefault(row.path, 0)
        if row.mode != "-":
            window["paths"][row.path] += row.calls
    windows_list = list(windows.values())
    return {
        "windows": windows_list,
        "window_count": len(windows_list),
        "ended_window_count": sum(1 for w in windows_list if w["ended_at"] is not None),
        "open_window_count": sum(1 for w in windows_list if w["ended_at"] is None),
        "origins": {origin: count for origin, count in sorted(origins.items())},
        "by_path": {path: count for path, count in sorted(by_path.items())},
        "by_mode": {
            path: {
                mode: by_mode[(path, mode)]
                for mode in sorted(m for p, m in by_mode if p == path)
            }
            for path in sorted({p for p, _ in by_mode})
        },
    }


compatibility_telemetry = CompatibilityTelemetry()
