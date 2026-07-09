"""第八阶段 M8 测试：本地集成样板（ICS 日历导入）。

覆盖（对齐 docs/phase8-plan.md §M8 / docs/phase8-requirements.md §5.8/§10.1）：
- ICS 解析：基本事件、行展开、转义、全天事件。
- 隐私预览：解析摘要（事件数/标题），不建对象。
- trusted paths：未授权路径 preview/import 返回 403。
- 导入 -> 提醒：创建带 source_type="integration:ics" 的 reminder，记录可撤销信息。
- 导入 -> 收件箱：target=inbox 创建 inbox item。
- 撤销：按来源删除本次创建的对象，标记 reverted。
- 来源追踪 + 列表路由。

注意：导入经 client（独立 session）创建对象，验证与清理用 fresh session，
避免 db fixture 旧事务快照看不到 client 写入（同 test_phase7_capture_ocr 注释）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_assistant.config import settings as cfg
from personal_assistant.core.integrations import ICS_SOURCE_TYPE, parse_ics
from personal_assistant.core.models import (
    InboxItem,
    IntegrationImport,
    IntegrationSource,
    Reminder,
    TrustedPath,
)
from personal_assistant.core.repo_tools import TrustedPathRepository

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-1@test
SUMMARY:团队周会
DTSTART:20260715T100000Z
DTEND:20260715T110000Z
DESCRIPTION:每周同步
LOCATION:会议室A
END:VEVENT
BEGIN:VEVENT
UID:event-2@test
SUMMARY:全天培训
DTSTART;VALUE=DATE:20260720
END:VEVENT
END:VCALENDAR
"""


@asynccontextmanager
async def _fresh():
    """独立 fresh engine session，用于跨 session 验证与清理。"""
    engine = create_async_engine(cfg.db_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


# ============ ICS 解析（纯函数，无 DB）============


def test_parse_ics_basic():
    events = parse_ics(SAMPLE_ICS)
    assert len(events) == 2
    assert events[0]["summary"] == "团队周会"
    assert events[0]["dtstart"] == datetime(2026, 7, 15, 10, 0, 0)
    assert events[0]["dtend"] == datetime(2026, 7, 15, 11, 0, 0)
    assert events[0]["location"] == "会议室A"
    assert events[0]["description"] == "每周同步"
    assert events[1]["summary"] == "全天培训"
    assert events[1]["dtstart"] == datetime(2026, 7, 20, 0, 0, 0)
    assert events[1]["all_day"] is True


def test_parse_ics_line_unfolding():
    content = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:团队\n 周会\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    events = parse_ics(content)
    assert events[0]["summary"] == "团队周会"


def test_parse_ics_unescape():
    content = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:a\\,b\\;c\\nd\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    events = parse_ics(content)
    assert events[0]["summary"] == "a,b;c\nd"


# ============ 服务 / 路由 ============


@pytest.fixture
async def integ_cleanup():
    """清理测试创建的集成源/导入/reminder/inbox/trusted_path（用 fresh session）。"""
    state = {"sources": [], "imports": [], "trusted": []}
    yield state
    async with _fresh() as s:
        for imp_id in state["imports"]:
            rems = (
                (
                    await s.execute(
                        select(Reminder).where(
                            Reminder.source_type == ICS_SOURCE_TYPE,
                            Reminder.source_id == imp_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for r in rems:
                await s.delete(r)
            items = (
                (
                    await s.execute(
                        select(InboxItem).where(
                            InboxItem.source_type == ICS_SOURCE_TYPE,
                            InboxItem.source_id == imp_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for it in items:
                await s.delete(it)
        await s.commit()
        for imp_id in state["imports"]:
            imp = await s.get(IntegrationImport, imp_id)
            if imp:
                await s.delete(imp)
        for sid in state["sources"]:
            src = await s.get(IntegrationSource, sid)
            if src:
                await s.delete(src)
        for tpid in state["trusted"]:
            tp = await s.get(TrustedPath, tpid)
            if tp:
                await s.delete(tp)
        await s.commit()


async def _setup_source(client, db, tmp_path, integ_cleanup, target="reminder"):
    ics = tmp_path / "cal.ics"
    ics.write_text(SAMPLE_ICS, encoding="utf-8")
    tp = await TrustedPathRepository(db).authorize(str(tmp_path), "directory")
    integ_cleanup["trusted"].append(tp.id)
    resp = await client.post(
        "/integrations/sources",
        json={
            "kind": "ics_calendar",
            "title": "测试日历",
            "file_path": str(ics),
            "target": target,
        },
    )
    assert resp.status_code == 201
    source = resp.json()
    integ_cleanup["sources"].append(source["id"])
    return source


@pytest.mark.asyncio
async def test_preview_import_revert_flow(client, db, tmp_path, integ_cleanup):
    source = await _setup_source(client, db, tmp_path, integ_cleanup)

    # 预览（不建对象）
    resp = await client.post("/integrations/preview", json={"source_id": source["id"]})
    assert resp.status_code == 200
    preview = resp.json()
    assert preview["event_count"] == 2
    assert "团队周会" in preview["sample_titles"]
    assert preview["target"] == "reminder"

    # 导入 -> 提醒
    resp = await client.post("/integrations/import", json={"source_id": source["id"]})
    assert resp.status_code == 200
    imp = resp.json()
    assert imp["status"] == "imported"
    assert imp["target_type"] == "reminder"
    integ_cleanup["imports"].append(imp["id"])
    rev = imp["reversal_info_json"]
    assert len(rev["reminder_ids"]) == 2
    assert len(rev["inbox_ids"]) == 0
    reminder_ids = rev["reminder_ids"]

    # 来源追踪：reminder 带 source_type="integration:ics"（用 fresh session 验证）
    async with _fresh() as s:
        rems = (
            (await s.execute(select(Reminder).where(Reminder.id.in_(reminder_ids))))
            .scalars()
            .all()
        )
        assert len(rems) == 2
        assert all(rm.source_type == ICS_SOURCE_TYPE for rm in rems)
        assert all(rm.source_id == imp["id"] for rm in rems)

    # 撤销
    resp = await client.delete(f"/integrations/imports/{imp['id']}")
    assert resp.status_code == 200
    reverted = resp.json()
    assert reverted["status"] == "reverted"
    async with _fresh() as s:
        rems2 = (
            (await s.execute(select(Reminder).where(Reminder.id.in_(reminder_ids))))
            .scalars()
            .all()
        )
        assert len(rems2) == 0


@pytest.mark.asyncio
async def test_import_to_inbox(client, db, tmp_path, integ_cleanup):
    source = await _setup_source(client, db, tmp_path, integ_cleanup, target="inbox")
    resp = await client.post("/integrations/import", json={"source_id": source["id"]})
    assert resp.status_code == 200
    imp = resp.json()
    integ_cleanup["imports"].append(imp["id"])
    assert imp["target_type"] == "inbox"
    rev = imp["reversal_info_json"]
    assert len(rev["inbox_ids"]) == 2
    assert len(rev["reminder_ids"]) == 0


@pytest.mark.asyncio
async def test_unauthorized_path_returns_403(client, integ_cleanup):
    resp = await client.post(
        "/integrations/sources",
        json={
            "kind": "ics_calendar",
            "title": "未授权",
            "file_path": "/nonexistent/unauthorized.ics",
            "target": "reminder",
        },
    )
    assert resp.status_code == 201
    source = resp.json()
    integ_cleanup["sources"].append(source["id"])
    resp = await client.post("/integrations/preview", json={"source_id": source["id"]})
    assert resp.status_code == 403
    resp = await client.post("/integrations/import", json={"source_id": source["id"]})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_sources_and_imports(client, db, tmp_path, integ_cleanup):
    source = await _setup_source(client, db, tmp_path, integ_cleanup)
    resp = await client.post("/integrations/import", json={"source_id": source["id"]})
    imp = resp.json()
    integ_cleanup["imports"].append(imp["id"])

    resp = await client.get("/integrations/sources")
    assert resp.status_code == 200
    assert any(s["id"] == source["id"] for s in resp.json())
    resp = await client.get("/integrations/imports")
    assert resp.status_code == 200
    assert any(i["id"] == imp["id"] for i in resp.json())
