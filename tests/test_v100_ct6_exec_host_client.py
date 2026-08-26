"""CT6-01 客户端契约测试：Exec Host JSONL 通道（fake host 子进程）。

用真实子进程（``python -c`` 运行内嵌 fake host 脚本）验证：

- 握手：initialize 成功返回 health；协议版本不符 → 失败关闭；
- execution/start → started/exited 事件按序到达；
- cancel → cancelled 事件；
- host 崩溃/EOF → ExecutorUnavailable + 终止哨兵事件；
- 启动命令不存在 → ExecutorUnavailable（不静默降级）。
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from personal_assistant.agent_v2.execution.contracts import (
    PROTOCOL_VERSION,
    ExecEvent,
    ExecStartParams,
)
from personal_assistant.agent_v2.execution.exec_host_client import (
    ExecHostClient,
    ExecutorUnavailable,
)

_FAKE_HOST_SCRIPT = textwrap.dedent(
    """
    import json, sys

    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
        sys.stdout.flush()

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            params = message.get("params") or {}
            if params.get("protocol_version") != "1.0":
                send({"id": request_id, "error": {
                    "code": "protocol_mismatch", "message": "version",
                    "retryable": False, "details": None, "trace_id": None}})
                break
            send({"id": request_id,
                  "result": {"protocol_version": "1.0", "sandbox_available": True,
                              "modes": ["argv"], "active_sessions": 0}})
        elif method == "execution/start":
            params = message.get("params") or {}
            exec_id = params["execution_id"]
            send({"id": request_id, "result": {"accepted": True}})
            seq = 0
            for stream in ("stdout", "stderr"):
                send({"notification": f"execution/{stream}/delta",
                      "execution_id": exec_id, "sequence": seq, "stream": stream,
                      "data": f"{stream}-payload"})
                seq += 1
            send({"notification": "execution/exited", "execution_id": exec_id,
                  "sequence": seq, "exit_code": 0})
        elif method == "execution/cancel":
            params = message.get("params") or {}
            send({"id": request_id, "result": {"cancelling": True}})
            send({"notification": "execution/cancelled",
                  "execution_id": params["execution_id"], "sequence": 99})
        elif method == "shutdown":
            send({"id": request_id, "result": {"bye": True}})
            break
    """
)


def _host_command(tmp_path: Path, *, version: str = "1.0") -> list[str]:
    script = _FAKE_HOST_SCRIPT.replace('"1.0"', json.dumps(version)) \
        if version != "1.0" else _FAKE_HOST_SCRIPT
    path = tmp_path / "fake_exec_host.py"
    path.write_text(script, encoding="utf-8")
    return [sys.executable, "-X", "utf8", str(path)]


def _start_params(execution_id: str = "exec-0001-ab") -> ExecStartParams:
    return ExecStartParams(
        execution_id=execution_id,
        argv=[sys.executable, "-c", "print('hi')"],
        cwd=str(Path.cwd()),
        sandbox_policy_hash="sandbox-hash-001",
    )


async def _collect(client: ExecHostClient, count: int):
    events: list[ExecEvent] = []
    for _ in range(count):
        event = await client.next_event(timeout=10)
        assert event is not None, "事件流提前结束"
        events.append(event)
    return events


async def test_handshake_and_execution_event_flow(tmp_path):
    client = ExecHostClient(_host_command(tmp_path))
    try:
        health = await client.start()
        assert health.protocol_version == PROTOCOL_VERSION
        assert health.sandbox_available is True

        await client.start_execution(_start_params())
        events = await _collect(client, 3)
        assert [event.notification.value for event in events] == [
            "execution/stdout/delta",
            "execution/stderr/delta",
            "execution/exited",
        ]
        assert events[0].data == "stdout-payload"
        assert events[2].exit_code == 0
        # stdout/stderr 分流正确。
        assert events[0].stream == "stdout" and events[1].stream == "stderr"
    finally:
        await client.close()


async def test_cancel_emits_cancelled_notification(tmp_path):
    client = ExecHostClient(_host_command(tmp_path))
    try:
        await client.start()
        await client.start_execution(_start_params())
        await client.cancel("exec-0001-ab")
        events = await _collect(client, 4)
        assert events[-1].notification.value == "execution/cancelled"
        assert events[-1].execution_id == "exec-0001-ab"
    finally:
        await client.close()


async def test_protocol_version_mismatch_fails_closed(tmp_path):
    client = ExecHostClient(_host_command(tmp_path, version="9.9"))
    with pytest.raises(ExecutorUnavailable):
        await client.start()
    assert client._process is None or client._process.returncode is not None


async def test_missing_binary_is_executor_unavailable(tmp_path):
    missing = tmp_path / "no-such-host.exe"
    client = ExecHostClient([str(missing)])
    with pytest.raises(ExecutorUnavailable):
        await client.start()


async def test_host_crash_surfaces_unavailable_on_next_request(tmp_path):
    crash_script = (
        "import sys\n"
        'sys.stdout.write(json.dumps({"id":1,"result":{"protocol_version":"1.0",'
        '"sandbox_available":True,"modes":["argv"],"active_sessions":0}})+"\\n")\n'
        "sys.stdout.flush()\n"
        "raise SystemExit(3)\n"
    )
    path = tmp_path / "crash_host.py"
    path.write_text("import json\n" + crash_script, encoding="utf-8")
    client = ExecHostClient([sys.executable, "-X", "utf8", str(path)])
    health = await client.start()
    assert health.protocol_version == "1.0"
    # host 已退出 → 后续执行请求失败关闭。
    with pytest.raises(ExecutorUnavailable):
        await client.start_execution(_start_params())
    await client.close()
