"""S1-T9：v0.9 性能基线测量（上位计划 §19.3，供阈值审批的证据输入）。

决议 D6：本脚本只在专用测试库（``<PA_DB_URL database>_test`` 或
``PA_TEST_DB_URL``）上运行，绝不触碰日常应用库；测试库需先经
``scripts/prepare_test_database.py --yes`` 建好。

决议 D7：本脚本只产出测量证据（JSON + Markdown），不包含任何阈值判定；
阈值由项目/发布负责人审批。

覆盖（§19.3 六项指标）：
  M1 无模型 Thread 列表（后端侧代理指标：GET /sessions，进程内 ASGI）
  M2 事件持久化延迟（record_event 严格序列路径，真实仲裁链路）
  M3 interrupt → 进程树终止（Job Object KILL_ON_JOB_CLOSE 实测）
  M4 5000 Item 首次可交互 —— 依赖桌面壳渲染，S5 桌面 harness 测量（本脚本登记口径）
  M5 reconnect 1000 事件缺口收敛 —— v2 通道行为，S5 测量（本脚本登记口径）
  M6 bounded queue 饱和显式拒绝 —— 已由 S1 transport spike 实证（319 次显式拒绝、
     零无界增长），引用证据，不重复测量

Usage::
    uv run python scripts/measure_v100_baseline.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 桌面形态下 PA_API_TOKEN 由 Tauri 注入；基线测量在 config 导入前预置令牌，
# 使完整安全中间件（Host 白名单 + Bearer）与生产路径一致地参与测量。
os.environ.setdefault("PA_API_TOKEN", secrets.token_hex(32))

from sqlalchemy import text  # noqa: E402

from personal_assistant import testing as pa_testing  # noqa: E402
from personal_assistant.config import settings as cfg  # noqa: E402

# 决议 D6：在任何 DB 模块导入前把 PA_DB_URL 指向专用测试库，
# 使 core.db 的模块级引擎直接绑定测试库（不做运行时 monkeypatch）。
_TEST_DB_URL = pa_testing.resolve_test_database_url(
    cfg.db_url, os.environ.get("PA_TEST_DB_URL")
)
os.environ["PA_DB_URL"] = _TEST_DB_URL
cfg.db_url = _TEST_DB_URL

OUT_DIR = PROJECT_ROOT / "docs" / "releases" / "v1.0.0" / "adr" / "evidence"

M4_M5_NOTE = [
    {
        "metric": "M4_5000_item_first_interactive",
        "target": "p95 ≤ 1.5 s（分页/虚拟化，§19.3）",
        "status": "desktop_harness_required",
        "method": "S5 桌面 harness：注入 5000 Item 夹具 Thread，测量首次可交互时间",
    },
    {
        "metric": "M5_reconnect_gap_convergence",
        "target": "1000 事件缺口 2 s 内收敛（§19.3）",
        "status": "v2_transport_required",
        "method": "S5：after_sequence 补读 1000 事件 + 实时订阅收敛时间",
    },
    {
        "metric": "M6_bounded_queue_saturation",
        "target": "饱和时显式拒绝、无无界内存增长（§19.3）",
        "status": "measured_by_s1_spike",
        "method": (
            "见 evidence/s1-transport-spike-results-20260824.json T6："
            "队列 64 / 洪泛 384 → 65 正常处理 + 319 显式 retryable 拒绝，零丢失零死锁"
        ),
    },
]


def resolve_test_db_url() -> str:
    return _TEST_DB_URL


async def db_available(url: str) -> tuple[bool, str]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT VERSION()"))).scalar()
            return True, str(version)
    except Exception as exc:  # noqa: BLE001 - 环境探测
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        return -1.0
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))
    return ordered[idx]


async def measure_m1_sessions_list(app, n: int = 30) -> list[float]:
    """M1 后端代理指标：GET /sessions（无模型、无工具，纯列表路径）。

    保留完整安全中间件路径：Host 用白名单内地址 + 携带启动令牌（与桌面一致）。
    """
    from httpx import ASGITransport, AsyncClient

    from personal_assistant import main_api

    headers = {}
    token = getattr(main_api, "_api_token", None)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    latencies: list[float] = []
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://127.0.0.1", headers=headers
    ) as client:
        for _ in range(n):
            t0 = time.perf_counter()
            resp = await client.get("/sessions")
            dt = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 200, f"/sessions 非 200: {resp.status_code}"
            latencies.append(dt)
    return latencies


async def measure_m2_record_event(n: int = 100) -> list[float]:
    """M2 事件持久化延迟：真实 record_event 严格序列仲裁路径（行锁 + 校验 + 投影）。"""
    from personal_assistant.agents.contracts import AgentEvent, AgentEventType
    from personal_assistant.agents.repository import AgentRunRepository
    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import AgentRun

    run_id = uuid4().hex
    async with async_session_factory() as session:
        session.add(
            AgentRun(
                id=run_id,
                trace_id=uuid4().hex,
                max_steps=10,
                max_tool_calls=10,
                max_wall_time_ms=60000,
            )
        )
        await session.commit()

    latencies: list[float] = []
    # 合法投影路径：seq1=run.started，其后循环 context.prepared（payload 契约完整）
    context_payload = {
        "estimated_tokens": 100,
        "history_included": 1,
        "memory_included": 0,
        "rag_included": 0,
        "summary_included": 0,
        "sensitive_excluded": 1,
        "truncated": False,
    }
    async with async_session_factory() as session:
        repo = AgentRunRepository(session)
        run = await repo.get_run(run_id)
        assert run is not None
        for i in range(n):
            event = AgentEvent(
                run_id=run_id,
                sequence=run.last_event_sequence + 1,
                type=(
                    AgentEventType.RUN_STARTED
                    if i == 0
                    else AgentEventType.CONTEXT_PREPARED
                ),
                payload={"baseline_probe": i} if i == 0 else dict(context_payload),
            )
            t0 = time.perf_counter()
            await repo.record_event(event)
            latencies.append((time.perf_counter() - t0) * 1000)
            run = await repo.get_run(run_id)
    # 清理探针数据（专用测试库内安全，FK 顺序：事件 → run）
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM agent_run_events WHERE run_id = :rid"), {"rid": run_id}
        )
        await session.execute(text("DELETE FROM agent_runs WHERE id = :rid"),
                              {"rid": run_id})
        await session.commit()
    return latencies


def measure_m3_kill_tree(rounds: int = 3) -> list[float]:
    """M3 interrupt → 进程树终止：Job Object KILL_ON_JOB_CLOSE 实测（父+孙两层）。"""
    from personal_assistant.core.command_workflow import _JobObject

    latencies: list[float] = []
    for _ in range(rounds):
        parent = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess,sys,time;"
             "subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)']);"
             "time.sleep(300)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        job = _JobObject()
        try:
            assert job.assign(parent.pid), "AssignProcessToJobObject failed"
            time.sleep(0.8)  # 等待孙进程启动并入 job
            t0 = time.perf_counter()
            job.terminate()
            while job.active_processes() > 0:
                if (time.perf_counter() - t0) > 5.0:
                    break
                time.sleep(0.005)
            latencies.append((time.perf_counter() - t0) * 1000)
        finally:
            job.close()
            if parent.poll() is None:
                parent.kill()
    return latencies


def summarize(samples: list[float]) -> dict:
    return {
        "n": len(samples),
        "p50_ms": round(percentile(samples, 0.50), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3) if samples else -1,
        "mean_ms": round(statistics.fmean(samples), 3) if samples else -1,
    }


async def run_measurements() -> dict:
    # core.db 模块级引擎已在导入时绑定测试库（见文件头环境变量前置）
    from personal_assistant.core import db as core_db  # noqa: F401 - 触发引擎初始化
    from personal_assistant.main_api import app

    results: dict[str, dict] = {}
    results["M1_sessions_list_backend"] = summarize(await measure_m1_sessions_list(app))
    results["M2_event_persistence"] = summarize(await measure_m2_record_event())
    results["M3_kill_tree"] = summarize(await asyncio.to_thread(measure_m3_kill_tree))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="v1.0.0 S1-T9 性能基线（只测专用测试库）")
    parser.add_argument("--skip-db-check", action="store_true")
    args = parser.parse_args()

    test_url = resolve_test_db_url()
    if not args.skip_db_check:
        ok, info = asyncio.run(db_available(test_url))
        if not ok:
            print(
                "ENV-ERROR: 专用测试库不可用（先运行 scripts/prepare_test_database.py --yes）"
                f"\n  目标: {pa_testing.display_database_target(test_url)}\n  原因: {info}"
            )
            return 2
        print(f"测试库可用: {pa_testing.display_database_target(test_url)} (MySQL {info})")

    started = datetime.now(timezone.utc)
    results = asyncio.run(run_measurements())
    payload = {
        "baseline": "v0.9.0-fe7bd1a",
        "purpose": "S1-T9 性能基线（§19.3 证据输入；阈值审批归项目/发布负责人，D7）",
        "measured_at_utc": started.isoformat(),
        "database": pa_testing.display_database_target(test_url),
        "python": sys.version,
        "metrics": results,
        "deferred_metrics": M4_M5_NOTE,
        "approval": "pending_project_owner_review",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "s1-performance-baseline-20260824.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    md_lines = [
        "# S1-T9 v0.9 性能基线报告（证据输入，阈值待审批）",
        "",
        f"> 基线：`v0.9.0` 封版提交 `fe7bd1a`；测量时间 {started.isoformat()}",
        f"> 数据库：`{pa_testing.display_database_target(test_url)}`（专用测试库，决议 D6）",
        "> 依据：上位计划 §19.3；决议 D7——阈值由项目/发布负责人审批，本报告不自批。",
        "",
        "| 指标 | 口径 | n | p50 (ms) | p95 (ms) | max (ms) |",
        "|---|---|---:|---:|---:|---:|",
        f"| M1 会话列表（后端代理指标） | GET /sessions，进程内 ASGI，无模型 | "
        f"{results['M1_sessions_list_backend']['n']} | "
        f"{results['M1_sessions_list_backend']['p50_ms']} | "
        f"{results['M1_sessions_list_backend']['p95_ms']} | "
        f"{results['M1_sessions_list_backend']['max_ms']} |",
        f"| M2 事件持久化延迟 | record_event 严格序列仲裁（行锁+校验+投影） | "
        f"{results['M2_event_persistence']['n']} | "
        f"{results['M2_event_persistence']['p50_ms']} | "
        f"{results['M2_event_persistence']['p95_ms']} | "
        f"{results['M2_event_persistence']['max_ms']} |",
        f"| M3 interrupt→进程树终止 | Job Object terminate→活跃进程=0（父+孙两层） | "
        f"{results['M3_kill_tree']['n']} | "
        f"{results['M3_kill_tree']['p50_ms']} | "
        f"{results['M3_kill_tree']['p95_ms']} | "
        f"{results['M3_kill_tree']['max_ms']} |",
        "",
        "## 延迟/引用项",
        "",
        "| 指标 | 目标（§19.3） | 状态 | 口径 |",
        "|---|---|---|---|",
    ]
    for item in M4_M5_NOTE:
        md_lines.append(
            f"| {item['metric']} | {item['target']} | {item['status']} | {item['method']} |"
        )
    md_lines += [
        "",
        "## 说明",
        "",
        "- M1 为后端侧代理指标：S5 桌面 harness 建立后以真实首屏测量替换；",
        "- M2 测得的是 v0.9 严格序列仲裁路径，v2 继承同模式（ADR-003 §3）；",
        "- M3 复用 v0.9 `_JobObject`（生产已验证），测终止延迟而非取消决策链；",
        "- 本机单项测量存在环境噪声，正式验收以 S8 多轮统计为准。",
        "",
    ]
    md_path = OUT_DIR / "s1-performance-baseline-20260824.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))
    print(f"证据已写入: {json_path.name} / {md_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
