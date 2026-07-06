"""第三阶段 M3 测试：学习系统。

覆盖：主题 CRUD、路线生成、笔记保存、练习生成、答题批改、复习卡片、工具注册。
LLM 经 monkeypatch OllamaProvider.chat 返回 JSON；生成类用 source_doc_ids 避免触发检索嵌入。
"""
from __future__ import annotations

import json

import pytest

from personal_assistant.core.provider import OllamaProvider
from personal_assistant.core.tools import default_registry


def _mock_chat(monkeypatch, payload):
    """让 OllamaProvider.chat 返回 payload（str 或对象）。"""
    if isinstance(payload, (list, dict)):
        text = json.dumps(payload, ensure_ascii=False)
    else:
        text = payload

    async def fake_chat(self, messages):
        return text

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)


async def _make_doc_with_chunk(db, content: str = "操作系统是管理硬件资源的软件。"):
    from personal_assistant.core.models import DocChunk, Document

    doc = Document(name="learn.md", status="ready", enabled=True, chunk_count=1)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    chunk = DocChunk(doc_id=doc.id, ordinal=1, content=content)
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return doc, chunk


# ============ 工具注册 ============

def test_learning_tools_registered():
    """M3 五个学习工具注册，风险等级正确（写 DB 的均为 confirm）。"""
    p = default_registry.get("create_learning_plan")
    n = default_registry.get("save_learning_note")
    q = default_registry.get("generate_quiz")
    g = default_registry.get("grade_quiz_answer")
    c = default_registry.get("create_review_cards")
    assert p and p.risk_level == "confirm"
    assert n and n.risk_level == "confirm"
    assert q and q.risk_level == "confirm"
    assert g and g.risk_level == "confirm"
    assert c and c.risk_level == "confirm"


# ============ 主题 CRUD ============

@pytest.mark.asyncio
async def test_topic_crud(client):
    res = await client.post(
        "/learning/topics",
        json={"title": "操作系统", "goal": "理解进程与内存", "level": "中级"},
    )
    assert res.status_code == 201, res.text
    t = res.json()
    assert t["title"] == "操作系统"
    assert t["status"] == "active"
    tid = t["id"]

    # list
    res = await client.get("/learning/topics")
    assert any(tt["id"] == tid for tt in res.json())

    # get
    res = await client.get(f"/learning/topics/{tid}")
    assert res.json()["goal"] == "理解进程与内存"

    # update
    res = await client.patch(
        f"/learning/topics/{tid}", json={"status": "paused", "tags": ["os", "kernel"]}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "paused"
    assert "os" in (body["tags_json"] or [])


# ============ 路线生成 ============

@pytest.mark.asyncio
async def test_generate_plan(client, db, monkeypatch):
    doc, _chunk = await _make_doc_with_chunk(db)
    tid = (
        await client.post("/learning/topics", json={"title": "OS基础"})
    ).json()["id"]
    _mock_chat(
        monkeypatch,
        [
            {"title": "进程概念", "summary": "进程是程序运行的实例"},
            {"title": "线程", "summary": "线程是进程内的执行单元"},
            {"title": "内存管理", "summary": "虚拟内存与分页"},
        ],
    )
    res = await client.post(
        f"/learning/topics/{tid}/plan",
        json={"source_doc_ids": [doc.id]},
    )
    assert res.status_code == 200, res.text
    nodes = res.json()
    assert len(nodes) == 3
    assert nodes[0]["title"] == "进程概念"
    assert nodes[0]["topic_id"] == tid

    # nodes 持久化
    res2 = await client.get(f"/learning/topics/{tid}/nodes")
    assert len(res2.json()) == 3


# ============ 笔记 ============

@pytest.mark.asyncio
async def test_save_and_list_note(client):
    tid = (
        await client.post("/learning/topics", json={"title": "笔记主题"})
    ).json()["id"]
    res = await client.post(
        "/learning/notes",
        json={
            "topic_id": tid,
            "title": "进程笔记",
            "body_md": "# 进程\n进程有就绪/运行/阻塞三态",
            "source_refs": [{"doc_name": "learn.md", "ordinal": 1}],
        },
    )
    assert res.status_code == 201, res.text
    note_id = res.json()["id"]

    res2 = await client.get("/learning/notes", params={"topic_id": tid})
    assert any(n["id"] == note_id for n in res2.json())


# ============ 练习生成 + 批改 ============

@pytest.mark.asyncio
async def test_generate_quiz_and_grade(client, db, monkeypatch):
    doc, _chunk = await _make_doc_with_chunk(db)
    tid = (
        await client.post("/learning/topics", json={"title": "测验主题"})
    ).json()["id"]
    _mock_chat(
        monkeypatch,
        [
            {"question": "进程的三态是？", "answer": "就绪、运行、阻塞", "explanation": "基本状态"},
            {"question": "什么是线程？", "answer": "进程内执行单元", "explanation": "轻量"},
        ],
    )
    res = await client.post(
        f"/learning/topics/{tid}/quizzes", json={"source_doc_ids": [doc.id], "count": 2}
    )
    assert res.status_code == 200, res.text
    quizzes = res.json()
    assert len(quizzes) == 2
    qid = quizzes[0]["id"]

    # 批改
    _mock_chat(
        monkeypatch, {"result": "correct", "explanation": "回答完整"}
    )
    res2 = await client.post(
        "/learning/quiz-attempts",
        json={"quiz_id": qid, "user_answer": "就绪、运行、阻塞"},
    )
    assert res2.status_code == 200, res2.text
    body = res2.json()
    assert body["result"] == "correct"
    assert body["attempt"]["result"] == "correct"
    assert body["attempt"]["quiz_id"] == qid


@pytest.mark.asyncio
async def test_grade_nonexistent_quiz(client, monkeypatch):
    _mock_chat(monkeypatch, {"result": "wrong", "explanation": "x"})
    res = await client.post(
        "/learning/quiz-attempts",
        json={"quiz_id": 999999, "user_answer": "x"},
    )
    assert res.status_code == 404


# ============ 复习卡片 ============

@pytest.mark.asyncio
async def test_create_cards(client, db, monkeypatch):
    doc, _chunk = await _make_doc_with_chunk(db)
    tid = (
        await client.post("/learning/topics", json={"title": "卡片主题"})
    ).json()["id"]
    _mock_chat(
        monkeypatch,
        [
            {"front": "进程是什么？", "back": "程序运行的实例"},
            {"front": "线程是什么？", "back": "进程内执行单元"},
        ],
    )
    res = await client.post(
        f"/learning/topics/{tid}/cards", json={"source_doc_ids": [doc.id], "count": 2}
    )
    assert res.status_code == 200, res.text
    cards = res.json()
    assert len(cards) == 2
    assert cards[0]["front"]
    assert cards[0]["topic_id"] == tid


# ============ 解析健壮性 ============

def test_parse_json_array_with_fence_and_prose():
    """LLM 输出带 markdown 围栏与散文时仍能提取数组。"""
    from personal_assistant.core.learning import parse_json_array

    raw = '好的，这是路线：\n```json\n[{"title":"A","summary":"a"},{"title":"B","summary":"b"}]\n```\n希望有帮助。'
    arr = parse_json_array(raw)
    assert len(arr) == 2
    assert arr[0]["title"] == "A"


def test_parse_json_array_empty_on_garbage():
    from personal_assistant.core.learning import parse_json_array

    assert parse_json_array("无 JSON") == []
