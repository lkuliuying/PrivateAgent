"""桌面私有管道协议；复用 ASGI 路由但不监听 TCP 端口。"""
from __future__ import annotations

import asyncio
import codecs
import json
import os
import queue
import threading
from urllib.parse import unquote, urlsplit

MAX_FRAME = 8 * 1024 * 1024
MAX_BODY = 2 * 1024 * 1024


def request_scope(frame: dict, nonce: str) -> tuple[dict, bytes]:
    request = frame.get("params")
    if not isinstance(request, dict) or set(request) - {"path", "method", "headers", "body"}:
        raise ValueError("无效的管道请求")
    path = request.get("path", "")
    if not isinstance(path, str) or len(path) > 8192 or not path.startswith("/") or path.startswith("//") or any(c in path for c in "\\\r\n\x00"):
        raise ValueError("无效的本机路径")
    url = urlsplit(path)
    if url.scheme or url.netloc or url.fragment or url.path.startswith("/internal/"):
        raise ValueError("管道只接受公开的本机接口路径")
    method = request.get("method", "GET")
    if method not in {"GET", "HEAD", "POST", "PATCH", "DELETE"}:
        raise ValueError("不支持的请求方法")
    text = request.get("body", "")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BODY:
        raise ValueError("请求正文超过限制")
    headers = request.get("headers", {})
    if not isinstance(headers, dict) or len(headers) > 8:
        raise ValueError("请求头无效")
    output = [(b"host", b"127.0.0.1"), (b"x-privateagent-local", nonce.encode("ascii"))]
    for key, value in headers.items():
        if key.lower() not in {"authorization", "content-type", "accept", "last-event-id"} or not isinstance(value, str) or len(value) > 16384 or any(c in value for c in "\r\n\x00"):
            raise ValueError("请求头超出允许范围")
        output.append((key.lower().encode("ascii"), value.encode("latin-1")))
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "method": method, "scheme": "http", "path": unquote(url.path),
             "raw_path": url.path.encode("utf-8"), "query_string": url.query.encode("ascii"),
             "root_path": "", "headers": output, "server": ("127.0.0.1", 0), "client": ("127.0.0.1", 0)}
    return scope, text.encode("utf-8")


async def serve(app, nonce: str, input_stream, output_stream, *, parent_alive=None):
    loop = asyncio.get_running_loop()
    incoming = asyncio.Queue(maxsize=64)
    outgoing = queue.Queue(maxsize=32)
    stopped = asyncio.Event()
    tasks: dict[str, asyncio.Task] = {}

    def finish(future, error=None):
        if not future.done():
            if error:
                future.set_exception(ConnectionError("桌面管道已关闭"))
            else:
                future.set_result(None)

    def read_pipe():
        buffered = bytearray()
        try:
            while True:
                chunk = os.read(input_stream.fileno(), 65536)
                if not chunk:
                    break
                buffered.extend(chunk)
                while (end := buffered.find(b"\n")) >= 0:
                    if end >= MAX_FRAME:
                        return
                    line = bytes(buffered[:end + 1])
                    del buffered[:end + 1]
                    future = asyncio.run_coroutine_threadsafe(incoming.put(line), loop)
                    try:
                        future.result(timeout=10)
                    except TimeoutError:
                        future.cancel()
                        return
                if len(buffered) > MAX_FRAME:
                    break
        except (OSError, RuntimeError):
            pass
        finally:
            if not loop.is_closed():
                loop.call_soon_threadsafe(stopped.set)

    def write_pipe():
        while True:
            item = outgoing.get()
            if item is None:
                return
            data, future = item
            try:
                # 不让守护线程持有 Python 标准流缓冲锁，避免退出时发生解释器致命错误。
                remaining = memoryview(data)
                while remaining:
                    remaining = remaining[os.write(output_stream.fileno(), remaining):]
            except (OSError, ValueError):
                if not loop.is_closed():
                    loop.call_soon_threadsafe(finish, future, True)
                    loop.call_soon_threadsafe(stopped.set)
                return
            if not loop.is_closed():
                loop.call_soon_threadsafe(finish, future)

    async def send(frame):
        data = (json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > MAX_FRAME or stopped.is_set():
            raise ConnectionError("桌面管道不可用")
        future = loop.create_future()
        try:
            outgoing.put_nowait((data, future))
            await asyncio.wait_for(future, timeout=10)
        except (queue.Full, TimeoutError):
            stopped.set()
            raise ConnectionError("桌面管道读取超时") from None

    async def dispatch(frame):
        request_id = frame["id"]
        decoder = codecs.getincrementaldecoder("utf-8")()
        consumed = False

        async def receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Future()

        async def response(message):
            if message["type"] == "http.response.start":
                headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in message.get("headers", [])}
                await send({"id": request_id, "status": message["status"], "headers": headers})
            elif message["type"] == "http.response.body":
                content = message.get("body", b"")
                for offset in range(0, len(content), 32768):
                    data = decoder.decode(content[offset:offset + 32768])
                    if data:
                        await send({"id": request_id, "data": data})
                if not message.get("more_body", False):
                    tail = decoder.decode(b"", final=True)
                    if tail:
                        await send({"id": request_id, "data": tail})
                    await send({"id": request_id, "done": True})
        try:
            scope, body = request_scope(frame, nonce)
            await app(scope, receive, response)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 协议错误与业务异常均不把账号、路径或异常正文写入管道诊断。
            if not stopped.is_set():
                await send({"id": request_id, "error": "本机请求失败，请检查连接或重试"})
        finally:
            tasks.pop(request_id, None)

    async def watch_parent():
        while not stopped.is_set():
            await asyncio.sleep(2)
            if parent_alive and not parent_alive():
                stopped.set()

    threading.Thread(target=read_pipe, daemon=True, name="desktop-pipe-reader").start()
    threading.Thread(target=write_pipe, daemon=True, name="desktop-pipe-writer").start()
    watcher = asyncio.create_task(watch_parent())
    pending_read = None
    stop_waiter = asyncio.create_task(stopped.wait())
    try:
        async with app.router.lifespan_context(app):
            try:
                while not stopped.is_set():
                    pending_read = asyncio.create_task(incoming.get())
                    ready, _ = await asyncio.wait({pending_read, stop_waiter}, return_when=asyncio.FIRST_COMPLETED)
                    if stop_waiter in ready:
                        break
                    try:
                        frame = json.loads(pending_read.result())
                    except (ValueError, UnicodeError):
                        break
                    if not isinstance(frame, dict):
                        break
                    if frame.get("method") == "shutdown":
                        break
                    request_id = frame.get("id")
                    if not isinstance(request_id, str) or not request_id.isascii() or not request_id.replace("-", "").isalnum() or len(request_id) > 64:
                        break
                    if frame.get("method") == "cancel":
                        if task := tasks.get(request_id):
                            task.cancel()
                    elif frame.get("method") == "request" and request_id not in tasks and len(tasks) < 64:
                        tasks[request_id] = asyncio.create_task(dispatch(frame))
                    else:
                        break
            finally:
                active = list(tasks.values())
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)
    finally:
        stopped.set()
        for task in (watcher, pending_read, stop_waiter):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (watcher, pending_read, stop_waiter) if t), return_exceptions=True)
        try:
            outgoing.put_nowait(None)
        except queue.Full:
            pass
