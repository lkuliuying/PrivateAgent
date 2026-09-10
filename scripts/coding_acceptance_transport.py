"""评测专用回环账号与正式私有 IPC 客户端，不读取真实账号配置。"""
from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from coding_acceptance_evidence import digest, redact
from coding_validation_process import managed_process
from run_coding_validation import ROOT, isolated_environment


def reply(text="", name=None, arguments=None):
    return {"provider": "s6-loopback", "model": "s6-fixture", "text": text,
            "tool_calls": [{"id": uuid.uuid4().hex, "name": name, "arguments": arguments or {}}] if name else [],
            "usage": {"input_tokens": 100, "output_tokens": 20}}


class Fixture:
    def __init__(self, protocol="service", *, model=None, legacy_stream=False):
        self.protocol = protocol
        self.model = model
        self.legacy_stream = legacy_stream
        self.responses = deque()
        self.calls = []
        self.errors = []
        self.token = secrets.token_urlsafe(48)
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, value, status=200):
                body = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def authorized(self):
                return self.headers.get("Authorization") == "Bearer " + owner.token

            def do_GET(self):
                if not self.authorized():
                    self.send({"detail": "fixture unauthorized"}, 401)
                    return
                if self.path == "/auth/me":
                    self.send({"id": 6001, "username": "s6-isolated"})
                elif self.path == "/agent-model-profiles?enabled_only=true":
                    self.send([{"id": "s6-profile", "model_name": owner.model_name, "context_tokens": owner.context_tokens,
                                "provider": "ollama" if owner.protocol == "ollama" else "openai", "provider_id": "s6-provider", "is_local": owner.protocol != "service",
                                "supports_streaming": True, "enabled": True, "is_default": True}])
                elif self.path == "/model-providers":
                    self.send([{"id": "s6-provider", "protocol": "ollama" if owner.protocol == "ollama" else "openai", "enabled": True,
                                "api_format": "ollama_chat" if owner.protocol == "ollama" else "chat_completions",
                                "base_url": "https://fixture.invalid/v1" if owner.protocol == "service" else owner.endpoint,
                                "api_key_configured": owner.protocol == "service",
                                "models": [{"profile_id": "s6-profile", "model_id": owner.model_name}]}])
                elif self.path == "/desktop/model/capabilities":
                    self.send({} if owner.legacy_stream else {"stream_protocol": "1.0"})
                else:
                    self.send({"detail": "fixture route missing"}, 404)

            def do_POST(self):
                try:
                    self.model_request()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # 已暂停或取消的客户端会关闭响应；不重放旧模型响应。
                    pass
                except (ValueError, KeyError, TypeError) as error:
                    owner.errors.append(type(error).__name__)
                    self.send({"detail": "invalid fixture protocol"}, 400)

            def model_request(self):
                is_service = self.path in {"/desktop/model/complete", "/desktop/model/stream"}
                if (is_service and not self.authorized()) or (not is_service and self.headers.get("Authorization")):
                    owner.errors.append("credential_boundary")
                    self.send({"detail": "fixture unauthorized"}, 401)
                    return
                if self.path not in {"/desktop/model/complete", "/desktop/model/stream", "/v1/chat/completions", "/api/chat"}:
                    self.send({}, 404)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2 * 1024 * 1024:
                    raise ValueError("模型请求大小无效")
                payload = json.loads(self.rfile.read(size))
                with owner.lock:
                    owner.calls.append({"path": self.path, "stream": self.path.endswith("/stream") or payload.get("stream", False)})
                    messages = payload.get("request", payload).get("messages", [])
                    last_tool = next((entry for entry in reversed(messages) if entry.get("role") == "tool"), None)
                    output = json.loads(last_tool["content"]).get("output", {}) if last_tool else {}
                    if output.get("status") in {"running", "starting"} and output.get("execution_id"):
                        item = reply(name="read_execution", arguments={"execution_id": output["execution_id"],
                                     "cursor": output.get("next_cursor", 0), "wait_ms": 30000})
                    else:
                        item = owner.responses.popleft() if owner.responses else reply("未完成，测试模型队列已耗尽。")
                    if operation := item.pop("patch_from_read", None):
                        item = reply(name="propose_project_patch", arguments={"operations": [{**operation, "snapshot_id": output["snapshot_id"]}]})
                    elif item.pop("apply_from_preview", False):
                        item = reply(name="apply_project_patch", arguments={"patch_set_id": output["patch_set_id"], "preview_sha256": output["preview_sha256"]})
                if owner.stopped.wait(item.pop("delay_seconds", 0)):
                    return
                if gate := item.pop("response_gate", None):
                    entered, release = gate
                    entered.set()
                    deadline = time.monotonic() + 30
                    while not release.wait(0.05):
                        if owner.stopped.is_set():
                            return
                        if time.monotonic() >= deadline:
                            owner.errors.append("fixture_response_gate_timeout")
                            return
                content, calls = item["text"], item["tool_calls"]
                interrupted = item.pop("interrupt_stream", False)
                if is_service and self.path.endswith("/complete"):
                    self.send(item)
                    return
                openai_calls = [{"index": index, "id": call["id"], "type": "function", "function": {
                    "name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)}} for index, call in enumerate(calls)]
                if is_service:
                    frames = [{"attempt_id": payload["attempt_id"], "sequence": 1, "type": "text.delta", "delta": content},
                              {"attempt_id": payload["attempt_id"], "sequence": 2, "type": "completed", "response": item}]
                    if interrupted:
                        frames.pop()
                    body = "".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in frames)
                    mime = "application/x-ndjson"
                elif owner.protocol == "ollama":
                    message = {"role": "assistant", "content": content, "tool_calls": [{"id": c["id"], "function": {
                        "name": c["name"], "arguments": c["arguments"]}} for c in calls]}
                    body = json.dumps({"model": owner.model_name, "message": message, "done": True,
                                       "prompt_eval_count": 100, "eval_count": 20}) + "\n"
                    mime = "application/x-ndjson" if payload.get("stream") else "application/json"
                elif payload.get("stream"):
                    frames = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": content, "tool_calls": openai_calls}, "finish_reason": None}]},
                              {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if calls else "stop"}],
                               "usage": {"prompt_tokens": 100, "completion_tokens": 20}}]
                    body = "".join("data: " + json.dumps(frame, ensure_ascii=False) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
                    mime = "text/event-stream"
                else:
                    body = json.dumps({"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": openai_calls},
                                                   "finish_reason": "tool_calls" if calls else "stop"}],
                                       "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
                    mime = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body.encode())))
                self.end_headers()
                self.wfile.write(body.encode())
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.endpoint = model["endpoint"] if model else self.origin + ("/v1" if protocol == "openai" else "")
        self.model_name = model["model"] if model else "s6-fixture"
        self.context_tokens = model["context_tokens"] if model else 131072

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stopped.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class RuntimeClient:
    def __init__(self, area: Path, fixture: Fixture, *, bundle: Path | None = None, rust_required=False,
                 tool_paths=(), tool_local_appdata=None):
        self.area, self.fixture = area, fixture
        self.frames = queue.Queue(maxsize=128)
        self.expired_requests = set()
        self.reader_error = None
        self.stderr_bytes = 0
        environment = isolated_environment(area)
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment.update(PRIVATEAGENT_LOCAL_NONCE=secrets.token_urlsafe(48), PATH=str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", ""))
        from coding_acceptance_catalog import rust_toolchain

        toolchain = rust_toolchain() if rust_required else None
        if toolchain:
            environment["PATH"] = str(toolchain) + os.pathsep + environment["PATH"]
        if tool_paths:
            environment["PATH"] = os.pathsep.join(map(str, tool_paths)) + os.pathsep + environment["PATH"]
        for key, relative in (("USERPROFILE", "home"), ("HOME", "home"),
                              ("APPDATA", "home/AppData/Roaming"), ("LOCALAPPDATA", "home/AppData/Local")):
            path = area / relative
            path.mkdir(parents=True, exist_ok=True)
            environment[key] = str(path)
        if tool_local_appdata:
            environment["LOCALAPPDATA"] = str(tool_local_appdata)
        (area / "tmp").mkdir(exist_ok=True)
        if bundle:
            staged = area / "binaries"
            staged.mkdir(exist_ok=True)
            for name in ("private-agent-local.exe", "exec-host.exe", "exec-host.sha256"):
                if not (staged / name).exists():
                    shutil.copyfile(bundle / name, staged / name)
            if digest(staged / "exec-host.exe") != (staged / "exec-host.sha256").read_text().strip():
                raise ValueError("候选执行宿主摘要不符")
            command = [str(staged / "private-agent-local.exe")]
        else:
            command = [sys.executable, "-B", "-m", "private_agent_local.entry"]
        command += ["--stdio", "--server", fixture.origin, "--data-dir", str(area / "records"), "--model-json", '{"inference_mode":"auto"}']
        self.context = managed_process(command, cwd=area, env=environment, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def __enter__(self):
        self.process = self.context.__enter__()
        self.readers = [threading.Thread(target=self._read_frames, daemon=True), threading.Thread(target=self._read_errors, daemon=True)]
        for thread in self.readers:
            thread.start()
        return self

    def _read_frames(self):
        try:
            while line := self.process.stdout.readline(2 * 1024 * 1024 + 1):
                if len(line) > 2 * 1024 * 1024:
                    raise ValueError("IPC 帧超过配额")
                self.frames.put(json.loads(line), timeout=5)
        except (ValueError, OSError, queue.Full) as error:
            self.reader_error = type(error).__name__
        finally:
            try:
                self.frames.put(None, timeout=1)
            except queue.Full:
                self.reader_error = "ipc_queue_exhausted"

    def _read_errors(self):
        try:
            while chunk := self.process.stderr.read(4096):
                self.stderr_bytes += len(chunk)
                if self.stderr_bytes > 1024 * 1024:
                    self.reader_error = "stderr_quota_exceeded"
                    self.process.kill()
                    return
        except OSError:
            self.reader_error = "stderr_read_failed"

    def request(self, path, method="GET", body=None, *, expected=None, timeout=30):
        if timeout <= 0 or len(self.expired_requests) >= 32:
            raise ValueError("IPC 等待期限无效或未收束请求过多")
        identity = uuid.uuid4().hex
        frame = {"id": identity, "method": "request", "params": {"path": path, "method": method,
                 "headers": {"content-type": "application/json", "authorization": "Bearer " + self.fixture.token},
                 "body": json.dumps(body, ensure_ascii=False) if body is not None else ""}}
        self.process.stdin.write((json.dumps(frame, ensure_ascii=False) + "\n").encode())
        self.process.stdin.flush()
        try:
            return self._response(identity, path, expected, time.monotonic() + timeout)
        except TimeoutError:
            # 请求只发送一次；其迟到帧不得污染下一次只读状态查询。
            self.expired_requests.add(identity)
            raise

    def _response(self, identity, path, expected, deadline):
        status, chunks, size = None, [], 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("IPC 响应超时")
            if self.reader_error:
                raise RuntimeError("IPC 读取失败：" + self.reader_error)
            try:
                item = self.frames.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError("IPC 响应超时") from None
            if item is not None and item.get("id") in self.expired_requests:
                if item.get("done") or item.get("error"):
                    self.expired_requests.remove(item["id"])
                continue
            if item is None or item.get("id") != identity or item.get("error"):
                raise RuntimeError("IPC 进程退出或协议响应不匹配")
            status = item.get("status", status)
            data = item.get("data", "")
            size += len(data.encode())
            if size > 8 * 1024 * 1024:
                raise ValueError("IPC 响应超过配额")
            chunks.append(data)
            if item.get("done"):
                break
        if status is None or not (status == expected if expected else 200 <= status < 300):
            detail = redact("".join(chunks))[:500]
            raise RuntimeError(f"本机 API 状态不符：{path} ({status})：{detail}")
        return json.loads("".join(chunks))

    def __exit__(self, *error):
        cleanup_error = None
        try:
            if self.process.poll() is None:
                self.process.stdin.write(b'{"method":"shutdown"}\n')
                self.process.stdin.flush()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    cleanup_error = "本机运行时未在 10 秒内退出"
            if self.process.poll() not in {None, 0}:
                cleanup_error = "本机运行时异常退出"
        except (OSError, ValueError):
            cleanup_error = "IPC 关闭失败"
        finally:
            self.context.__exit__(*error)
            for thread in self.readers:
                thread.join(timeout=2)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()
        if cleanup_error:
            raise RuntimeError(cleanup_error)
