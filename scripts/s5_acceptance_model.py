"""S5 桌面验收的回环模型替身：只读取显式队列，不保存请求正文或认证信息。"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def serve(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    stopped = threading.Event()
    sequence = 0

    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/v1/models":
                self.reply({"data": [{"id": "s5-acceptance-loopback", "object": "model"}]})
            else:
                self.reply({"error": "unknown route"}, 404)

        def do_POST(self):
            nonlocal sequence
            if self.path != "/v1/chat/completions" or self.headers.get("Authorization"):
                self.reply({"error": "unexpected route or authorization"}, 400)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2 * 1024 * 1024:
                self.reply({"error": "invalid body size"}, 400)
                return
            payload = json.loads(self.rfile.read(size))
            if payload.get("model") != "s5-acceptance-loopback":
                self.reply({"error": "unexpected model"}, 400)
                return
            with lock:
                queue_path = directory / "responses.json"
                queue = json.loads(queue_path.read_text(encoding="utf-8"))
                if not queue:
                    self.reply({"error": "acceptance queue exhausted"}, 409)
                    return
                item = queue.pop(0)
                queue_path.write_text(json.dumps(queue), encoding="utf-8")
                sequence += 1
                request_id = f"s5-{sequence}"
                with (directory / "model-events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"request_id": request_id, "time": time.time(), "stream": bool(payload.get("stream")),
                        "tool": item.get("tool"), "hold": bool(item.get("hold")), "authorization_absent": True}) + "\n")
            if item.get("hold"):
                # 保持模型轮次处于进行中，留给真实客户端强退；不生成工具或完成结论。
                stopped.wait(170)
                return
            delay_ms = item.get("delay_ms", 0)
            if not isinstance(delay_ms, int) or not 0 <= delay_ms <= 120_000:
                self.reply({"error": "invalid acceptance delay"}, 400)
                return
            if stopped.wait(delay_ms / 1000):
                return
            with lock, (directory / "model-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"request_id": request_id, "time": time.time(), "response_attempt": True}) + "\n")
            calls = [{"id": request_id, "type": "function", "function": {"name": item["tool"],
                "arguments": json.dumps(item["arguments"])}}] if item.get("tool") else []
            message = {"role": "assistant", "content": item.get("text", ""), "tool_calls": calls}
            usage = {"prompt_tokens": 2000, "completion_tokens": 100}
            try:
                if payload.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    delta = {**message, "tool_calls": [{"index": index, **call} for index, call in enumerate(calls)]}
                    chunks = [{"id": request_id, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                        {"id": request_id, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if calls else "stop"}], "usage": usage}]
                    for chunk in chunks:
                        self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    self.close_connection = True
                else:
                    self.reply({"id": request_id, "model": payload["model"], "choices": [{"index": 0, "message": message,
                        "finish_reason": "tool_calls" if calls else "stop"}], "usage": usage})
            except (BrokenPipeError, ConnectionResetError):
                # 强退与暂停会关闭这条测试连接，模型不重试、不补发。
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    (directory / "endpoint.json").write_text(json.dumps({"endpoint": f"http://127.0.0.1:{server.server_port}/v1"}), encoding="utf-8")
    try:
        server.serve_forever()
    finally:
        stopped.set()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    serve(parser.parse_args().directory.resolve())
