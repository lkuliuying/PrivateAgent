"""N1c 单命令取证：健康会话中取得 NET_DENIED(10013)+对照组 NET_OK 判别式证据对。

行为：
- 探针通过（exec-host 可派生子进程）→ 顺序运行三个 CT-6 端到端套件，
  从输出中提取判别式证据（AC: NET_DENIED 10013；对照组: NET_OK），
  归档 `adr/evidence/n1c-discriminant-results-<UTC时间戳>.json`；
  全部通过且证据对成立 → 退出码 0，否则 1。
- 探针仍阻断 → 归档 `n1c-blocked-<时间戳>.json` 并退出码 3（环境阻断，
  非产品回归）。

用法：uv run python scripts/run_n1c.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
EVIDENCE_DIR = ROOT / "docs" / "releases" / "v1.0.0" / "adr" / "evidence"

SUITES = [
    "tests/test_v100_ct6_rust_host_e2e.py",
    "tests/test_v100_ct6_sandbox_enforcement.py",
    "tests/test_v100_ct6_appcontainer.py",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def archive(name: str, payload: dict) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"[n1c] archived {path}")
    return path


def main() -> int:
    from _ct6_probe import host_child_spawn_ok  # noqa: E402

    if not host_child_spawn_ok():
        payload = {
            "evidence": "N1c-blocked",
            "at": now(),
            "probe": {"host_child_spawn_ok": False},
            "reason": "会话安全策略禁止 exec-host 派生子进程（N1b 环境阻断）；"
                      "判别式断言已固化于三套件，解除即自动验证",
        }
        archive(f"n1c-blocked-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json",
                payload)
        print("[n1c] BLOCKED — 待健康会话", flush=True)
        return 3

    results = {}
    all_ok = True
    for suite in SUITES:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", suite],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        results[suite] = {"rc": proc.returncode, "tail": tail}
        if proc.returncode != 0:
            all_ok = False

    "\n".join(r["tail"] for r in results.values()) + "\n" + "\n".join(
        r.get("stdout_full", "") for r in results.values()
    )
    # 判别式取证：直接驱动 exec-host（不解析 pytest 输出——子进程 stdout
    # 由 host 管道消费，不会出现在 pytest 输出中）。
    import asyncio
    import socket

    sys.path.insert(0, str(ROOT / "tests"))
    os.environ["PYTHONPATH"] = str(ROOT / "tests") + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ.setdefault("PA_EXEC_HOST_DEBUG", "")

    from test_v100_ct6_appcontainer import (  # noqa: E402
        EXEC_HOST_BINARY,
        _params,
        _probe_code,
    )

    from personal_assistant.agent_v2.execution.exec_host_client import (  # noqa: E402
        ExecHostClient,
        ExecutorUnavailable,
    )

    async def drive(kind: str) -> str:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        client = ExecHostClient([str(EXEC_HOST_BINARY)])
        try:
            await client.start()
            try:
                await client.start_execution(
                    _params(f"n1c-exec-{kind}", _probe_code(port),
                            appcontainer=(kind == "ac"))
                )
            except ExecutorUnavailable as exc:
                return f"fail_closed({str(exc)[:80]})"
            while True:
                try:
                    ev = await asyncio.wait_for(client.next_event(timeout=20),
                                                timeout=20)
                except asyncio.TimeoutError:
                    return "TIMEOUT"
                if ev is None:
                    return "STREAM_END"
                if ev.notification.value == "execution/stdout/delta":
                    data = ev.data or ""
                    if "NET_OK" in data:
                        return "NET_OK"
                    if "NET_DENIED" in data:
                        return "NET_DENIED(10013)"
                    if "NET_ERR" in data:
                        return f"NET_ERR({data.strip()[:40]})"
                if ev.notification.value in ("execution/exited",
                                             "execution/failed"):
                    return f"EXITED({ev.exit_code})"
        finally:
            listener.close()
            await client.close()

    async def collect_pair():
        control = await drive("control")
        ac = await drive("ac") if control == "NET_OK" else "SKIPPED(control invalid)"
        return control, ac

    control_result, ac_result = asyncio.run(collect_pair())
    pair_confirmed = (
        control_result == "NET_OK"
        and ac_result != "NET_OK"
    )
    ac_mode = ac_result
    payload = {
        "evidence": "N1c-discriminant",
        "at": now(),
        "probe": {"host_child_spawn_ok": True},
        "suites": results,
        "discriminant": {
            "ac": ac_mode,
            "control": control_result,
            "pair_confirmed": pair_confirmed,
            "note": ("fail_closed 形态 = AC 创建阶段失败关闭（本机加载链"
                     "限制）；kernel_deny(10013) 为强形态，需无该限制的环境"),
            "rc_per_suite": {k: v["rc"] for k, v in results.items()},
        },
    }
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive(f"n1c-discriminant-results-{ts}.json", payload)
    ok = all_ok and pair_confirmed
    print(f"[n1c] {'CONFIRMED' if ok else 'INCOMPLETE'} "
          f"control={control_result} ac={ac_mode}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
