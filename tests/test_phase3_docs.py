"""第三阶段 M4 测试：文档工作台增强。

覆盖：章节摘要、多文档对比、Markdown 导出（授权路径/未授权拒绝）、生成笔记入库、工具注册。
LLM 经 monkeypatch OllamaProvider.chat 返回 JSON。
"""
from __future__ import annotations

import json
import uuid

import pytest

from personal_assistant.core.provider import OllamaProvider
from personal_assistant.core.tools import default_registry


def _mock_chat(monkeypatch, payload):
    text = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (list, dict)) else payload

    async def fake_chat(self, messages):
        return text

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)


async def _make_doc_with_chunks(db, content: str, name: str = "doc.md"):
    from personal_assistant.core.models import DocChunk, Document

    doc = Document(name=name, status="ready", enabled=True, chunk_count=1, doc_type="markdown")
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    chunk = DocChunk(doc_id=doc.id, ordinal=1, content=content, heading="章节一")
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return doc, chunk


# ============ 工具注册 ============

def test_doc_workbench_tools_registered():
    """M4 四个文档工具注册，风险等级正确。"""
    s = default_registry.get("summarize_document_sections")
    c = default_registry.get("compare_documents")
    e = default_registry.get("export_markdown")
    i = default_registry.get("import_generated_note_to_kb")
    assert s and s.risk_level == "safe"
    assert c and c.risk_level == "safe"
    assert e and e.risk_level == "confirm"
    assert i and i.risk_level == "confirm"


# ============ 章节摘要 ============

@pytest.mark.asyncio
async def test_summarize_sections(client, db, monkeypatch):
    doc, _ = await _make_doc_with_chunks(db, "操作系统管理硬件资源。进程是运行实例。")
    _mock_chat(monkeypatch, [{"heading": "进程", "summary": "进程是程序运行实例"}])
    res = await client.post(f"/documents/{doc.id}/sections/summary")
    assert res.status_code == 200, res.text
    sections = res.json()["sections"]
    assert len(sections) == 1
    assert sections[0]["heading"] == "进程"


# ============ 多文档对比 ============

@pytest.mark.asyncio
async def test_compare_documents(client, db, monkeypatch):
    doc_a, _ = await _make_doc_with_chunks(db, "A: 进程是运行实例", "a.md")
    doc_b, _ = await _make_doc_with_chunks(db, "B: 线程是轻量执行单元", "b.md")
    _mock_chat(
        monkeypatch,
        {
            "common": ["都是执行单元"],
            "differences": [{"doc": "a.md", "point": "进程更重"}],
            "conflicts": [],
            "reading_order": ["先读 a.md", "再读 b.md"],
        },
    )
    res = await client.post("/documents/compare", json={"doc_ids": [doc_a.id, doc_b.id]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert "a.md" in body["doc_names"]
    assert len(body["common"]) >= 1
    assert body["reading_order"]


@pytest.mark.asyncio
async def test_compare_documents_needs_two(client):
    res = await client.post("/documents/compare", json={"doc_ids": [1]})
    assert res.status_code == 400


# ============ Markdown 导出 ============

@pytest.mark.asyncio
async def test_export_markdown_authorized(client, tmp_path):
    """导出到授权目录成功，文件不覆盖。"""
    d = tmp_path / "exports"
    d.mkdir()
    await client.post("/files/authorize", json={"path": str(d), "kind": "directory"})
    res = await client.post(
        "/documents/export",
        json={"content": "# 笔记\n正文", "filename": "note", "target_dir": str(d)},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["path"].endswith("note.md")
    # 再次导出同名 → 不覆盖，加序号
    res2 = await client.post(
        "/documents/export",
        json={"content": "# 笔记\n正文", "filename": "note", "target_dir": str(d)},
    )
    assert res2.status_code == 200
    assert res2.json()["path"] != body["path"]


@pytest.mark.asyncio
async def test_export_markdown_unauthorized(client, tmp_path):
    """导出到未授权目录 → 403。"""
    d = tmp_path / "no_auth_export"
    d.mkdir()
    res = await client.post(
        "/documents/export",
        json={"content": "x", "filename": "note", "target_dir": str(d)},
    )
    assert res.status_code == 403


# ============ 生成笔记入库 ============

@pytest.mark.asyncio
async def test_import_note_to_kb(client, monkeypatch):
    """生成内容可导入知识库（建 doc + 后台导入）。"""
    async def fake_embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    monkeypatch.setattr(OllamaProvider, "embed", fake_embed)
    res = await client.post(
        "/documents/import-note",
        json={"title": f"笔记_{uuid.uuid4().hex[:6]}", "content": f"# 笔记\n{uuid.uuid4().hex}"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "imported"
    assert body["doc_id"]
