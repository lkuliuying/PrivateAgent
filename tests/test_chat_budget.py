"""R3 预算口径统一测试：旧聊天历史截断 + 远程审计 token 估算。

覆盖：
- 预算内会话：历史全量注入，行为不变；
- 超预算会话：从旧到新截断、保留最近消息；
- 远程审计的 estimated_input_tokens 使用 ConservativeTokenEstimator 统一口径
  （不再用字符数 /4 的低估），与 AgentRuntime 预算口径一致。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from personal_assistant.context.builder import ConservativeTokenEstimator
from personal_assistant.core.chat import ChatService
from personal_assistant.core.history import MessageRepository
from personal_assistant.core.models import ChatSession, ProviderCallAudit, Setting


class CapturingProvider:
    def __init__(self) -> None:
        self.sent_msgs: list[dict] | None = None

    async def chat_stream(self, msgs):
        self.sent_msgs = list(msgs)
        for token in ["回答", "内容"]:
            yield token


async def _seed_context_length(db, value: int) -> None:
    db.add(Setting(key="llm_context_length", value=str(value)))
    await db.commit()


async def _add_messages(db, session_id: int, count: int, content: str) -> None:
    repo = MessageRepository(db)
    for i in range(count):
        await repo.add(session_id, "user" if i % 2 == 0 else "assistant", content)


async def _new_session(db) -> ChatSession:
    session = ChatSession(title="budget-test")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _cleanup(db, session_id: int | None, setting_keys: list[str]) -> None:
    if session_id is not None:
        await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    if setting_keys:
        await db.execute(delete(Setting).where(Setting.key.in_(setting_keys)))
    await db.commit()


@pytest.mark.asyncio
async def test_chat_includes_full_history_within_budget(db):
    session = await _new_session(db)
    await _add_messages(db, session.id, 3, "短消息" * 10)  # 预算内
    provider = CapturingProvider()
    svc = ChatService(db, provider=provider)
    try:
        tokens = []
        async for event in svc.stream_reply(session.id, "你好"):
            if event["type"] == "token":
                tokens.append(event["content"])
        assert provider.sent_msgs is not None
        assert provider.sent_msgs[0]["role"] == "system"
        assert provider.sent_msgs[-1] == {"role": "user", "content": "你好"}
        # 预算内：3 条历史全部注入
        history_roles = [m["role"] for m in provider.sent_msgs[1:-1]]
        assert history_roles == ["user", "assistant", "user"]
        assert "".join(tokens) == "回答内容"
    finally:
        await _cleanup(db, session.id, ["llm_context_length"])


@pytest.mark.asyncio
async def test_chat_truncates_oversized_history_keeping_recent(db):
    session = await _new_session(db)
    await _seed_context_length(db, 900)  # 小预算触发截断（安全系数 2.0 后每条约 396 tokens）
    long_msg = "操作系统管理硬件资源。" * 18  # 198 CJK 字符
    await _add_messages(db, session.id, 6, long_msg)
    provider = CapturingProvider()
    svc = ChatService(db, provider=provider)
    try:
        async for _ in svc.stream_reply(session.id, "简述"):
            pass
        assert provider.sent_msgs is not None
        history = provider.sent_msgs[1:-1]
        assert 0 < len(history) < 6, "超预算历史必须被截断但保留最近消息"
        # 最近一条历史必须保留（从旧到新截断）
        assert history[-1]["content"] == long_msg
    finally:
        await _cleanup(db, session.id, ["llm_context_length"])


@pytest.mark.asyncio
async def test_chat_audit_tokens_use_unified_estimator(db):
    """远程审计的 token 估算必须与 Runtime 使用同一保守口径。"""
    session = await _new_session(db)
    await _add_messages(db, session.id, 2, "短消息" * 8)
    # 远程 provider：触发审计分支（先清掉可能残留的同 key 行）
    await db.execute(
        delete(Setting).where(
            Setting.key.in_(
                ["provider_type", "remote_provider_enabled", "claude_api_key"]
            )
        )
    )
    await db.commit()
    db.add_all(
        [
            Setting(key="provider_type", value="claude"),
            Setting(key="remote_provider_enabled", value="true"),
            Setting(key="claude_api_key", value="test-key-not-real"),
        ]
    )
    await db.commit()

    provider = CapturingProvider()
    svc = ChatService(db, provider=provider)
    audit_id: int | None = None
    try:
        async for _ in svc.stream_reply(session.id, "你好"):
            pass
        assert provider.sent_msgs is not None

        estimator = ConservativeTokenEstimator()
        expected_tokens = estimator.estimate_text(
            "\n".join(m["content"] for m in provider.sent_msgs)
        )
        naive = sum(len(m["content"]) for m in provider.sent_msgs) // 4
        row = (
            await db.execute(
                select(ProviderCallAudit).order_by(ProviderCallAudit.id.desc()).limit(1)
            )
        ).scalar_one()
        audit_id = row.id
        assert row.estimated_input_tokens == expected_tokens
        assert row.estimated_input_tokens > naive, (
            "CJK 内容下旧口径（字符/4）会低估 token，统一口径必须更大"
        )
    finally:
        if audit_id is not None:
            await db.execute(
                delete(ProviderCallAudit).where(ProviderCallAudit.id == audit_id)
            )
        await _cleanup(
            db,
            session.id,
            ["llm_context_length", "provider_type", "remote_provider_enabled", "claude_api_key"],
        )
