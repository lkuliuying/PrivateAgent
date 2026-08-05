"""第七阶段 M6 测试：Provider 生产化治理。

覆盖（对齐 docs/phase7-plan.md §M6 / docs/phase7-requirements.md §5.6）：
- classify_error 把异常/状态码映射到 7 类失败分类。
- ProviderError 携带 error_code；各远程 Provider 缺 key -> missing_api_key。
- ProviderCallAuditRepository create/transition/finish 记录 M6 字段
  (started_at/duration_ms/tokens/error_code/fallback_used)。
- ProviderRouter.fallback_provider() 返回 OllamaProvider。
- 审计记录能区分 succeeded/failed，failed 带 error_code 与 fallback_used。
"""
from __future__ import annotations

import json

import httpx
import pytest

import personal_assistant.core.provider as provider_module
from personal_assistant.core.provider import (
    ClaudeProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRouter,
    classify_error,
)
from personal_assistant.core.repo_privacy import ProviderCallAuditRepository
from personal_assistant.core.timeutil import utcnow


@pytest.fixture
async def cleanup(db):
    created: list = []
    yield created
    for obj in reversed(created):
        try:
            await db.delete(obj)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()


# ============ classify_error ============


def test_classify_missing_api_key():
    err = ProviderError("no key", error_code="missing_api_key")
    assert classify_error(err) == "missing_api_key"


def test_classify_http_status_codes():
    def _err(status: int) -> httpx.HTTPStatusError:
        req = httpx.Request("POST", "https://example.com")
        resp = httpx.Response(status, request=req)
        return httpx.HTTPStatusError("err", request=req, response=resp)

    assert classify_error(_err(401), api_key="x") == "unauthorized"
    assert classify_error(_err(403), api_key="x") == "unauthorized"
    assert classify_error(_err(429), api_key="x") == "rate_limited"
    assert classify_error(_err(404), api_key="x") == "model_not_found"
    assert classify_error(_err(500), api_key="x") == "provider_error"


def test_classify_timeout_and_network():
    assert classify_error(httpx.TimeoutException("timed out")) == "timeout"
    assert classify_error(httpx.ConnectError("refused")) == "network_error"


def test_classify_fallback_provider_error():
    assert classify_error(Exception("something broke")) == "provider_error"


# ============ Provider 缺 key ============


@pytest.mark.asyncio
async def test_openai_missing_api_key():
    p = OpenAICompatibleProvider(base_url="https://api.openai.com/v1", api_key="", model="gpt-4o-mini")
    with pytest.raises(ProviderError) as ei:
        await p.chat([{"role": "user", "content": "hi"}])
    assert ei.value.error_code == "missing_api_key"


@pytest.mark.asyncio
async def test_claude_missing_api_key():
    p = ClaudeProvider(api_key="", model="claude-3-5-sonnet-latest")
    with pytest.raises(ProviderError) as ei:
        await p.chat([{"role": "user", "content": "hi"}])
    assert ei.value.error_code == "missing_api_key"


@pytest.mark.asyncio
async def test_legacy_openai_chat_stream_yields_native_sse_deltas():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        body = (
            'data: {"choices":[{"index":0,"delta":{"content":"hello "}}]}\n\n'
            'data: {"choices":[{"index":0,"delta":{"content":"world"},'
            '"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, request=request, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://api.openai.com/v1",
            api_key="secret",
            model="gpt-test",
            client=client,
        )
        tokens = [
            token
            async for token in provider.chat_stream(
                [{"role": "user", "content": "hello"}]
            )
        ]

    assert captured["stream"] is True
    assert captured["stream_options"] == {"include_usage": True}
    assert tokens == ["hello ", "world"]


@pytest.mark.asyncio
async def test_legacy_claude_chat_stream_hides_thinking_and_yields_text():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        events = [
            {"type": "message_start", "message": {"content": []}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "private"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "visible "},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "answer"},
            },
            {"type": "message_stop"},
        ]
        body = "".join(
            f"event: {event['type']}\n"
            f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
            for event in events
        )
        return httpx.Response(200, request=request, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ClaudeProvider(
            api_key="secret",
            model="claude-test",
            client=client,
        )
        tokens = [
            token
            async for token in provider.chat_stream(
                [
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": "hello"},
                ]
            )
        ]

    assert captured["stream"] is True
    assert captured["system"] == "Be concise."
    assert tokens == ["visible ", "answer"]
    assert "private" not in "".join(tokens)


# ============ 审计 M6 字段 ============


@pytest.mark.asyncio
async def test_audit_m6_fields(db, cleanup):
    repo = ProviderCallAuditRepository(db)
    audit = await repo.create(
        provider_type="openai",
        purpose="chat",
        model="gpt-4o-mini",
        remote=True,
        context_types_json=["chat_messages"],
        estimated_input_chars=1200,
        estimated_input_tokens=300,
        status="sent",
        started_at=utcnow(),
    )
    cleanup.append(audit)
    assert audit.started_at is not None
    assert audit.estimated_input_tokens == 300
    assert audit.fallback_used is False
    assert audit.error_code is None

    # finish 带 M6 字段
    await repo.finish(
        audit.id,
        status="failed",
        error_message="unauthorized",
        error_code="unauthorized",
        fallback_used=True,
        duration_ms=250,
        estimated_output_tokens=0,
    )
    fresh = await repo.get(audit.id)
    assert fresh.status == "failed"
    assert fresh.error_code == "unauthorized"
    assert fresh.fallback_used is True
    assert fresh.duration_ms == 250
    assert fresh.finished_at is not None


@pytest.mark.asyncio
async def test_audit_transition_sent(db, cleanup):
    repo = ProviderCallAuditRepository(db)
    audit = await repo.create(
        provider_type="openai", purpose="chat", remote=True, status="planned"
    )
    cleanup.append(audit)
    await repo.transition(audit.id, status="sent", started_at=utcnow())
    fresh = await repo.get(audit.id)
    assert fresh.status == "sent"
    assert fresh.started_at is not None


# ============ fallback_provider ============


def test_fallback_provider_returns_ollama():
    router = ProviderRouter({"provider_type": "openai", "remote_provider_enabled": "true"})
    fb = router.fallback_provider()
    assert isinstance(fb, OllamaProvider)


def test_ollama_client_is_loaded_only_when_used(monkeypatch):
    provider_module._load_ollama_components.cache_clear()
    imported: list[str] = []

    def fail_import(name: str):
        imported.append(name)
        raise ImportError("SOCKS support is not installed")

    monkeypatch.setattr(provider_module.importlib, "import_module", fail_import)

    provider = OllamaProvider(base_url="http://127.0.0.1:11434")
    assert imported == []

    with pytest.raises(ProviderError) as exc_info:
        provider._chat_llm()

    assert imported == ["langchain_ollama"]
    assert exc_info.value.error_code == "provider_error"
    provider_module._load_ollama_components.cache_clear()


@pytest.mark.asyncio
async def test_ollama_embedding_client_is_reused(monkeypatch):
    created: list[dict] = []

    class FakeEmbeddings:
        def __init__(self, **kwargs):
            created.append(kwargs)

        async def aembed_query(self, _text):
            return [1.0, 0.0]

        async def aembed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        provider_module,
        "_load_ollama_components",
        lambda: (object, FakeEmbeddings),
    )
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")

    assert await provider.embed_one("query") == [1.0, 0.0]
    assert await provider.embed(["one", "two"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert len(created) == 1


@pytest.mark.asyncio
async def test_ollama_stream_error_has_classification(monkeypatch):
    class FailingChat:
        async def astream(self, _messages):
            raise httpx.TimeoutException("timed out")
            yield  # pragma: no cover

    provider = OllamaProvider()
    monkeypatch.setattr(provider, "_chat_llm", lambda: FailingChat())

    with pytest.raises(ProviderError) as exc_info:
        async for _ in provider.chat_stream([{"role": "user", "content": "hi"}]):
            pass

    assert exc_info.value.error_code == "timeout"


@pytest.mark.asyncio
async def test_ollama_embedding_error_has_classification(monkeypatch):
    class FailingEmbedder:
        async def aembed_query(self, _text):
            raise httpx.ConnectError("connection refused")

    provider = OllamaProvider()
    monkeypatch.setattr(provider, "_embedder", lambda: FailingEmbedder())

    with pytest.raises(ProviderError) as exc_info:
        await provider.embed_one("hello")

    assert exc_info.value.error_code == "network_error"
