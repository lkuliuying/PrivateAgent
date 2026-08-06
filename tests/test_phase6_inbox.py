"""第六阶段 M2 测试：今日路由 + 统一收件箱。

覆盖：
- GET /today 返回完整快照结构。
- inbox CRUD（POST/GET 列表/GET 详情/PATCH/DELETE）。
- 状态流转 complete/snooze/ignore/archive：handled_at 写入，原始来源字段不变。
- to-task：生成 plan_draft 任务，inbox 标记 done 并 link target。
- to-reminder：生成到期提醒，inbox 标记 done 并 link target，且出现在 /today。

共享 MySQL DB：inbox 用 API DELETE 清理；to-task/to-reminder 产生的 task/reminder
用 db 直接按 id 删除（同库），避免跨测试污染。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete

from personal_assistant.core.models import AgentTask, InboxItem, Reminder
from personal_assistant.core.timeutil import utcnow

# ============ fixtures ============


@pytest.fixture
async def cleanup(db):
    """按 (Model, id) 清理 to-task/to-reminder 产生的 task/reminder（同库直删）。"""
    to_delete: list[tuple[type, int]] = []
    yield to_delete
    for model, oid in reversed(to_delete):
        try:
            await db.execute(delete(model).where(model.id == oid))
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


async def _create_inbox(client, **overrides) -> dict:
    payload = {
        "title": "整理 MySQL 索引笔记",
        "item_type": "todo",
        "priority": "high",
    }
    payload.update(overrides)
    res = await client.post("/inbox", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# ============ /today 路由 ============


@pytest.mark.asyncio
async def test_today_route_structure(client):
    res = await client.get("/today")
    assert res.status_code == 200, res.text
    snap = res.json()
    assert "generated_at" in snap
    assert "summary" in snap
    for key in (
        "due_cards",
        "attention_tasks",
        "failed_activities",
        "draft_memories",
        "due_reminders",
        "open_inbox",
    ):
        assert key in snap["summary"]
    # 内部一致性
    assert snap["summary"]["open_inbox"] == len(snap["open_inbox"])
    assert "backup" in snap


# ============ inbox CRUD ============


@pytest.mark.asyncio
async def test_inbox_crud(client):
    item = await _create_inbox(client, body_md="复习覆盖索引与联合索引")
    iid = item["id"]
    assert item["status"] == "open"
    assert item["priority"] == "high"

    # 列表 + 过滤
    res = await client.get("/inbox", params={"status": "open"})
    assert any(x["id"] == iid for x in res.json())
    res = await client.get("/inbox", params={"priority": "high"})
    assert any(x["id"] == iid for x in res.json())

    # 详情
    assert (await client.get(f"/inbox/{iid}")).json()["title"] == "整理 MySQL 索引笔记"

    # 404
    assert (await client.get("/inbox/999999")).status_code == 404

    # 更新
    res = await client.patch(
        f"/inbox/{iid}", json={"title": "整理索引（更新）", "priority": "urgent"}
    )
    assert res.status_code == 200
    assert res.json()["title"] == "整理索引（更新）"
    assert res.json()["priority"] == "urgent"

    # 删除
    assert (await client.delete(f"/inbox/{iid}")).status_code == 204
    assert (await client.get(f"/inbox/{iid}")).status_code == 404


# ============ 状态流转：不删原始来源 ============


@pytest.mark.asyncio
async def test_inbox_status_transitions(client):
    item = await _create_inbox(
        client, source_type="chat_message", source_id=77, body_md="来源正文"
    )
    iid = item["id"]

    # 完成：补 handled_at，来源字段不变
    res = await client.patch(f"/inbox/{iid}", json={"status": "done"})
    body = res.json()
    assert body["status"] == "done"
    assert body["handled_at"] is not None
    assert body["source_type"] == "chat_message"
    assert body["source_id"] == 77
    assert body["body_md"] == "来源正文"  # 原始内容未被触碰

    # 稍后：status=snoozed + due_at 延后
    future = (utcnow() + timedelta(days=1)).replace(microsecond=0).isoformat()
    res = await client.patch(
        f"/inbox/{iid}", json={"status": "snoozed", "due_at": future}
    )
    assert res.json()["status"] == "snoozed"

    # 忽略 / 归档同样补 handled_at
    res = await client.patch(f"/inbox/{iid}", json={"status": "ignored"})
    assert res.json()["handled_at"] is not None
    res = await client.patch(f"/inbox/{iid}", json={"status": "archived"})
    assert res.json()["status"] == "archived"

    await client.delete(f"/inbox/{iid}")


# ============ to-task ============


@pytest.mark.asyncio
async def test_inbox_to_task(client, cleanup):
    item = await _create_inbox(client, body_md="把这份笔记整理成复习卡片")
    iid = item["id"]

    res = await client.post(f"/inbox/{iid}/to-task")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "done"
    assert body["target_type"] == "agent_task"
    task_id = body["target_id"]
    assert task_id is not None
    cleanup.append((AgentTask, task_id))
    cleanup.append((InboxItem, iid))

    # 任务为 plan_draft，plan_json 携带 inbox 来源
    task = (await client.get(f"/agent-tasks/{task_id}")).json()
    assert task["status"] == "plan_draft"
    assert task["plan_json"]["source"] == {"type": "inbox_item", "id": iid}
    assert task["plan_json"]["steps"] == []
    assert task["title"] == "整理 MySQL 索引笔记"

    # 已出现在今日待关注任务
    snap = (await client.get("/today")).json()
    assert any(t["id"] == task_id for t in snap["attention_tasks"])


# ============ to-reminder ============


@pytest.mark.asyncio
async def test_inbox_to_reminder(client, cleanup):
    # 用过去 due_at：to-reminder 沿用 item.due_at，生成到期提醒进 /today
    past = (utcnow() - timedelta(hours=1)).replace(microsecond=0).isoformat()
    item = await _create_inbox(client, due_at=past, item_type="reminder")
    iid = item["id"]

    res = await client.post(f"/inbox/{iid}/to-reminder", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "done"
    assert body["target_type"] == "reminder"
    reminder_id = body["target_id"]
    assert reminder_id is not None
    cleanup.append((Reminder, reminder_id))
    cleanup.append((InboxItem, iid))

    # 到期提醒出现在今日
    snap = (await client.get("/today")).json()
    assert any(r["id"] == reminder_id for r in snap["due_reminders"])

    # 自定义 due_at 覆盖
    item2 = await _create_inbox(client, item_type="todo")
    future = (utcnow() + timedelta(days=2)).replace(microsecond=0).isoformat()
    res = await client.post(
        f"/inbox/{item2['id']}/to-reminder", json={"due_at": future}
    )
    assert res.status_code == 200
    cleanup.append((Reminder, res.json()["target_id"]))
    cleanup.append((InboxItem, item2["id"]))
