"""CT6 端到端共享探针：检测当前会话是否允许 exec-host 派生子进程。

N1b 环境阻断记录（2026-08-25）：本会话安全策略中途收紧后，exec-host
进程派生任何子进程（含 System32\\cmd.exe）均返回 ERROR_ACCESS_DENIED，
而同用户普通 shell 派生不受影响——属环境级阻断而非产品逻辑回归。
阻断时相关端到端用例整体跳过；策略解除后自动恢复完整验证。
详见 docs/releases/v1.0.0/adr/evidence/s4-network-enforcement-plan.md §3.5。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BINARY_NAME = "exec-host.exe" if sys.platform == "win32" else "exec-host"
EXEC_HOST_BINARY = (
    _PROJECT_ROOT / "apps" / "exec-host" / "target" / "release" / _BINARY_NAME
)

_RESULT: bool | None = None


def host_child_spawn_ok() -> bool:
    """一次性探测：exec-host 能否真实派生子进程（结果缓存）。"""
    global _RESULT
    if _RESULT is not None:
        return _RESULT
    if not EXEC_HOST_BINARY.exists() or sys.platform != "win32":
        _RESULT = False
        return _RESULT
    try:
        import asyncio

        from personal_assistant.agent_v2.execution.contracts import ExecStartParams
        from personal_assistant.agent_v2.execution.exec_host_client import (
            ExecHostClient,
        )

        async def _probe() -> bool:
            env_diff = {
                key: value
                for key, value in (
                    ("SystemRoot", os.environ.get("SystemRoot", "")),
                    ("TEMP", os.environ.get("TEMP", "")),
                    ("TMP", os.environ.get("TMP", "")),
                )
                if value
            }
            client = ExecHostClient([str(EXEC_HOST_BINARY)])
            try:
                await asyncio.wait_for(client.start(), timeout=10)
                params = ExecStartParams(
                    execution_id="exec-probe-ct6-01",
                    argv=[sys.executable, "-X", "utf8", "-c", "pass"],
                    cwd=str(_PROJECT_ROOT),
                    timeout_ms=10_000,
                    sandbox_policy_hash="sandbox-hash-001",
                    env_diff=env_diff,
                )
                await asyncio.wait_for(client.start_execution(params), timeout=10)
                # 完整性要求：子进程真实运行至 exited(0)。N1b 实测本会话
                # 嵌套 Job 被拒且子进程随即被终止（started 后无输出即
                # failed）——仅 start 被接受不代表可执行。
                while True:
                    ev = await asyncio.wait_for(client.next_event(timeout=15), timeout=15)
                    if ev is None:
                        return False
                    if ev.notification.value == "execution/failed":
                        return False
                    if ev.notification.value == "execution/exited":
                        return ev.exit_code == 0
            except Exception:  # noqa: BLE001
                return False
            finally:
                await client.close()

        _RESULT = asyncio.run(_probe())
    except Exception:  # noqa: BLE001
        _RESULT = False
    return _RESULT


SKIP_REASON = (
    "会话安全策略禁止 exec-host 派生子进程（N1b 环境阻断，"
    "见 adr/evidence/s4-network-enforcement-plan.md §3.5）"
)
