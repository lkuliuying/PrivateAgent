#!/usr/bin/env python3
"""第八阶段 M6：性能基线测量。

生成样本数据（1000 消息 / 500 inbox / 100 文档 / 5000 切片 / 200 通知 / 100 完整性发现），
测量关键路径耗时（Today 聚合 / 全局搜索 / 诊断快照 / 完整性体检 / 备份导出），按
warning / release_blocker 阈值标记，输出 JSON + Markdown 报告到 dist/。

sidecar 冷/热启动由 scripts/measure_sidecar_baseline.py 单独覆盖（--startup），
本脚本聚焦 DB + 业务逻辑路径，经 ASGITransport 在进程内调用真实端点（无需独立后端）。

Usage::
    uv run python scripts/measure_perf_baseline.py                  # 全量样本 + 测量 + 报告
    uv run python scripts/measure_perf_baseline.py --scale 0.1      # 小样本快速验证
    uv run python scripts/measure_perf_baseline.py --skip-generate  # 复用已有数据
    uv run python scripts/measure_perf_baseline.py --clean          # 清理 perf-* 样本数据
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import insert, select  # noqa: E402

from personal_assistant.core.db import async_session_factory  # noqa: E402
from personal_assistant.core.models import (  # noqa: E402
    AppNotification,
    ChatSession,
    DataIntegrityFinding,
    DocChunk,
    Document,
    InboxItem,
    Message,
)
from personal_assistant.core.timeutil import utcnow  # noqa: E402
from personal_assistant.main_api import app  # noqa: E402

DIST = PROJECT_ROOT / "dist"

SAMPLE_COUNTS = {
    "sessions": 50,
    "messages": 1000,
    "inbox": 500,
    "documents": 100,
    "chunks": 5000,
    "notifications": 200,
    "findings": 100,
}

# 阈值（毫秒）：warning=开发提醒，blocker=发布阻断。超过 blocker 时退出码非 0。
THRESHOLDS: dict[str, dict[str, int]] = {
    "today": {"warning_ms": 500, "blocker_ms": 2000},
    "search": {"warning_ms": 800, "blocker_ms": 3000},
    "diagnostics": {"warning_ms": 1000, "blocker_ms": 4000},
    "integrity": {"warning_ms": 2000, "blocker_ms": 8000},
    "backup_export": {"warning_ms": 3000, "blocker_ms": 15000},
}

# 已识别热点 + 优化 + 后续方案（对齐 phase8-plan §M6「至少一处优化或给出后续方案」）。
HOTSPOTS = [
    {
        "path": "diagnostics",
        "finding": (
            "diagnostics.snapshot 调用 HealthService.check_all()，其中 Ollama 健康探测在 "
            "Ollama 不健康/慢响应时阻塞（本机实测 ~5-9s，触发 blocker 阈值）。"
        ),
        "optimization_done": (
            "OllamaProvider.health() 的 httpx 超时由 5s 收紧到 3s（provider.py），"
            "对 Ollama 完全不可达（连接拒绝/超时）的场景生效。"
        ),
        "follow_up": (
            "慢响应但最终返回（如 503）的场景 httpx read-timeout 与 asyncio.wait_for 均无法"
            "在 Python 3.13 上即时截断（wait_for 需等待取消完成）。后续方案："
            "(a) 诊断路径缓存最近一次 health 结果（短 TTL，如 10s）；"
            "(b) 将 Ollama 探测改为线程内 sync httpx + 短超时（asyncio.to_thread，可被 wait_for 真正放弃）；"
            "(c) 诊断快照不阻塞完整 health，先返回其余字段，health 异步刷新。"
        ),
    },
]


def check_thresholds(timings: dict[str, float]) -> dict[str, list]:
    """按阈值分类：blocker 超过 blocker_ms，warning 超过 warning_ms 但未到 blocker。"""
    warnings: list[dict] = []
    blockers: list[dict] = []
    for path, ms in timings.items():
        th = THRESHOLDS.get(path)
        if not th:
            continue
        if ms >= th["blocker_ms"]:
            blockers.append({"path": path, "ms": ms, "threshold": th["blocker_ms"]})
        elif ms >= th["warning_ms"]:
            warnings.append({"path": path, "ms": ms, "threshold": th["warning_ms"]})
    return {"warnings": warnings, "blockers": blockers}


async def generate_sample_data(scale: float = 1.0) -> dict:
    """生成 perf-* 样本数据（bulk insert），返回各表生成数量。"""
    base = utcnow()
    n_sess = max(1, int(SAMPLE_COUNTS["sessions"] * scale))
    n_msg = max(n_sess, int(SAMPLE_COUNTS["messages"] * scale))
    n_inbox = int(SAMPLE_COUNTS["inbox"] * scale)
    n_docs = max(1, int(SAMPLE_COUNTS["documents"] * scale))
    n_chunks = int(SAMPLE_COUNTS["chunks"] * scale)
    n_notif = int(SAMPLE_COUNTS["notifications"] * scale)
    n_findings = int(SAMPLE_COUNTS["findings"] * scale)

    async with async_session_factory() as db:
        sess_rows = [
            {"title": f"perf-session-{i}", "created_at": base - timedelta(minutes=i)}
            for i in range(n_sess)
        ]
        await db.execute(insert(ChatSession), sess_rows)
        sids = [
            r[0]
            for r in (
                await db.execute(
                    select(ChatSession.id).order_by(ChatSession.id.desc()).limit(n_sess)
                )
            ).all()
        ]
        msg_rows = [
            {
                "session_id": sids[i % len(sids)],
                "role": "user" if i % 2 else "assistant",
                "content": f"perf message {i} 性能基线内容",
                "created_at": base - timedelta(seconds=i),
            }
            for i in range(n_msg)
        ]
        await db.execute(insert(Message), msg_rows)
        inbox_rows = [
            {"title": f"perf-inbox-{i}", "item_type": "todo", "status": "open", "priority": "normal"}
            for i in range(n_inbox)
        ]
        await db.execute(insert(InboxItem), inbox_rows)
        doc_rows = [
            {"name": f"perf-doc-{i}.md", "status": "ready", "chunk_count": 0, "enabled": True}
            for i in range(n_docs)
        ]
        await db.execute(insert(Document), doc_rows)
        dids = [
            r[0]
            for r in (
                await db.execute(
                    select(Document.id).order_by(Document.id.desc()).limit(n_docs)
                )
            ).all()
        ]
        per_doc = max(1, n_chunks // len(dids))
        chunk_rows = [
            {"doc_id": d, "ordinal": o, "content": f"perf chunk {o}", "bm25_text": f"perf chunk {o}"}
            for d in dids
            for o in range(per_doc)
        ]
        await db.execute(insert(DocChunk), chunk_rows)
        notif_rows = [
            {"level": "info", "kind": "perf", "title": f"perf-notif-{i}", "status": "unread"}
            for i in range(n_notif)
        ]
        await db.execute(insert(AppNotification), notif_rows)
        finding_rows = [
            {"check_name": "perf_test", "severity": "info", "ref_type": "perf", "ref_id": i, "status": "open"}
            for i in range(n_findings)
        ]
        await db.execute(insert(DataIntegrityFinding), finding_rows)
        await db.commit()
    return {
        "sessions": n_sess,
        "messages": n_msg,
        "inbox": n_inbox,
        "documents": n_docs,
        "chunks": len(chunk_rows),
        "notifications": n_notif,
        "findings": n_findings,
    }


async def clean_sample_data() -> int:
    """删除所有 perf-* 样本数据（按 title/name/check_name 前缀识别）。返回删除行数。"""
    from sqlalchemy import delete

    async with async_session_factory() as db:
        n = 0
        n += (await db.execute(delete(Message).where(Message.content.like("perf message%")))).rowcount or 0
        n += (await db.execute(delete(ChatSession).where(ChatSession.title.like("perf-session-%")))).rowcount or 0
        n += (await db.execute(delete(InboxItem).where(InboxItem.title.like("perf-inbox-%")))).rowcount or 0
        n += (await db.execute(delete(DocChunk).where(DocChunk.content.like("perf chunk%")))).rowcount or 0
        n += (await db.execute(delete(Document).where(Document.name.like("perf-doc-%")))).rowcount or 0
        n += (await db.execute(delete(AppNotification).where(AppNotification.title.like("perf-notif-%")))).rowcount or 0
        n += (await db.execute(delete(DataIntegrityFinding).where(DataIntegrityFinding.check_name == "perf_test"))).rowcount or 0
        await db.commit()
    return n


async def measure_endpoints() -> dict[str, float]:
    """经 ASGITransport 测量关键端点耗时（毫秒）。

    完整性体检单独走 measure_integrity（直接调服务并清理产生的 finding，避免污染）。
    """
    timings: dict[str, float] = {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path, method, url in [
            ("today", "GET", "/today"),
            ("search", "GET", "/search?q=perf"),
            ("diagnostics", "GET", "/diagnostics"),
            ("backup_export", "POST", "/backup/export"),
        ]:
            t0 = time.perf_counter()
            if method == "GET":
                r = await client.get(url)
            else:
                r = await client.post(url)
            elapsed = (time.perf_counter() - t0) * 1000
            timings[path] = round(elapsed, 1)
            # 清理 backup 产生的 zip
            if path == "backup_export" and r.status_code == 200:
                try:
                    Path(r.json()["path"]).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
    return timings


async def measure_integrity() -> float:
    """直接测量完整性体检耗时，并删除本次产生的 finding（避免污染 DB）。"""
    from personal_assistant.core.integrity import IntegrityService

    async with async_session_factory() as db:
        t0 = time.perf_counter()
        findings = await IntegrityService(db).check()
        elapsed = (time.perf_counter() - t0) * 1000
        for f in findings:
            await db.delete(f)
        await db.commit()
    return round(elapsed, 1)


def write_report(results: dict, out_dir: Path) -> tuple[Path, Path]:
    """输出 JSON + Markdown 报告。返回 (json_path, md_path)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "perf-baseline.json"
    md_path = out_dir / "perf-baseline.md"
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 性能基线报告",
        "",
        f"- 生成时间：{results['generated_at']}",
        f"- 样本规模：{results['sample_counts']}",
        "",
        "## 关键路径耗时",
        "",
        "| 路径 | 耗时(ms) | warning 阈值 | blocker 阈值 | 状态 |",
        "|---|---|---|---|---|",
    ]
    th = check_thresholds(results["timings"])
    blocker_paths = {b["path"] for b in th["blockers"]}
    warning_paths = {w["path"] for w in th["warnings"]}
    for path, ms in results["timings"].items():
        t = THRESHOLDS.get(path, {})
        status = "❌ blocker" if path in blocker_paths else ("⚠️ warning" if path in warning_paths else "✅ ok")
        lines.append(
            f"| {path} | {ms} | {t.get('warning_ms','-')} | {t.get('blocker_ms','-')} | {status} |"
        )
    lines += [
        "",
        "## 阈值结果",
        "",
        f"- warning：{len(th['warnings'])} 项",
        f"- blocker：{len(th['blockers'])} 项",
        "",
        "## 已识别热点与后续方案",
        "",
    ]
    for hs in HOTSPOTS:
        lines += [
            f"### {hs['path']}",
            f"- 发现：{hs['finding']}",
            f"- 已优化：{hs['optimization_done']}",
            f"- 后续：{hs['follow_up']}",
            "",
        ]
    lines += [
        "> sidecar 冷/热启动见 `scripts/measure_sidecar_baseline.py --startup --markdown`。",
        "> blocker > 0 时发布前必须优化或调整阈值。",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


async def run(scale: float, skip_generate: bool, out: Path) -> dict:
    sample = None
    if not skip_generate:
        sample = await generate_sample_data(scale=scale)
    timings = await measure_endpoints()
    timings["integrity"] = await measure_integrity()
    th = check_thresholds(timings)
    results = {
        "generated_at": utcnow().isoformat(),
        "sample_counts": sample or "skipped (reused existing data)",
        "thresholds": THRESHOLDS,
        "timings": timings,
        "warnings": th["warnings"],
        "blockers": th["blockers"],
        "hotspots": HOTSPOTS,
    }
    json_path, md_path = write_report(results, out)
    results["report_json"] = str(json_path)
    results["report_md"] = str(md_path)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=float, default=1.0, help="样本规模系数（默认 1.0 全量）")
    ap.add_argument("--skip-generate", action="store_true", help="复用已有数据，不生成样本")
    ap.add_argument("--clean", action="store_true", help="清理 perf-* 样本数据后退出")
    ap.add_argument("--out", default=str(DIST), help="报告输出目录（默认 dist/）")
    args = ap.parse_args()

    if args.clean:
        n = asyncio.run(clean_sample_data())
        print(f"[perf] cleaned {n} perf-* sample rows")
        return 0

    results = asyncio.run(run(args.scale, args.skip_generate, Path(args.out)))
    print(f"[perf] report: {results['report_md']}")
    print(f"[perf] timings: {results['timings']}")
    if results["blockers"]:
        print(f"[perf] BLOCKERS: {results['blockers']}")
        return 1
    if results["warnings"]:
        print(f"[perf] warnings: {results['warnings']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
