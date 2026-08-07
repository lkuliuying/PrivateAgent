#!/usr/bin/env python3
"""R3 §6.4 / 0.3.0 M1 兼容遥测观察窗口报告。

聚合 ``compatibility_telemetry`` 表（schema 0021+）跨窗口计数，输出：
- 窗口列表（scope / scope_key / started_at / ended_at）；
- 各 path 与各 mode 的调用总数（mode 维度）；
- 窗口 origin 分布（process 真实用户 / qa QA smoke）；
- 正常 shutdown 窗口验收：窗口 started_at 早于 ``--window-grace-minutes``
  且仍未写入 ended_at 视为异常（强制终止/崩溃），验收失败时列出；
- §6.4 验收判定：指定 since 之后 legacy 调用是否为零（/tools legacy_registry、
  /tools/plan legacy_full、/tool-calls*），并列出仍非零的路径；
- 生产归零判定（排除 QA 窗口后单独计算），避免把测试调用计入生产结论。

只读；输出不含用户内容。用法：
    uv run python scripts/telemetry_window_report.py --since 2026-08-06T00:00:00Z
    uv run python scripts/telemetry_window_report.py --version 0.2.1 --origin process
    uv run python scripts/telemetry_window_report.py --until 2026-08-08T00:00:00Z --out data/rehearsals/r3-telemetry-window/20260807.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.compatibility import (  # noqa: E402
    windowed_telemetry_summary,
)

# §6.4：legacy 归零观察的目标路径（Agent Runtime 接管后不应再有调用）
LEGACY_PATHS = {
    "/tools": "legacy_registry",
    "/tools/plan": "legacy_full",
    "/tool-calls/:id/approve": None,
    "/tool-calls/:id/reject": None,
    "/tool-calls": None,
    "/tool-calls/:id": None,
}


def _parse_since(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"invalid --since: {value}") from exc


async def _run(
    since: datetime | None,
    until: datetime | None,
    origins: set[str] | None,
    version: str | None,
) -> dict:
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            return await windowed_telemetry_summary(
                db,
                since=since,
                until=until,
                scope_origins=origins,
                version=version,
            )
    finally:
        await engine.dispose()


def _legacy_counts(by_path: dict[str, int], by_mode: dict[str, dict[str, int]]) -> dict:
    """legacy 调用按 path 统计：优先按 path 专属 mode 精确匹配。"""
    counts: dict[str, int] = {}
    for path, mode in LEGACY_PATHS.items():
        if mode is None:
            counts[path] = by_path.get(path, 0)
        else:
            counts[path] = by_mode.get(path, {}).get(mode, 0)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default=None,
        help="观察起始时间（ISO 8601）；缺省为全窗口",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="观察结束时间（ISO 8601，排他）；缺省为现在",
    )
    parser.add_argument(
        "--origin",
        action="append",
        default=None,
        choices=["process", "qa"],
        help="只统计指定来源窗口（可重复）；缺省为全部来源",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="只统计 scope 版本段等于该值的窗口（如 0.2.1、0.3.0）",
    )
    parser.add_argument(
        "--mode",
        action="append",
        default=None,
        help="只输出指定 mode（如 agent_runtime、agent_runtime_rag、legacy_full）",
    )
    parser.add_argument(
        "--window-grace-minutes",
        type=int,
        default=60,
        help="窗口 started_at 早于该时长仍未 ended_at 视为异常（默认 60）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON 报告路径（不指定则打印 stdout）",
    )
    args = parser.parse_args()

    since = _parse_since(args.since) if args.since else None
    until = _parse_since(args.until) if args.until else None
    origins = set(args.origin) if args.origin else None
    summary = asyncio.run(_run(since, until, origins, args.version))

    # 正常 shutdown 验收：早于 grace 仍打开的窗口视为异常退出（ended_at 缺失）。
    # MySQL DATETIME 返回 naive（UTC），统一按 naive UTC 比较。
    grace = args.window_grace_minutes * 60
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_open = [
        w
        for w in summary["windows"]
        if w["ended_at"] is None and (now - w["started_at"]).total_seconds() > grace
    ]

    legacy_by_path = _legacy_counts(summary["by_path"], summary["by_mode"])
    nonzero = {path: count for path, count in legacy_by_path.items() if count > 0}
    report = {
        "generated_at": now.isoformat(),
        "since": args.since,
        "until": args.until,
        "window_count": summary["window_count"],
        "ended_window_count": summary["ended_window_count"],
        "open_window_count": summary["open_window_count"],
        "origins": summary["origins"],
        "windows": summary["windows"],
        "by_path": summary["by_path"],
        "by_mode": summary["by_mode"],
        "legacy_by_path": legacy_by_path,
        "legacy_zero": not nonzero,
        "nonzero_legacy_paths": nonzero,
        "shutdown_acceptance": not stale_open,
        "stale_open_windows": stale_open,
    }
    if args.mode:
        report["by_mode"] = {
            path: {mode: count for mode, count in modes.items() if mode in args.mode}
            for path, modes in summary["by_mode"].items()
        }
        report["mode_filter"] = list(args.mode)

    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.exists():
            print(f"[telemetry-window] refusing to overwrite: {args.out}", file=sys.stderr)
            return 1
        args.out.write_text(payload, encoding="utf-8")
        print(f"[telemetry-window] report: {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
