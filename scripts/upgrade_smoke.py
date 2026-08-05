#!/usr/bin/env python3
"""第八阶段 M3：升级 smoke 工具与数据保留校验。

真实 vN -> vN+1 升级需构建两份安装包、部署更新源、运行 Tauri updater，依赖真实
Windows 环境与证书，本脚本提供可重复的数据保留校验与样本数据，并记录升级 smoke
运行结果（upgrade_smoke_runs）。真实升级步骤见 build_runbook()，标注「待真实环境执行」。

Usage::
    uv run python scripts/upgrade_smoke.py --runbook               # 打印 runbook
    uv run python scripts/upgrade_smoke.py --snapshot              # 当前数据计数快照
    uv run python scripts/upgrade_smoke.py --generate-sample       # 生成样本数据
    uv run python scripts/upgrade_smoke.py --verify before.json after.json
    uv run python scripts/upgrade_smoke.py --record --from 0.1.1 --to 0.1.2 --result blocked
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from personal_assistant.config import settings as cfg  # noqa: E402
from personal_assistant.core.models import (  # noqa: E402
    AgentTask,
    AppNotification,
    CaptureItem,
    ChatSession,
    Document,
    InboxItem,
    MemoryItem,
    Message,
    OcrJob,
    PersonalGoal,
    Reminder,
    UpgradeSmokeRun,
)

# 数据保留校验覆盖的表（升级前后计数对比）。
PRESERVATION_TABLES = {
    "sessions": ChatSession,
    "documents": Document,
    "memory_items": MemoryItem,
    "agent_tasks": AgentTask,
    "inbox_items": InboxItem,
    "reminders": Reminder,
    "personal_goals": PersonalGoal,
    "app_notifications": AppNotification,
    "capture_items": CaptureItem,
    "ocr_jobs": OcrJob,
}


def verify_data_preservation(before: dict, after: dict) -> dict:
    """校验升级前后数据保留：after >= before（不丢数据；新增允许）。

    返回 {preserved, deltas:[{table, before, after, lost}]}。
    """
    deltas: list[dict] = []
    lost_any = False
    for table in PRESERVATION_TABLES:
        b = before.get(table, 0)
        a = after.get(table, 0)
        lost = a < b
        if lost:
            lost_any = True
        deltas.append({"table": table, "before": b, "after": a, "lost": lost})
    return {"preserved": not lost_any, "deltas": deltas}


def build_runbook() -> str:
    """升级 smoke runbook（真实环境执行步骤 + 负面场景 + 回滚）。"""
    return """\
# 升级 smoke runbook（vN -> vN+1）

## 准备
1. 旧版本安装并写入样本数据：`uv run python scripts/upgrade_smoke.py --generate-sample`
2. 记录升级前数据快照：`uv run python scripts/upgrade_smoke.py --snapshot > before.json`
3. 构建新版本安装包 + .sig + latest.json：`scripts/build-release.bat` +
   `scripts/generate-latest-json.py`
4. 部署本地等价更新源（或 GitHub Release v<new>）：把 latest.json + 安装包 + .sig
   放到 tauri.conf.json updater endpoint 指向的位置（本地可用 file:// 或本地 HTTP）。

## 执行
5. 旧版本应用内「检查更新」-> 下载 -> 签名验证 -> 安装 -> 重启。
6. 重启后版本变化（设置页显示新版本）。
7. 记录升级后数据快照：`uv run python scripts/upgrade_smoke.py --snapshot > after.json`
8. 数据保留校验：`uv run python scripts/upgrade_smoke.py --verify before.json after.json`
9. schema head 检查：`uv run alembic current` 应为新 head，诊断中心显示一致。
10. 记录运行：`uv run python scripts/upgrade_smoke.py --record --from <old> --to <new> --result passed`

## 负面场景（不破坏当前可用版本）
- 签名错误：篡改 .sig 或换错公钥 -> updater 拒绝安装，旧版本仍可用。
- latest.json 缺字段：删除 platforms/signature -> updater 报清单错误，不安装。
- 下载失败：断网或错误 URL -> updater 报下载失败，旧版本仍可用。
- 迁移失败：构造不可用迁移 -> 诊断中心给出迁移失败 runbook（GET /backup/migration-runbook）。

## 回滚
- 旧版本仍在（升级不卸载旧数据目录），卸载新版本 + 重装旧版本即可回到 vN。
- 必要时从备份恢复：POST /backup/restore/drill 预览 + POST /backup/restore（仅 settings）。
- 数据目录行为见 docs/release-checklist.md（卸载/升级保留 .env/chroma/logs/backups）。

> 本机环境无法构建两份安装包并运行真实 updater，上述步骤标注「待真实环境执行」。
> 工具（数据快照/校验/样本数据/记录）已就绪，可在真实 Windows 环境直接执行。
"""


async def snapshot_counts() -> dict:
    """当前数据计数快照（PRESERVATION_TABLES 各表行数）。"""
    eng = create_async_engine(cfg.db_url)
    try:
        factory = async_sessionmaker(eng, expire_on_commit=False)
        async with factory() as db:
            counts: dict[str, int] = {}
            for name, model in PRESERVATION_TABLES.items():
                total = await db.scalar(select(func.count(model.id)))
                counts[name] = int(total or 0)
        return counts
    finally:
        await eng.dispose()


async def generate_sample_data() -> dict:
    """生成升级 smoke 样本数据（每类一条，标题/名称带 upgrade-smoke 前缀，便于清理）。"""
    from datetime import datetime

    from personal_assistant.core.timeutil import utcnow

    tag = utcnow().strftime("%Y%m%d%H%M%S")
    eng = create_async_engine(cfg.db_url)
    try:
        factory = async_sessionmaker(eng, expire_on_commit=False)
        async with factory() as db:
            from sqlalchemy import insert

            sess = ChatSession(title=f"upgrade-smoke-session-{tag}")
            db.add(sess)
            await db.commit()
            await db.refresh(sess)
            db.add(Message(session_id=sess.id, role="user", content=f"upgrade-smoke-msg-{tag}"))
            db.add(Document(name=f"upgrade-smoke-doc-{tag}.md", status="ready", chunk_count=0, enabled=True))
            db.add(MemoryItem(kind="note", title=f"upgrade-smoke-mem-{tag}", content_md="smoke", status="confirmed"))
            db.add(AgentTask(title=f"upgrade-smoke-task-{tag}", status="planned"))
            db.add(InboxItem(title=f"upgrade-smoke-inbox-{tag}", item_type="todo", status="open"))
            db.add(Reminder(title=f"upgrade-smoke-reminder-{tag}", due_at=utcnow(), next_fire_at=utcnow()))
            db.add(PersonalGoal(title=f"upgrade-smoke-goal-{tag}"))
            db.add(AppNotification(level="info", kind="upgrade_smoke", title=f"upgrade-smoke-notif-{tag}"))
            db.add(CaptureItem(content_md=f"upgrade-smoke-capture-{tag}", source="manual"))
            db.add(OcrJob(source="manual"))
            await db.commit()
        return await snapshot_counts()
    finally:
        await eng.dispose()


async def record_run(
    from_v: str, to_v: str, result: str, data_preserved: bool | None, schema_ok: bool | None, notes: str | None
) -> int:
    """记录一次升级 smoke 运行到 upgrade_smoke_runs，返回 id。"""
    eng = create_async_engine(cfg.db_url)
    try:
        factory = async_sessionmaker(eng, expire_on_commit=False)
        async with factory() as db:
            run = UpgradeSmokeRun(
                from_version=from_v,
                to_version=to_v,
                result=result,
                data_preserved=data_preserved,
                schema_ok=schema_ok,
                notes_md=notes,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return run.id
    finally:
        await eng.dispose()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runbook", action="store_true")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--generate-sample", action="store_true")
    ap.add_argument("--verify", nargs=2, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--from", dest="from_v")
    ap.add_argument("--to", dest="to_v")
    ap.add_argument("--result", default="blocked")
    ap.add_argument("--data-preserved", default=None)
    ap.add_argument("--schema-ok", default=None)
    ap.add_argument("--notes", default=None)
    args = ap.parse_args()

    if args.runbook:
        print(build_runbook())
        return 0
    if args.snapshot:
        print(json.dumps(asyncio.run(snapshot_counts()), ensure_ascii=False, indent=2))
        return 0
    if args.generate_sample:
        counts = asyncio.run(generate_sample_data())
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        return 0
    if args.verify:
        before = json.loads(Path(args.verify[0]).read_text(encoding="utf-8"))
        after = json.loads(Path(args.verify[1]).read_text(encoding="utf-8"))
        result = verify_data_preservation(before, after)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["preserved"] else 1
    if args.record:
        data_preserved = _parse_flag(args.data_preserved)
        schema_ok = _parse_flag(args.schema_ok)
        rid = asyncio.run(
            record_run(
                args.from_v or "?",
                args.to_v or "?",
                args.result,
                data_preserved,
                schema_ok,
                args.notes,
            )
        )
        print(f"[upgrade-smoke] recorded run #{rid}: {args.from_v}->{args.to_v} result={args.result}")
        return 0
    ap.print_help()
    return 0


def _parse_flag(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "passed"}


if __name__ == "__main__":
    sys.exit(main())
