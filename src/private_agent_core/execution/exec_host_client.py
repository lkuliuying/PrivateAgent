"""Exec Host JSONL stdio 客户端（专项计划 §11.1/CT6-01）。

职责边界：
- 建立子进程 JSONL 通道，握手校验协议版本；
- execution/start → 事件流转发（有界缓冲）、cancel、shutdown；
- **失败关闭**：Exec Host 不可用/握手失败/协议版本不符时抛
  :class:`ExecutorUnavailable`——调用方必须把新副作用请求失败关闭，
  绝不静默降级到无沙箱执行路径。

本客户端不做审批、不写数据库、不判定完成（AD-T02）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
from typing import Any

from .contracts import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ExecCancelParams,
    ExecEvent,
    ExecHealth,
    ExecInitializeParams,
    ExecStartParams,
    ExecStdinParams,
)

_HANDSHAKE_TIMEOUT_S = 10.0
_REQUEST_TIMEOUT_S = 15.0


class ExecutorUnavailable(RuntimeError):
    """Exec Host 不可用或协议不兼容；副作用执行必须失败关闭。

    ``code`` 携带稳定错误码（专项计划 §7.7）；host 返回结构化 code
    时不得只保留可读文案而丢弃码。
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ExecHostClient:
    """单进程生命周期的 Exec Host 连接（一个 Python Core 对一个 host）。"""

    def __init__(self, command: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None) -> None:
        if not command:
            raise ValueError("Exec Host 启动命令不能为空")
        self._command = [str(item) for item in command]
        self._cwd = cwd
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 0
        self._events: asyncio.Queue[ExecEvent | None] = asyncio.Queue(maxsize=4_096)
        self._reader_task: asyncio.Task[None] | None = None
        self._session_nonce = ""
        # 单一读取泵分发：响应 → pending future；通知 → 事件队列。
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._pump_ready = asyncio.Event()
        self._failure: ExecutorUnavailable | None = None

    # ---- 生命周期 -------------------------------------------------------

    async def start(self) -> ExecHealth:
        """拉起 Exec Host 并完成 initialize 握手（版本不符即失败关闭）。"""
        try:
            import os as _os

            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=self._cwd,
                env=self._env,
                limit=MAX_MESSAGE_BYTES + 1,
                **({"creationflags": 0x08000000} if os.name == "nt" else {}),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=(
                    None
                    if _os.environ.get("PA_EXEC_HOST_DEBUG")
                    else asyncio.subprocess.DEVNULL
                ),
            )
        except (OSError, ValueError) as exc:
            raise ExecutorUnavailable(
                f"无法启动 exec host：{type(exc).__name__}"
            ) from exc
        self._reader_task = asyncio.create_task(self._pump_events())
        self._reader_task.add_done_callback(self._reader_finished)
        try:
            response = await asyncio.wait_for(
                self._await_response(1), timeout=_HANDSHAKE_TIMEOUT_S
            )
        except ExecutorUnavailable:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise ExecutorUnavailable("exec host 握手超时") from exc
        try:
            health = ExecHealth.model_validate(response)
        except Exception as exc:  # noqa: BLE001 - 非法握手响应按不可用处理
            await self.close()
            raise ExecutorUnavailable("exec host 握手响应非法") from exc
        if health.protocol_version != PROTOCOL_VERSION:
            await self.close()
            raise ExecutorUnavailable(
                f"exec host 协议版本不符：{health.protocol_version}"
            )
        self._next_id = 1
        return health

    def _reader_finished(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._failure = ExecutorUnavailable("exec host 通道异常，执行状态需要检查", code="executor_protocol_error")
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(self._failure)
            if self._events.full():
                self._events.get_nowait()
            self._events.put_nowait(None)

    async def close(self) -> None:
        """shutdown 并回收进程（尽力而为，不掩盖取消）。"""
        if self._process is not None and self._process.returncode is None:
            with contextlib.suppress(Exception):
                await self._request("shutdown", {}, timeout=5.0)
        if self._process is not None and self._process.returncode is None:
            self._process.kill()
        if self._reader_task is not None:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
            self._reader_task = None
        if self._process is not None:
            await asyncio.gather(self._process.wait(), return_exceptions=True)
            self._process = None

    @property
    def session_nonce(self) -> str:
        return self._session_nonce

    # ---- 执行面 ---------------------------------------------------------

    async def start_execution(self, params: ExecStartParams) -> None:
        self._require_alive()
        self._session_nonce = secrets.token_urlsafe(32)
        if params.session_nonce is None:
            # 使用不可预测的会话凭证，不从公开执行 ID 派生。
            params = params.model_copy(
                update={"session_nonce": self._session_nonce}
            )
        else:
            self._session_nonce = params.session_nonce
        await self._request(
            "execution/start", params.model_dump(), timeout=_REQUEST_TIMEOUT_S
        )

    async def write_stdin(self, params: ExecStdinParams) -> None:
        self._require_alive()
        await self._request("execution/stdin/write", params.model_dump())

    async def read_output(
        self,
        execution_id: str,
        *,
        from_offset: int = 0,
        limit: int = 65_536,
    ) -> dict[str, Any]:
        """execution/output/read：有界滑动窗口续读（§11.4）。"""
        self._require_alive()
        return await self._request(
            "execution/output/read",
            {
                "execution_id": execution_id,
                "from_offset": from_offset,
                "limit": limit,
            },
        )

    async def cancel(self, execution_id: str) -> None:
        self._require_alive()
        await self._request(
            "execution/cancel",
            ExecCancelParams(execution_id=execution_id).model_dump(),
        )

    async def next_event(self, timeout: float = 30.0) -> ExecEvent | None:
        """读取下一个事件；超时返回 None（连接仍存活）。"""
        try:
            if self._failure:
                raise self._failure
            event = await asyncio.wait_for(self._events.get(), timeout)
            if self._failure:
                raise self._failure
            return event
        except asyncio.TimeoutError:
            return None

    # ---- 内部 -----------------------------------------------------------

    def _require_alive(self) -> None:
        if self._failure:
            raise self._failure
        if self._process is None or self._process.returncode is not None:
            raise ExecutorUnavailable("exec host 未运行")

    def ensure_alive(self) -> None:
        """确认通道与子进程仍可用，供等待执行事件的宿主检查。"""
        self._require_alive()

    async def _send_line(self, payload: dict[str, Any]) -> None:
        assert self._process is not None and self._process.stdin is not None
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        encoded = line.encode("utf-8")
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ExecutorUnavailable("exec host 请求超限")
        self._process.stdin.write(encoded + b"\n")
        await self._process.stdin.drain()

    async def _request(
        self, method: str, params: dict[str, Any], *, timeout: float = _REQUEST_TIMEOUT_S
    ) -> dict[str, Any]:
        self._require_alive()
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send_line(
                {"id": request_id, "method": method, "params": params}
            )
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise ExecutorUnavailable(f"{method} 响应超时") from exc
        finally:
            self._pending.pop(request_id, None)

    async def _await_response(self, request_id: int) -> dict[str, Any]:
        """握手专用：注册 future 后发送 initialize 并等待（由泵分发）。"""
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._pump_ready.wait()
            await self._send_line(
                {
                    "id": request_id,
                    "method": "initialize",
                    "params": ExecInitializeParams().model_dump(),
                }
            )
            return await asyncio.wait_for(future, timeout=_HANDSHAKE_TIMEOUT_S)
        finally:
            self._pending.pop(request_id, None)

    async def _pump_events(self) -> None:
        """单一读取泵：响应分发到 pending future，通知入队（有界）。"""
        assert self._process is not None and self._process.stdout is not None
        self._pump_ready.set()
        while True:
            raw = await self._process.stdout.readline()
            if not raw:
                for future in list(self._pending.values()):
                    if not future.done():
                        future.set_exception(ExecutorUnavailable("exec host 已退出"))
                self._pending.clear()
                await self._events.put(None)
                break
            if len(raw) > MAX_MESSAGE_BYTES:
                raise ExecutorUnavailable("exec host 消息超出协议上限")
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(parsed, dict):
                continue
            message_id = parsed.get("id")
            if isinstance(message_id, int) and message_id in self._pending:
                future = self._pending.pop(message_id)
                if future.done():
                    continue
                error = parsed.get("error")
                if error is not None:
                    detail = (
                        error.get("message", "exec host 请求失败")
                        if isinstance(error, dict)
                        else str(error)
                    )
                    code = (
                        error.get("code")
                        if isinstance(error, dict)
                        else None
                    )
                    prefix = f"[{code}] " if isinstance(code, str) and code else ""
                    future.set_exception(
                        ExecutorUnavailable(
                            f"请求失败：{prefix}{detail}",
                            code=code if isinstance(code, str) else None,
                        )
                    )
                else:
                    result = parsed.get("result") or {}
                    future.set_result(result if isinstance(result, dict) else {})
                continue
            notification = parsed.get("notification")
            if not isinstance(notification, str):
                continue
            try:
                event = ExecEvent.model_validate(
                    {**parsed, "notification": notification}
                )
            except Exception:  # noqa: BLE001 - 非法事件丢弃，不影响通道
                continue
            if self._events.full():
                raise ExecutorUnavailable("exec host 事件缓冲溢出，不能丢弃执行证据")
            await self._events.put(event)
