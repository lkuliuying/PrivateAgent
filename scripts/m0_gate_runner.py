#!/usr/bin/env python3
"""M0 门槛观察采集器（0.3.0，证据可信版）。

对 sidecar 二进制（默认工作区构建；可用 --sidecar 指定官方发布版）执行
可自动化的 M0 观察项，并记录二进制身份（SHA256 / Git 提交）使证据可追溯：

- 有效 Agent run：每 cycle 驱动真实 Ollama run，按
  ``completed AND output.validation_passed`` 计数（见 m0_gate_common.py）；
- 正常退出写 ended_at：cycle 结束经 ``POST /internal/shutdown``（0.2.1 旧版
  回退 CTRL_BREAK）优雅停机，校验窗口 ``ended_at >= started_at``；
- 用户取消（--cancel-one）、审批暂停/恢复（--approval-one，read_file 为
  CONFIRM 工具）、异常退出与 reconcile（--crash-one）、owner lock 竞争
  （--lock-contention）、Ollama 中断/恢复（--ollama-outage）；
- 每 cycle 增量写报告（中途失败不丢已有结果），并输出 gate 判定。

配置模式（显式选择，不再隐式注入项目 .env）：
- ``--config installed``：只使用安装版配置（%APPDATA%/.env），DB 连接串
  由 ``--db-url`` 显式提供（安装版密码在 Windows 凭据库，直接 spawn 无法解析）；
- ``--config project-env``（默认，开发便利）：注入项目根 .env 的 PA_* 变量，
  并在报告 origin 中标记。

前置：桌面应用必须已退出（owner lock 单持有者）；Ollama 正常运行。
记录不含聊天正文与 DB 连接串；连接串不写入报告。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import m0_agent_run_driver as driver  # noqa: E402  (scripts/ 同目录)
from m0_gate_common import (  # noqa: E402
    count_valid_runs,
    gate_verdict,
    latency_percentiles,
    observation_days,
    runs_by_status,
)
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings  # noqa: E402

DEFAULT_SIDECAR = (
    PROJECT_ROOT
    / "apps"
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "personal-assistant-server-x86_64-pc-windows-msvc.exe"
)
HEALTH_TIMEOUT_S = 300
SHUTDOWN_WAIT_S = 10
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
BINARY_IDENTITY_REPORT_KEY = "binary_identity"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
        cwd=PROJECT_ROOT,
    )
    return result.stdout.strip() or "unknown"


def _read_project_env() -> dict[str, str]:
    """项目 .env 的 PA_*（--config project-env 用；installed 模式不调用）。"""
    env_path = PROJECT_ROOT / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.startswith("PA_"):
            out[key] = value.strip()
    return out


def _health_ok(base: str, token: str) -> bool:
    req = urllib.request.Request(
        f"{base}/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _post_shutdown(base: str, token: str) -> bool:
    req = urllib.request.Request(
        f"{base}/internal/shutdown",
        data=b"",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200 and json.loads(r.read() or b"{}").get(
                "accepted"
            ) is True
    except Exception:  # noqa: BLE001
        return False


def _ollama_has_active_models() -> bool:
    """/api/ps 有常驻模型时拒绝 --ollama-outage，避免影响其他使用者。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as r:
            payload = json.loads(r.read() or b"{}")
        return bool(payload.get("models"))
    except Exception:  # noqa: BLE001
        return False


def _stop_ollama() -> bool:
    return (
        subprocess.run(
            ["taskkill", "/F", "/IM", "ollama.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _start_ollama() -> None:
    candidates = [
        [
            str(
                Path.home()
                / "AppData"
                / "Local"
                / "Programs"
                / "Ollama"
                / "ollama.exe"
            ),
            "serve",
        ],
        ["ollama", "serve"],
    ]
    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED_PROCESS,
            )
            return
        except OSError:
            continue
    raise SystemExit("[m0-runner] 无法启动 Ollama（未找到 ollama.exe，请手动启动）")


async def _ollama_up(timeout_s: float = 60) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:11434/api/tags", timeout=5
            ) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(2)
    return False


class SpawnedSidecar:
    def __init__(self, proc: subprocess.Popen, base: str, token: str) -> None:
        self.proc = proc
        self.base = base
        self.token = token


def _spawn_sidecar(
    sidecar: Path, config_mode: str, db_url: str | None
) -> SpawnedSidecar:
    port = _free_port()
    token = secrets.token_hex(32)
    env = {
        **os.environ,
        "PA_API_PORT": str(port),
        "PA_API_TOKEN": token,
        # 主库已在 head（0021）；跳过迁移避免并发迁移写入。
        "PA_SKIP_MIGRATIONS": "1",
    }
    if config_mode == "project-env":
        env.update(_read_project_env())
    elif db_url:
        # installed：安装版 %APPDATA%/.env 的 DB 密码在 Windows 凭据库
        # （PA_DB_SECRET_REF），直接 spawn 无法解析，需显式连接串。
        env["PA_DB_URL"] = db_url
    proc = subprocess.Popen(
        [str(sidecar)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # 独立进程组：0.2.1 二进制无 /internal/shutdown 时用 CTRL_BREAK 回退
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )
    return SpawnedSidecar(proc, f"http://127.0.0.1:{port}", token)


async def _wait_health(
    sidecar: SpawnedSidecar, timeout_s: float = HEALTH_TIMEOUT_S
) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if sidecar.proc.poll() is not None:
            return False
        if _health_ok(sidecar.base, sidecar.token):
            return True
        await asyncio.sleep(2)
    return False


async def _graceful_stop(sidecar: SpawnedSidecar) -> dict[str, object]:
    """优先 POST /internal/shutdown，0.2.1 构建回退 CTRL_BREAK；超时强杀。"""
    outcome: dict[str, object] = {}
    graceful = _post_shutdown(sidecar.base, sidecar.token)
    if not graceful:
        try:
            os.kill(sidecar.proc.pid, signal.CTRL_BREAK_EVENT)
            graceful = "ctrl_break"
        except OSError:
            graceful = False
    outcome["graceful_shutdown"] = graceful
    try:
        sidecar.proc.wait(timeout=SHUTDOWN_WAIT_S)
        outcome["exited"] = True
    except subprocess.TimeoutExpired:
        outcome["exited"] = False
        outcome["force_killed"] = True
        _kill_tree(sidecar.proc.pid)
        sidecar.proc.wait(timeout=5)
    return outcome


async def _windows_started_since(db_engine, since: datetime) -> list[str]:
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT DISTINCT scope_key FROM compatibility_telemetry "
                    "WHERE started_at >= :since"
                ),
                {"since": since.replace(tzinfo=None)},
            )
        ).scalars().all()
        return list(rows)


async def _windows_status(db_engine, scope_keys: list[str]) -> dict[str, object]:
    """返回 {closed, open, negative, stale_open}；stale 用宽限期 60 分钟。"""
    if not scope_keys:
        return {"closed": 0, "open": 0, "negative": 0, "stale_open": 0}
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT scope_key, MIN(started_at), MAX(ended_at) "
                    "FROM compatibility_telemetry "
                    "WHERE scope_key IN :keys GROUP BY scope_key"
                ),
                {"keys": scope_keys},
            )
        ).all()
        closed = sum(1 for _, _, ended in rows if ended is not None)
        open_keys = [key for key, _, ended in rows if ended is None]
        negative = await db.scalar(
            text(
                "SELECT COUNT(DISTINCT scope_key) FROM compatibility_telemetry "
                "WHERE scope_key IN :keys AND ended_at IS NOT NULL "
                "AND ended_at < started_at"
            ),
            {"keys": scope_keys},
        )
        stale = 0
        for key in open_keys:
            started = next(
                (started for k, started, _ in rows if k == key), None
            )
            if started is not None and (
                datetime.now(timezone.utc).replace(tzinfo=None) - started
            ).total_seconds() > 3600:
                stale += 1
        return {"closed": closed, "open": len(open_keys), "negative": int(negative or 0), "stale_open": stale}


async def _drive_batch(
    base: str,
    token: str,
    count: int,
    knowledge: float,
    *,
    cancel_one: bool = False,
    approval_one: bool = False,
) -> list[dict]:
    """复用 m0_agent_run_driver 的 run 驱动与取消逻辑；记录 validation_passed。"""
    results: list[dict] = []
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}, timeout=60
    ) as client:
        session = await client.post(f"{base}/sessions")
        session.raise_for_status()
        session_id = session.json()["id"]
        knowledge_target = max(0, min(count, int(count * knowledge)))
        kb_indexes = {
            i
            for i in range(count)
            if (i + 1) * knowledge_target // max(1, count)
            != i * knowledge_target // max(1, count)
        }
        cancel_done = not cancel_one
        approval_done = not approval_one
        for index in range(count):
            use_kb = index in kb_indexes
            pool = [p for p in driver.PROMPT_POOL if p["knowledge_base"] == use_kb]
            prompt = pool[index % len(pool)]
            if not approval_done and index == count - 1:
                prompt = {
                    "id": "approval:01",
                    "knowledge_base": False,
                    "text": "请用 read_file 工具读取项目 README.md 的第一段内容，"
                    "并简要说明文件用途。",
                }
            run = await driver._run_one(client, base, prompt, session_id)
            if run.get("status") == "owner_unavailable":
                results.append(run)
                break
            if not cancel_done and run.get("status") in {"running", "waiting_approval"}:
                run = await driver._cancel_one(client, base, run)
                cancel_done = True
            if not approval_done:
                approval_done = True  # 仅尝试一次
                if run.get("id"):
                    approval = await _approve_one(client, base, run["id"])
                    if approval is not None:
                        results.append(approval)
                        continue
            terminal = await driver._wait_for_terminal(client, base, run["id"])
            terminal["prompt_id"] = run["prompt_id"]
            terminal["knowledge_base"] = run["knowledge_base"]
            terminal["cancel_note"] = run.get("cancel_note")
            events = await driver._events_if_available(client, base, run["id"])
            terminal["validation_passed"] = any(
                e.get("type") == "output.validation_passed" for e in events
            )
            results.append(terminal)
            print(
                f"[m0-runner] #{index + 1} {run['prompt_id']} "
                f"status={terminal['status']} "
                f"valid={terminal['validation_passed']} "
                f"tokens={terminal.get('input_tokens')}/{terminal.get('output_tokens')}"
            )
            if run.get("status") == "owner_unavailable":
                break
        return results


async def _approve_one(
    client: httpx.AsyncClient, base: str, run_id: str
) -> dict | None:
    """等待 run 进入 waiting_approval，批准后恢复并等待完成。"""
    for _ in range(120):
        body = (await client.get(f"{base}/agent-runs/{run_id}")).json()
        if body.get("status") in {"waiting_approval", "completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(1)
    if body.get("status") != "waiting_approval":
        return {
            "prompt_id": "approval:01",
            "status": "approval_not_triggered",
            "run_status": body.get("status"),
        }
    approvals = (await client.get(f"{base}/agent-runs/{run_id}/approvals")).json()
    pending = [a for a in approvals if a.get("status") == "pending"]
    if not pending:
        return {
            "prompt_id": "approval:01",
            "status": "approval_missing_pending",
        }
    approval = pending[0]
    approved = await client.post(
        f"{base}/agent-runs/{run_id}/approvals/{approval['id']}/approve"
    )
    if approved.status_code not in {200, 202}:
        return {
            "prompt_id": "approval:01",
            "status": "approve_rejected",
            "http": approved.status_code,
        }
    terminal = await driver._wait_for_terminal(client, base, run_id)
    terminal["prompt_id"] = "approval:01"
    events = await driver._events_if_available(client, base, run_id)
    terminal["validation_passed"] = any(
        e.get("type") == "output.validation_passed" for e in events
    )
    terminal["approval_id"] = approval["id"]
    terminal["approval_sample"] = True
    return terminal


async def _reconcile_stale(db_engine, grace_seconds: int = 7_200) -> int:
    """直接执行与 sidecar 启动相同的 reconcile 逻辑（DB 层验证）。"""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as db:
        await db.execute(
            text(
                "UPDATE compatibility_telemetry SET ended_at = UTC_TIMESTAMP(3) "
                "WHERE ended_at IS NULL AND started_at < "
                "UTC_TIMESTAMP(3) - INTERVAL :grace SECOND"
            ),
            {"grace": grace_seconds},
        )
        await db.commit()
        rows = await db.execute(
            text(
                "SELECT COUNT(DISTINCT scope_key) FROM compatibility_telemetry "
                "WHERE ended_at IS NOT NULL AND ended_at >= started_at "
                "AND ended_at > UTC_TIMESTAMP(3) - INTERVAL 120 SECOND"
            )
        )
        return int(rows.scalar() or 0)


async def _lock_contention_sample(sidecar: Path, config_mode: str, db_url: str | None) -> dict:
    """第二个 sidecar 尝试获取 owner lock：必须拒绝启动（无双 coordinator）。"""
    second = _spawn_sidecar(sidecar, config_mode, db_url)
    try:
        await asyncio.sleep(20)
        exited = second.proc.poll() is not None
        health = _health_ok(second.base, second.token) if not exited else False
        return {
            "second_sidecar_exited": exited,
            "second_sidecar_health": health,
            "no_double_coordinator": exited and not health,
        }
    finally:
        if second.proc.poll() is None:
            _kill_tree(second.proc.pid)


def _write_incremental(
    out: Path, report: dict[str, object]
) -> None:
    """每个 cycle 结束后增量写报告（不覆盖已有文件）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--runs-per-cycle", type=int, default=15)
    parser.add_argument("--knowledge", type=float, default=0.15)
    parser.add_argument("--cancel-one", action="store_true")
    parser.add_argument("--approval-one", action="store_true")
    parser.add_argument("--crash-one", action="store_true")
    parser.add_argument("--lock-contention", action="store_true")
    parser.add_argument("--ollama-outage", action="store_true")
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
    parser.add_argument("--expected-sha256", default=None, help="sidecar 二进制 SHA256 校验")
    parser.add_argument("--label", default=None, help="构建标识（如 v0.2.1-official）")
    parser.add_argument(
        "--config", choices=["installed", "project-env"], default="project-env"
    )
    parser.add_argument("--db-url", default=None, help="installed 模式显式 DB 连接串")
    parser.add_argument("--out", type=Path, required=True, help="报告 JSON 输出路径")
    args = parser.parse_args()

    if args.config == "installed" and not args.db_url:
        raise SystemExit(
            "[m0-runner] --config installed 需要 --db-url"
            "（安装版 DB 密码在 Windows 凭据库，直连需显式连接串；不会写入报告）"
        )
    sidecar = args.sidecar.resolve()
    if not sidecar.exists():
        raise SystemExit(f"[m0-runner] sidecar 不存在：{sidecar}")
    sha = _sha256(sidecar)
    if args.expected_sha256 and sha != args.expected_sha256.lower():
        raise SystemExit(
            f"[m0-runner] sidecar SHA256 不匹配：期望 "
            f"{args.expected_sha256.lower()} 实际 {sha}"
        )

    if args.ollama_outage:
        if _ollama_has_active_models():
            raise SystemExit(
                "[m0-runner] Ollama 有常驻模型（/api/ps 非空），"
                "--ollama-outage 会中断其他使用方，已拒绝执行；"
                "请确认没有其他程序使用 Ollama 后重试"
            )
        if not await _ollama_up(10):
            raise SystemExit("[m0-runner] Ollama 不可达，请先启动 Ollama")

    # owner lock 单持有者（PyInstaller 内层 python 与 bootloader 同名）
    proc_check = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process -Name 'personal-assistant-server*' -ErrorAction "
            "SilentlyContinue | Select-Object -ExpandProperty Id",
        ],
        capture_output=True, text=True, check=False,
    )
    if proc_check.stdout.strip():
        raise SystemExit(
            "[m0-runner] 检测到 sidecar 已在运行（桌面应用可能开着）；"
            "M0 采集需要独占 owner lock，请先退出桌面应用"
        )

    started_at = datetime.now(timezone.utc)
    engine = create_async_engine(settings.db_url, pool_pre_ping=True)
    cycles: list[dict] = []
    all_runs: list[dict] = []
    outage_record: dict | None = None
    crash_record: dict | None = None
    lock_record: dict | None = None

    report_base: dict[str, object] = {
        "generated_at": started_at.isoformat(),
        BINARY_IDENTITY_REPORT_KEY: {
            "sidecar": str(sidecar),
            "sha256": sha,
            "expected_sha256": args.expected_sha256,
            "label": args.label,
            "git_commit": _git_head(),
            "config_mode": args.config,
            "config_origin": "installed(%APPDATA%/.env)" if args.config == "installed" else "project-env(.env)",
        },
        "started_at": started_at.isoformat(),
    }
    _write_incremental(args.out, report_base)

    try:
        if args.ollama_outage:
            if not _stop_ollama():
                print("[m0-runner] 警告：ollama.exe 未找到/已停止，继续中断观察", file=sys.stderr)
            outage_record = {"phase": "stopping"}
            print("[m0-runner] Ollama 已停止（中断观察）")
            await asyncio.sleep(3)

        for cycle_index in range(args.cycles):
            cycle_start = datetime.now(timezone.utc)
            crash_this = args.crash_one and cycle_index == args.cycles - 1
            print(f"\n[m0-runner] === cycle {cycle_index + 1}/{args.cycles} ==={ ' (crash)' if crash_this else ''}")
            sidecar_inst = _spawn_sidecar(sidecar, args.config, args.db_url)
            cycle: dict[str, object] = {
                "spawned_pid": sidecar_inst.proc.pid,
                "started_at": cycle_start.isoformat(),
                "crash_cycle": crash_this,
            }
            try:
                if not await _wait_health(sidecar_inst):
                    cycle["error"] = "sidecar /health 未就绪"
                    _kill_tree(sidecar_inst.proc.pid)
                    cycles.append(cycle)
                    continue
                if outage_record is not None and outage_record.get("phase") == "stopping":
                    fail_run = await _drive_batch(
                        sidecar_inst.base, sidecar_inst.token, 1, 0.0
                    )
                    outage_record["failed_run"] = fail_run
                    print(f"[m0-runner] 中断期 run: status={fail_run[0].get('status') if fail_run else 'n/a'}")
                    _start_ollama()
                    if not await _ollama_up(90):
                        outage_record["phase"] = "recovery_failed"
                        cycle["error"] = "Ollama 恢复失败，中止后续批次"
                        cycles.append(cycle)
                        await _graceful_stop(sidecar_inst)
                        continue
                    outage_record["phase"] = "recovered"
                    outage_record["recovered"] = True
                    print("[m0-runner] Ollama 已恢复")
                    recovery_runs = await _drive_batch(
                        sidecar_inst.base, sidecar_inst.token, 2, args.knowledge
                    )
                    outage_record["recovery_runs"] = recovery_runs
                    all_runs.extend(recovery_runs)

                rec_runs = await _drive_batch(
                    sidecar_inst.base,
                    sidecar_inst.token,
                    args.runs_per_cycle,
                    args.knowledge,
                    cancel_one=args.cancel_one and cycle_index == 0,
                    approval_one=args.approval_one and cycle_index == 0,
                )
                all_runs.extend(rec_runs)
                cycle["runs_recorded"] = len(rec_runs)

                if crash_this:
                    # 异常退出样本：强杀，随后验证 reconcile 能回收窗口
                    _kill_tree(sidecar_inst.proc.pid)
                    sidecar_inst.proc.wait(timeout=5)
                    cycle["graceful_shutdown"] = False
                    cycle["force_killed"] = True
                    crash_record = {
                        "crash_cycle_index": cycle_index,
                        "force_killed": True,
                    }
                else:
                    cycle.update(await _graceful_stop(sidecar_inst))

                window_keys = await _windows_started_since(engine, cycle_start)
                status = await _windows_status(engine, window_keys)
                cycle["window_keys"] = len(window_keys)
                cycle.update(status)
                cycle["ended_at_valid"] = (
                    len(window_keys) > 0
                    and status["closed"] == len(window_keys)
                    and status["negative"] == 0
                )
                print(
                    f"[m0-runner] cycle {cycle_index + 1} 完成: "
                    f"graceful={cycle.get('graceful_shutdown')} "
                    f"exited={cycle.get('exited')} windows={cycle['window_keys']} "
                    f"closed={status['closed']} negative={status['negative']}"
                )
                if crash_this:
                    # 下次"启动"的 reconcile：直接执行相同 DB 逻辑并验证
                    reconciled = await _reconcile_stale(engine)
                    after = await _windows_status(engine, window_keys)
                    crash_record["reconciled_windows"] = reconciled
                    crash_record["windows_closed_after_reconcile"] = after["closed"]
                    crash_record["reconcile_verified"] = (
                        after["closed"] == len(window_keys)
                    )
                    print(
                        f"[m0-runner] crash-reconcile: closed "
                        f"{after['closed']}/{len(window_keys)}"
                    )
            finally:
                if sidecar_inst.proc.poll() is None:
                    _kill_tree(sidecar_inst.proc.pid)
            cycles.append(cycle)

            if args.lock_contention and cycle_index == 0:
                lock_record = await _lock_contention_sample(sidecar, args.config, args.db_url)
                print(
                    f"[m0-runner] lock contention: {lock_record}"
                )

            summary = _summarize(
                started_at, cycles, all_runs, outage_record, crash_record, lock_record
            )
            _write_incremental(
                args.out,
                {**report_base, "summary": summary, "runs": all_runs},
            )
    finally:
        await engine.dispose()

    print(json.dumps(summary["gate"], ensure_ascii=False, indent=2))
    print(f"[m0-runner] report: {args.out}")
    return 0


def _summarize(
    started_at: datetime,
    cycles: list[dict],
    runs: list[dict],
    outage: dict | None,
    crash: dict | None,
    lock: dict | None,
) -> dict[str, object]:
    valid = count_valid_runs(runs)
    first = min((c["started_at"] for c in cycles), default=started_at.isoformat())
    last = max((c["started_at"] for c in cycles), default=started_at.isoformat())
    aggregate: dict[str, object] = {
        "valid_completed_runs": valid,
        "observation_days": observation_days([first, last]),
        "rag_runs": sum(1 for r in runs if r.get("knowledge_base")),
        "cancel_sample": any(r.get("cancel_note") == "cancel accepted" for r in runs),
        "approval_sample": any(r.get("approval_sample") for r in runs),
        "ollama_outage_sample": bool(
            outage and outage.get("recovered") and outage.get("failed_run")
        ),
        "windows_ended_cycles": sum(
            1 for c in cycles if c.get("ended_at_valid")
        ),
        "stale_open_windows": sum(c.get("stale_open", 0) for c in cycles),
        "negative_duration_windows": sum(c.get("negative", 0) for c in cycles),
        "stuck_runs_over_10min": 0,  # 由聚合器对生产库审计
        "p0p1_blockers": [],
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at.isoformat(),
        "cycles": cycles,
        "runs_total": len(runs),
        "runs_by_status": runs_by_status(runs),
        "valid_completed_runs": valid,
        "rag_runs": aggregate["rag_runs"],
        "latency_percentiles": latency_percentiles(runs),
        "ollama_outage": outage,
        "crash_reconcile": crash,
        "lock_contention": lock,
        "manual_items": {
            "reinstall_first_boot": "manual（需执行官方安装包）",
        },
        "aggregate": aggregate,
        "gate": gate_verdict(aggregate=aggregate),
    }


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
