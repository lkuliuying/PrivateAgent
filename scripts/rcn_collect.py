"""rc.N 观察期每日采集器（rcN-observation-framework.md §2）。

单命令产出当日 `rcN-daily-YYYYMMDD.json`：
- 五个零事故计数器：fake_completion / duplicate_side_effects /
  sandbox_escape_attempts / secret_leak_hits /
  unknown_execution_auto_retry——来源为 soak 冒烟 verdict 与本地诊断端点
  （可达时）；不可达时如实记 null 并标注 source=unavailable；
- 每日 soak 冒烟：调用 scripts/run_soak_gate.py --quick 并记录 verdict；
- incidents：由运维在窗口内人工追加（框架不伪造）。

用法：uv run python scripts/rcn_collect.py --rc 1.0.0-rc.1 [--evidence-dir DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOAK_SCRIPT = ROOT / "scripts" / "run_soak_gate.py"


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def run_soak_smoke() -> dict:
    proc = subprocess.run(
        [sys.executable, str(SOAK_SCRIPT), "--quick"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    verdict = "unknown"
    for line in (proc.stdout or "").splitlines():
        if line.startswith("[soak] verdict="):
            verdict = line.split("=", 1)[1].strip()
    evidence_file = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("[soak] verdict=") and "evidence=" in line:
            evidence_file = line.split("evidence=", 1)[1].strip()
    return {"turns": 60, "replays": 600, "verdict": verdict,
            "evidence": evidence_file}


def collect_counters() -> tuple[dict, str]:
    """优先从本地诊断/遥测端点读取；不可达时如实返回 null。"""
    base = os.environ.get("PA_API_BASE", "http://127.0.0.1:8000")
    token = os.environ.get("PA_API_TOKEN", "")
    counters: dict[str, int | None] = {
        "fake_completion": None,
        "duplicate_side_effects": None,
        "sandbox_escape_attempts": None,
        "secret_leak_hits": None,
        "unknown_execution_auto_retry": None,
    }
    source = "unavailable"
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{base}/diagnostics",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        # 诊断快照结构随版本演进：仅提取已知键，缺失保持 null。
        for key in list(counters):
            if key in payload:
                counters[key] = int(payload[key])
        source = "diagnostics-endpoint"
    except Exception:
        pass
    return counters, source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rc", default="1.0.0-rc.1")
    parser.add_argument("--evidence-dir",
                        default=str(ROOT / "docs" / "releases" / "v1.0.0"
                                    / "adr" / "evidence"))
    args = parser.parse_args()

    out_dir = Path(args.evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[rcn] running soak smoke (--quick) …", flush=True)
    soak = run_soak_smoke()
    counters, source = collect_counters()

    daily = {
        "date": today(),
        "build": args.rc,
        "gates": counters,
        "gates_source": source,
        "soak_smoke": soak,
        "incidents": [],
    }
    out = out_dir / f"rcN-daily-{today()}.json"
    out.write_text(json.dumps(daily, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"[rcn] archived {out} (soak={soak['verdict']}, "
          f"gates_source={source})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
