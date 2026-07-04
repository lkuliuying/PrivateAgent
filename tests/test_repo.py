"""仓储层测试：会话/消息/文档 CRUD。"""
from __future__ import annotations

import pytest

from personal_assistant.core.history import MessageRepository, SessionRepository
from personal_assistant.core.repo import DocumentRepository


@pytest.mark.asyncio
async def test_session_and_messages(db):
    sessions = SessionRepository(db)
    s = await sessions.create()
    try:
        assert s.title == "新对话"
        await sessions.rename(s.id, "测试标题")
        refetched = await sessions.get(s.id)
        assert refetched is not None
        assert refetched.title == "测试标题"

        msgs = MessageRepository(db)
        await msgs.add(s.id, "user", "你好")
        await msgs.add(s.id, "assistant", "你好，我是助手")
        listed = await msgs.list_by_session(s.id)
        assert len(listed) == 2
        assert listed[0].role == "user"
        assert listed[1].role == "assistant"
    finally:
        obj = await sessions.get(s.id)
        if obj:
            await db.delete(obj)
            await db.commit()


@pytest.mark.asyncio
async def test_document_status_update(db):
    docs = DocumentRepository(db)
    doc = await docs.create(name="test.txt", content_hash="hash_test_unit_001")
    try:
        assert doc.status == "pending"
        assert doc.chunk_count == 0
        await docs.update_status(doc.id, status="ready", chunk_count=3)
        refetched = await docs.get(doc.id)
        assert refetched is not None
        assert refetched.status == "ready"
        assert refetched.chunk_count == 3

        by_hash = await docs.get_by_hash("hash_test_unit_001")
        assert by_hash is not None
        assert by_hash.id == doc.id
    finally:
        await docs.delete(doc.id)
