"""第三阶段 M2 测试：混合检索 + 命中原因 + 元数据过滤。

覆盖：
- 精确关键词查询命中含原词的片段（关键词召回）。
- 禁用文档在关键词召回中也被排除。
- 向量+关键词同时命中 → matched_via 含两者（RRF 融合）。
- format_sources 含命中原因与分数。
- /documents 支持 doc_type 元数据过滤。
- 导入时自动推断 doc_type。
"""
from __future__ import annotations

import pytest

from personal_assistant.core.provider import OllamaProvider
from personal_assistant.core.rag import RagService
from personal_assistant.core import store_chroma


def _patch_embed_one(monkeypatch):
    """mock OllamaProvider.embed_one 返回固定向量（必须 async，与原方法一致）。"""
    async def fake(self, text):
        return [0.0] * 8

    monkeypatch.setattr(OllamaProvider, "embed_one", fake)


def _patch_query(monkeypatch, chunk_ids):
    """mock chroma_store.query 返回指定 chunk_id 列表（必须是 async，与原方法一致）。"""
    async def fake(embedding, top_k=5):
        return list(chunk_ids)

    monkeypatch.setattr(store_chroma.chroma_store, "query", fake)


async def _make_doc_chunk(db, *, content: str, enabled: bool = True, doc_type: str | None = None):
    from personal_assistant.core.models import DocChunk, Document

    doc = Document(
        name="test.md", status="ready", enabled=enabled, chunk_count=1, doc_type=doc_type
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    chunk = DocChunk(
        doc_id=doc.id, ordinal=1, content=content, heading=content[:32], bm25_text=content
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return doc, chunk


# ============ 关键词召回 ============

@pytest.mark.asyncio
async def test_keyword_recall_exact_match(db, monkeypatch):
    """精确关键词查询命中含原词的片段；命中原因含 keyword。"""
    doc, chunk = await _make_doc_chunk(db, content="def import_document(doc_id): pass")
    # 屏蔽向量召回，隔离关键词路径
    _patch_query(monkeypatch, [])
    _patch_embed_one(monkeypatch)
    try:
        svc = RagService(db)
        results = await svc.retrieve("import_document", top_k=5)
        assert len(results) >= 1
        assert results[0].chunk_id == chunk.id
        assert "keyword" in (results[0].matched_via or [])
        assert "import_document" in (results[0].matched_keywords or [])
    finally:
        await db.delete(chunk)
        await db.delete(doc)
        await db.commit()


@pytest.mark.asyncio
async def test_disabled_excluded_from_keyword_recall(db, monkeypatch):
    """禁用文档的切片在关键词召回中也被排除；启用后恢复。"""
    doc, chunk = await _make_doc_chunk(
        db, content="unique_secret_term_xyz marker", enabled=False
    )
    _patch_query(monkeypatch, [])
    _patch_embed_one(monkeypatch)
    svc = RagService(db)
    try:
        assert await svc.retrieve("unique_secret_term_xyz", top_k=5) == []
        doc.enabled = True
        await db.commit()
        results = await svc.retrieve("unique_secret_term_xyz", top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == chunk.id
    finally:
        await db.delete(chunk)
        await db.delete(doc)
        await db.commit()


# ============ RRF 融合 ============

@pytest.mark.asyncio
async def test_vector_and_keyword_both_match(db, monkeypatch):
    """向量与关键词同时命中同一切片 → matched_via 含两者。"""
    doc, chunk = await _make_doc_chunk(db, content="config_value_alpha = 42")
    # 向量召回命中该 chunk
    _patch_query(monkeypatch, [chunk.id])
    _patch_embed_one(monkeypatch)
    try:
        svc = RagService(db)
        results = await svc.retrieve("config_value_alpha", top_k=5)
        assert len(results) >= 1
        via = results[0].matched_via or []
        assert "vector" in via
        assert "keyword" in via
    finally:
        await db.delete(chunk)
        await db.delete(doc)
        await db.commit()


# ============ 命中原因展示 ============

@pytest.mark.asyncio
async def test_format_sources_has_hit_reason(db, monkeypatch):
    """format_sources 含 matched_via / matched_keywords / score。"""
    doc, chunk = await _make_doc_chunk(db, content="def run_whitelisted_command(): pass")
    _patch_query(monkeypatch, [])
    _patch_embed_one(monkeypatch)
    try:
        svc = RagService(db)
        results = await svc.retrieve("run_whitelisted_command", top_k=5)
        sources = RagService.format_sources(results)
        assert len(sources) >= 1
        s = sources[0]
        assert s["chunk_id"] == chunk.id
        assert "keyword" in s["matched_via"]
        assert "run_whitelisted_command" in s["matched_keywords"]
        assert s["score"] is not None
    finally:
        await db.delete(chunk)
        await db.delete(doc)
        await db.commit()


# ============ 元数据过滤 ============

@pytest.mark.asyncio
async def test_list_documents_doc_type_filter(client, monkeypatch):
    """/documents 支持 doc_type 过滤；导入时自动推断 doc_type。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    monkeypatch.setattr(OllamaProvider, "embed", fake_embed)

    import uuid

    md_name = f"doc_{uuid.uuid4().hex[:6]}.md"
    txt_name = f"doc_{uuid.uuid4().hex[:6]}.txt"
    md_content = f"# title\n{uuid.uuid4().hex}".encode()
    txt_content = f"plain {uuid.uuid4().hex}".encode()
    # 导入 .md
    res_md = await client.post(
        "/documents/import",
        files={"file": (md_name, md_content, "text/markdown")},
    )
    assert res_md.status_code == 201
    md_id = res_md.json()["id"]
    assert res_md.json()["doc_type"] == "markdown"

    # 导入 .txt
    res_txt = await client.post(
        "/documents/import",
        files={"file": (txt_name, txt_content, "text/plain")},
    )
    txt_id = res_txt.json()["id"]
    assert res_txt.json()["doc_type"] == "text"

    # 过滤 doc_type=markdown → 只含 md
    res = await client.get("/documents", params={"doc_type": "markdown"})
    assert res.status_code == 200
    ids = [d["id"] for d in res.json()]
    assert md_id in ids
    assert txt_id not in ids


@pytest.mark.asyncio
async def test_patch_document_metadata(client, monkeypatch):
    """PATCH /documents/{id} 可设置 topic/tags/language 元数据。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    monkeypatch.setattr(OllamaProvider, "embed", fake_embed)
    import uuid

    res = await client.post(
        "/documents/import",
        files={
            "file": (
                f"meta_{uuid.uuid4().hex[:6]}.md",
                f"content {uuid.uuid4().hex}".encode(),
                "text/markdown",
            )
        },
    )
    doc_id = res.json()["id"]

    res2 = await client.patch(
        f"/documents/{doc_id}",
        json={"topic": "操作系统", "tags": ["内核", "进程"], "language": "zh"},
    )
    assert res2.status_code == 200
    body = res2.json()
    assert body["topic"] == "操作系统"
    assert body["language"] == "zh"
    assert "内核" in (body["tags_json"] or [])
