from __future__ import annotations

import json

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import personal_assistant.workers.conversation_summarizer as worker_mod
from personal_assistant.agents.contracts import ModelResponse, TokenUsage
from personal_assistant.config import Settings
from personal_assistant.core.context_summaries import ConversationSummaryRepository
from personal_assistant.core.conversation_summarizer import (
    ConversationSummaryGenerationError,
    ConversationSummaryService,
)
from personal_assistant.core.history import MessageRepository, SessionRepository
from personal_assistant.core.models import (
    ChatSession,
    ConversationSummary,
    Message,
    Setting,
)
from personal_assistant.core.settings import SettingsService
from personal_assistant.workers.conversation_summarizer import (
    run_conversation_summary_once,
    schema_supports_conversation_summaries,
)


def _summary_payload() -> dict:
    return {
        "goal": "Finish the migration safely.",
        "decisions": ["Keep production schema unchanged without approval."],
        "completed": ["Validated the isolated clone."],
        "pending": ["Review the rollout gate."],
        "constraints": ["Do not delete production rows."],
        "important_facts": ["The source revision is 0012."],
        "errors": [],
        "files": ["docs/migration-plan.md"],
        "tools": ["pytest"],
        "next_steps": ["Run the final read-only snapshot."],
    }


class RecordingModel:
    def __init__(self, text: str | None = None) -> None:
        self.text = text or json.dumps(_summary_payload())
        self.requests = []

    async def complete(self, request, *, cancellation):
        cancellation.raise_if_cancelled()
        self.requests.append(request)
        return ModelResponse(
            text=self.text,
            provider="test-provider",
            model="test-model",
            usage=TokenUsage(input_tokens=321, output_tokens=87),
        )


async def _seed_messages(db, *, count: int, secret: bool = False):
    session = await SessionRepository(db).create("summary-worker-test")
    repository = MessageRepository(db)
    messages = []
    for index in range(count):
        content = f"message-{index + 1}"
        if secret and index == 0:
            content = "api_key=sk-test-secret-value"
        messages.append(
            await repository.add(
                session.id,
                "user" if index % 2 == 0 else "assistant",
                content,
            )
        )
    return session, messages


async def _cleanup_session(db, session_id: int) -> None:
    await db.execute(
        delete(ConversationSummary).where(
            ConversationSummary.session_id == session_id
        )
    )
    await db.execute(delete(Message).where(Message.session_id == session_id))
    await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db.commit()


@pytest.mark.asyncio
async def test_summary_worker_creates_bounded_traceable_chunks(db):
    session, messages = await _seed_messages(db, count=7)
    model = RecordingModel()
    service = ConversationSummaryService(
        db,
        min_source_messages=2,
        keep_recent_messages=2,
        max_source_messages=3,
        max_source_chars=1_000,
    )
    try:
        first = await service.summarize_next(model, session_id=session.id)
        assert first is not None
        assert first.first_message_id == messages[0].id
        assert first.last_message_id == messages[2].id
        assert first.source_message_count == 3
        assert first.provider == "test-provider"
        assert first.model == "test-model"
        assert first.input_tokens == 321
        assert first.output_tokens == 87
        assert first.sensitive is False
        assert json.loads(first.summary_text) == _summary_payload()

        source_request = json.loads(model.requests[0].messages[1].content)
        assert [item["id"] for item in source_request["source_messages"]] == [
            message.id for message in messages[:3]
        ]

        second = await service.summarize_next(model, session_id=session.id)
        assert second is not None
        assert second.first_message_id == messages[3].id
        assert second.last_message_id == messages[4].id
        assert await service.summarize_next(model, session_id=session.id) is None

        active = await ConversationSummaryRepository(db).list_active(session.id)
        assert [(item.first_message_id, item.last_message_id) for item in active] == [
            (messages[0].id, messages[2].id),
            (messages[3].id, messages[4].id),
        ]
    finally:
        await _cleanup_session(db, session.id)


@pytest.mark.asyncio
async def test_summary_worker_rejects_invalid_model_output_without_writing(db):
    session, _ = await _seed_messages(db, count=4)
    service = ConversationSummaryService(
        db,
        min_source_messages=2,
        keep_recent_messages=2,
        max_source_messages=2,
        max_source_chars=1_000,
    )
    try:
        with pytest.raises(ConversationSummaryGenerationError, match="JSON"):
            await service.summarize_next(
                RecordingModel("not-json"),
                session_id=session.id,
            )
        assert await ConversationSummaryRepository(db).list_all(session.id) == []
    finally:
        await _cleanup_session(db, session.id)


@pytest.mark.asyncio
async def test_summary_worker_marks_secret_bearing_sources_sensitive(db):
    session, _ = await _seed_messages(db, count=4, secret=True)
    service = ConversationSummaryService(
        db,
        min_source_messages=2,
        keep_recent_messages=2,
        max_source_messages=2,
        max_source_chars=1_000,
    )
    try:
        record = await service.summarize_next(
            RecordingModel(),
            session_id=session.id,
        )
        assert record is not None
        assert record.sensitive is True
    finally:
        await _cleanup_session(db, session.id)


def test_summary_worker_configuration_rejects_inverted_message_limits():
    with pytest.raises(ValueError, match="MAX_SOURCE_MESSAGES"):
        Settings(
            _env_file=None,
            conversation_summary_min_source_messages=20,
            conversation_summary_max_source_messages=10,
        )


@pytest.mark.parametrize(
    ("revision", "expected"),
    [
        (None, False),
        ("0012", False),
        ("0016", False),
        ("0017", True),
        ("0019", True),
        ("0020", True),
        ("head", False),
    ],
)
def test_summary_worker_requires_schema_0017_or_later(revision, expected):
    assert schema_supports_conversation_summaries(revision) is expected


async def _bind_worker_to_test_db(db, monkeypatch):
    """把 run_conversation_summary_once 的 engine/factory 绑到测试库。"""
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(worker_mod, "engine", db.bind)
    monkeypatch.setattr(worker_mod, "async_session_factory", factory)
    return factory


async def _enable_remote_provider(db) -> None:
    await SettingsService(db).update(
        {
            "provider_type": "openai",
            "remote_provider_enabled": "true",
            "openai_api_key": "secret://os-keyring/provider/openai",
        }
    )


async def _cleanup_settings(db) -> None:
    await db.execute(
        delete(Setting).where(
            Setting.key.in_(
                ["provider_type", "remote_provider_enabled", "openai_api_key"]
            )
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_summary_worker_skips_remote_provider_without_authorization(db, monkeypatch):
    """M4 §9.2：远程 provider 未显式授权时 worker 跳过，不产生模型调用与摘要。"""
    monkeypatch.setattr(
        worker_mod.settings, "conversation_summary_allow_remote_provider", False
    )
    session, _ = await _seed_messages(db, count=21)
    await _enable_remote_provider(db)
    called = {"n": 0}
    try:
        original_gateway = worker_mod.ProviderRouter.model_gateway

        def counting_gateway(self):
            called["n"] += 1
            return original_gateway(self)

        monkeypatch.setattr(
            worker_mod.ProviderRouter, "model_gateway", counting_gateway
        )
        await _bind_worker_to_test_db(db, monkeypatch)

        outcome = await run_conversation_summary_once()

        assert outcome.status == "skipped"
        assert outcome.reason == "remote_provider_not_allowed"
        assert called["n"] == 0, "远程未授权时不得构建模型网关"
        assert await ConversationSummaryRepository(db).list_all(session.id) == []
    finally:
        await _cleanup_settings(db)
        await _cleanup_session(db, session.id)


@pytest.mark.asyncio
async def test_summary_worker_allows_remote_only_with_explicit_flag(db, monkeypatch):
    """M4 §9.2：PA_CONVERSATION_SUMMARY_ALLOW_REMOTE_PROVIDER=true 时才放行远程。"""
    monkeypatch.setattr(
        worker_mod.settings, "conversation_summary_allow_remote_provider", True
    )
    session, _ = await _seed_messages(db, count=21)
    await _enable_remote_provider(db)
    try:
        model = RecordingModel()

        def fake_gateway(self):
            del self
            return model

        monkeypatch.setattr(
            worker_mod.ProviderRouter, "model_gateway", fake_gateway
        )
        await _bind_worker_to_test_db(db, monkeypatch)

        outcome = await run_conversation_summary_once()

        assert outcome.status == "created"
        assert outcome.session_id == session.id
        assert model.requests, "授权后必须实际调用模型"
    finally:
        await _cleanup_settings(db)
        await _cleanup_session(db, session.id)


@pytest.mark.asyncio
async def test_summary_worker_never_deletes_messages_and_is_idempotent(db):
    """M4 §9.4：摘要不删除原始消息；已摘要范围不会被重复调度。"""
    session, messages = await _seed_messages(db, count=7)
    service = ConversationSummaryService(
        db,
        min_source_messages=2,
        keep_recent_messages=2,
        max_source_messages=3,
        max_source_chars=1_000,
    )
    try:
        await service.summarize_next(RecordingModel(), session_id=session.id)

        # 原始消息完整保留（数量与内容不变）
        remaining = list(
            (
                await db.execute(
                    select(Message).where(Message.session_id == session.id)
                )
            )
            .scalars()
            .all()
        )
        assert [message.id for message in remaining] == [
            message.id for message in messages
        ]
        assert [message.content for message in remaining] == [
            message.content for message in messages
        ]

        # 幂等：重复调度不会重新生成已覆盖范围（cursor 已推进）
        again = await service.find_candidate(session_id=session.id)
        if again is not None:
            assert again.first_message_id > messages[2].id, (
                "已摘要范围被重复调度"
            )
        active = await ConversationSummaryRepository(db).list_active(session.id)
        assert [(s.first_message_id, s.last_message_id) for s in active] == [
            (messages[0].id, messages[2].id)
        ]
    finally:
        await _cleanup_session(db, session.id)
