"""CT6-N3/N4：AppContainer 网络强制端到端。

前置：``cargo build --release --manifest-path apps/exec-host/Cargo.toml``；
binary 缺失、非 Windows，或当前会话禁止 exec-host 派生子进程（N1b 环境
阻断，见 _ct6_probe）时整组跳过。

门禁口径（§19.1：未授权网络外发 = 0）：

- 对照子进程连接测试进程监听的 loopback 端口必须成功（NET_OK），
  证明探针与协议栈可达；
- AC 子进程（零能力）对同一端口：**绝不允许 NET_OK**——内核级拒绝
  （PermissionError/10013）或启动失败被结构化失败关闭均为合法结局；
- network_policy != none + appcontainer 一律拒绝（能力授予未开放）。
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest
from _ct6_probe import SKIP_REASON, host_child_spawn_ok

from personal_assistant.agent_v2.execution.contracts import ExecStartParams
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


def _runtime_grant_roots() -> list[str]:
    """N1b 运行时根：解释器目录与真实 base prefix（DLL/标准库所在）。"""
    roots = {str(Path(sys.executable).parent), sys.base_prefix}
    return sorted(roots)


def _params(execution_id: str, code: str, *, appcontainer: bool) -> ExecStartParams:
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
        sandbox_policy_hash="sandbox-hash-ac01",
        env_diff=env_diff,
        appcontainer=appcontainer,
        ac_grant_paths=_runtime_grant_roots() if appcontainer else [],
    )


async def _run_to_exited(client: ExecHostClient, max_events: int = 16):
    events = []
    for _ in range(max_events):
        event = await client.next_event(timeout=20)
        assert event is not None, "事件流提前结束"
        events.append(event)
        if event.notification.value == "execution/exited":
            break
    assert events[-1].notification.value == "execution/exited"
    return events


def _stdout(events) -> str:
    return "".join(
        event.data or ""
        for event in events
        if event.notification.value == "execution/stdout/delta"
    )


def _probe_code(port: int) -> str:
    return (
        "import socket\n"
        "try:\n"
        f"    s = socket.create_connection(('127.0.0.1', {port}), timeout=3)\n"
        "    print('NET_OK')\n"
        "    s.close()\n"
        "except PermissionError as exc:\n"
        "    print('NET_DENIED', exc.errno)\n"
        "except OSError as exc:\n"
        "    print('NET_ERR', type(exc).__name__, getattr(exc, 'errno', None))\n"
    )


async def test_appcontainer_never_lets_probe_succeed(tmp_path):
    """AC 下探针永不成功：内核拒绝或失败关闭；NET_OK 即门禁失败。"""
    del tmp_path
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        try:
            await client.start_execution(
                _params("exec-rust-ac-net-1", _probe_code(port), appcontainer=True)
            )
            events = await _run_to_exited(client)
            text = _stdout(events)
            assert "NET_OK" not in text, f"AC 泄漏出网：{text!r}"
            if text:
                assert "NET_DENIED" in text and "10013" in text, (
                    f"AC 非预期网络结果：{text!r}"
                )
            else:
                pytest.fail("AC 子进程无输出且未拒绝执行，行为未定义")
        except ExecutorUnavailable as exc:
            # N1b 环境阻断：AC 创建失败 → 结构化失败关闭（合法结局）。
            assert "ac:create_process" in str(exc) or (
                "sandbox_policy_unavailable" in str(exc)
            ), str(exc)
    finally:
        listener.close()
        await client.close()


async def test_control_group_establishes_connection(tmp_path):
    """对照组：同一探针在同一端口建立连接（NET_OK），证明探针有效。"""
    del tmp_path
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-rust-ac-net-2", _probe_code(port), appcontainer=False)
        )
        events = await _run_to_exited(client)
        text = _stdout(events)
        assert "NET_OK" in text, f"对照组无法建立连接：{text!r}"
        assert events[-1].exit_code == 0
    finally:
        listener.close()
        await client.close()


async def test_appcontainer_child_runs_with_pipes_and_exit_facts(tmp_path):
    """N1b 后：AC 子进程 stdout/stderr/退出码事实链完整。

    本机 AC 加载链不兼容时以跳过语义处理（失败关闭已由上一用例验证）。
    """
    del tmp_path
    code = (
        "print('ac-hello')\n"
        "import sys\n"
        "print('ac-stderr-line', file=sys.stderr)\n"
    )
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        try:
            await client.start_execution(
                _params("exec-rust-ac-run-3", code, appcontainer=True)
            )
        except ExecutorUnavailable:
            pytest.skip("本机 AC 加载链不兼容（失败关闭已验证）")
        events = await _run_to_exited(client)
        kinds = [event.notification.value for event in events]
        assert kinds[0] == "execution/started"
        streams = {event.stream for event in events[1:-1]}
        assert {"stdout", "stderr"} <= streams
        assert "ac-hello" in _stdout(events)
        assert events[-1].exit_code == 0
    finally:
        await client.close()


async def test_appcontainer_with_non_none_network_policy_is_rejected(tmp_path):
    """N3 失败关闭：capability 授予未开放，network_policy!=none 拒绝启动。"""
    del tmp_path
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        params = _params("exec-rust-ac-net-4", "print('x')", appcontainer=True)
        payload = params.model_dump()
        payload["network_policy"] = "allowlist"
        with pytest.raises(ExecutorUnavailable):
            await client._request(  # noqa: SLF001 - 契约级负向用例
                "execution/start", payload
            )
    finally:
        await client.close()
