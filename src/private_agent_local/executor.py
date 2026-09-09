"""受控命令只经私有 stdio 宿主执行；宿主不可用时不回退执行。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from contextlib import nullcontext
from pathlib import Path

from private_agent_core.execution.contracts import ExecStartParams
from private_agent_core.execution.exec_host_client import (
    ExecHostClient,
    ExecutorUnavailable,
)

from . import files


class ExecutionFailure(ValueError):
    """传递安全错误类别和已收集输出，不伪造进程退出。"""

    def __init__(self, message: str, *, outcome: str, output: dict):
        super().__init__(message)
        self.outcome, self.output = outcome, output


class ExecutionTimeout(TimeoutError):
    def __init__(self, output: dict):
        super().__init__("本机命令超时，进程已停止")
        self.output = output


def host_path() -> Path:
    name = "exec-host.exe" if os.name == "nt" else "exec-host"
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / name
    return Path(__file__).resolve().parents[2] / "apps" / "exec-host" / "target" / "release" / name


def verify_host(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("安装包缺少可信执行宿主；命令未执行，请重新安装完整客户端")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if getattr(sys, "frozen", False):
        manifest = path.with_suffix(".sha256")
        if not manifest.is_file() or manifest.read_text(encoding="ascii").strip() != digest:
            raise ValueError("执行宿主 SHA-256 校验失败；命令未执行")
    return digest


async def run_command(root: Path, args: list[str], *, timeout: float = 600, executable: Path | None = None,
                      execution_id: str | None = None, trusted: bool = False, sandbox_directory: Path | None = None) -> dict:
    path = executable or host_path()
    host_sha256 = verify_host(path)
    command, env = files.prepare_process(args)
    # 宿主环境也采用同一白名单；模型与账号凭据从不进入子进程环境。
    client = ExecHostClient([str(path)], cwd=str(root), env=env)
    execution_id = execution_id or str(uuid.uuid4())
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = False
    submitted = False
    cancelled = False
    sandbox = None

    def collected():
        return {**{key: value.decode("utf-8", errors="replace") for key, value in buffers.items()},
                "truncated": truncated, "execution_host_sha256": host_sha256}

    try:
        dll_search = nullcontext()
        if os.name == "nt" and getattr(sys, "frozen", False):
            from .windows_process import system_dll_search
            dll_search = system_dll_search()
        with dll_search:
            health = await client.start()
        if "argv" not in health.modes:
            raise ExecutorUnavailable("执行宿主未提供 argv 能力")
        if not trusted:
            if health.sandbox_profile_protocol != 1 or not health.sandbox_available:
                raise ExecutorUnavailable("宿主没有独立沙箱协议，请升级完整客户端", code="sandbox_policy_unavailable")
            from .windows_sandbox import SandboxLease
            sandbox = await SandboxLease.prepare(root, args, env, directory=sandbox_directory)
            sandbox.bind(client.pid)
            env = sandbox.environment
        network = "approved" if trusted else "none"
        binding = json.dumps({"cwd": str(root), "argv": command, "network_policy": network}, sort_keys=True).encode()
        submitted = True
        await client.start_execution(ExecStartParams(execution_id=execution_id, argv=command, cwd=str(root), env_diff=env,
            timeout_ms=max(1, min(600000, int(timeout * 1000))), output_limit_bytes=files.MAX_OUTPUT,
            sandbox_policy_hash=hashlib.sha256(binding).hexdigest(), network_policy=network,
            appcontainer=not trusted, appcontainer_profile=sandbox.name if sandbox else None))
        async with asyncio.timeout(timeout + 5):
            while True:
                event = await client.next_event(timeout=1)
                if event is None:
                    client.ensure_alive()
                    continue
                if event.execution_id != execution_id:
                    raise ExecutorUnavailable("执行宿主返回了其他任务的事件")
                if event.data and event.stream in buffers:
                    current = buffers[event.stream]
                    data = event.data.encode("utf-8")
                    truncated |= len(current) + len(data) > files.MAX_OUTPUT
                    current.extend(data[:max(0, files.MAX_OUTPUT - len(current))])
                if event.notification.value == "execution/failed":
                    raise ExecutionFailure("执行宿主无法确认进程或完整输出，结果未知", outcome="unknown", output=collected())
                if event.notification.value == "execution/cancelled":
                    # 宿主先发取消通知，随后 exited 才携带超时原因；等待终态并收齐输出。
                    cancelled = True
                if event.notification.value == "execution/exited":
                    if event.cancelled_by_timeout:
                        raise TimeoutError("本机命令超时")
                    if cancelled:
                        raise ExecutionFailure("命令已取消", outcome="cancelled", output=collected())
                    if event.exit_code is None:
                        raise ExecutorUnavailable("执行宿主未报告退出码")
                    return {"returncode": event.exit_code, **collected(), "sandbox_available": health.sandbox_available}
    except ExecutorUnavailable as error:
        failed_to_start = not submitted or error.code in {"spawn_failed", "bad_params", "unsupported_mode", "sandbox_policy_unavailable"}
        raise ExecutionFailure("执行宿主无法启动，命令未执行" if failed_to_start else "执行宿主通信中断，执行结果未知",
                               outcome="failed" if failed_to_start else "unknown", output=collected()) from error
    except TimeoutError:
        raise ExecutionTimeout(collected()) from None
    except asyncio.CancelledError as error:
        error.execution_output = collected()
        raise
    finally:
        # 每次命令独立宿主；关闭宿主会回收其 Job 内残留后代，不留下后台脚本。
        try:
            await client.close()
        finally:
            if sandbox:
                await asyncio.to_thread(sandbox.close)
