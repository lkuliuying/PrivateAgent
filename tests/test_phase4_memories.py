"""第四阶段 M1 测试：长期记忆系统。

覆盖：记忆 CRUD、status/enabled/sensitive 过滤、搜索、候选生成（mock LLM）、
使用事件、聊天上下文记忆注入（mock chat_stream + 预置记忆 → done.memories）。

LLM 经 monkeypatch OllamaProvider.chat / chat_stream 返回固定内容，保持确定且快速。
记忆按 id 断言（不依赖列表为空），并用 autouse fixture 清理本测试创建的记忆，
避免共享 MySQL DB 跨测试污染。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.core.models import (
    MemoryConflict,
    MemoryEvent,
    MemoryItem,
    MemoryRevision,
)
from personal_assistant.core.provider import OllamaProvider

# ============ helpers ============


def _mock_chat(monkeypatch, payload) -> None:
    """让 OllamaProvider.chat 返回 payload（str 或可序列化对象）。"""
    text = (
        json.dumps(payload, ensure_ascii=False)
        if isinstance(payload, (list, dict))
        else payload
    )

    async def fake_chat(self, messages):
        return text

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)


def _patch_stream(monkeypatch) -> None:
    """让 chat_stream 产出一个固定 token，chat 返回固定标题。"""

    async def fake_chat_stream(
        self: OllamaProvider, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        yield "好的"

    async def fake_chat(self: OllamaProvider, messages: list[dict[str, str]]) -> str:
        return "标题"

    monkeypatch.setattr(OllamaProvider, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
    return events


async def _read_stream(response) -> list[dict]:
    body = await response.aread()
    return _parse_sse(body.decode("utf-8"))


async def _stream_done(client, session_id: int, message: str) -> dict:
    async with client.stream(
        "POST",
        "/chat/stream",
        json={"session_id": session_id, "message": message, "knowledge_base": False},
    ) as response:
        events = await _read_stream(response)
    return next(e for e in events if e["type"] == "done")


async def _create_memory(client, created: list[int], **overrides) -> dict:
    marker = uuid4().hex
    payload = {
        "kind": "preference",
        "title": f"类比解释偏好 {marker}",
        "content_md": f"我喜欢用类比解释操作系统。{marker}",
        "summary": "偏好用类比解释",
        "tags": ["os", "类比"],
    }
    payload.update(overrides)
    res = await client.post("/memories", json=payload)
    assert res.status_code == 201, res.text
    m = res.json()
    created.append(m["id"])
    return m


@pytest.fixture(autouse=True)
async def _mem_cleanup(client, db):
    """追踪并清理本测试创建的记忆，避免共享 DB 跨测试污染。"""
    created: list[int] = []
    yield created
    if not created:
        return
    await db.execute(
        delete(MemoryConflict).where(
            (MemoryConflict.left_memory_id.in_(created))
            | (MemoryConflict.right_memory_id.in_(created))
        )
    )
    await db.execute(delete(MemoryEvent).where(MemoryEvent.memory_id.in_(created)))
    await db.execute(
        delete(MemoryRevision).where(MemoryRevision.memory_id.in_(created))
    )
    await db.execute(delete(MemoryItem).where(MemoryItem.id.in_(created)))
    await db.commit()


# ============ CRUD ============


@pytest.mark.asyncio
async def test_memory_crud(client, _mem_cleanup):
    m = await _create_memory(client, _mem_cleanup)
    assert m["status"] == "confirmed"
    assert m["enabled"] is True
    assert m["sensitive"] is False
    assert m["memory_version"] == 1
    assert len(m["stable_key"]) == 32
    assert len(m["content_sha256"]) == 64
    assert m["importance"] == pytest.approx(0.5)
    assert m["sensitivity_level"] == "normal"
    mid = m["id"]

    res = await client.get(f"/memories/{mid}")
    assert res.status_code == 200
    assert res.json()["title"].startswith("类比解释偏好")

    res = await client.get("/memories", params={"kind": "preference"})
    assert any(x["id"] == mid for x in res.json())

    res = await client.patch(
        f"/memories/{mid}", json={"title": "类比偏好（更新）", "tags": ["os"]}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "类比偏好（更新）"
    assert body["tags_json"] == ["os"]
    assert body["memory_version"] == 2

    assert (await client.get("/memories/999999")).status_code == 404

    assert (await client.delete(f"/memories/{mid}")).status_code == 204
    assert (await client.get(f"/memories/{mid}")).status_code == 404
    revisions = (await client.get(f"/memories/{mid}/revisions")).json()
    assert [revision["change_type"] for revision in revisions] == [
        "created",
        "edited",
        "deleted",
    ]


@pytest.mark.asyncio
async def test_memory_conflict_api(client, _mem_cleanup):
    left = await _create_memory(client, _mem_cleanup, content_md="部署到 A 区域")
    right = await _create_memory(client, _mem_cleanup, content_md="部署到 B 区域")

    created = await client.post(
        "/memory-conflicts",
        json={
            "left_memory_id": right["id"],
            "right_memory_id": left["id"],
            "reason": "部署区域相互冲突",
        },
    )
    assert created.status_code == 201, created.text
    conflict = created.json()
    assert conflict["left_memory_id"] == min(left["id"], right["id"])
    assert conflict["right_memory_id"] == max(left["id"], right["id"])
    assert any(
        item["id"] == conflict["id"]
        for item in (await client.get("/memory-conflicts")).json()
    )

    resolved = await client.post(
        f"/memory-conflicts/{conflict['id']}/resolve",
        json={"resolution": {"winner_memory_id": right["id"]}},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"


# ============ 搜索 ============


@pytest.mark.asyncio
async def test_memory_search(client, _mem_cleanup):
    m = await _create_memory(
        client, _mem_cleanup, title="进程调度笔记", content_md="进程调度的类比解释"
    )
    res = await client.post("/memories/search", json={"query": "进程调度"})
    assert res.status_code == 200
    assert any(x["id"] == m["id"] for x in res.json())

    res = await client.post(
        "/memories/search", json={"query": "zzzz_not_found_zzzz"}
    )
    assert not any(x["id"] == m["id"] for x in res.json())

    res = await client.get("/memories", params={"search": "进程调度"})
    assert any(x["id"] == m["id"] for x in res.json())


# ============ 使用事件 ============


@pytest.mark.asyncio
async def test_memory_use_event(client, _mem_cleanup):
    m = await _create_memory(client, _mem_cleanup)

    res = await client.post(
        f"/memories/{m['id']}/use", json={"ref_type": "chat_session", "ref_id": 1}
    )
    assert res.status_code == 200

    res = await client.get(f"/memories/{m['id']}/events")
    assert res.status_code == 200
    types = [ev["event_type"] for ev in res.json()]
    assert "created" in types
    assert "used" in types


# ============ 聊天上下文记忆注入 ============


@pytest.mark.asyncio
async def test_memory_injected_into_chat(client, monkeypatch, _mem_cleanup):
    _patch_stream(monkeypatch)
    m = await _create_memory(client, _mem_cleanup)

    sess = (await client.post("/sessions")).json()
    done = await _stream_done(client, sess["id"], "请用类比解释进程调度")

    ids = [mem["id"] for mem in done.get("memories", [])]
    assert m["id"] in ids


@pytest.mark.asyncio
async def test_disabled_memory_not_injected(client, monkeypatch, _mem_cleanup):
    _patch_stream(monkeypatch)
    m = await _create_memory(client, _mem_cleanup)
    res = await client.patch(f"/memories/{m['id']}", json={"enabled": False})
    assert res.status_code == 200

    sess = (await client.post("/sessions")).json()
    done = await _stream_done(client, sess["id"], "请用类比解释进程调度")

    ids = [mem["id"] for mem in done.get("memories", [])]
    assert m["id"] not in ids


@pytest.mark.asyncio
async def test_draft_memory_not_injected(client, monkeypatch, _mem_cleanup):
    _patch_stream(monkeypatch)
    m = await _create_memory(client, _mem_cleanup)
    res = await client.patch(f"/memories/{m['id']}", json={"status": "draft"})
    assert res.status_code == 200
    assert res.json()["status"] == "draft"

    sess = (await client.post("/sessions")).json()
    done = await _stream_done(client, sess["id"], "请用类比解释进程调度")

    ids = [mem["id"] for mem in done.get("memories", [])]
    assert m["id"] not in ids


@pytest.mark.asyncio
async def test_sensitive_memory_not_injected(client, monkeypatch, _mem_cleanup):
    _patch_stream(monkeypatch)
    m = await _create_memory(client, _mem_cleanup, sensitive=True)
    assert m["sensitive"] is True

    sess = (await client.post("/sessions")).json()
    done = await _stream_done(client, sess["id"], "请用类比解释进程调度")

    ids = [mem["id"] for mem in done.get("memories", [])]
    assert m["id"] not in ids


@pytest.mark.asyncio
async def test_unrelated_query_not_injected(client, monkeypatch, _mem_cleanup):
    _patch_stream(monkeypatch)
    m = await _create_memory(client, _mem_cleanup)

    sess = (await client.post("/sessions")).json()
    # 与记忆内容无 CJK 2-gram 重叠
    done = await _stream_done(client, sess["id"], "今天天气怎么样")

    ids = [mem["id"] for mem in done.get("memories", [])]
    assert m["id"] not in ids


# ============ 候选记忆生成（mock LLM）============


@pytest.mark.asyncio
async def test_candidates_from_task(client, db, monkeypatch, _mem_cleanup):
    from personal_assistant.core.models import AgentTask

    task = AgentTask(
        title="修复测试失败",
        goal="修复 pytest 失败用例",
        status="succeeded",
        final_report_md="任务完成：测试失败原因是断言写反，已修复。",
        plan_json={"goal": "修复", "steps": []},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    _mock_chat(
        monkeypatch,
        [
            {
                "kind": "project",
                "title": "项目用 pytest 跑测试",
                "content_md": "该项目使用 pytest -q 作为测试命令。",
                "summary": "测试命令",
                "confidence": 0.9,
            }
        ],
    )

    res = await client.post(
        "/memories/candidates",
        json={"source_type": "agent_task", "source_id": task.id},
    )
    assert res.status_code == 201, res.text
    items = res.json()
    assert len(items) == 1
    it = items[0]
    assert it["status"] == "draft"
    assert it["source_type"] == "agent_task"
    assert it["source_id"] == task.id
    assert it["kind"] == "project"
    _mem_cleanup.extend(it["id"] for it in items)


@pytest.mark.asyncio
async def test_candidates_from_chat(client, db, monkeypatch, _mem_cleanup):
    from personal_assistant.core.models import Message

    sess = (await client.post("/sessions")).json()
    sid = sess["id"]
    # 直接写入两条消息（绕过 LLM 流式），作为候选抽取的对话来源
    db.add_all(
        [
            Message(session_id=sid, role="user", content="我习惯用 TypeScript 写前端。"),
            Message(
                session_id=sid,
                role="assistant",
                content="已记下你偏好 TypeScript。",
            ),
        ]
    )
    await db.commit()

    _mock_chat(
        monkeypatch,
        [
            {
                "kind": "preference",
                "title": "偏好 TypeScript",
                "content_md": "用户习惯用 TypeScript 编写前端代码。",
                "summary": "前端用 TypeScript",
            }
        ],
    )

    res = await client.post(
        "/memories/candidates",
        json={"source_type": "chat_session", "source_id": sid},
    )
    assert res.status_code == 201, res.text
    items = res.json()
    assert len(items) == 1
    assert items[0]["status"] == "draft"
    assert items[0]["source_type"] == "chat_session"
    _mem_cleanup.extend(it["id"] for it in items)


@pytest.mark.asyncio
async def test_candidate_confirm_flow(client, _mem_cleanup):
    """draft 候选确认后转 confirmed。"""
    m = await _create_memory(client, _mem_cleanup)
    assert m["status"] == "confirmed"
    # 模拟候选：先转 draft，再确认
    res = await client.patch(f"/memories/{m['id']}", json={"status": "draft"})
    assert res.json()["status"] == "draft"
    res = await client.patch(f"/memories/{m['id']}", json={"status": "confirmed"})
    assert res.json()["status"] == "confirmed"
