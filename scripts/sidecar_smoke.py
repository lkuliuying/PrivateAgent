#!/usr/bin/env python3
"""第八阶段 M1：sidecar smoke（端口协商 / /health / 退出清理）。

启动已构建的 PyInstaller sidecar，用空闲端口 + 临时数据目录 + 跳过迁移，轮询
/health 至 200，然后清理子进程树。无 sidecar 二进制时跳过（标注待构建）。

复用 measure_sidecar_baseline.py 的端口协商与 kill_tree 思路；本脚本聚焦 smoke
通过/失败判定。Usage: uv run python scripts/sidecar_smoke.py
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIDECAR = (
    PROJECT_ROOT
    / "apps"
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "personal-assistant-server-x86_64-pc-windows-msvc.exe"
)
HEALTH_TIMEOUT_S = 90
HEALTH_REQUEST_TIMEOUT_S = 25


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def kill_tree(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True
            )
        else:
            import signal as _sig

            os.killpg(os.getpgid(pid), _sig.SIGTERM)
    except Exception:  # noqa: BLE001
        pass


def read_dev_env() -> dict[str, str]:
    """从项目 .env 读 PA_DB_URL / PA_OLLAMA_BASE_URL（sidecar 需要连真实 MySQL/Ollama）。"""
    env_path = PROJECT_ROOT / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.startswith("PA_"):
            out[k] = v.strip()
    return out


def main() -> int:
    if not SIDECAR.exists():
        print(f"[sidecar-smoke] SKIP: sidecar binary not found at {SIDECAR}")
        print("  Run scripts/build-sidecar.bat first to build the sidecar.")
        return 0

    port = free_port()
    token = secrets.token_hex(32)
    dev_env = read_dev_env()
    with tempfile.TemporaryDirectory() as td:
        env = {
            **os.environ,
            **dev_env,
            "PA_API_PORT": str(port),
            "PA_API_TOKEN": token,
            "PA_SKIP_MIGRATIONS": "1",
            "PA_DATA_DIR": td,
            # 0.2.1 QA：smoke 只验证 sidecar 可启动与 /health，不参与 Agent owner
            # 竞争——显式关闭 agent 开关，避免与正在运行的安装版（批 A 持有
            # MySQL named lock）冲突导致 acquire 失败。
            "PA_AGENT_RUNS_API_ENABLED": "false",
            "PA_CHAT_AGENT_RUNTIME_ENABLED": "false",
        }
        print(f"[sidecar-smoke] starting sidecar on port {port}...")
        proc = subprocess.Popen(
            [str(SIDECAR)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            ok = False
            deadline = time.time() + HEALTH_TIMEOUT_S
            while time.time() < deadline:
                try:
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/health",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    with urllib.request.urlopen(
                        request, timeout=HEALTH_REQUEST_TIMEOUT_S
                    ) as r:
                        if r.status == 200:
                            ok = True
                            break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2)
            if ok:
                print(f"[sidecar-smoke] PASS: /health 200 on port {port}")
                return 0
            print(
                f"[sidecar-smoke] FAIL: /health did not return 200 within {HEALTH_TIMEOUT_S}s"
            )
            return 1
        finally:
            kill_tree(proc.pid)
            print("[sidecar-smoke] sidecar terminated, cleanup done")


if __name__ == "__main__":
    sys.exit(main())
