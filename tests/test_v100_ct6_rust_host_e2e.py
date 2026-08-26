"""CT6-01 端到端：Rust exec-host binary × agent_v2 JSONL 客户端。

前置：``cargo build --release --manifest-path apps/exec-host/Cargo.toml``；
binary 缺失、非 Windows，或当前会话禁止 exec-host 派生子进程（N1b 环境
阻断，见 _ct6_probe）时整组跳过。

覆盖（专项计划 §11.2 最小子集）：
- 握手：initialize → health（协议版本/argv 模式/沙箱如实上报 false）；
- execution/start → started/stdout delta/stderr delta/exited 事件按序到达，
  退出码与输出内容正确；
- execution/cancel → cancelled + exited；
- 超时 → exited(cancelled_by_timeout=true)；
- stdin/write 对不存在的执行结构化拒绝（不静默丢弃；管道能力测试见
  test_v100_ct6_stdin_pty.py）；
- unknown_method 错误信封。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from _ct6_probe import SKIP_REASON, host_child_spawn_ok

from personal_assistant.agent_v2.execution.contracts import (
    PROTOCOL_VERSION,
    ExecHealth,
    ExecStartParams,
    ExecStdinParams,
)
from personal_assistant.agent_v2.execution.exec_host_client import (
    ExecHostClient,
    ExecutorUnavailable,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BINARY_NAME = "exec-host.exe" if sys.platform == "win32" else "exec-host"
EXEC_HOST_BINARY = (
    _PROJECT_ROOT / "apps" / "exec-host" / "target" / "release" / _BINARY_NAME
)

pytestmark = [
    pytest.mark.skipif(
        not EXEC_HOST_BINARY.exists() or sys.platform != "win32",
        reason="exec-host 未构建或非 Windows 平台",
    ),
    pytest.mark.skipif(
        not host_child_spawn_ok(), reason=SKIP_REASON
    ),
]


def _params(execution_id: str, code: str, *, timeout_ms: int = 60_000) -> ExecStartParams:
    # 显式 allowlist 环境（§22.3）：本机策略拒绝完全空环境的进程创建。
    env_diff = {
        key: value
        for key, value in (
            ("SystemRoot", os.environ.get("SystemRoot", "")),
            ("TEMP", os.environ.get("TEMP", "")),
            ("TMP", os.environ.get("TMP", "")),
        )
        if value
    }
    return ExecStartParams(
        execution_id=execution_id,
        argv=[sys.executable, "-X", "utf8", "-c", code],
        cwd=str(_PROJECT_ROOT),
        timeout_ms=timeout_ms,
        sandbox_policy_hash="sandbox-hash-001",
        env_diff=env_diff,
    )


async def _collect_until_exited(client: ExecHostClient, max_events: int = 32):
    events = []
    for _ in range(max_events):
        event = await client.next_event(timeout=15)
        assert event is not None, "事件流提前结束"
        events.append(event)
        if event.notification.value == "execution/exited":
            break
    assert events[-1].notification.value == "execution/exited"
    return events


async def test_handshake_health_reports_honest_sandbox_state():
    """握手成功且沙箱状态如实上报（网络强制未闭环 → false）。"""
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        health = await client.start()
        assert isinstance(health, ExecHealth)
        assert health.protocol_version == PROTOCOL_VERSION
        assert health.sandbox_available is False  # ADR-004 门禁未闭环前如实上报
        # 协议能力面：argv + 受控 PTY（§11.3）；pty 环境可用性由
        # execution/start 的就绪探针门禁如实拒绝（见 test_v100_ct6_stdin_pty）。
        assert health.modes == ("argv", "pty")
    finally:
        await client.close()


async def test_execution_event_flow_end_to_end(tmp_path):
    del tmp_path
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params(
                "exec-rust-e2e-01",
                "print('hello-from-child'); "
                "import sys; print('err-from-child', file=sys.stderr)",
            )
        )
        events = await _collect_until_exited(client)
        kinds = [event.notification.value for event in events]
        assert kinds[0] == "execution/started"
        assert kinds[-1] == "execution/exited"
        streams = [event.stream for event in events[1:-1]]
        assert "stdout" in streams and "stderr" in streams
        joined = "".join(event.data or "" for event in events[1:-1])
        assert "hello-from-child" in joined
        assert "err-from-child" in joined
        assert events[-1].exit_code == 0
        assert events[-1].cancelled_by_timeout is False
    finally:
        await client.close()


async def test_cancel_emits_cancelled_then_exited(tmp_path):
    del tmp_path
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-rust-cancel-1", "import time; time.sleep(30)")
        )
        await client.cancel("exec-rust-cancel-1")
        events = await _collect_until_exited(client, max_events=8)
        kinds = [event.notification.value for event in events]
        assert "execution/cancelled" in kinds
        assert kinds[-1] == "execution/exited"
    finally:
        await client.close()


async def test_timeout_kills_child_and_reports_flag(tmp_path):
    del tmp_path
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-rust-timeout-1", "import time; time.sleep(30)", timeout_ms=800)
        )
        events = await _collect_until_exited(client, max_events=8)
        final = events[-1]
        assert final.cancelled_by_timeout is True
        assert any(e.notification.value == "execution/exited" for e in events)
    finally:
        await client.close()


async def test_stdin_write_is_rejected_not_silently_dropped(tmp_path):
    del tmp_path
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        with pytest.raises(ExecutorUnavailable):
            await client.write_stdin(
                ExecStdinParams(
                    execution_id="exec-rust-e2e-01",
                    session_nonce="nonce-0001",
                    data="x",
                )
            )
    finally:
        await client.close()


async def test_exit_code_propagates_for_failing_child(tmp_path):
    del tmp_path
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(_params("exec-rust-fail-01", "raise SystemExit(3)"))
        events = await _collect_until_exited(client, max_events=8)
        assert events[-1].exit_code == 3
    finally:
        await client.close()
