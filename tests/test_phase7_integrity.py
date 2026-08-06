"""第七阶段 M7 测试：数据完整性体检与修复计划。

覆盖（对齐 docs/phase7-plan.md §M7 / docs/phase7-requirements.md §5.7）：
- goal_links 悬空（target_id 失效）能被检测。
- document_collection_items.doc_id 悬空能被检测。
- 修复计划预览（不执行破坏性操作）。
- apply 标记 finding 状态（不删用户业务数据）。
- ignored/resolved 不被重复打扰。
- 路由 GET /maintenance/integrity + POST run/repair-plan/apply。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from personal_assistant.core.integrity import IntegrityService
from personal_assistant.core.models import (
    DataIntegrityFinding,
    DocumentCollection,
    DocumentCollectionItem,
    GoalLink,
)
from personal_assistant.core.repo_goals import PersonalGoalRepository


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


async def _cleanup_findings(db, ref_ids: list[int]):
    stmt = select(DataIntegrityFinding).where(DataIntegrityFinding.ref_id.in_(ref_ids))
    rows = (await db.execute(stmt)).scalars().all()
    for r in rows:
        await db.delete(r)
    await db.commit()


@pytest.mark.asyncio
async def test_goal_link_dangling_detected(db, cleanup):
    goal = await PersonalGoalRepository(db).create(title="完整性测试目标")
    cleanup.append(goal)
    # 悬空链接：target_id 指向不存在的 learning_topic
    link = GoalLink(goal_id=goal.id, target_type="learning_topic", target_id=999987, relation="supports")
    db.add(link)
    await db.commit()
    await db.refresh(link)
    cleanup.append(link)

    svc = IntegrityService(db)
    findings = await svc.check()
    matched = [f for f in findings if f.check_name == "goal_links_dangling" and f.ref_id == link.id]
    assert matched, "应检测到 goal_link 悬空"
    assert matched[0].suggested_action == "relink"
    cleanup.append(matched[0])


@pytest.mark.asyncio
async def test_collection_item_dangling_detected(db, cleanup):
    coll = DocumentCollection(title="悬空集合测试")
    db.add(coll)
    await db.commit()
    await db.refresh(coll)
    cleanup.append(coll)
    item = DocumentCollectionItem(collection_id=coll.id, doc_id=888777, order_index=0)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    cleanup.append(item)

    svc = IntegrityService(db)
    findings = await svc.check()
    matched = [
        f for f in findings
        if f.check_name == "collection_items_dangling" and f.ref_id == item.id
    ]
    assert matched, "应检测到 collection_item 悬空"
    cleanup.append(matched[0])


@pytest.mark.asyncio
async def test_repair_plan_preview_and_apply(db, cleanup):
    goal = await PersonalGoalRepository(db).create(title="修复计划测试目标")
    cleanup.append(goal)
    link = GoalLink(goal_id=goal.id, target_type="agent_task", target_id=776655, relation="evidence")
    db.add(link)
    await db.commit()
    await db.refresh(link)
    cleanup.append(link)

    svc = IntegrityService(db)
    await svc.check()
    plan = await svc.repair_plan()
    assert any(p["finding_id"] for p in plan)
    # 预览项含影响范围与 destructive 标记
    for p in plan:
        assert "impact" in p and "destructive" in p

    # apply（relink -> ignored，不删用户数据）
    my_plan = [p for p in plan if p.get("ref_id") == link.id]
    if my_plan:
        result = await svc.apply(my_plan[0]["finding_id"])
        assert result["ok"] is True
        f = await db.get(DataIntegrityFinding, my_plan[0]["finding_id"])
        assert f.status == "ignored"
        # 不 append 到 cleanup：_cleanup_findings 已负责删除该 finding（避免双删警告）
    await _cleanup_findings(db, [link.id])


@pytest.mark.asyncio
async def test_ignored_not_reflagged(db, cleanup):
    goal = await PersonalGoalRepository(db).create(title="去重测试目标")
    cleanup.append(goal)
    link = GoalLink(goal_id=goal.id, target_type="project", target_id=555444, relation="supports")
    db.add(link)
    await db.commit()
    await db.refresh(link)
    cleanup.append(link)

    svc = IntegrityService(db)
    first = await svc.check()
    f1 = [x for x in first if x.check_name == "goal_links_dangling" and x.ref_id == link.id]
    assert f1
    await svc.set_status(f1[0].id, "ignored")
    # 不 append：_cleanup_findings 负责删除（避免双删警告）

    # 第二次 check：ignored 的不再重复创建新 finding（DB 中仍只有原那一条）
    await svc.check()
    stmt = select(DataIntegrityFinding).where(
        DataIntegrityFinding.check_name == "goal_links_dangling",
        DataIntegrityFinding.ref_id == link.id,
    )
    all_findings = (await db.execute(stmt)).scalars().all()
    assert len(all_findings) == 1, "ignored 的不应被重复创建"
    assert all_findings[0].id == f1[0].id
    assert all_findings[0].status == "ignored"
    await _cleanup_findings(db, [link.id])


# ============ 路由 ============


@pytest.mark.asyncio
async def test_integrity_routes(client, db, cleanup):
    goal = await PersonalGoalRepository(db).create(title="路由体检目标")
    cleanup.append(goal)
    link = GoalLink(goal_id=goal.id, target_type="learning_topic", target_id=333222, relation="supports")
    db.add(link)
    await db.commit()
    await db.refresh(link)
    cleanup.append(link)

    # 运行体检
    r = await client.post("/maintenance/integrity/run")
    assert r.status_code == 200
    assert any(x["check_name"] == "goal_links_dangling" and x["ref_id"] == link.id for x in r.json())

    # 列表
    r = await client.get("/maintenance/integrity")
    assert r.status_code == 200

    # 修复计划
    r = await client.post("/maintenance/repair-plan")
    assert r.status_code == 200

    await _cleanup_findings(db, [link.id])


# ============ delete_orphan 修复（第八阶段审查修复）============


@pytest.mark.asyncio
async def test_apply_delete_orphan_uses_chunk_id_and_resolves(db, cleanup, monkeypatch):
    """delete_orphan 按 chunk_id 删向量（非 doc_id），成功才标记 resolved。"""
    from personal_assistant.core.integrity import IntegrityService, chroma_store

    deleted = {"chunk_id": None}

    async def fake_del(cid):
        deleted["chunk_id"] = cid

    monkeypatch.setattr(chroma_store, "delete_by_chunk_id", fake_del)

    f = DataIntegrityFinding(
        check_name="chroma_mysql_mismatch",
        severity="warning",
        ref_type="chunk",
        ref_id=999,
        suggested_action="delete_orphan",
        status="open",
    )
    db.add(f)
    await db.commit()
    await db.refresh(f)
    cleanup.append(f)

    result = await IntegrityService(db).apply(f.id)
    assert result["ok"] is True
    assert deleted["chunk_id"] == 999  # 按 chunk_id 删，不是 doc_id
    assert result.get("deleted_orphan_chunk_id") == 999
    fresh = await db.get(DataIntegrityFinding, f.id)
    assert fresh.status == "resolved"


@pytest.mark.asyncio
async def test_apply_delete_orphan_failure_keeps_open(db, cleanup, monkeypatch):
    """delete_orphan 删除失败时保持 open，不标记 resolved（避免永久抑制复检）。"""
    from personal_assistant.core.integrity import IntegrityService, chroma_store

    async def fake_del(cid):
        raise RuntimeError("chroma 不可用")

    monkeypatch.setattr(chroma_store, "delete_by_chunk_id", fake_del)

    f = DataIntegrityFinding(
        check_name="chroma_mysql_mismatch",
        severity="warning",
        ref_type="chunk",
        ref_id=888,
        suggested_action="delete_orphan",
        status="open",
    )
    db.add(f)
    await db.commit()
    await db.refresh(f)
    cleanup.append(f)

    result = await IntegrityService(db).apply(f.id)
    assert result["ok"] is False
    fresh = await db.get(DataIntegrityFinding, f.id)
    assert fresh.status == "open"  # 失败不 resolved，可被复检
