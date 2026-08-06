#!/usr/bin/env python3
"""R3 §6.4 兼容遥测观察窗口报告。

聚合 ``compatibility_telemetry`` 表（schema 0021+）跨窗口计数，输出：
- 窗口列表（scope_key / started_at / ended_at）；
- 各 path 的 legacy 调用总数（mode 维度）；
- §6.4 验收判定：指定 since 之后 legacy 调用是否为零（/tools legacy_registry、
  /tools/plan legacy_full、/tool-calls*），并列出仍非零的路径。

只读；输出不含用户内容。用法：
    uv run python scripts/telemetry_window_report.py --since 2026-08-06T00:00:00Z
    uv run python scripts/telemetry_window_report.py --out data/rehearsals/r3-telemetry-window/20260806.json
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


async def _run(since: datetime | None) -> dict:
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            return await windowed_telemetry_summary(db, since=since)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default=None,
        help="观察起始时间（ISO 8601）；缺省为全窗口",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON 报告路径（不指定则打印 stdout）",
    )
    args = parser.parse_args()

    since = _parse_since(args.since) if args.since else None
    summary = asyncio.run(_run(since))

    nonzero = {
        path: count
        for path, count in summary["by_path"].items()
        if count > 0 and path in LEGACY_PATHS
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": args.since,
        "window_count": summary["window_count"],
        "windows": summary["windows"],
        "legacy_by_path": {
            path: summary["by_path"].get(path, 0) for path in sorted(LEGACY_PATHS)
        },
        "legacy_zero": not nonzero,
        "nonzero_legacy_paths": nonzero,
    }
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
