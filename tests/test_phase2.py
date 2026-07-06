"""第二阶段 M2/M3/M4 测试。

覆盖：
- M3：文档搜索筛选、批量导入、启用/禁用、引用片段详情、禁用文档不参与检索。
- M4：活动流列表、文档导入写活动、失败活动重试。
- M2：summarize_file/import_to_kb 工具注册、read_file 支持 pdf/docx、/files/scan、/files/summarize。

照 test_tools.py 模式：client fixture 走 ASGITransport + 真实 MySQL，
OllamaProvider 在集成缝处 monkeypatch（embed/embed_one/chat）。
"""
from __future__ import annotations

import asyncio

import pytest

from personal_assistant.core.provider import OllamaProvider
from personal_assistant.core.tools import _READABLE_EXT, default_registry


def _file(name: str, content: bytes, mime: str = "text/plain"):
    """构造 httpx 上传用的 (filename, bytes, mime) 元组。"""
    return (name, content, mime)


def _u() -> bytes:
    """生成唯一内容，避免跨测试运行的 content_hash 去重冲突。"""
    import uuid

    return uuid.uuid4().hex.encode()


def _patch_embed(monkeypatch, fn):
    """把 OllamaProvider.embed 替换为 fn（后台导入用，不依赖 Ollama 服务）。"""
    monkeypatch.setattr(OllamaProvider, "embed", fn)


# ============ M2：工具注册 ============

def test_registry_has_summarize_and_import():
    """工具注册表含 summarize_file / import_to_kb，均为 confirm 风险。"""
    s = default_registry.get("summarize_file")
    i = default_registry.get("import_to_kb")
    assert s is not None and s.risk_level == "confirm"
    assert i is not None and i.risk_level == "confirm"
    names = {t["name"] for t in default_registry.for_planning()}
    assert {"read_file", "summarize_file", "import_to_kb"}.issubset(names)


def test_readable_ext_includes_pdf_docx():
    """read_file 工具支持 .pdf/.docx。"""
    assert {".pdf", ".docx", ".txt", ".md", ".markdown"}.issubset(_READABLE_EXT)


# ============ M3：知识库增强 API ============

@pytest.mark.asyncio
async def test_list_documents_search_and_status(client, monkeypatch):
    """GET /documents 支持 search 与 status 查询参数。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    _patch_embed(monkeypatch, fake_embed)
    await import_one(client, "alpha.md", _u())

    res = await client.get("/documents", params={"search": "alpha"})
    assert res.status_code == 200
    names = [d["name"] for d in res.json()]
    assert any("alpha" in n for n in names)

    res2 = await client.get("/documents", params={"search": "zzz_no_match"})
    assert all("alpha" not in d["name"] for d in res2.json())

    res3 = await client.get("/documents", params={"status": "ready"})
    assert res3.status_code == 200


@pytest.mark.asyncio
async def test_batch_import(client, monkeypatch):
    """POST /documents/batch-import 返回每个文件状态，重复导入标记 duplicate。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    _patch_embed(monkeypatch, fake_embed)
    c1, c2 = _u(), _u()
    files = [
        ("files", _file("b1.txt", c1)),
        ("files", _file("b2.txt", c2)),
    ]
    res = await client.post("/documents/batch-import", files=files)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    assert all(i["status"] == "imported" for i in items)

    files2 = [("files", _file("b1.txt", c1))]
    res2 = await client.post("/documents/batch-import", files=files2)
    assert res2.json()[0]["status"] == "duplicate"


@pytest.mark.asyncio
async def test_patch_document_enabled(client, monkeypatch):
    """PATCH /documents/{id} 切换启用状态，DocumentOut 含 enabled 字段。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    _patch_embed(monkeypatch, fake_embed)
    doc = await import_one(client, "patchme.md", _u())
    assert doc["enabled"] is True

    res = await client.patch(f"/documents/{doc['id']}", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["enabled"] is False

    res2 = await client.patch(f"/documents/{doc['id']}", json={"enabled": True})
    assert res2.json()["enabled"] is True


@pytest.mark.asyncio
async def test_get_chunk(client, db):
    """GET /chunks/{id} 返回片段详情。"""
    from personal_assistant.core.models import DocChunk, Document

    doc = Document(name="chunk.md", status="ready", enabled=True, chunk_count=1)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    chunk = DocChunk(doc_id=doc.id, ordinal=1, content="片段原文")
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    try:
        res = await client.get(f"/chunks/{chunk.id}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == chunk.id
        assert body["doc_id"] == doc.id
        assert body["content"] == "片段原文"
        assert body["ordinal"] == 1
    finally:
        await db.delete(chunk)
        await db.delete(doc)
        await db.commit()


@pytest.mark.asyncio
async def test_reindex_all(client, monkeypatch):
    """POST /documents/reindex-all 返回 triggered/skipped 计数。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    _patch_embed(monkeypatch, fake_embed)
    await import_one(client, "reidx.md", _u())
    res = await client.post("/documents/reindex-all")
    assert res.status_code == 200
    assert res.json()["triggered"] >= 1


@pytest.mark.asyncio
async def test_disabled_doc_excluded_from_rag(db, monkeypatch):
    """禁用文档的切片不参与 RAG 检索；启用后恢复。"""
    from personal_assistant.core.models import DocChunk, Document
    from personal_assistant.core.rag import RagService
    from personal_assistant.core import store_chroma

    doc = Document(name="disabled.md", status="ready", enabled=False, chunk_count=1)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    chunk = DocChunk(doc_id=doc.id, ordinal=1, content="secret content")
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)

    async def fake_query(embedding, top_k=5):
        return [chunk.id]

    async def fake_embed_one(self, text):
        return [0.0] * 8

    monkeypatch.setattr(store_chroma.chroma_store, "query", fake_query)
    monkeypatch.setattr(OllamaProvider, "embed_one", fake_embed_one)

    svc = RagService(db)
    try:
        # 禁用：检索结果为空
        assert await svc.retrieve("any", top_k=5) == []
        # 启用：检索返回该切片
        doc.enabled = True
        await db.commit()
        results = await svc.retrieve("any", top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == chunk.id
    finally:
        await db.delete(chunk)
        await db.delete(doc)
        await db.commit()


# ============ M4：活动流 API ============

@pytest.mark.asyncio
async def test_list_activities(client, monkeypatch):
    """GET /activities 返回活动列表，支持 kind 过滤；文档导入写入活动。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    _patch_embed(monkeypatch, fake_embed)
    await import_one(client, "act.md", _u())
    act = await wait_for_activity(client, kind="document_import")
    assert act is not None

    res = await client.get("/activities")
    assert res.status_code == 200
    assert any(a["kind"] == "document_import" for a in res.json())

    res2 = await client.get("/activities", params={"kind": "document_import"})
    assert all(a["kind"] == "document_import" for a in res2.json())


@pytest.mark.asyncio
async def test_retry_failed_activity(client, monkeypatch):
    """文档导入失败后活动变 failed，POST /activities/{id}/retry 返回 200。"""
    async def fake_embed_boom(self, texts):
        raise RuntimeError("embed broken")

    _patch_embed(monkeypatch, fake_embed_boom)
    await import_one(client, "boom.md", _u())
    act = await wait_for_activity(client, kind="document_import", status="failed")
    assert act is not None, "失败导入应产生 failed 活动"

    res = await client.post(f"/activities/{act['id']}/retry")
    assert res.status_code == 200


# ============ M2：文件处理 API ============

@pytest.mark.asyncio
async def test_files_scan(client, tmp_path):
    """GET /files/scan 扫描授权目录下可处理文件，过滤不支持类型。"""
    d = tmp_path / "scan_dir"
    d.mkdir()
    (d / "a.txt").write_text("a", encoding="utf-8")
    (d / "b.md").write_text("b", encoding="utf-8")
    (d / "c.bin").write_bytes(b"\x00")  # 不支持的类型

    auth = await client.post(
        "/files/authorize", json={"path": str(d), "kind": "directory"}
    )
    assert auth.status_code == 201

    res = await client.get("/files/scan", params={"path": str(d)})
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2  # a.txt + b.md
    assert {f["name"] for f in body["files"]} == {"a.txt", "b.md"}


@pytest.mark.asyncio
async def test_files_scan_unauthorized(client, tmp_path):
    """未授权目录扫描返回 403。"""
    d = tmp_path / "no_auth"
    d.mkdir()
    (d / "a.txt").write_text("a", encoding="utf-8")
    res = await client.get("/files/scan", params={"path": str(d)})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_files_summarize(client, tmp_path, monkeypatch):
    """POST /files/summarize 总结已授权文件（monkeypatch LLM）。"""
    f = tmp_path / "sum.txt"
    f.write_text("需要总结的内容", encoding="utf-8")
    await client.post("/files/authorize", json={"path": str(f), "kind": "file"})

    async def fake_chat(self, messages):
        return "这是摘要"

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)

    res = await client.post("/files/summarize", json={"path": str(f)})
    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == "这是摘要"
    assert body["name"] == "sum.txt"


@pytest.mark.asyncio
async def test_files_summarize_unauthorized(client, tmp_path):
    """未授权文件总结返回 403。"""
    f = tmp_path / "secret.txt"
    f.write_text("x", encoding="utf-8")
    res = await client.post("/files/summarize", json={"path": str(f)})
    assert res.status_code == 403


# ============ 辅助 ============

async def import_one(client, name: str, content: bytes) -> dict:
    """导入单个文档，返回 DocumentOut。"""
    res = await client.post(
        "/documents/import", files={"file": _file(name, content)}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def wait_for_activity(
    client, kind: str | None = None, status: str | None = None, timeout_s: float = 10
):
    """轮询活动列表直到出现匹配项，返回该活动 dict。"""
    for _ in range(int(timeout_s * 5)):
        res = await client.get("/activities")
        for a in res.json():
            if kind and a["kind"] != kind:
                continue
            if status and a["status"] != status:
                continue
            return a
        await asyncio.sleep(0.2)
    return None
