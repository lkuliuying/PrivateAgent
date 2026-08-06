"""第四阶段 M3 测试：文档工作台 2.0（集合 / 结构化抽取 / 模板报告 / OCR）。

覆盖：集合 CRUD、成员增删、单文档抽取、集合级跨文档抽取、模板报告、OCR stub、
来源溯源（source_refs 含 doc_id/chunk_ordinal）、缺失文档 404。

文档/切片直接经 db 建立以避免导入流程；抽取/模板 monkeypatch OllamaProvider.chat
返回固定 JSON/Markdown。autouse fixture 清理集合（CASCADE 成员）、文档（CASCADE 切片）
与抽取（软引用，需显式删）。按 id 断言避免共享 DB 污染。
"""
from __future__ import annotations

import json

import pytest

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


async def _make_doc(
    db,
    doc_ids: list[int],
    *,
    name: str = "OS 论文",
    chunks: list[tuple[str, str]] | None = None,
) -> int:
    from personal_assistant.core.models import DocChunk, Document

    doc = Document(name=name, status="ready", doc_type="markdown")
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    doc_ids.append(doc.id)
    for i, (head, content) in enumerate(
        chunks if chunks is not None else [("进程", "进程是程序运行的实例")], start=1
    ):
        db.add(DocChunk(doc_id=doc.id, ordinal=i, heading=head, content=content))
    await db.commit()
    return doc.id


async def _make_collection(client, coll_ids: list[int], title: str = "集合A") -> int:
    res = await client.post(
        "/document-collections", json={"title": title, "goal": "测试目标"}
    )
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    coll_ids.append(cid)
    return cid


@pytest.fixture(autouse=True)
async def _cleanup(client, db):
    """清理集合（CASCADE 成员）、文档（CASCADE 切片）、抽取（软引用显式删）。"""
    coll_ids: list[int] = []
    doc_ids: list[int] = []
    ext_ids: list[int] = []
    yield coll_ids, doc_ids, ext_ids
    from personal_assistant.core.models import (
        Document,
        DocumentCollection,
        DocumentExtraction,
    )

    for eid in ext_ids:
        e = await db.get(DocumentExtraction, eid)
        if e:
            await db.delete(e)
    for cid in coll_ids:
        c = await db.get(DocumentCollection, cid)
        if c:
            await db.delete(c)  # cascade items
    for did in doc_ids:
        d = await db.get(Document, did)
        if d:
            await db.delete(d)  # cascade chunks
    await db.commit()


# ============ 集合 CRUD ============


@pytest.mark.asyncio
async def test_collection_crud(client, _cleanup):
    coll_ids, _, _ = _cleanup
    res = await client.post(
        "/document-collections", json={"title": "集合1", "goal": "G", "tags": ["t1"]}
    )
    assert res.status_code == 201, res.text
    c = res.json()
    coll_ids.append(c["id"])
    assert c["title"] == "集合1"
    assert c["tags_json"] == ["t1"]

    res = await client.get("/document-collections")
    assert any(x["id"] == c["id"] for x in res.json())

    res = await client.get(f"/document-collections/{c['id']}")
    assert res.status_code == 200
    assert res.json()["items"] == []

    res = await client.patch(f"/document-collections/{c['id']}", json={"title": "集合1改"})
    assert res.json()["title"] == "集合1改"

    assert (await client.delete(f"/document-collections/{c['id']}")).status_code == 204
    assert (await client.get(f"/document-collections/{c['id']}")).status_code == 404
    coll_ids.clear()


# ============ 成员增删 ============


@pytest.mark.asyncio
async def test_collection_items(client, db, _cleanup):
    coll_ids, doc_ids, _ = _cleanup
    did = await _make_doc(db, doc_ids, name="成员文档")
    cid = await _make_collection(client, coll_ids)

    res = await client.post(f"/document-collections/{cid}/items", json={"doc_id": did})
    assert res.status_code == 201, res.text
    assert res.json()["doc_name"] == "成员文档"

    # 重复添加 → 409
    res2 = await client.post(f"/document-collections/{cid}/items", json={"doc_id": did})
    assert res2.status_code == 409

    detail = (await client.get(f"/document-collections/{cid}")).json()
    assert len(detail["items"]) == 1
    assert detail["items"][0]["doc_id"] == did

    # 移除
    assert (
        await client.delete(f"/document-collections/{cid}/items/{did}")
    ).status_code == 204
    detail = (await client.get(f"/document-collections/{cid}")).json()
    assert len(detail["items"]) == 0
    # 再移除 → 404
    assert (
        await client.delete(f"/document-collections/{cid}/items/{did}")
    ).status_code == 404


# ============ 单文档抽取 ============


@pytest.mark.asyncio
async def test_extract_terms(client, db, monkeypatch, _cleanup):
    coll_ids, doc_ids, ext_ids = _cleanup
    did = await _make_doc(
        db,
        doc_ids,
        chunks=[("进程", "进程是程序运行的实例"), ("调度", "调度器分配 CPU")],
    )
    _mock_chat(
        monkeypatch,
        [{"term": "进程", "definition": "程序运行的实例", "source": "片段1"}],
    )
    res = await client.post(f"/documents/{did}/extract", json={"kind": "terms"})
    assert res.status_code == 200, res.text
    ext = res.json()
    ext_ids.append(ext["id"])
    assert ext["kind"] == "terms"
    assert ext["doc_id"] == did
    items = ext["content_json"]["items"]
    assert any(it["term"] == "进程" for it in items)
    # 来源溯源：source_refs 含两片段，带 doc_id/chunk_ordinal
    refs = ext["source_refs_json"]
    assert len(refs) == 2
    assert {r["doc_id"] for r in refs} == {did}
    assert {r["chunk_ordinal"] for r in refs} == {1, 2}


# ============ 集合级跨文档抽取 ============


@pytest.mark.asyncio
async def test_extract_collection(client, db, monkeypatch, _cleanup):
    coll_ids, doc_ids, ext_ids = _cleanup
    d1 = await _make_doc(db, doc_ids, name="文档A", chunks=[("A1", "内容A1")])
    d2 = await _make_doc(db, doc_ids, name="文档B", chunks=[("B1", "内容B1")])
    cid = await _make_collection(client, coll_ids)
    await client.post(f"/document-collections/{cid}/items", json={"doc_id": d1})
    await client.post(f"/document-collections/{cid}/items", json={"doc_id": d2})

    _mock_chat(monkeypatch, [{"term": "X", "definition": "Y", "source": "文档A 片段1"}])
    res = await client.post(
        f"/document-collections/{cid}/extract", json={"kind": "terms"}
    )
    assert res.status_code == 200, res.text
    ext = res.json()
    ext_ids.append(ext["id"])
    assert ext["collection_id"] == cid
    refs = ext["source_refs_json"]
    ref_docs = {r["doc_id"] for r in refs}
    assert d1 in ref_docs and d2 in ref_docs  # 跨两文档溯源


# ============ 模板报告 ============


@pytest.mark.asyncio
async def test_template_report(client, db, monkeypatch, _cleanup):
    coll_ids, doc_ids, ext_ids = _cleanup
    did = await _make_doc(db, doc_ids, chunks=[("进程", "进程概念")])
    _mock_chat(monkeypatch, "# 学习笔记\n\n## 进程\n\n进程是程序运行的实例。")
    res = await client.post(
        "/documents/template-report",
        json={"template": "study_note", "doc_ids": [did]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    ext_ids.append(body["extraction"]["id"])
    assert "学习笔记" in body["report_md"]
    assert body["extraction"]["kind"] == "template_report"
    assert body["extraction"]["content_json"]["template"] == "study_note"
    assert body["extraction"]["doc_id"] is None  # 模板报告不绑单文档


# ============ OCR stub ============


@pytest.mark.asyncio
async def test_ocr_stub(client, db, _cleanup):
    coll_ids, doc_ids, ext_ids = _cleanup

    did = await _make_doc(db, doc_ids)
    res = await client.post(f"/documents/{did}/ocr")
    assert res.status_code == 200, res.text
    body = res.json()
    # 第七阶段 M3：OCR 不再返回 unavailable 桩，而是创建 OCR job（status=pending）。
    assert body["status"] == "pending"
    assert body["job_id"] is not None
    assert body["doc_id"] == did


# ============ 来源溯源结构 ============


@pytest.mark.asyncio
async def test_source_refs_structure(client, db, monkeypatch, _cleanup):
    coll_ids, doc_ids, ext_ids = _cleanup
    did = await _make_doc(
        db, doc_ids, name="溯源文档", chunks=[("标题甲", "内容甲")]
    )
    _mock_chat(monkeypatch, [{"term": "甲", "definition": "d", "source": "片段1"}])
    res = await client.post(f"/documents/{did}/extract", json={"kind": "terms"})
    ext = res.json()
    ext_ids.append(ext["id"])
    ref = ext["source_refs_json"][0]
    # 来源项含完整溯源字段
    assert ref["doc_id"] == did
    assert ref["doc_name"] == "溯源文档"
    assert ref["chunk_ordinal"] == 1
    assert ref["heading"] == "标题甲"


# ============ 缺失文档 404 ============


@pytest.mark.asyncio
async def test_extract_missing_doc_404(client):
    res = await client.post("/documents/999999/extract", json={"kind": "terms"})
    assert res.status_code == 404


# ============ review 修复回归 ============


@pytest.mark.asyncio
async def test_template_report_retrievable(client, db, monkeypatch, _cleanup):
    """doc_ids 路径模板报告不绑单文档，靠 GET /document-extractions/{id} 检索。"""
    coll_ids, doc_ids, ext_ids = _cleanup
    did = await _make_doc(db, doc_ids, chunks=[("进程", "进程概念")])
    _mock_chat(monkeypatch, "# 学习笔记\n\n内容。")
    res = await client.post(
        "/documents/template-report",
        json={"template": "study_note", "doc_ids": [did]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    eid = body["extraction"]["id"]
    ext_ids.append(eid)
    assert body["extraction"]["content_json"]["doc_ids"] == [did]

    res2 = await client.get(f"/document-extractions/{eid}")
    assert res2.status_code == 200
    assert res2.json()["id"] == eid
    assert (await client.get("/document-extractions/999999")).status_code == 404


@pytest.mark.asyncio
async def test_extract_empty_doc_guard(client, db, _cleanup):
    """无切片文档抽取应 400（空上下文守卫，含 2+ 空文档 join 不再被绕过）。"""
    coll_ids, doc_ids, ext_ids = _cleanup
    did = await _make_doc(db, doc_ids, chunks=[])  # 无切片
    res = await client.post(f"/documents/{did}/extract", json={"kind": "terms"})
    assert res.status_code == 400
    assert "索引" in res.json()["detail"]


@pytest.mark.asyncio
async def test_meeting_minutes_template(client, db, monkeypatch, _cleanup):
    """会议纪要模板可用（§5.3 第 5 种模板）。"""
    coll_ids, doc_ids, ext_ids = _cleanup
    did = await _make_doc(db, doc_ids, chunks=[("议题", "讨论内容")])
    _mock_chat(monkeypatch, "# 会议纪要\n\n## 决议\n\n通过。")
    res = await client.post(
        "/documents/template-report",
        json={"template": "meeting_minutes", "doc_ids": [did]},
    )
    assert res.status_code == 200, res.text
    ext_ids.append(res.json()["extraction"]["id"])
    assert res.json()["extraction"]["content_json"]["template"] == "meeting_minutes"


@pytest.mark.asyncio
async def test_collection_title_validation(client, _cleanup):
    """PATCH 集合标题与 POST 一致：空→422，超长→截断 255。"""
    coll_ids, _, _ = _cleanup
    cid = await _make_collection(client, coll_ids, "T")
    assert (
        await client.patch(f"/document-collections/{cid}", json={"title": ""})
    ).status_code == 422
    res = await client.patch(
        f"/document-collections/{cid}", json={"title": "x" * 300}
    )
    assert res.status_code == 200
    assert len(res.json()["title"]) == 255
