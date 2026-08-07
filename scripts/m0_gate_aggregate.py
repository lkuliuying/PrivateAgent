#!/usr/bin/env python3
"""M0 门槛聚合器：合并多日 runner 报告并审计生产库，输出 gate_pass 判定。

- 合并所有报告的有效 completed run（completed AND output.validation_passed）；
- 观察天数按全部报告的首末时间戳计算；
- 审计生产库：超过 10 分钟无推进的 run、负时长窗口、陈旧 open 窗口；
- P0/P1 清单通过 --p0p1 传入（每条一行），否则视为空；
- 输出逐项判定与最终 gate_pass。

用法：
    uv run python scripts/m0_gate_aggregate.py --reports data/rehearsals/m0-gate/*.json
    uv run python scripts/m0_gate_aggregate.py --reports data/rehearsals/m0-gate/*.json \
        --p0p1 "issue-1: 说明" --out data/rehearsals/m0-gate/m0-final.json
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
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from m0_gate_common import (  # noqa: E402
    count_valid_runs,
    gate_verdict,
    observation_days,
    runs_by_status,
)
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings  # noqa: E402


def _load_reports(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    """加载 runner 报告，返回 (runs, 报告元数据列表)。"""
    runs: list[dict] = []
    meta: list[dict] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = payload.get("summary", payload)
        runs.extend(payload.get("runs", []))
        meta.append(
            {
                "file": str(path),
                "started_at": report.get("started_at"),
                "binary_identity": report.get("binary_identity"),
                "runs_total": report.get("runs_total"),
            }
        )
    return runs, meta


async def _audit_db() -> dict[str, int]:
    """生产库审计：stuck run、负时长窗口、陈旧 open 窗口。"""
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            stuck = await db.scalar(
                text(
                    "SELECT COUNT(*) FROM agent_runs "
                    "WHERE status='running' AND started_at < "
                    "UTC_TIMESTAMP(3) - INTERVAL 10 MINUTE"
                )
            )
            negative = await db.scalar(
                text(
                    "SELECT COUNT(DISTINCT scope_key) FROM compatibility_telemetry "
                    "WHERE ended_at IS NOT NULL AND ended_at < started_at"
                )
            )
            stale = await db.scalar(
                text(
                    "SELECT COUNT(DISTINCT scope_key) FROM compatibility_telemetry "
                    "WHERE ended_at IS NULL AND started_at < "
                    "UTC_TIMESTAMP(3) - INTERVAL 3600 SECOND"
                )
            )
            return {
                "stuck_runs_over_10min": int(stuck or 0),
                "negative_duration_windows": int(negative or 0),
                "stale_open_windows": int(stale or 0),
            }
    finally:
        await engine.dispose()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports", nargs="+", type=Path, required=True,
        help="m0_gate_runner 生成的报告（支持 glob 展开）",
    )
    parser.add_argument(
        "--p0p1", action="append", default=None,
        help="P0/P1 处置清单条目（可重复）；缺省视为无阻断",
    )
    parser.add_argument("--skip-db-audit", action="store_true", help="跳过生产库审计")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    paths: list[Path] = []
    for pattern in args.reports:
        if any(ch in pattern.name for ch in "*?"):
            paths.extend(PROJECT_ROOT.glob(str(pattern.relative_to(PROJECT_ROOT)) if pattern.is_relative_to(PROJECT_ROOT) else str(pattern)))
        else:
            paths.append(pattern)
    paths = sorted(set(paths))
    if not paths:
        raise SystemExit("[m0-aggregate] 没有匹配的报告文件")

    runs, meta = _load_reports(paths)
    valid = count_valid_runs(runs)
    timestamps = [m["started_at"] for m in meta if m.get("started_at")]
    db_audit = {} if args.skip_db_audit else await _audit_db()

    aggregate = {
        "valid_completed_runs": valid,
        "observation_days": observation_days(timestamps),
        "rag_runs": sum(1 for r in runs if r.get("knowledge_base")),
        "cancel_sample": any(r.get("cancel_note") == "cancel accepted" for r in runs),
        "approval_sample": any(r.get("approval_sample") for r in runs),
        "ollama_outage_sample": any(
            r.get("status") != "driver_timeout" for r in runs
        ) and any(
            r.get("prompt_id") == "outage:01" or r.get("prompt_id") == "approval:01"
            for r in runs
        ),
        "windows_ended_cycles": 0,  # 由 runner 报告的 cycles 汇总
        **db_audit,
        "p0p1_blockers": list(args.p0p1 or []),
    }
    # 合并各报告里的正常退出周期证据
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = payload.get("summary", payload)
        for cycle in report.get("cycles", []):
            if cycle.get("ended_at_valid"):
                aggregate["windows_ended_cycles"] = (
                    aggregate["windows_ended_cycles"] + 1
                )

    verdict = gate_verdict(aggregate=aggregate)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reports": meta,
        "report_count": len(paths),
        "runs_total": len(runs),
        "runs_by_status": runs_by_status(runs),
        "valid_completed_runs": valid,
        "observation_days": aggregate["observation_days"],
        "db_audit": db_audit,
        "aggregate": aggregate,
        "gate": verdict,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.exists():
            print(f"[m0-aggregate] refusing to overwrite: {args.out}", file=sys.stderr)
            return 1
        args.out.write_text(payload, encoding="utf-8")
        print(f"[m0-aggregate] report: {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
