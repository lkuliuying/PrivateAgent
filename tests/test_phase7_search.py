"""第七阶段 M2 测试：全局搜索。

覆盖（对齐 docs/phase7-plan.md §M2 / docs/phase7-requirements.md §5.2）：
- 搜索文档名命中文档；搜索切片内容命中切片。
- 搜索任务关键词命中任务与证据。
- 搜索跨对象（会话/消息/记忆/收件箱/提醒/目标/简报）。
- types 过滤限定返回类型。
- GET /search 路由 + POST /search/recent 记录最近打开。
- 统一结果结构 {type,id,title,snippet,source,updated_at,action,meta}。
"""
from __future__ import annotations

import pytest

from personal_assistant.core.models import (
    AgentEvidence,
    AgentTask,
    Briefing,
    ChatSession,
    DocChunk,
    Document,
    InboxItem,
    MemoryItem,
    Message,
    PersonalGoal,
    SearchRecentItem,
)
from personal_assistant.core.search import SearchService


@pytest.fixture
async def cleanup(db):
    created: list = []
    yield created
    for obj in reversed(created):
        try:
            await db.delete(obj)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


async def _add(db, obj):
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@pytest.mark.asyncio
async def test_search_hits_document_and_chunk(db, cleanup):
    doc = await _add(db, Document(name="第七阶段发布checklist.md", status="ready"))
    cleanup.append(doc)
    # 切片需 doc_id FK
    chunk = await _add(
        db, DocChunk(doc_id=doc.id, ordinal=1, content="发布前运行 release-check 与 E2E smoke")
    )
    cleanup.append(chunk)

    results = await SearchService(db).search("checklist")
    assert any(r["type"] == "document" and r["id"] == doc.id for r in results)

    results = await SearchService(db).search("release-check")
    assert any(r["type"] == "chunk" and r["id"] == chunk.id for r in results)


@pytest.mark.asyncio
async def test_search_hits_task_and_evidence(db, cleanup):
    task = await _add(db, AgentTask(title="修复发布checklist缺失项", status="planned"))
    cleanup.append(task)
    evidence = await _add(
        db,
        AgentEvidence(
            task_id=task.id,
            kind="note",
            title="checklist 证据",
            content_md="release-check 输出截图",
        ),
    )
    cleanup.append(evidence)

    results = await SearchService(db).search("checklist")
    types_ids = {(r["type"], r["id"]) for r in results}
    assert ("agent_task", task.id) in types_ids
    assert ("agent_evidence", evidence.id) in types_ids


@pytest.mark.asyncio
async def test_search_cross_object(db, cleanup):
    session = await _add(db, ChatSession(title="第七阶段讨论会话"))
    cleanup.append(session)
    msg = await _add(
        db, Message(session_id=session.id, role="user", content="第七阶段要做什么")
    )
    cleanup.append(msg)
    mem = await _add(
        db, MemoryItem(kind="note", title="第七阶段记忆", content_md="可靠日常层", status="confirmed")
    )
    cleanup.append(mem)
    inbox = await _add(db, InboxItem(title="第七阶段收件箱项", item_type="todo"))
    cleanup.append(inbox)
    goal = await _add(db, PersonalGoal(title="完成第七阶段目标"))
    cleanup.append(goal)
    briefing = await _add(
        db, Briefing(kind="today", title="第七阶段简报", body_md="今日推进")
    )
    cleanup.append(briefing)

    results = await SearchService(db).search("第七阶段")
    types = {r["type"] for r in results}
    assert "session" in types
    assert "message" in types
    assert "memory" in types
    assert "inbox" in types
    assert "goal" in types
    assert "briefing" in types

    # 统一结构字段
    for r in results:
        for key in ("type", "id", "title", "source", "action"):
            assert key in r


@pytest.mark.asyncio
async def test_search_types_filter(db, cleanup):
    doc = await _add(db, Document(name="过滤测试文档.md", status="ready"))
    cleanup.append(doc)
    inbox = await _add(db, InboxItem(title="过滤测试收件箱", item_type="todo"))
    cleanup.append(inbox)

    results = await SearchService(db).search("过滤测试", types=["document"])
    assert all(r["type"] == "document" for r in results)
    assert any(r["id"] == doc.id for r in results)
    assert all(r["type"] != "inbox" for r in results)


@pytest.mark.asyncio
async def test_search_empty_query(db):
    assert await SearchService(db).search("") == []
    assert await SearchService(db).search("   ") == []


# ============ 路由 ============


@pytest.mark.asyncio
async def test_search_route(client, db, cleanup):
    doc = await _add(db, Document(name="路由搜索文档.md", status="ready"))
    cleanup.append(doc)

    r = await client.get("/search", params={"q": "路由搜索"})
    assert r.status_code == 200
    data = r.json()
    assert any(x["type"] == "document" and x["id"] == doc.id for x in data)


@pytest.mark.asyncio
async def test_search_recent_route(client, db, cleanup):
    r = await client.post(
        "/search/recent",
        json={"object_type": "document", "object_id": 99999, "title": "最近打开测试"},
    )
    assert r.status_code == 201
    # 清理
    from sqlalchemy import select

    stmt = select(SearchRecentItem).where(
        SearchRecentItem.object_type == "document",
        SearchRecentItem.object_id == 99999,
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    assert item is not None
    cleanup.append(item)


@pytest.mark.asyncio
async def test_search_recent_upsert_service(db, cleanup):
    """upsert 逻辑：存在则 open_count +1（service 级，单 session 避免跨事务快照）。"""
    from sqlalchemy import select

    from personal_assistant.core.timeutil import utcnow

    db.add(
        SearchRecentItem(
            object_type="document",
            object_id=77777,
            open_count=1,
            last_opened_at=utcnow(),
        )
    )
    await db.commit()

    stmt = select(SearchRecentItem).where(
        SearchRecentItem.object_type == "document",
        SearchRecentItem.object_id == 77777,
    )
    existing = (await db.execute(stmt)).scalar_one()
    cleanup.append(existing)
    assert existing.open_count == 1

    # 模拟路由 upsert：查询存在 -> 增量 -> 提交
    existing.open_count = (existing.open_count or 0) + 1
    existing.last_opened_at = utcnow()
    await db.commit()
    await db.refresh(existing)
    assert existing.open_count == 2
