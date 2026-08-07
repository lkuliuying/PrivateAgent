#!/usr/bin/env python3
"""0.3.0 M1/M0：兼容遥测陈旧窗口 reconcile 维护脚本。

关闭上次启动前（早于宽限期）仍未写入 ended_at 的观察窗口——强杀/崩溃的
进程不会执行 ``flush_now(ended=True)``，窗口会永远保持 open；本脚本在
sidecar 之外手动执行同样的回收逻辑（应用内每次启动也会自动执行）。

只写 compatibility_telemetry 表的 ended_at 字段；不接触任何用户数据。
用法：
    uv run python scripts/reconcile_telemetry_windows.py
    uv run python scripts/reconcile_telemetry_windows.py --grace-seconds 7200
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings  # noqa: E402
from personal_assistant.core.compatibility import (  # noqa: E402
    CompatibilityTelemetry,
    CompatibilityTelemetryPersister,
)


async def _run(grace_seconds: int) -> int:
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        persister = CompatibilityTelemetryPersister(
            CompatibilityTelemetry(),
            factory,
            scope_key="manual-reconcile",
            reconcile_grace_seconds=grace_seconds,
        )
        return await persister.reconcile_stale_windows()
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grace-seconds",
        type=int,
        default=7_200,
        help="窗口 started_at 早于该时长仍未 ended_at 视为陈旧（默认 7200）",
    )
    args = parser.parse_args()
    count = asyncio.run(_run(args.grace_seconds))
    print(f"[telemetry-reconcile] closed {count} stale window(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
