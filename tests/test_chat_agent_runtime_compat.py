from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import delete, select

import personal_assistant.api.routes_chat as routes_chat
from personal_assistant.agents import (
    AgentRuntime,
    ModelMessage,
    ModelResponse,
    PersistentAgentRunner,
    ReloadingRagCitationOutputVerifier,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    TokenUsage,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    ValidatedToolDispatcher,
    VersionedToolRegistry,
)
from personal_assistant.api.routes_agent_runs import (
    AgentToolBundle,
    get_agent_model_client,
    get_agent_tool_bundle,
)
from personal_assistant.config import settings
from personal_assistant.core.chat import ChatService
from personal_assistant.core.compatibility import CompatibilityTelemetry
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import AgentRunEvent as AgentRunEventRecord
from personal_assistant.core.models import ChatSession
from personal_assistant.core.rag_citation_evidence import (
    load_durable_rag_citation_sources,
)
from personal_assistant.main_api import app


class CompatModel:
    async def complete(self, request, *, cancellation):
        del request, cancellation
        return ModelResponse(
            text="新运行时回答",
            usage=TokenUsage(input_tokens=6, output_tokens=3),
            provider="fake",
            model="compat-model",
        )


class ApprovalCompatModel:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request, *, cancellation):
        del request, cancellation
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="chat-call-1", name="chat_echo", arguments={"value": "ok"}
                    ),
                )
            )
        return ModelResponse(text="approved chat result")


class StreamingCompatModel:
    async def complete(self, request, *, cancellation):
        raise AssertionError(f"unexpected fallback: {request}; {cancellation}")

    async def complete_stream(self, request, *, cancellation, on_delta):
        del request, cancellation
        await on_delta("streamed ")
        await on_delta("answer")
        return ModelResponse(text="streamed answer", provider="fake", model="stream")


class RagCompatModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request, *, cancellation):
        del cancellation
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="rag-chat-search-1",
                        name="search_knowledge_base",
                        arguments={"query": "deployment window"},
                    ),
                )
            )
        return ModelResponse(
            text=json.dumps(
                {
                    "answer": "部署窗口从 09:30 UTC 开始。",
                    "citations": [
                        {
                            "chunk_id": 41,
                            "index_version_id": "version-1",
                            "quote": "deployment window starts at 09:30 UTC",
                        }
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            provider="fake",
            model="rag-compat",
        )


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
    return events


@pytest.mark.asyncio
async def test_feature_gated_chat_maps_agent_run_back_to_legacy_sse(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)
    monkeypatch.setattr(settings, "agent_rag_tools_enabled", False)
    monkeypatch.setattr(settings, "agent_output_verification_enabled", False)
    telemetry = CompatibilityTelemetry()
    monkeypatch.setattr(routes_chat, "compatibility_telemetry", telemetry)

    plain = routes_chat.ChatRequest(session_id=1, message="plain")
    with_tool_result = routes_chat.ChatRequest(
        session_id=1,
        message="legacy tool",
        tool_result={"tool_name": "read_file", "output": {}},
    )
    with_rag = routes_chat.ChatRequest(
        session_id=1,
        message="rag",
        knowledge_base=True,
    )
    assert routes_chat._chat_route_mode(plain) == "agent_runtime"
    assert routes_chat._chat_route_mode(with_tool_result) == "legacy_tool_result"
    assert routes_chat._chat_route_mode(with_rag) == "legacy_rag_tools_disabled"
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", False)
    assert routes_chat._chat_route_mode(plain) == "legacy_runtime_disabled"
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)

    async def fake_model(_db):
        return CompatModel()

    monkeypatch.setattr(routes_chat, "_build_agent_model", fake_model)
    session = (await client.post("/sessions")).json()
    run_id: str | None = None
    try:
        async with client.stream(
            "POST",
            "/chat/stream",
            json={
                "session_id": session["id"],
                "message": "测试新的运行时兼容聊天",
                "knowledge_base": False,
            },
        ) as response:
            assert response.status_code == 200
            body = (await response.aread()).decode("utf-8")

        events = _parse_sse(body)
        assert [event["type"] for event in events] == [
            "run",
            "token",
            "done",
            "title",
        ]
        run_id = events[0]["run_id"]
        assert events[1]["content"] == "新运行时回答"
        assert events[2]["run_id"] == run_id
        assert events[2]["content"] == "新运行时回答"
        assert events[3]["title"] == "测试新的运行时兼容聊天"[:12]
        metric = telemetry.snapshot()["paths"]["/chat/stream"]
        assert metric["calls"] == 1
        assert metric["modes"]["agent_runtime"] == 1

        messages = (await client.get(f"/sessions/{session['id']}/messages")).json()
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "测试新的运行时兼容聊天"
        assert messages[1]["content"] == "新运行时回答"

        continued = await client.get(f"/chat/agent-runs/{run_id}/stream")
        continued_events = _parse_sse(continued.text)
        assert continued.status_code == 200
        assert continued_events[-1]["message_id"] == events[2]["message_id"]
        messages_after_reconnect = (
            await client.get(f"/sessions/{session['id']}/messages")
        ).json()
        assert [message["role"] for message in messages_after_reconnect] == [
            "user",
            "assistant",
        ]

        await db.rollback()
        persisted = await db.get(AgentRunRecord, run_id)
        assert persisted is not None
        assert persisted.status == "completed"
        assert persisted.session_id == session["id"]
    finally:
        if run_id is not None:
            await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_agent_chat_forwards_native_model_deltas_without_final_duplication(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)

    async def fake_model(_db):
        return StreamingCompatModel()

    async def no_tools(_db):
        return None

    monkeypatch.setattr(routes_chat, "_build_agent_model", fake_model)
    monkeypatch.setattr(routes_chat, "get_agent_tool_bundle", no_tools)
    session = (await client.post("/sessions")).json()
    run_id: str | None = None
    try:
        response = await client.post(
            "/chat/stream",
            json={
                "session_id": session["id"],
                "message": "stream this",
                "knowledge_base": False,
            },
        )
        assert response.status_code == 200
        events = _parse_sse(response.text)
        assert [event["type"] for event in events] == [
            "run",
            "token",
            "token",
            "done",
            "title",
        ]
        run_id = events[0]["run_id"]
        assert [event["content"] for event in events if event["type"] == "token"] == [
            "streamed ",
            "answer",
        ]
        assert events[-2]["content"] == "streamed answer"
        messages = (await client.get(f"/sessions/{session['id']}/messages")).json()
        assert messages[-1]["content"] == "streamed answer"
    finally:
        if run_id is not None:
            await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_runtime_chat_keeps_sse_open_for_durable_tool_approval(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)
    model = ApprovalCompatModel()
    executed: list[dict] = []

    async def fake_model(_db):
        return model

    async def execute(arguments, cancellation):
        del cancellation
        executed.append(arguments)
        return {"value": arguments["value"]}

    spec = ToolSpec(
        name="chat_echo",
        version="1.0.0",
        description="Approval-gated chat echo",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset(),
        timeout_ms=5_000,
        max_output_bytes=4_096,
        idempotency=ToolIdempotency.NON_IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=execute,
    )

    def registry():
        result = VersionedToolRegistry()
        result.register(spec)
        return result

    def initial_dispatcher(run_db, run_id):
        return ValidatedToolDispatcher(
            registry(),
            policy=ToolCapabilityPolicy(),
            approval_requester=SqlToolApprovalRequester(run_db, run_id=run_id),
            execution_store=ToolExecutionRepository(run_db, run_id=run_id),
        )

    def resumed_dispatcher(run_db, run_id, approval_id, token):
        return ValidatedToolDispatcher(
            registry(),
            policy=ToolCapabilityPolicy(),
            approval_requester=SqlToolApprovalRequester(run_db, run_id=run_id),
            approval_consumer=SqlToolApprovalConsumer(
                run_db, approval_id=approval_id, token=token
            ),
            execution_store=ToolExecutionRepository(run_db, run_id=run_id),
        )

    bundle = AgentToolBundle(
        definitions=(spec.to_model_definition(),),
        dispatcher_factory=initial_dispatcher,
        resume_dispatcher_factory=resumed_dispatcher,
    )

    async def fake_bundle(_db):
        return bundle

    monkeypatch.setattr(routes_chat, "_build_agent_model", fake_model)
    monkeypatch.setattr(routes_chat, "get_agent_tool_bundle", fake_bundle)
    app.dependency_overrides[get_agent_model_client] = lambda: model
    app.dependency_overrides[get_agent_tool_bundle] = lambda: bundle
    session = (await client.post("/sessions")).json()
    run_id: str | None = None
    request_task = asyncio.create_task(
        client.post(
            "/chat/stream",
            json={
                "session_id": session["id"],
                "message": "use approved tool",
                "knowledge_base": False,
            },
        )
    )
    try:
        approvals: list[dict] = []
        for _ in range(100):
            response = await client.get(
                f"/agent-runs/sessions/{session['id']}/pending-approvals"
            )
            assert response.status_code == 200
            approvals = response.json()
            if approvals:
                break
            await asyncio.sleep(0.02)
        assert len(approvals) == 1
        run_id = approvals[0]["run_id"]
        assert "arguments_json" not in approvals[0]

        approved = await client.post(
            f"/agent-runs/{run_id}/approvals/{approvals[0]['id']}/approve"
        )
        assert approved.status_code == 202, approved.text
        streamed = await asyncio.wait_for(request_task, timeout=5)
        events = _parse_sse(streamed.text)

        assert [event["type"] for event in events] == [
            "run",
            "approval",
            "token",
            "done",
            "title",
        ]
        assert events[1]["approval"]["id"] == approvals[0]["id"]
        assert events[3]["content"] == "approved chat result"
        assert executed == [{"value": "ok"}]
        messages = (await client.get(f"/sessions/{session['id']}/messages")).json()
        assert messages[-1]["content"] == "approved chat result"
    finally:
        if not request_task.done():
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        app.dependency_overrides.pop(get_agent_tool_bundle, None)
        app.dependency_overrides.pop(get_agent_model_client, None)
        if run_id is not None:
            await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_completed_chat_run_can_reconnect_and_persist_its_answer(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)
    session = (await client.post("/sessions")).json()
    registry = VersionedToolRegistry()
    dispatcher = ValidatedToolDispatcher(registry, policy=ToolCapabilityPolicy())
    runner = PersistentAgentRunner(
        AgentRuntime(CompatModel(), dispatcher),
        routes_chat.AgentRunRepository(db),
    )
    result = await runner.run(
        (ModelMessage(role="user", content="resume me"),),
        session_id=session["id"],
    )
    try:
        stream_path = f"/chat/agent-runs/{result.run_id}/stream"
        first, second = await asyncio.gather(
            client.get(stream_path),
            client.get(stream_path),
        )
        assert first.status_code == second.status_code == 200
        first_events = _parse_sse(first.text)
        second_events = _parse_sse(second.text)
        assert [event["type"] for event in first_events] == ["run", "token", "done"]
        assert [event["type"] for event in second_events] == [
            "run",
            "token",
            "done",
        ]
        assert first_events[-1]["run_id"] == result.run_id
        assert second_events[-1]["message_id"] == first_events[-1]["message_id"]
        messages = (await client.get(f"/sessions/{session['id']}/messages")).json()
        assert [message["role"] for message in messages] == ["assistant"]
        await db.rollback()
        delivery_events = list(
            (
                await db.execute(
                    select(AgentRunEventRecord).where(
                        AgentRunEventRecord.run_id == result.run_id,
                        AgentRunEventRecord.event_type == "chat.output_persisted",
                    )
                )
            ).scalars()
        )
        assert len(delivery_events) == 1
        assert delivery_events[0].payload_json == {
            "message_id": first_events[-1]["message_id"]
        }
    finally:
        await db.execute(
            delete(AgentRunRecord).where(AgentRunRecord.id == result.run_id)
        )
        await db.execute(delete(ChatSession).where(ChatSession.id == session["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_verified_rag_chat_uses_runtime_and_projects_trusted_sources(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)
    monkeypatch.setattr(settings, "agent_rag_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_output_verification_enabled", True)
    monkeypatch.setattr(settings, "agent_output_verification_max_retries", 1)
    model = RagCompatModel()

    async def fake_model(_db):
        return model

    async def search(arguments, cancellation):
        del arguments, cancellation
        return {
            "count": 1,
            "results": [
                {
                    "doc_name": "operations.md",
                    "ordinal": 3,
                    "chunk_id": 41,
                    "index_version_id": "version-1",
                    "heading": "Deployment",
                    "score": 0.93,
                    "fusion_score": 0.82,
                    "bm25_score": 0.71,
                    "rerank_score": None,
                    "matched_via": ["vector", "bm25"],
                    "matched_keywords": ["deployment", "window"],
                    "content_excerpt": (
                        "The deployment window starts at 09:30 UTC."
                    ),
                }
            ],
        }

    spec = ToolSpec(
        name="search_knowledge_base",
        version="1.0.0",
        description="Search the local knowledge base for trusted test evidence.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "doc_name": {"type": "string"},
                            "ordinal": {"type": "integer"},
                            "chunk_id": {"type": "integer"},
                            "index_version_id": {"type": "string"},
                            "heading": {"type": "string"},
                            "score": {"type": "number"},
                            "fusion_score": {"type": "number"},
                            "bm25_score": {"type": "number"},
                            "rerank_score": {"type": "null"},
                            "matched_via": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "matched_keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "content_excerpt": {"type": "string"},
                        },
                        "required": [
                            "doc_name",
                            "ordinal",
                            "chunk_id",
                            "index_version_id",
                            "heading",
                            "score",
                            "fusion_score",
                            "bm25_score",
                            "rerank_score",
                            "matched_via",
                            "matched_keywords",
                            "content_excerpt",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["count", "results"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.SAFE,
        required_capabilities=frozenset({ToolCapability.DATABASE_QUERY}),
        timeout_ms=5_000,
        max_output_bytes=32_768,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=search,
    )

    def registry():
        result = VersionedToolRegistry()
        result.register(spec)
        return result

    def dispatcher_factory(run_db, run_id):
        return ValidatedToolDispatcher(
            registry(),
            policy=ToolCapabilityPolicy(
                granted_capabilities=frozenset({ToolCapability.DATABASE_QUERY})
            ),
            execution_store=ToolExecutionRepository(run_db, run_id=run_id),
        )

    def verifier_factory(run_db, run_id):
        async def load_sources():
            return await load_durable_rag_citation_sources(run_db, run_id=run_id)

        return ReloadingRagCitationOutputVerifier(load_sources)

    bundle = AgentToolBundle(
        definitions=(spec.to_model_definition(),),
        dispatcher_factory=dispatcher_factory,
        output_verifier_factory=verifier_factory,
    )

    async def fake_bundle(_db):
        return bundle

    async def legacy_must_not_run(self, *args, **kwargs):
        raise AssertionError(f"legacy RAG path used: {self}; {args}; {kwargs}")

    monkeypatch.setattr(routes_chat, "_build_agent_model", fake_model)
    monkeypatch.setattr(routes_chat, "get_agent_tool_bundle", fake_bundle)
    monkeypatch.setattr(ChatService, "stream_reply", legacy_must_not_run)
    session = (await client.post("/sessions")).json()
    run_id: str | None = None
    try:
        response = await client.post(
            "/chat/stream",
            json={
                "session_id": session["id"],
                "message": "知识库中的部署窗口是什么时候？",
                "knowledge_base": True,
            },
        )
        assert response.status_code == 200
        events = _parse_sse(response.text)
        assert [event["type"] for event in events] == [
            "run",
            "token",
            "done",
            "title",
        ]
        run_id = events[0]["run_id"]
        assert events[1]["content"] == "部署窗口从 09:30 UTC 开始。"
        assert events[2]["content"] == "部署窗口从 09:30 UTC 开始。"
        assert events[2]["sources"] == [
            {
                "doc_name": "operations.md",
                "ordinal": 3,
                "chunk_id": 41,
                "heading": "Deployment",
                "score": 0.93,
                "fusion_score": 0.82,
                "bm25_score": 0.71,
                "rerank_score": None,
                "matched_via": ["vector", "bm25"],
                "matched_keywords": ["deployment", "window"],
            }
        ]
        assert "citations" not in events[1]["content"]
        assert all(request.output_format is not None for request in model.requests)
        assert "本地知识库" in model.requests[0].messages[0].content

        messages = (await client.get(f"/sessions/{session['id']}/messages")).json()
        assert messages[-1]["content"] == "部署窗口从 09:30 UTC 开始。"
        await db.rollback()
        persisted = await db.get(AgentRunRecord, run_id)
        assert persisted is not None
        assert json.loads(persisted.output or "")["citations"][0]["chunk_id"] == 41
    finally:
        if run_id is not None:
            await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session["id"]))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rag_tools_enabled", "verification_enabled"),
    [(False, True), (True, False)],
)
async def test_runtime_chat_flag_keeps_rag_requests_on_legacy_path(
    client,
    db,
    monkeypatch,
    rag_tools_enabled,
    verification_enabled,
):
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)
    monkeypatch.setattr(settings, "agent_rag_tools_enabled", rag_tools_enabled)
    monkeypatch.setattr(
        settings,
        "agent_output_verification_enabled",
        verification_enabled,
    )
    telemetry = CompatibilityTelemetry()
    monkeypatch.setattr(routes_chat, "compatibility_telemetry", telemetry)

    async def must_not_build_model(_db):
        raise AssertionError("AgentRuntime path must not handle RAG yet")

    async def fake_legacy_stream(self, session_id, message, knowledge_base, **kwargs):
        del self, session_id, message, kwargs
        assert knowledge_base is True
        yield {
            "type": "done",
            "message_id": 1,
            "content": "legacy-rag",
            "sources": [],
            "memories": [],
        }

    monkeypatch.setattr(routes_chat, "_build_agent_model", must_not_build_model)
    monkeypatch.setattr(ChatService, "stream_reply", fake_legacy_stream)
    session = (await client.post("/sessions")).json()
    try:
        async with client.stream(
            "POST",
            "/chat/stream",
            json={
                "session_id": session["id"],
                "message": "RAG 请求",
                "knowledge_base": True,
            },
        ) as response:
            events = _parse_sse((await response.aread()).decode("utf-8"))

        assert response.status_code == 200
        assert events == [
            {
                "type": "done",
                "message_id": 1,
                "content": "legacy-rag",
                "sources": [],
                "memories": [],
            }
        ]
        expected_mode = (
            "legacy_rag_tools_disabled"
            if not rag_tools_enabled
            else "legacy_output_verification_disabled"
        )
        metric = telemetry.snapshot()["paths"]["/chat/stream"]
        assert metric["calls"] == 1
        assert metric["modes"][expected_mode] == 1
    finally:
        await db.execute(delete(ChatSession).where(ChatSession.id == session["id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_sse_disconnect_cancels_active_run(client, db, monkeypatch):
    """R3：SSE 断线（流关闭）时 _agent_chat_stream 的 finally 取消运行。"""
    monkeypatch.setattr(settings, "chat_agent_runtime_enabled", True)
    model = ApprovalCompatModel()

    async def fake_model(_db):
        return model

    async def execute(arguments, cancellation):
        del cancellation
        return {"value": arguments["value"]}

    spec = ToolSpec(
        name="chat_echo",
        version="1.0.0",
        description="Approval-gated chat echo",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset(),
        timeout_ms=5_000,
        max_output_bytes=4_096,
        idempotency=ToolIdempotency.NON_IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=execute,
    )

    def registry():
        result = VersionedToolRegistry()
        result.register(spec)
        return result

    def initial_dispatcher(run_db, run_id):
        return ValidatedToolDispatcher(
            registry(),
            policy=ToolCapabilityPolicy(),
            approval_requester=SqlToolApprovalRequester(run_db, run_id=run_id),
            execution_store=ToolExecutionRepository(run_db, run_id=run_id),
        )

    def resumed_dispatcher(run_db, run_id, approval_id, token):
        return ValidatedToolDispatcher(
            registry(),
            policy=ToolCapabilityPolicy(),
            approval_requester=SqlToolApprovalRequester(run_db, run_id=run_id),
            approval_consumer=SqlToolApprovalConsumer(
                run_db, approval_id=approval_id, token=token
            ),
            execution_store=ToolExecutionRepository(run_db, run_id=run_id),
        )

    bundle = AgentToolBundle(
        definitions=(spec.to_model_definition(),),
        dispatcher_factory=initial_dispatcher,
        resume_dispatcher_factory=resumed_dispatcher,
    )

    async def fake_bundle(_db):
        return bundle

    monkeypatch.setattr(routes_chat, "_build_agent_model", fake_model)
    monkeypatch.setattr(routes_chat, "get_agent_tool_bundle", fake_bundle)
    app.dependency_overrides[get_agent_model_client] = lambda: model
    app.dependency_overrides[get_agent_tool_bundle] = lambda: bundle
    session = (await client.post("/sessions")).json()
    run_id: str | None = None
    try:
        async with client.stream(
            "POST",
            "/chat/stream",
            json={
                "session_id": session["id"],
                "message": "use approved tool then disconnect",
                "knowledge_base": False,
            },
        ) as response:
            assert response.status_code == 200
            # 读取首个 SSE 块后立即断开（不等审批完成）
            async for chunk in response.aiter_raw():
                if chunk:
                    break
            run_id = None
            for block in chunk.decode("utf-8", errors="ignore").split("\n\n"):
                for line in block.splitlines():
                    if line.startswith("data:"):
                        run_id = json.loads(line.removeprefix("data:").strip())["run_id"]

        assert run_id is not None
        # 流关闭后 finally 应已请求取消；等待 coordinator 落地取消状态
        cancelled = False
        for _ in range(100):
            record = await db.get(AgentRunRecord, run_id)
            assert record is not None
            if record.status == "cancelled":
                cancelled = True
                break
            await asyncio.sleep(0.05)
        assert cancelled is True, "SSE 断线后 run 必须被取消"
    finally:
        app.dependency_overrides.pop(get_agent_tool_bundle, None)
        app.dependency_overrides.pop(get_agent_model_client, None)
        if run_id is not None:
            await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session["id"]))
        await db.commit()
