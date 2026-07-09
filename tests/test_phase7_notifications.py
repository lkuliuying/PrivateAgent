"""第七阶段 M4 测试：统一通知中心。

覆盖（对齐 docs/phase7-plan.md §M4 / docs/phase7-requirements.md §5.4）：
- NotificationService notify/list/mark/mark_all_read CRUD + 状态流转。
- GET/POST/PATCH /notifications 路由 + read-all。
- 通知只存摘要（不存敏感正文字段）。
"""
from __future__ import annotations

import pytest

from personal_assistant.core.models import AppNotification
from personal_assistant.core.notifications import NotificationService


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


@pytest.mark.asyncio
async def test_notification_service_crud(db, cleanup):
    svc = NotificationService(db)
    n = await svc.notify(
        kind="import",
        title="文档导入完成：test.md",
        level="success",
        message="12 个切片已入库",
        source_type="document",
        source_id=42,
    )
    cleanup.append(n)
    assert n.status == "unread"
    assert n.read_at is None

    listed = await svc.list()
    assert any(x.id == n.id for x in listed)

    await svc.mark(n.id, "read")
    fresh = await svc.repo.get(n.id)
    assert fresh.status == "read"
    assert fresh.read_at is not None


@pytest.mark.asyncio
async def test_notification_mark_all_read(db, cleanup):
    svc = NotificationService(db)
    n1 = await svc.notify(kind="import", title="t1", level="info")
    n2 = await svc.notify(kind="backup", title="t2", level="success")
    cleanup.append(n1)
    cleanup.append(n2)

    count = await svc.mark_all_read()
    assert count >= 2
    unread = await svc.list(status="unread")
    assert all(x.id not in {n1.id, n2.id} for x in unread)


@pytest.mark.asyncio
async def test_notification_list_filter(db, cleanup):
    svc = NotificationService(db)
    a = await svc.notify(kind="import", title="a", level="error")
    b = await svc.notify(kind="backup", title="b", level="success")
    cleanup.append(a)
    cleanup.append(b)

    imports = await svc.list(kind="import")
    assert all(x.kind == "import" for x in imports)
    assert any(x.id == a.id for x in imports)
    assert all(x.id != b.id for x in imports)


@pytest.mark.asyncio
async def test_notification_no_sensitive_fields(db, cleanup):
    """通知模型不含敏感正文字段（聊天全文/文档原文/敏感记忆）。"""
    svc = NotificationService(db)
    n = await svc.notify(kind="import", title="t", level="info")
    cleanup.append(n)
    cols = {c.name for c in n.__table__.columns}
    # 不存完整 prompt/聊天/文档原文/记忆正文
    assert "prompt" not in cols
    assert "chat_content" not in cols
    assert "doc_content" not in cols
    assert "memory_content" not in cols
    # 只存摘要 message
    assert "message" in cols


# ============ 路由 ============


@pytest.mark.asyncio
async def test_notification_routes(client, db, cleanup):
    # POST 创建
    r = await client.post(
        "/notifications",
        json={"kind": "import", "title": "路由通知", "level": "success", "message": "ok"},
    )
    assert r.status_code == 201
    nid = r.json()["id"]
    cleanup.append(await db.get(AppNotification, nid))

    # GET 列表
    r = await client.get("/notifications", params={"kind": "import"})
    assert r.status_code == 200
    assert any(x["id"] == nid for x in r.json())

    # PATCH 标记已读
    r = await client.patch(f"/notifications/{nid}", json={"status": "read"})
    assert r.status_code == 200
    assert r.json()["status"] == "read"

    # read-all
    r = await client.post("/notifications/read-all")
    assert r.status_code == 200
    assert "marked" in r.json()
