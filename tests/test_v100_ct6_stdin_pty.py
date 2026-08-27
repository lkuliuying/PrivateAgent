"""CT-6 收尾端到端：stdin 管道（§11.4 绑定）、output/read 续读、受控 PTY（§11.3）。

前置：``cargo build --release --manifest-path apps/exec-host/Cargo.toml``；
binary 缺失、非 Windows，或当前会话禁止 exec-host 派生子进程（_ct6_probe）
时整组跳过。

覆盖（专项计划 §11.2/§11.3/§11.4）：
- stdin_mode=pipe + session_nonce 绑定：写入→子进程读到→回显；
  nonce 不匹配 → 结构化 ``bad_nonce``；未开管道 → ``stdin_closed``；
  缺 nonce 的 pipe 请求 → ``bad_params``（不隐式放行）；
- execution/output/read：字节偏移续读、不重复、执行移除后
  ``unknown_execution``（持久化输出由 Python Core artifact 承担）；
- mode=pty：ConPTY 回显回读；``appcontainer`` 组合一律拒绝（失败关闭）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from _ct6_probe import SKIP_REASON, host_child_spawn_ok

from personal_assistant.agent_v2.execution.contracts import (
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


def _env_diff() -> dict[str, str]:
    return {
        key: value
        for key, value in (
            ("SystemRoot", os.environ.get("SystemRoot", "")),
            ("TEMP", os.environ.get("TEMP", "")),
            ("TMP", os.environ.get("TMP", "")),
        )
        if value
    }


def _params(
    execution_id: str,
    code: str,
    *,
    stdin_mode: str = "closed",
    mode: str = "argv",
    timeout_ms: int = 60_000,
) -> ExecStartParams:
    return ExecStartParams(
        execution_id=execution_id,
        mode=mode,  # type: ignore[arg-type]
        argv=[sys.executable, "-X", "utf8", "-c", code],
        cwd=str(_PROJECT_ROOT),
        timeout_ms=timeout_ms,
        sandbox_policy_hash="sandbox-hash-stdin-pty",
        env_diff=_env_diff(),
        stdin_mode=stdin_mode,  # type: ignore[arg-type]
    )


async def _collect_until_exited(client: ExecHostClient, max_events: int = 64):
    events = []
    for _ in range(max_events):
        event = await client.next_event(timeout=20)
        assert event is not None, "事件流提前结束"
        events.append(event)
        if event.notification.value == "execution/exited":
            break
    assert events[-1].notification.value == "execution/exited"
    return events


def _stdout_text(events) -> str:
    return "".join(
        event.data or ""
        for event in events
        if event.notification.value == "execution/stdout/delta"
    )


async def test_stdin_pipe_roundtrip_and_close(tmp_path):
    """pipe + nonce：写入被读到并回显；close 后子进程正常退出。"""
    del tmp_path
    code = "line = input()\nprint('ECHO:' + line)\n"
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-stdin-rt-01", code, stdin_mode="pipe")
        )
        await client.write_stdin(
            ExecStdinParams(
                execution_id="exec-stdin-rt-01",
                session_nonce=client.session_nonce,
                data="ping-ct6\n",
                close=True,
            )
        )
        events = await _collect_until_exited(client)
        assert "ECHO:ping-ct6" in _stdout_text(events).replace("\r", "")
        assert events[-1].exit_code == 0
    finally:
        await client.close()


async def test_stdin_write_with_wrong_nonce_rejected(tmp_path):
    """§11.4 绑定：nonce 不匹配 → 结构化 bad_nonce，不执行写入。"""
    del tmp_path
    code = "import time\nprint('ready')\ntime.sleep(10)\n"
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-stdin-badnonce", code, stdin_mode="pipe")
        )
        with pytest.raises(ExecutorUnavailable) as excinfo:
            await client.write_stdin(
                ExecStdinParams(
                    execution_id="exec-stdin-badnonce",
                    session_nonce="wrong-nonce-999",
                    data="x",
                )
            )
        assert excinfo.value.code == "bad_nonce"
        await client.cancel("exec-stdin-badnonce")
    finally:
        await client.close()


async def test_stdin_write_without_pipe_is_structurally_rejected(tmp_path):
    """stdin_mode=closed 时写入 → stdin_closed；缺 nonce 的 pipe 请求 → bad_params。"""
    del tmp_path
    code = "import time\ntime.sleep(5)\n"
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(_params("exec-stdin-nopipe", code))
        with pytest.raises(ExecutorUnavailable) as closed_exc:
            await client.write_stdin(
                ExecStdinParams(
                    execution_id="exec-stdin-nopipe",
                    session_nonce=client.session_nonce,
                    data="x",
                )
            )
        assert closed_exc.value.code == "stdin_closed"
        # 缺 session_nonce 的 pipe 启动请求：不隐式放行。
        payload = _params(
            "exec-stdin-nononce", "print(1)", stdin_mode="pipe"
        ).model_dump()
        payload["session_nonce"] = None
        with pytest.raises(ExecutorUnavailable) as params_exc:
            await client._request(  # noqa: SLF001 - 契约级负向用例
                "execution/start", payload
            )
        assert params_exc.value.code == "bad_params"
        await client.cancel("exec-stdin-nopipe")
    finally:
        await client.close()


async def test_output_read_continuation_and_removal(tmp_path):
    """output/read：偏移续读不重复；执行移除后 unknown_execution。"""
    del tmp_path
    code = (
        "import time\n"
        "print('chunk-a')\n"
        "import sys; sys.stdout.flush()\n"
        "time.sleep(3)\n"
        "print('chunk-b')\n"
    )
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(_params("exec-outread-01", code))
        await asyncio.sleep(1.0)
        first = await client.read_output("exec-outread-01", from_offset=0)
        assert "chunk-a" in first["data"]
        assert first["next_offset"] > 0
        second = await client.read_output(
            "exec-outread-01", from_offset=first["next_offset"]
        )
        assert "chunk-a" not in second["data"], "续读不得重复已读内容"
        events = await _collect_until_exited(client)
        assert events[-1].exit_code == 0
        # 退出事件与执行移除分属不同线程：移除最终发生（有界轮询验证）。
        for _ in range(30):
            try:
                await client.read_output("exec-outread-01")
            except ExecutorUnavailable as removed_exc:
                assert removed_exc.code == "unknown_execution"
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("执行退出后未被移除，续读窗口仍可访问")
    finally:
        await client.close()


async def test_pty_echo_roundtrip_or_fail_closed(tmp_path):
    """受控 PTY（§11.3）二选一结局，不得静默交付伪会话：

    - ConPTY 附着可用 → 回显回读成功；
    - 环境受限（本机实证：属性表附着不生效）→ 结构化
      ``pty_environment_unavailable`` 失败关闭。
    """
    del tmp_path
    code = "line = input()\nprint('PTY:' + line.strip())\n"
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        try:
            await client.start_execution(
                _params("exec-pty-echo-01", code, stdin_mode="pipe", mode="pty")
            )
        except ExecutorUnavailable as exc:
            assert exc.code == "pty_environment_unavailable", (
                f"pty 拒绝必须结构化：{exc}"
            )
            pytest.skip(f"ConPTY 附着环境不可用（失败关闭已验证）：{exc}")
        await client.write_stdin(
            ExecStdinParams(
                execution_id="exec-pty-echo-01",
                session_nonce=client.session_nonce,
                data="hello-pty\r\n",  # 终端语义：CR 结束行（cooked 输入）
                close=True,
            )
        )
        events = await _collect_until_exited(client)
        # ConPTY 排空晚于退出事实：继续收尽迟到 delta（有界等待）。
        while True:
            late = await client.next_event(timeout=2)
            if late is None:
                break
            events.append(late)
        text = _stdout_text(events).replace("\r", "")
        assert "PTY:hello-pty" in text, f"PTY 输出异常：{text!r}"
        assert any(
            event.notification.value == "execution/exited"
            and event.exit_code == 0
            for event in events
        )
    finally:
        await client.close()


async def test_pty_with_appcontainer_is_rejected(tmp_path):
    """失败关闭：AC + ConPTY 组合未经验证，一律拒绝（§11.5）。"""
    del tmp_path
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        payload = _params(
            "exec-pty-ac-deny", "print(1)", stdin_mode="pipe", mode="pty"
        ).model_dump()
        payload["session_nonce"] = "pty-ac-nonce-01"
        payload["appcontainer"] = True
        with pytest.raises(ExecutorUnavailable) as excinfo:
            await client._request(  # noqa: SLF001 - 契约级负向用例
                "execution/start", payload
            )
        assert excinfo.value.code == "unsupported_mode"
    finally:
        await client.close()
