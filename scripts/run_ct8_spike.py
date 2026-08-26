"""CT-8 Spike 触发门（按 ct8-app-server-spike-evaluation.md §2/§3）。

单命令评估：前置条件全部满足 → 输出 READY 并打印五步执行清单起点；
任一不满足 → 归档 `ct8-deferred-<时间戳>.json`（status=DEFER + 缺失项）
并退出码 3。当前会话预期为 DEFER。

前置检查项（评估文档 §2）：
1. App Server 可执行产物存在（--app-server 指向文件，或环境变量
   PA_CT8_APP_SERVER 指定）；
2. 独立样例 workspace 存在且非空（--workspace）；
3. 本地 Ollama 可达（http://127.0.0.1:11434/api/tags，仅告警不阻断——
   Provider 可换 OpenAI-compatible）；
4. N1c 已关闭（adr/evidence 下最新 n1c-discriminant-results-*.json 的
   pair_confirmed=true；未关闭时双执行器风险面放大，评估文档 §1 风险行）。

用法：uv run python scripts/run_ct8_spike.py [--app-server PATH] [--workspace DIR]
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "docs" / "releases" / "v1.0.0" / "adr" / "evidence"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def latest_n1c_confirmed() -> tuple[bool, str]:
    files = sorted(glob.glob(str(EVIDENCE_DIR / "n1c-discriminant-results-*.json")))
    if not files:
        return False, "无 n1c-discriminant-results-*.json 归档"
    payload = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    confirmed = bool(payload.get("discriminant", {}).get("pair_confirmed"))
    return confirmed, Path(files[-1]).name


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--app-server", default=os.environ.get("PA_CT8_APP_SERVER", ""))
    parser.add_argument("--workspace", default="")
    args = parser.parse_args()

    missing: list[str] = []
    app_server = args.app_server
    if not app_server or not Path(app_server).is_file():
        missing.append(
            f"App Server 产物缺失：{app_server or '(未指定 --app-server / PA_CT8_APP_SERVER)'}"
        )
    workspace = args.workspace
    if not workspace or not Path(workspace).is_dir():
        missing.append(
            f"独立样例 workspace 缺失：{workspace or '(未指定 --workspace)'}"
        )

    n1c_ok, n1c_detail = latest_n1c_confirmed()
    if not n1c_ok:
        missing.append(f"N1c 未关闭（{n1c_detail}）——双执行器风险面未收敛")

    ollama_ok = False
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=2):
            ollama_ok = True
    except Exception:
        pass  # 仅告警：Provider 可替换为任意 OpenAI-compatible。

    payload = {
        "evidence": "CT-8-spike-trigger-gate",
        "at": now(),
        "checks": {
            "app_server_present": not (not app_server or not Path(app_server).is_file()),
            "sample_workspace_present": bool(workspace) and Path(workspace).is_dir(),
            "n1c_closed": n1c_ok,
            "ollama_reachable_warn_only": ollama_ok,
        },
        "missing": missing,
    }

    if missing:
        payload["status"] = "DEFER"
        payload["reason"] = "触发条件未满足（评估文档 §2）；满足后重跑本脚本进入 READY"
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = EVIDENCE_DIR / f"ct8-deferred-{ts}.json"
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[ct8] DEFER — 缺失项：{missing}")
        print(f"[ct8] archived {out}")
        return 3

    payload["status"] = "READY"
    payload["next"] = [
        "更新 docs/third-party/codex-adoption-manifest.md 分类 C 条目（新冻结 commit）",
        "步骤 2 协议探针：stdio 握手 + thread/start + turn/start 最小往返",
        "步骤 3 Provider 兼容：本地 Ollama/Qwen 复跑 §8.2 六类 probe 对比",
        "步骤 4 审批/证据边界验证（任一绕过即 Reject）",
        "步骤 5 结论报告归档 adr/evidence/ct8-app-server-spike-results-*.json",
    ]
    print("[ct8] READY — 按 next 清单启动五步 Spike")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
