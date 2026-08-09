#!/usr/bin/env python3
"""v0.5.0 Beta.1：安装版运行时可信工作流 smoke。

启动已构建的 PyInstaller sidecar（含 B0-B2 代码），用真实 LLM（Ollama）跑
Patch 与命令可信工作流，全部通过 API 验证并生成证据：

1. Patch 工作流：propose_patch 预览 → apply_patch_to_workspace 审批 →
   原子写入 → 回读验证（execution verified=True）；
2. 命令工作流：预授权 profile（python -c）→ 长命令 → run cancel →
   Job Object 进程树清理（无残留 python 子进程）；
3. 输出 dist/qa-evidence-0.5.0-beta.1.json。

Usage: uv run python scripts/v050_workflow_smoke.py
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from personal_assistant import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIDECAR = (
    PROJECT_ROOT
    / "apps"
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "personal-assistant-server-x86_64-pc-windows-msvc.exe"
)
EVIDENCE_PATH = PROJECT_ROOT / "dist" / f"qa-evidence-{__version__}.json"
STARTUP_TIMEOUT_S = 120
RUN_TIMEOUT_S = 240
POLL_INTERVAL_S = 2


class _EchoHandler(BaseHTTPRequestHandler):
    """loopback 测试服务：/echo 返回方法与 JSON body（HTTP 工作流 smoke 用）。"""

    protocol_version = "HTTP/1.1"

    def _reply(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._reply(json.dumps({"method": "GET", "path": self.path}).encode())

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw) if raw else {}
        self._reply(
            json.dumps({"method": "POST", "body": body, "auth": self.headers.get("X-Api-Key")}).encode()
        )

    def log_message(self, *args: Any) -> None:
        pass


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def kill_tree(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True
            )
        else:
            import signal as _sig

            os.killpg(os.getpgid(pid), _sig.SIGTERM)
    except Exception:  # noqa: BLE001
        pass


def read_dev_env() -> dict[str, str]:
    env_path = PROJECT_ROOT / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.startswith("PA_"):
            out[k] = v.strip()
    return out


class SidecarApi:
    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self.token = token

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self._request("POST", path, body)


def wait_for_run_terminal(api: SidecarApi, run_id: str, *, timeout: float) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = api.get(f"/agent-runs/{run_id}")
        status = run.get("status")
        if status in {"completed", "failed", "cancelled", "timed_out"}:
            return run
        time.sleep(POLL_INTERVAL_S)
    run = api.get(f"/agent-runs/{run_id}")
    events = api.get(f"/agent-runs/{run_id}/events")
    print(
        "[v050-smoke] DIAG run status:", run.get("status"),
        "steps:", [
            (s.get("kind"), s.get("status"), s.get("name"))
            for s in run.get("steps", [])[-6:]
        ],
        "last events:", [e["type"] for e in events.get("items", [])[-6:]],
        "error:", run.get("error_message"),
    )
    raise TimeoutError(f"run {run_id} 未在 {timeout}s 内到达终态")


def wait_for_approvals(api: SidecarApi, run_id: str, *, timeout: float) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        approvals = api.get(f"/agent-runs/{run_id}/approvals")
        pending = [a for a in approvals if a["status"] == "pending"]
        if pending:
            return approvals
        run = api.get(f"/agent-runs/{run_id}")
        if run.get("status") in {"completed", "failed", "cancelled"}:
            return approvals
        time.sleep(POLL_INTERVAL_S)
    run = api.get(f"/agent-runs/{run_id}")
    events = api.get(f"/agent-runs/{run_id}/events")
    print(
        "[v050-smoke] DIAG run status:", run.get("status"),
        "last events:", [e["type"] for e in events.get("items", [])[-6:]],
        "error:", run.get("error_message"),
    )
    raise TimeoutError(f"run {run_id} 未在 {timeout}s 内产生待审批项")


def approve_all(api: SidecarApi, run_id: str, approvals: list[dict]) -> None:
    for approval in approvals:
        if approval["status"] == "pending":
            api.post(
                f"/agent-runs/{run_id}/approvals/{approval['id']}/approve",
                None,
            )


def count_sleeping_python(needle: str) -> int:
    """统计命令行包含 needle 的 python 进程数（取消后应归零）。"""
    if os.name != "nt":
        return -1
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
             f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | Measure-Object | "
             f"Select-Object -ExpandProperty Count"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return int(result.stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        return -1


def main() -> int:
    if not SIDECAR.exists():
        print("[v050-smoke] SKIP: sidecar binary not found; run scripts/build-sidecar.bat")
        return 0

    evidence: dict = {
        "scenario": f"v{__version__} 安装版运行时可信工作流 smoke",
        "git_commit": _git_head(),
        "checks": [],
    }
    port = free_port()
    token = secrets.token_hex(32)
    dev_env = read_dev_env()
    started_at = time.time()
    run_suffix = secrets.token_hex(4)  # profile 名称随机化，避免测试库跨运行冲突

    # loopback HTTP 测试服务（HTTP 工作流场景）
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    http_port = http_server.server_address[1]
    threading.Thread(target=http_server.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as project_dir:
        project_dir_path = Path(project_dir)
        (project_dir_path / "test_sample.py").write_text(
            "def greeting():\n    return \"hello\"\n\n"
            "def test_greeting():\n    assert greeting() == \"hello\"\n",
            encoding="utf-8",
        )
        # 注意：慢测试文件不能匹配 pytest 收集模式（test_*），否则 run A 的
        # pytest 会被慢用例拖到超时；run B 的取消场景由 profile 命令直接 sleep。
        (project_dir_path / "slow_holder.py").write_text(
            "import time\n\ndef slow_helper():\n    time.sleep(30)\n    return True\n",
            encoding="utf-8",
        )
        # SQL 密码通道：测试库凭据与主库同用户（.env 的 PA_DB_URL 派生）
        import re as _re

        db_password = ""
        db_match = _re.search(r"://([^:]+):([^@]*)@", dev_env.get("PA_DB_URL", ""))
        if db_match:
            db_password = db_match.group(2)
        sql_secrets_json = json.dumps(
            {"secret://os-keyring/sql/beta2-sql/password": db_password}
        )
        env = {
            **os.environ,
            **dev_env,
            "PA_API_PORT": str(port),
            "PA_API_TOKEN": token,
            "PA_SKIP_MIGRATIONS": "1",
            "PA_DATA_DIR": data_dir,
            "PA_AGENT_RUNS_API_ENABLED": "true",
            "PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED": "true",
            "PA_AGENT_PATCH_WORKFLOW_ENABLED": "true",
            "PA_AGENT_COMMAND_WORKFLOW_ENABLED": "true",
            "PA_AGENT_HTTP_WORKFLOW_ENABLED": "true",
            "PA_AGENT_SQL_READONLY_WORKFLOW_ENABLED": "true",
            "PA_SQL_PROFILES_SECRETS_JSON": sql_secrets_json,
            "PA_CHAT_AGENT_RUNTIME_ENABLED": "false",
        }
        print(f"[v050-smoke] starting sidecar on port {port}...")
        proc = subprocess.Popen(
            [str(SIDECAR)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            api = SidecarApi(f"http://127.0.0.1:{port}", token)
            deadline = time.time() + STARTUP_TIMEOUT_S
            healthy = False
            while time.time() < deadline:
                try:
                    api.get("/health")
                    healthy = True
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(2)
            if not healthy:
                print("[v050-smoke] FAIL: sidecar /health 未就绪")
                return 1
            print("[v050-smoke] PASS: sidecar 启动")

            project = api.post(
                "/projects",
                {"name": "beta1-smoke", "root_path": str(project_dir_path)},
            )
            project_id = project["id"]
            evidence["project_id"] = project_id
            print(f"[v050-smoke] project {project_id} created")

            api.post(
                f"/projects/{project_id}/commands",
                {
                    "name": "py-sleep",
                    "command_json": {"args": ["python", "-c"]},
                    "kind": "custom",
                    "timeout_seconds": 120,
                },
            )
            print("[v050-smoke] command profile py-sleep created")

            # ---------- 场景 1：Patch + 命令工作流（真实 LLM） ----------
            print("[v050-smoke] run A: Patch 工作流...")
            run_a = api.post(
                "/agent-runs",
                {
                    "message": (
                        f"项目 ID 是 {project_id}，项目根目录下有文件 test_sample.py。"
                        "注意：propose_patch 只是预览、不会修改文件；只有调用 "
                        "apply_patch_to_workspace 才能实际写入文件。请严格执行："
                        "1) 用 propose_patch 预览（project_id={project_id}，"
                        "rel_path='test_sample.py'）；2) 必须调用 apply_patch_to_workspace "
                        "把 greeting 返回值从 \"hello\" 改为 \"hello beta1\""
                        "（project_id={project_id}，rel_path='test_sample.py'，"
                        "expected_old_sha256 用预览返回的 old_sha256）；"
                        "3) 用 run_whitelisted_command 运行 ['python', '-m', 'pytest', '-q']"
                        "（project_id={project_id}）。三步都必须完成。"
                    )
                },
            )
            run_a_id = run_a["id"]
            # 轮询循环：pending 审批即批准；到达终态即结束（多步骤审批逐步出现）
            deadline = time.time() + RUN_TIMEOUT_S
            final_a = None
            while time.time() < deadline:
                run = api.get(f"/agent-runs/{run_a_id}")
                if run.get("status") in {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}:
                    final_a = run
                    break
                approvals_a = api.get(f"/agent-runs/{run_a_id}/approvals")
                pending = [a for a in approvals_a if a["status"] == "pending"]
                if pending:
                    approve_all(api, run_a_id, approvals_a)
                time.sleep(POLL_INTERVAL_S)
            if final_a is None:
                final_a = wait_for_run_terminal(api, run_a_id, timeout=30)
            # LLM 行为波动容忍：patch/command 各自在会话内至少成功一次即可
            # （每次失败用新 run 重试，最多 3 轮；能力可用性按累计成功判定）。
            any_patch_ok = False
            any_command_ok = False
            retries = 0
            while retries < 3:
                executions_a = api.get(f"/agent-runs/{run_a_id}/executions")
                patch_exec = next(
                    (e for e in executions_a if e["tool_name"] == "apply_patch_to_workspace"),
                    None,
                )
                command_exec_a = next(
                    (e for e in executions_a if e["tool_name"] == "run_whitelisted_command"),
                    None,
                )
                file_text = (project_dir_path / "test_sample.py").read_text(
                    encoding="utf-8"
                )
                patch_ok = bool(
                    patch_exec
                    and patch_exec["status"] == "succeeded"
                    and (patch_exec.get("output") or {}).get("verified") is True
                    and "hello beta1" in file_text
                )
                command_ok = bool(
                    command_exec_a
                    and command_exec_a["status"] == "succeeded"
                    and (command_exec_a.get("output") or {}).get("succeeded") is True
                )
                any_patch_ok = any_patch_ok or patch_ok
                any_command_ok = any_command_ok or command_ok
                if any_patch_ok and any_command_ok:
                    break
                retries += 1
                print(
                    f"[v050-smoke] run A 未全部成功（patch累计={any_patch_ok} "
                    f"command累计={any_command_ok}），重试 {retries}/3"
                )
                # 重置项目文件后重试
                (project_dir_path / "test_sample.py").write_text(
                    "def greeting():\n    return \"hello\"\n\n"
                    "def test_greeting():\n    assert greeting() == \"hello\"\n",
                    encoding="utf-8",
                )
                run_a = api.post(
                    "/agent-runs",
                    {
                        "message": (
                            f"项目 ID 是 {project_id}，项目根目录下有文件 test_sample.py。"
                            "注意：propose_patch 只是预览、不会修改文件；只有调用 "
                            "apply_patch_to_workspace 才能实际写入文件。请严格执行："
                            "1) 用 propose_patch 预览（project_id={project_id}，"
                            "rel_path='test_sample.py'）；2) 必须调用 apply_patch_to_workspace "
                            "把 greeting 返回值从 \"hello\" 改为 \"hello beta1\""
                            "（project_id={project_id}，rel_path='test_sample.py'，"
                            "expected_old_sha256 用预览返回的 old_sha256）；"
                            "3) 用 run_whitelisted_command 运行 ['python', '-m', 'pytest', '-q']"
                            "（project_id={project_id}）。三步都必须完成。"
                        )
                    },
                )
                run_a_id = run_a["id"]
                deadline = time.time() + RUN_TIMEOUT_S
                final_a = None
                while time.time() < deadline:
                    run = api.get(f"/agent-runs/{run_a_id}")
                    if run.get("status") in {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}:
                        final_a = run
                        break
                    approvals_a = api.get(f"/agent-runs/{run_a_id}/approvals")
                    pending = [a for a in approvals_a if a["status"] == "pending"]
                    if pending:
                        approve_all(api, run_a_id, approvals_a)
                    time.sleep(POLL_INTERVAL_S)
                if final_a is None:
                    final_a = wait_for_run_terminal(api, run_a_id, timeout=30)
            executions_a = api.get(f"/agent-runs/{run_a_id}/executions")
            project_out = api.get(f"/projects/{project_id}")
            evidence["project_root_seen_by_sidecar"] = project_out.get("root_path")
            evidence["run_a"] = {
                "status": final_a.get("status"),
                "error": final_a.get("error_message"),
                "retries": retries,
                "executions": [
                    {
                        "tool": e["tool_name"],
                        "status": e["status"],
                        "error": e["error_message"],
                        "verified": (e.get("output") or {}).get("verified"),
                        "rel_path": (e.get("output") or {}).get("rel_path"),
                    }
                    for e in executions_a
                ],
            }
            file_text = (project_dir_path / "test_sample.py").read_text(
                encoding="utf-8"
            )
            evidence["checks"].append(
                {
                    "name": "patch_workflow_atomic_write_verified",
                    "passed": any_patch_ok,
                    "detail": (
                        "apply_patch_to_workspace succeeded + verified=True + 磁盘内容含新值"
                        if any_patch_ok
                        else f"最后轮 patch_exec={patch_exec} file_has_new={('hello beta1' in file_text)}"
                    ),
                }
            )
            evidence["checks"].append(
                {
                    "name": "command_workflow_pytest_succeeded",
                    "passed": any_command_ok,
                    "detail": f"最后轮 command_exec={command_exec_a}",
                }
            )
            print(
                f"[v050-smoke] run A final={final_a.get('status')} "
                f"patch累计={any_patch_ok} command累计={any_command_ok} retries={retries}"
            )

            # ---------- 场景 2：命令取消 + 进程树清理 ----------
            print("[v050-smoke] run B: 命令取消 + 进程树清理...")
            needle = "beta1-sleep-marker"
            run_b = api.post(
                "/agent-runs",
                {
                    "message": (
                        f"项目 ID 是 {project_id}。请使用 run_whitelisted_command 运行命令 "
                        f"['python', '-c', 'import time; time.sleep(30); "
                        f"print(\"{needle}\")']（project_id 必须为上面的真实值），"
                        "不要做其他任何事。"
                    )
                },
            )
            run_b_id = run_b["id"]
            approvals_b = wait_for_approvals(api, run_b_id, timeout=RUN_TIMEOUT_S)
            approve_all(api, run_b_id, approvals_b)

            # 等待命令 execution 进入 running 后取消
            deadline = time.time() + RUN_TIMEOUT_S
            cancelled: dict | None = None
            while time.time() < deadline:
                executions_b = api.get(f"/agent-runs/{run_b_id}/executions")
                running = [
                    e for e in executions_b if e["status"] == "running"
                ]
                if running:
                    api.post(f"/agent-runs/{run_b_id}/cancel", None)
                    cancelled = wait_for_run_terminal(
                        api, run_b_id, timeout=60
                    )
                    break
                if api.get(f"/agent-runs/{run_b_id}").get("status") in {
                    "completed", "failed",
                }:
                    break
                time.sleep(POLL_INTERVAL_S)
            time.sleep(2)
            leftovers = count_sleeping_python(needle)
            cancel_ok = bool(
                cancelled
                and cancelled.get("status") == "cancelled"
                and leftovers == 0
            )
            evidence["run_b"] = {
                "status": cancelled.get("status") if cancelled else None,
                "sleeping_processes_after_cancel": leftovers,
            }
            evidence["checks"].append(
                {
                    "name": "command_cancel_process_tree_cleanup",
                    "passed": cancel_ok,
                    "detail": (
                        f"run status={cancelled.get('status') if cancelled else None} "
                        f"sleeping python after cancel={leftovers}"
                    ),
                }
            )
            print(
                f"[v050-smoke] run B cancelled={cancelled.get('status') if cancelled else None} "
                f"leftovers={leftovers}"
            )

            # ---------- 场景 3：只读 SQL 工作流（真实 LLM） ----------
            print("[v050-smoke] run C: 只读 SQL 工作流...")
            # name 固定（无后缀）：keyring 通道引用与 profile 名一致；
            # 先清理测试库同名残留避免 409。
            for leftover in api.get("/sql-profiles") or []:
                if leftover["name"] == "beta2-sql":
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/sql-profiles/{leftover['id']}",
                        method="DELETE",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    try:
                        urllib.request.urlopen(req, timeout=15).read()
                    except urllib.error.HTTPError:
                        pass
            sql_profile = api.post(
                "/sql-profiles",
                {
                    "name": "beta2-sql",
                    "dialect": "mysql",
                    "host": "127.0.0.1",
                    "port": 3306,
                    "database": "personal_assistant_test",
                    "username": "root",
                    "max_rows": 5,
                    "max_bytes": 1048576,
                    "timeout_ms": 15000,
                    "enabled": True,
                },
            )
            sql_profile_id = sql_profile["id"]
            run_c = api.post(
                "/agent-runs",
                {
                    "message": (
                        f"SQL profile ID 是 {sql_profile_id}。请使用 query_readonly_sql "
                        f"查询 'SELECT COUNT(*) AS total FROM sessions'"
                        f"（profile_id 必须为上面的真实值），然后简要报告结果行数与结论，"
                        "不要做其他任何事。"
                    )
                },
            )
            run_c_id = run_c["id"]
            approvals_c = wait_for_approvals(api, run_c_id, timeout=RUN_TIMEOUT_S)
            approve_all(api, run_c_id, approvals_c)
            final_c = wait_for_run_terminal(api, run_c_id, timeout=RUN_TIMEOUT_S)
            executions_c = api.get(f"/agent-runs/{run_c_id}/executions")
            sql_exec = next(
                (e for e in executions_c if e["tool_name"] == "query_readonly_sql"),
                None,
            )
            sql_ok = bool(
                sql_exec
                and sql_exec["status"] == "succeeded"
                and (sql_exec.get("output") or {}).get("read_only_confirmed") is True
            )
            evidence["run_c"] = {
                "status": final_c.get("status"),
                "sql_exec": {
                    "status": sql_exec["status"] if sql_exec else None,
                    "error": sql_exec.get("error_message") if sql_exec else None,
                    "read_only": (sql_exec.get("output") or {}).get("read_only_confirmed"),
                    "rows": (sql_exec.get("output") or {}).get("rows"),
                    "statement": (sql_exec.get("output") or {}).get("statement_type"),
                },
            }
            evidence["checks"].append(
                {
                    "name": "sql_readonly_workflow_query_succeeded",
                    "passed": sql_ok,
                    "detail": (
                        f"run={final_c.get('status')} sql_exec={evidence['run_c']['sql_exec']}"
                    ),
                }
            )
            print(
                f"[v050-smoke] run C final={final_c.get('status')} "
                f"sql_ok={sql_ok} rows={evidence['run_c']['sql_exec'].get('rows')}"
            )

            # ---------- 场景 4：HTTP/API 工作流（真实 LLM + loopback） ----------
            print("[v050-smoke] run D: HTTP/API 工作流...")
            http_profile = api.post(
                "/http-profiles",
                {
                    "name": f"beta2-http-{run_suffix}",
                    "scheme": "http",
                    "host": "127.0.0.1",
                    "port": http_port,
                    "path_prefix": "/",
                    "allowed_methods": ["GET", "POST"],
                    "timeout_ms": 5000,
                    "max_response_bytes": 262144,
                    "allow_insecure_local": True,
                    "allow_private_network": True,
                    "enabled": True,
                },
            )
            http_profile_id = http_profile["id"]
            run_d = api.post(
                "/agent-runs",
                {
                    "message": (
                        f"HTTP profile ID 是 {http_profile_id}。请使用 call_allowlisted_api "
                        f"调用 GET 路径 '/echo'（profile_id 必须为上面的真实值，"
                        "method 为 GET，path 为 /echo），然后简要报告响应状态码与 body，"
                        "不要做其他任何事。"
                    )
                },
            )
            run_d_id = run_d["id"]
            approvals_d = wait_for_approvals(api, run_d_id, timeout=RUN_TIMEOUT_S)
            approve_all(api, run_d_id, approvals_d)
            final_d = wait_for_run_terminal(api, run_d_id, timeout=RUN_TIMEOUT_S)
            executions_d = api.get(f"/agent-runs/{run_d_id}/executions")
            http_exec = next(
                (e for e in executions_d if e["tool_name"] == "call_allowlisted_api"),
                None,
            )
            http_ok = bool(
                http_exec
                and http_exec["status"] == "succeeded"
                and (http_exec.get("output") or {}).get("status_code") == 200
            )
            evidence["run_d"] = {
                "status": final_d.get("status"),
                "http_exec": {
                    "status": http_exec["status"] if http_exec else None,
                    "status_code": (http_exec.get("output") or {}).get("status_code"),
                    "body": (http_exec.get("output") or {}).get("body"),
                },
            }
            evidence["checks"].append(
                {
                    "name": "http_workflow_get_succeeded",
                    "passed": http_ok,
                    "detail": (
                        f"run={final_d.get('status')} http_exec={evidence['run_d']['http_exec']}"
                    ),
                }
            )
            print(
                f"[v050-smoke] run D final={final_d.get('status')} "
                f"http_ok={http_ok} status={evidence['run_d']['http_exec'].get('status_code')}"
            )
        finally:
            kill_tree(proc.pid)
            http_server.shutdown()

    evidence["duration_seconds"] = round(time.time() - started_at, 1)
    evidence["passed"] = all(check["passed"] for check in evidence["checks"])
    EVIDENCE_PATH.parent.mkdir(exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[v050-smoke] evidence: {EVIDENCE_PATH}")
    print(f"[v050-smoke] {'PASS' if evidence['passed'] else 'FAIL'}: "
          f"{sum(1 for c in evidence['checks'] if c['passed'])}/"
          f"{len(evidence['checks'])} checks")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
