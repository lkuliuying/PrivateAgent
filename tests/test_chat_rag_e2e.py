"""Chat/RAG API end-to-end tests.

These tests exercise the FastAPI boundary, MySQL repositories, SSE event shape,
document import state machine, and RAG source plumbing. Ollama and ChromaDB are
patched at their integration seams so the tests stay deterministic and fast.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from personal_assistant.core.provider import OllamaProvider
from personal_assistant.core.store_chroma import chroma_store


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
    return events


async def _read_stream_response(response) -> list[dict]:
    body = await response.aread()
    return _parse_sse(body.decode("utf-8"))


@pytest.mark.asyncio
async def test_chat_stream_saves_history_and_generates_title(client, monkeypatch):
    async def fake_chat_stream(
        self: OllamaProvider, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        yield "你好"
        yield "，这是流式回复"

    async def fake_chat(self: OllamaProvider, messages: list[dict[str, str]]) -> str:
        return "流式测试"

    monkeypatch.setattr(OllamaProvider, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)

    created = await client.post("/sessions")
    assert created.status_code == 201
    session = created.json()

    async with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session["id"],
            "message": "帮我测试流式聊天",
            "knowledge_base": False,
        },
    ) as response:
        assert response.status_code == 200
        events = await _read_stream_response(response)

    assert [e["type"] for e in events] == ["token", "token", "done", "title"]
    assert "".join(e["content"] for e in events if e["type"] == "token") == (
        "你好，这是流式回复"
    )
    assert events[-1]["title"] == "流式测试"

    messages = (await client.get(f"/sessions/{session['id']}/messages")).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "帮我测试流式聊天"
    assert messages[1]["content"] == "你好，这是流式回复"

    sessions = (await client.get("/sessions")).json()
    saved = next(s for s in sessions if s["id"] == session["id"])
    assert saved["title"] == "流式测试"


@pytest.mark.asyncio
async def test_imported_document_can_answer_with_rag_sources(client, monkeypatch):
    seen_prompts: list[list[dict[str, str]]] = []
    vectors: dict[int, int] = {}

    async def fake_embed(
        self: OllamaProvider, texts: list[str]
    ) -> list[list[float]]:
        return [[float(i + 1), 0.0, 0.0] for i, _ in enumerate(texts)]

    async def fake_embed_one(self: OllamaProvider, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def fake_chat_stream(
        self: OllamaProvider, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        seen_prompts.append(messages)
        yield "根据资料回答："
        yield "阶段验收通过"

    async def fake_chat(self: OllamaProvider, messages: list[dict[str, str]]) -> str:
        return "RAG 测试"

    async def fake_chroma_add(
        *, chunk_ids: list[int], embeddings: list[list[float]], doc_ids: list[int]
    ) -> None:
        for chunk_id, doc_id in zip(chunk_ids, doc_ids, strict=True):
            vectors[chunk_id] = doc_id

    async def fake_chroma_query(embedding: list[float], top_k: int = 5) -> list[int]:
        return list(vectors.keys())[:top_k]

    async def fake_chroma_delete(doc_id: int) -> None:
        for chunk_id, stored_doc_id in list(vectors.items()):
            if stored_doc_id == doc_id:
                del vectors[chunk_id]

    monkeypatch.setattr(OllamaProvider, "embed", fake_embed)
    monkeypatch.setattr(OllamaProvider, "embed_one", fake_embed_one)
    monkeypatch.setattr(OllamaProvider, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)
    monkeypatch.setattr(chroma_store, "add", fake_chroma_add)
    monkeypatch.setattr(chroma_store, "query", fake_chroma_query)
    monkeypatch.setattr(chroma_store, "delete_by_doc", fake_chroma_delete)

    marker = f"rag-e2e-{uuid4().hex}"
    content = (
        f"{marker}\n"
        "第一阶段验收结论：聊天、知识库、设置状态均已通过端到端测试。"
    )
    uploaded = await client.post(
        "/documents/import",
        files={"file": (f"{marker}.txt", content.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 201
    doc = uploaded.json()

    try:
        ready_doc = None
        for _ in range(50):
            docs = (await client.get("/documents")).json()
            ready_doc = next((d for d in docs if d["id"] == doc["id"]), None)
            if ready_doc and ready_doc["status"] in {"ready", "failed"}:
                break
            await asyncio.sleep(0.05)
        assert ready_doc is not None
        assert ready_doc["status"] == "ready", ready_doc
        assert ready_doc["chunk_count"] >= 1

        created = await client.post("/sessions")
        assert created.status_code == 201
        session = created.json()

        async with client.stream(
            "POST",
            "/chat/stream",
            json={
                "session_id": session["id"],
                "message": "第一阶段验收结论是什么？",
                "knowledge_base": True,
            },
        ) as response:
            assert response.status_code == 200
            events = await _read_stream_response(response)

        done = next(e for e in events if e["type"] == "done")
        assert done["content"] == "根据资料回答：阶段验收通过"
        assert done["sources"]
        assert done["sources"][0]["doc_name"] == f"{marker}.txt"
        assert done["sources"][0]["ordinal"] == 1

        assert seen_prompts
        prompt_text = "\n".join(m["content"] for m in seen_prompts[0])
        assert marker in prompt_text
        assert "来源：" in prompt_text

    finally:
        await client.delete(f"/documents/{doc['id']}")
