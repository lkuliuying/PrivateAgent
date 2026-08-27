"""S1-T2/T6 spike：Agent 协议 transport 可行性实证（stdio/JSONL 方向）。

用途：为 ADR-002 提供实测数据。按决议 D5 预倾向「Tauri Rust bridge 管理的
sidecar stdio/JSONL」，本脚本实现最小 JSON-RPC 2.0 over stdio/JSONL 服务端，
实证上位计划 §8.1/§8.4 的关键传输语义：

  T1 initialize 必须是首个方法；未初始化即调用其他方法 → 协议错误
  T2 initialize 交换 protocol_version/capabilities/notifications
  T3 ping 往返与 request id 原样回带
  T4 未知方法 → 固定错误信封（code/message/retryable/details/trace_id）
  T5 超长消息 → 拒绝且不中断连接（消息大小限制）
  T6 有界队列背压：队列饱和时返回 retryable 错误，不发生无界排队
  T7 管道关闭 → 服务端干净退出（退出码 0），无挂起
  T8 吞吐基线：N 条 ping 的 p50/p95 往返时延（本机管道，非生产承诺值）

架构说明：生产形态下本服务端逻辑运行在 sidecar（Python）内，Tauri Rust bridge
负责 spawn/生命周期/stdio 管道管理（现有 start_sidecar 端口协商模式改管道协商）。
stdio 通道天然无网络监听面：无 Host/Origin 校验需求；一次性高熵令牌改为
「初始化握手参数 + 进程隔离」模型（见 ADR-002 §4）。

运行：python scripts/spikes/s1_transport_stdio_spike.py [--json PATH]
退出码：0 = 全部一致；1 = 存在失败项；2 = 环境错误。仅依赖标准库。
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "1.0-draft"
MAX_LINE_BYTES = 1 * 1024 * 1024  # 1 MiB 消息大小限制（§8.1 消息大小限制）
WORK_QUEUE_SIZE = 64  # 有界工作队列（§8.4-7 背压）
SERVER_READY_MARK = "PA-SPIKE-SERVER-READY"

ERR_NOT_INITIALIZED = {"code": -32001, "message": "not_initialized", "retryable": False}
ERR_UNKNOWN_METHOD = {"code": -32601, "message": "method_not_found", "retryable": False}
ERR_OVERSIZE = {"code": -32002, "message": "message_too_large", "retryable": False}
ERR_OVERLOADED = {"code": -32003, "message": "server_overloaded", "retryable": True}
ERR_PARSE = {"code": -32700, "message": "parse_error", "retryable": False}


# --- 服务端 --------------------------------------------------------------------
class Server:
    """最小 JSON-RPC 2.0 over stdio 服务端：读线程 → 有界队列 → 工作线程 → 写锁输出。"""

    def __init__(self, stdin, stdout) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.write_lock = threading.Lock()
        self.work_queue: "queue.Queue[tuple[int, dict[str, Any]]]" = queue.Queue(
            maxsize=WORK_QUEUE_SIZE
        )
        self.initialized = False
        self.client_info: dict[str, Any] = {}

    def send(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self.write_lock:
            self.stdout.write(line)
            self.stdout.flush()

    def send_result(self, req_id: Any, result: dict[str, Any]) -> None:
        self.send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def send_error(self, req_id: Any, err: dict[str, Any], details: str = "") -> None:
        self.send({
            "jsonrpc": "2.0", "id": req_id,
            "error": {
                "code": err["code"], "message": err["message"],
                "retryable": err["retryable"], "details": details,
                "trace_id": f"spike-{int(time.time() * 1000)}",
            },
        })

    def handle(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            self.initialized = True
            self.client_info = msg.get("params", {}).get("client_info", {})
            self.send_result(req_id, {
                "protocol_version": PROTOCOL_VERSION,
                "server_info": {"name": "pa-agent-spike", "version": "0.1.0"},
                "capabilities": {
                    "thread": ["start", "read", "list"],
                    "turn": ["start", "steer", "interrupt"],
                    "notifications": ["item/started", "item/delta", "item/completed"],
                },
                "notification_preferences": msg.get("params", {}).get(
                    "notification_preferences", []),
            })
            return
        if not self.initialized:
            self.send_error(req_id, ERR_NOT_INITIALIZED,
                            "initialize 必须是首个方法（§8.1）")
            return
        if method == "ping":
            self.send_result(req_id, {"pong": True, "echo": msg.get("params", {})})
        elif method == "server/capabilities":
            self.send_result(req_id, {"protocol_version": PROTOCOL_VERSION})
        elif method == "spike/slow":
            # 背压测试专用：人为慢方法，使队列在洪泛下饱和
            time.sleep(0.05)
            self.send_result(req_id, {"slow": True})
        else:
            self.send_error(req_id, ERR_UNKNOWN_METHOD, f"unknown method: {method}")

    def reader_loop(self) -> None:
        # 二进制模式读取以实施字节级大小限制
        while True:
            raw = self.stdin.readline()
            if not raw:
                break
            if len(raw) > MAX_LINE_BYTES:
                self.send_error(None, ERR_OVERSIZE,
                                f"line {len(raw)} bytes > {MAX_LINE_BYTES}")
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self.send_error(None, ERR_PARSE, "invalid json line")
                continue
            # 背压：队列满 → 立即拒绝（有界内存，§8.4-7）
            try:
                self.work_queue.put_nowait((0, msg))
            except queue.Full:
                self.send_error(msg.get("id") if isinstance(msg, dict) else None,
                                ERR_OVERLOADED, "work queue saturated")

    def run(self) -> None:
        worker = threading.Thread(target=self._worker_loop, daemon=True)
        worker.start()
        self.reader_loop()  # stdin EOF → 返回

    def _worker_loop(self) -> None:
        while True:
            try:
                _, msg = self.work_queue.get(timeout=0.5)
            except queue.Empty:
                if not _server_alive_flag[0]:
                    return
                continue
            try:
                self.handle(msg)
            except Exception as exc:  # noqa: BLE001 - spike：错误也必须以信封返回
                self.send_error(msg.get("id") if isinstance(msg, dict) else None,
                                {"code": -32603, "message": "internal_error",
                                 "retryable": True}, str(exc))


_server_alive_flag = [True]


def serve() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout
    server = Server(stdin, stdout)
    stdout.write(SERVER_READY_MARK + "\n")
    stdout.flush()
    server.run()
    _server_alive_flag[0] = False


# --- 客户端 / 驱动器 -------------------------------------------------------------
@dataclass
class TraceResult:
    proof: str
    description: str
    passed: bool
    expected: bool
    detail: str
    raw: dict[str, Any] = field(default_factory=dict)


class Client:
    """持久读线程 + 按 id 匹配：通知/非 JSON 行与响应分流，避免对头阻塞。"""

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self.send_lock = threading.Lock()
        self.msg_cond = threading.Condition()
        self.messages: list[dict[str, Any]] = []
        self.closed = False
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self) -> None:
        while True:
            line = self.proc.stdout.readline()
            if not line:
                with self.msg_cond:
                    self.closed = True
                    self.msg_cond.notify_all()
                return
            try:
                msg = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                msg = {"_raw": line[:200].decode("utf-8", errors="replace")}
            with self.msg_cond:
                self.messages.append(msg)
                self.msg_cond.notify_all()

    def send(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self.send_lock:
            self.proc.stdin.write(line.encode("utf-8"))
            self.proc.stdin.flush()

    def send_raw(self, raw: bytes) -> None:
        with self.send_lock:
            self.proc.stdin.write(raw)
            self.proc.stdin.flush()

    def _pop_matching(self, predicate, timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        with self.msg_cond:
            while True:
                for i, msg in enumerate(self.messages):
                    if predicate(msg):
                        return self.messages.pop(i)
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.closed:
                    # 关闭后仍把已到达的缓冲消费完再放弃（predicate 不命中时退出）
                    return None
                self.msg_cond.wait(timeout=min(0.5, remaining))

    def recv_for_id(self, req_id: Any, timeout: float = 8.0) -> dict[str, Any] | None:
        return self._pop_matching(lambda m: m.get("id") == req_id, timeout)

    def recv_first(self, timeout: float, predicate=None) -> dict[str, Any] | None:
        pred = predicate or (lambda m: True)
        return self._pop_matching(pred, timeout)

    def request(self, req_id: Any, method: str, params: dict[str, Any] | None = None,
                timeout: float = 8.0) -> dict[str, Any] | None:
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method,
                   "params": params or {}})
        return self.recv_for_id(req_id, timeout)


def run_traces(server_cmd: list[str]) -> tuple[list[TraceResult], dict[str, Any]]:
    results: list[TraceResult] = []
    meta: dict[str, Any] = {"server_cmd": server_cmd}
    # 协议线格式为 UTF-8；显式强制子进程 UTF-8 IO，避免控制台代码页（GBK）污染
    server_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        server_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=server_env,
    )
    client = Client(proc)
    try:
        # 就绪标记为非 JSON 行：由读线程收入 messages，不影响按 id 匹配

        # T1 未初始化即调用 → not_initialized
        resp = client.request("t1", "ping")
        ok = bool(resp and resp.get("id") == "t1"
                  and resp.get("error", {}).get("code") == ERR_NOT_INITIALIZED["code"])
        results.append(TraceResult(
            "T1", "initialize 顺序强制：未初始化调用被拒绝", ok, True,
            f"响应: {json.dumps(resp, ensure_ascii=False)[:160]}", raw=resp or {}))

        # T2 initialize 握手
        resp = client.request("t2", "initialize", {
            "client_info": {"name": "spike-client", "version": "0.1"},
            "protocol_versions": [PROTOCOL_VERSION],
            "notification_preferences": ["item/delta"],
        })
        result = (resp or {}).get("result", {})
        ok = bool(resp and resp.get("id") == "t2"
                  and result.get("protocol_version") == PROTOCOL_VERSION
                  and "capabilities" in result
                  and result.get("notification_preferences") == ["item/delta"])
        results.append(TraceResult(
            "T2", "initialize 交换版本/能力/通知偏好", ok, True,
            f"protocol_version={result.get('protocol_version')}，"
            f"capabilities keys={sorted(result.get('capabilities', {}))}",
            raw=resp or {}))

        # T3 ping 往返 + id 原样回带
        resp = client.request("t3", "ping", {"nonce": 42})
        ok = bool(resp and resp.get("id") == "t3"
                  and resp.get("result", {}).get("echo", {}).get("nonce") == 42)
        results.append(TraceResult(
            "T3", "ping 往返与 request id 原样回带", ok, True,
            f"result={resp.get('result') if resp else None}", raw=resp or {}))

        # T4 未知方法 → 固定错误信封
        resp = client.request("t4", "no/such/method")
        err = (resp or {}).get("error", {})
        ok = bool(resp and resp.get("id") == "t4"
                  and err.get("code") == ERR_UNKNOWN_METHOD["code"]
                  and {"code", "message", "retryable", "details", "trace_id"} <= set(err))
        results.append(TraceResult(
            "T4", "未知方法 → 五字段错误信封", ok, True,
            f"error keys={sorted(err)}", raw=resp or {}))

        # T5 超长消息 → 拒绝且连接存活（错误信封 id=null，按错误码匹配）
        client.send_raw(b"x" * (MAX_LINE_BYTES + 1024) + b"\n")
        resp = client.recv_first(
            5.0, lambda m: m.get("error", {}).get("code") == ERR_OVERSIZE["code"])
        oversize_rejected = bool(resp and resp.get("error", {}).get("code")
                                 == ERR_OVERSIZE["code"])
        alive_resp = client.request("t5b", "ping")
        conn_alive = bool(alive_resp and alive_resp.get("id") == "t5b"
                          and "result" in alive_resp)
        results.append(TraceResult(
            "T5", "超长消息被拒且连接不中断", oversize_rejected and conn_alive, True,
            f"超长拒绝={oversize_rejected}，后续 ping 正常={conn_alive}",
            raw={"oversize": resp or {}, "followup": alive_resp or {}}))

        # T6 有界队列背压：洪泛慢方法，观察饱和拒绝。
        # 发送与接收必须并行：否则服务端响应填满 stdout 管道缓冲后双方死锁。
        flood_total = WORK_QUEUE_SIZE * 6

        def _flood() -> None:
            for i in range(flood_total):
                client.send({"jsonrpc": "2.0", "id": f"t6-{i}", "method": "spike/slow"})

        flood_thread = threading.Thread(target=_flood, daemon=True)
        flood_thread.start()
        overloaded = 0
        served = 0
        deadline = time.monotonic() + 20.0
        seen: set[str] = set()
        while time.monotonic() < deadline and (overloaded + served) < flood_total:
            resp = client.recv_first(
                2.0, lambda m: isinstance(m.get("id"), str)
                and m["id"].startswith("t6-") and m["id"] not in seen)
            if not resp:
                continue
            rid = resp.get("id")
            seen.add(rid)
            if resp.get("error", {}).get("code") == ERR_OVERLOADED["code"]:
                overloaded += 1
            elif "result" in resp:
                served += 1
        flood_thread.join(timeout=5.0)
        ok = overloaded > 0 and served > 0
        results.append(TraceResult(
            "T6", "有界队列背压：饱和时显式拒绝且不丢失正常服务", ok, True,
            f"正常处理={served}，过载拒绝={overloaded}（队列上限={WORK_QUEUE_SIZE}，"
            f"洪泛={flood_total}）",
            raw={"served": served, "overloaded": overloaded}))

        # T8 吞吐/时延基线（T7 之前，连接仍开放）
        n = 500
        latencies: list[float] = []
        for i in range(n):
            t0 = time.perf_counter()
            resp = client.request(f"t8-{i}", "ping")
            dt = time.perf_counter() - t0
            if resp and resp.get("id") == f"t8-{i}":
                latencies.append(dt)
        latencies.sort()
        p50 = latencies[len(latencies) // 2] if latencies else -1
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else -1
        meta["latency"] = {"n": len(latencies), "p50_ms": round(p50 * 1000, 3),
                           "p95_ms": round(p95 * 1000, 3)}
        results.append(TraceResult(
            "T8", "吞吐基线：500 次 ping 往返（仅本机管道参考值）",
            len(latencies) == n, True,
            f"完成={len(latencies)}/{n}，p50={p50 * 1000:.2f}ms，p95={p95 * 1000:.2f}ms",
            raw=meta["latency"]))

        # T7 管道关闭 → 干净退出
        client.proc.stdin.close()
        exit_code = proc.wait(timeout=10.0)
        results.append(TraceResult(
            "T7", "stdin EOF → 服务端干净退出（码 0）", exit_code == 0, True,
            f"exit_code={exit_code}", raw={"exit_code": exit_code}))
    finally:
        if proc.poll() is None:
            proc.kill()
    return results, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-T2/T6 stdio/JSONL transport spike")
    parser.add_argument("--json", default=None, help="结果 JSON 输出路径")
    parser.add_argument("--server-mode", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.server_mode:
        serve()
        return 0

    server_cmd = [sys.executable, sys.argv[0], "--server-mode"]
    try:
        results, meta = run_traces(server_cmd)
    except Exception as exc:  # noqa: BLE001 - spike：环境异常以退出码 2 区分
        print(f"ENV-ERROR: {type(exc).__name__}: {exc}")
        return 2

    for r in results:
        status = "PASS" if r.passed == r.expected else "FAIL"
        print(f"[{status}] {r.proof} {r.description}\n       {r.detail}")

    payload = {
        "spike": "s1-transport-stdio-jsonl",
        "protocol_version": PROTOCOL_VERSION,
        "max_line_bytes": MAX_LINE_BYTES,
        "work_queue_size": WORK_QUEUE_SIZE,
        "python": sys.version,
        "results": [vars(r) for r in results],
        "meta": meta,
        "all_consistent": all(r.passed == r.expected for r in results),
    }
    if args.json:
        from pathlib import Path

        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 证据已写入: {args.json}")
    return 0 if payload["all_consistent"] else 1


if __name__ == "__main__":
    sys.exit(main())
