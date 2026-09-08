"""真实 Rust 宿主的正反对照；只触碰临时文件和本机临时监听端口。"""
import asyncio
import hashlib
import os
import sys
import uuid

import pytest
from test_baseline import record

from private_agent_core.execution.contracts import ExecStartParams, ExecStdinParams
from private_agent_core.execution.exec_host_client import (
    ExecHostClient,
    ExecutorUnavailable,
)
from private_agent_local import files
from private_agent_local.executor import host_path, run_command


async def raw_execution(root, code, *, network="approved", mode="argv", stdin=None, integrity="inherit"):
    command, environment = files.prepare_process([sys.executable, "-c", code])
    client = ExecHostClient([str(host_path())], cwd=str(root), env=environment)
    execution_id = str(uuid.uuid4())
    output = ""
    try:
        health = await client.start()
        await client.start_execution(ExecStartParams(
            execution_id=execution_id, argv=command, cwd=str(root), env_diff=environment,
            network_policy=network, integrity_level=integrity, mode=mode,
            stdin_mode="pipe" if stdin is not None else "closed", timeout_ms=5000,
            sandbox_policy_hash=hashlib.sha256(b"s0-isolated-probe").hexdigest(),
        ))
        if stdin is not None:
            with pytest.raises(ExecutorUnavailable):
                await client.write_stdin(ExecStdinParams(execution_id=execution_id, session_nonce="incorrect-nonce", data="bad"))
            await client.write_stdin(ExecStdinParams(execution_id=execution_id, session_nonce=client.session_nonce, data=stdin, close=True))
        async with asyncio.timeout(10):
            while True:
                event = await client.next_event(timeout=1)
                if event is None:
                    client.ensure_alive()
                    continue
                if event.data:
                    output += event.data
                if event.notification.value == "execution/failed":
                    raise ExecutorUnavailable("宿主执行失败", code=event.error.code if event.error else None)
                if event.notification.value == "execution/exited":
                    return {"exit_code": event.exit_code, "output": output,
                            "sandbox_available": health.sandbox_available, "modes": list(health.modes)}
    finally:
        await client.close()


async def test_host_stdin_nonce_and_unicode(tmp_path):
    result = await raw_execution(tmp_path, "import sys; print('ECHO:'+sys.stdin.read())", stdin="中文输入\n")
    record("HOST-STDIN", **result)
    assert result["exit_code"] == 0 and "ECHO:中文输入" in result["output"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="G10：当前可信项目命令可以间接写入项目外文件")
async def test_host_file_scope_with_allowed_control(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    code = "from pathlib import Path; Path('inside.txt').write_text('inside'); Path('../outside.txt').write_text('outside'); print('READY')"
    result = await run_command(root, [sys.executable, "-c", code])
    # 正对照不成立时直接报环境错误，不能将未启动视为隔离通过。
    if result["returncode"] != 0 or not (root / "inside.txt").exists():
        raise RuntimeError("文件允许对照失败，无法判断隔离")
    outside = (tmp_path / "outside.txt").exists()
    record("HOST-FILE", inside_allowed=True, outside_written=outside, sandbox_available=result["sandbox_available"])
    assert outside is False


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="G10：非 AppContainer 执行时 network_policy=none 不强制阻断网络")
async def test_host_network_none_with_allowed_control(tmp_path):
    accepted = []

    async def handle(reader, writer):
        accepted.append(await reader.read(1))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        code = f"import socket; s=socket.create_connection(('127.0.0.1',{port}),timeout=2); s.sendall(b'x'); s.close(); print('CONNECTED')"
        allowed = await raw_execution(tmp_path, code)
        if allowed["exit_code"] != 0 or "CONNECTED" not in allowed["output"]:
            raise RuntimeError("网络允许对照失败，不能据此宣称网络隔离")
        denied = await raw_execution(tmp_path, code, network="none")
        record("HOST-NETWORK", allowed=allowed, requested_none=denied, accepted_connections=len(accepted), scope="loopback-only")
        assert "CONNECTED" not in denied["output"]
    finally:
        server.close()
        await server.wait_closed()


async def test_host_pty_requires_successful_argv_control(tmp_path):
    code = "print('PTY-CONTROL')"
    allowed = await raw_execution(tmp_path, code)
    assert allowed["exit_code"] == 0 and "PTY-CONTROL" in allowed["output"]
    try:
        result = await raw_execution(tmp_path, code, mode="pty")
    except ExecutorUnavailable as error:
        record("HOST-PTY", argv_control=allowed, pty_status="unavailable", code=error.code)
        if error.code != "pty_environment_unavailable":
            raise
        pytest.skip("真实 argv 对照成功，但 ConPTY 环境探针失败；PTY 功能未通过")
    record("HOST-PTY", argv_control=allowed, pty_status="executed", result=result)
    assert result["exit_code"] == 0 and "PTY-CONTROL" in result["output"]


@pytest.mark.skipif(os.name != "nt", reason="Low MIC 仅适用于 Windows")
async def test_host_low_integrity_has_a_startup_control(tmp_path):
    allowed = await raw_execution(tmp_path, "print('STARTED')")
    assert allowed["exit_code"] == 0 and "STARTED" in allowed["output"]
    try:
        restricted = await raw_execution(tmp_path, "print('STARTED')", integrity="low")
    except ExecutorUnavailable as error:
        record("HOST-LOW", allowed=allowed, status="startup_blocked", code=error.code)
        if error.code != "sandbox_policy_unavailable":
            raise
        pytest.skip("低完整性进程无法启动，不能将此当作文件隔离有效")
    record("HOST-LOW", allowed=allowed, restricted=restricted, scope="startup-only")
    assert restricted["exit_code"] == 0 and "STARTED" in restricted["output"]
