"""0.3.0 A4 安装版验收：摘要 worker 本地模型端到端 smoke。

对已构建 sidecar 执行：
1. 直连 DB 创建达到摘要阈值的会话（用户/助手交替消息）；
2. 启动带 PA_CONVERSATION_SUMMARY_WORKER_ENABLED=true 的 sidecar，等待 tick；
3. 通过 DB 验证摘要已生成、原始消息数与内容不变、worker 幂等
   （二次 tick 不重复生成）、报告不含聊天正文；
4. 优雅停机后无残留进程。

用法：python scripts/summary_worker_smoke.py [--min-source 12]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

SIDECAR = (
    PROJECT_ROOT
    / "apps"
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "personal-assistant-server-x86_64-pc-windows-msvc.exe"
)
HEALTH_TIMEOUT_S = 120
TICK_WAIT_S = 300


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


def _read_project_env() -> dict[str, str]:
    env_path = PROJECT_ROOT / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.startswith("PA_"):
            out[k] = v.strip()
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False, cwd=PROJECT_ROOT,
    )
    return result.stdout.strip() or "unknown"


def _hash_messages(rows: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


async def _wait_health(base: str, token: str) -> bool:
    deadline = time.time() + HEALTH_TIMEOUT_S
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                f"{base}/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return False


async def _graceful_stop(port: int, token: str) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/internal/shutdown",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200 and json.loads(r.read())["accepted"]
    except Exception:  # noqa: BLE001
        return False


async def _sidecar_count() -> int:
    result = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process -Name 'personal-assistant-server*' -ErrorAction "
        "SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    out, _ = await result.communicate()
    try:
        return int(out.decode(errors="replace").strip() or "0")
    except ValueError:
        return -1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-source", type=int, default=12)
    parser.add_argument("--keep-recent", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, default=PROJECT_ROOT / "dist" / "summary-smoke-report.json"
    )
    args = parser.parse_args()

    from personal_assistant.core.db import async_session_factory, engine
    from personal_assistant.core.models import ChatSession, ConversationSummary, Message

    report: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "binary_identity": {
            "sidecar": str(SIDECAR),
            "sha256": _sha256(SIDECAR),
            "git_commit": _git_head(),
        },
        "min_source_messages": args.min_source,
    }
    async with async_session_factory() as db:
        session = ChatSession(title=f"summary-smoke-{int(time.time())}")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id
        report["session_id"] = session_id
        # find_candidate 要求 count >= min_source + keep_recent 才生成摘要
        for index in range(args.min_source + args.keep_recent + 1):
            db.add(
                Message(
                    session_id=session_id,
                    role="user" if index % 2 == 0 else "assistant",
                    content=(
                        f"测试消息 {index + 1}：本地优先、隐私可控的私人助手"
                        f"会话内容，用于验证摘要 worker 阈值与保留。"
                    ),
                )
            )
        await db.commit()
        before = [
            {
                "role": m.role,
                "content": m.content,
            }
            for m in (await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.id.asc())
            )).scalars()
        ]
        report["seeded_message_count"] = len(before)
        report["message_hash_before"] = _hash_messages(before)
    print(f"[summary-smoke] seeded {len(before)} messages (session {session_id})")

    # 2. 启动 sidecar（worker 开启，本地模型，远程 Provider 拒绝）
    env = {**os.environ, **_read_project_env()}
    token = secrets.token_hex(32)
    port = _free_port()
    env.update(
        {
            "PA_API_PORT": str(port),
            "PA_API_TOKEN": token,
            "PA_SKIP_MIGRATIONS": "1",
            "PA_CONVERSATION_SUMMARY_WORKER_ENABLED": "true",
            "PA_CONVERSATION_SUMMARY_ALLOW_REMOTE_PROVIDER": "false",
            "PA_CONVERSATION_SUMMARY_TICK_SECONDS": "15",
            "PA_CONVERSATION_SUMMARY_MIN_SOURCE_MESSAGES": str(args.min_source),
            "PA_CONVERSATION_SUMMARY_KEEP_RECENT_MESSAGES": "8",
            "PA_CONVERSATION_SUMMARY_MAX_SOURCE_MESSAGES": "40",
            "PA_CONVERSATION_SUMMARY_MAX_SOURCE_CHARS": "24000",
        }
    )
    base = f"http://127.0.0.1:{port}"
    log_path = PROJECT_ROOT / ".tmp" / "summary-worker-smoke.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(SIDECAR)],
        env=env,
        stdout=log_path.open("w"),
        stderr=subprocess.STDOUT,
    )
    try:
        if not await _wait_health(base, token):
            report["health"] = "failed"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        report["health"] = "ok"
        print(f"[summary-smoke] sidecar healthy on {base}")

        # 3. 等待 worker tick 生成摘要（DB 轮询 conversation_summaries）
        summary_id: str | None = None
        deadline = time.time() + TICK_WAIT_S
        while time.time() < deadline:
            async with async_session_factory() as db:
                row = (
                    await db.execute(
                        select(ConversationSummary)
                        .where(ConversationSummary.session_id == session_id)
                        .order_by(ConversationSummary.created_at.desc())
                    )
                ).scalars().first()
                if row is not None:
                    summary_id = row.id
                    report["summary_summary_version"] = row.summary_version
                    report["summary_provider"] = row.provider
                    report["summary_model"] = row.model
                    report["summary_source_count"] = row.source_message_count
                    report["summary_prompt_version"] = row.prompt_version
                    report["summary_status"] = row.status
                    report["summary_source_range"] = (
                        row.first_message_id,
                        row.last_message_id,
                    )
                    break
            await asyncio.sleep(5)
        if summary_id is None:
            report["summary_created"] = False
            print("[summary-smoke] FAIL: 摘要未在期限内生成")
            await engine.dispose()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        report["summary_created"] = True
        print(f"[summary-smoke] summary created: {summary_id}")

        # 4. 幂等：等待至少一个 tick 周期，摘要数不应增加
        await asyncio.sleep(35)
        async with async_session_factory() as db:
            count_after = await db.scalar(
                select(func.count())
                .select_from(ConversationSummary)
                .where(ConversationSummary.session_id == session_id)
            )
        report["summary_count_after_second_tick"] = int(count_after or 0)
        report["idempotent"] = int(count_after or 0) == 1
        print(
            f"[summary-smoke] summaries after second tick: {count_after} "
            f"(idempotent={report['idempotent']})"
        )

        # 5. 原始消息保留：数量与内容哈希不变
        async with async_session_factory() as db:
            after = [
                {"role": m.role, "content": m.content}
                for m in (await db.execute(
                    select(Message)
                    .where(Message.session_id == session_id)
                    .order_by(Message.id.asc())
                )).scalars()
            ]
        report["message_count_after_summary"] = len(after)
        report["messages_preserved"] = len(after) == len(before)
        report["message_hash_after"] = _hash_messages(after)
        report["hash_unchanged"] = (
            report["message_hash_before"] == report["message_hash_after"]
        )
        print(
            f"[summary-smoke] messages preserved: {report['messages_preserved']} "
            f"hash unchanged: {report['hash_unchanged']}"
        )

        # 6. 报告/API 不应泄露正文（chat 消息列表是业务数据，这里检查的是
        #    摘要相关遥测路径；诊断接口不含正文）
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=60
        ) as client:
            diag = (await client.get(f"{base}/diagnostics")).json()
            report["telemetry_has_message_body"] = (
                "测试消息" in json.dumps(diag, ensure_ascii=False)
            )
            print(
                f"[summary-smoke] telemetry leaks body: "
                f"{report['telemetry_has_message_body']}"
            )

        # 7. 优雅停机 + 无残留
        shutdown = await _graceful_stop(port, token)
        report["graceful_shutdown"] = shutdown
        print(f"[summary-smoke] graceful shutdown: {shutdown}")
        time.sleep(5)
        residual = await _sidecar_count()
        report["sidecar_residual_count"] = residual
        report["sidecar_residual"] = residual > 0
        print(f"[summary-smoke] residual sidecar: {residual}")
    finally:
        if proc.poll() is None:
            _kill_tree(proc.pid)
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
        await engine.dispose()

    checks = (
        report.get("summary_created"),
        report.get("idempotent"),
        report.get("messages_preserved"),
        report.get("hash_unchanged"),
        not report.get("telemetry_has_message_body"),
        report.get("graceful_shutdown"),
        not report.get("sidecar_residual"),
    )
    report["out"] = "passed" if all(checks) else "failed"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[summary-smoke] report: {args.out}")
    return 0 if report["out"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
