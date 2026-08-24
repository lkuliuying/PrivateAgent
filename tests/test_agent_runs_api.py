from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    CancellationToken,
    ModelResponse,
    ModelToolDefinition,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    TokenUsage,
    ToolCall,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolResult,
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
from personal_assistant.core.history import MessageRepository, SessionRepository
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import ChatSession
from personal_assistant.main_api import app


class ImmediateModel:
    async def complete(self, request, *, cancellation):
        del request, cancellation
        return ModelResponse(
            text="持久化回答",
            usage=TokenUsage(input_tokens=9, output_tokens=4, cached_tokens=2),
            provider="fake",
            model="fake-model",
            request_id="fake-request",
            latency_ms=1.5,
        )


class BlockingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.was_cancelled = False

    async def complete(self, request, *, cancellation):
        del request, cancellation
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise
        raise AssertionError("blocking model should have been cancelled")


class ContextRecordingModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request, *, cancellation):
        del cancellation
        self.requests.append(request)
        return ModelResponse(text="context complete")


class EmptyThenCorrectedModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request, *, cancellation):
        del cancellation
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(text="")
        return ModelResponse(text="corrected final answer")


class ToolCallingModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request, *, cancellation):
        del cancellation
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(
                    ToolCall(id="call-1", name="safe_echo", arguments={"value": "ok"}),
                )
            )
        return ModelResponse(text="工具闭环完成")


class RecordingToolDispatcher:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def execute(
        self,
        call: ToolCall,
        *,
        cancellation: CancellationToken,
    ) -> ToolResult:
        del cancellation
        self.calls.append(call)
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            success=True,
            output={"value": call.arguments["value"]},
        )


async def _wait_for_status(client, run_id: str, expected: str) -> dict:
    for _ in range(100):
        response = await client.get(f"/agent-runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] == expected:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {expected}")


async def _cleanup(db, run_id: str | None, session_id: int | None) -> None:
    if run_id is not None:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if session_id is not None:
        await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db.commit()


@pytest.mark.asyncio
async def test_agent_runs_api_is_hidden_when_feature_flag_is_disabled(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", False)

    response = await client.post("/agent-runs", json={"message": "hello"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_agent_run_create_status_and_event_replay(client, db, monkeypatch):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    app.dependency_overrides[get_agent_model_client] = lambda: ImmediateModel()
    session = await SessionRepository(db).create("agent-run-api-test")
    run_id: str | None = None
    try:
        created = await client.post(
            "/agent-runs",
            json={"session_id": session.id, "message": "你好"},
        )
        assert created.status_code == 202
        run_id = created.json()["id"]

        completed = await _wait_for_status(client, run_id, "completed")
        assert completed["output"] == "持久化回答"
        assert completed["provider"] == "fake"
        assert completed["model"] == "fake-model"
        assert completed["input_tokens"] == 9
        assert completed["output_tokens"] == 4
        assert completed["cached_tokens"] == 2
        assert completed["active_in_process"] is False
        assert len(completed["steps"]) == 1
        assert completed["steps"][0]["status"] == "succeeded"

        all_events = await client.get(f"/agent-runs/{run_id}/events")
        assert all_events.status_code == 200
        items = all_events.json()["items"]
        assert [item["sequence"] for item in items] == [1, 2, 3, 4, 5]
        assert [item["type"] for item in items] == [
            "run.started",
            "model.started",
            "model.completed",
            # v0.9.0 H0 §8：逐轮公开决策摘要（additive，只含公开事实）
            "decision.summary",
            "run.completed",
        ]

        replay = await client.get(
            f"/agent-runs/{run_id}/events", params={"after_sequence": 2}
        )
        # v0.9.0 H0 §8：after_sequence 重放含新增的 decision.summary（seq 4）
        assert [item["sequence"] for item in replay.json()["items"]] == [3, 4, 5]
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)
        await _cleanup(db, run_id, session.id)


@pytest.mark.asyncio
async def test_agent_run_context_builder_is_default_off_but_emits_safe_metadata_when_enabled(
    client,
    db,
    monkeypatch,
):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "agent_context_builder_enabled", True)
    model = ContextRecordingModel()
    app.dependency_overrides[get_agent_model_client] = lambda: model
    session = await SessionRepository(db).create("context-agent-run")
    await MessageRepository(db).add(session.id, "user", "prior unique question")
    await MessageRepository(db).add(session.id, "assistant", "prior unique answer")
    run_id: str | None = None
    try:
        created = await client.post(
            "/agent-runs",
            json={"session_id": session.id, "message": "current unique question"},
        )
        assert created.status_code == 202
        run_id = created.json()["id"]
        await _wait_for_status(client, run_id, "completed")
        events = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]

        assert [event["type"] for event in events[:2]] == [
            "run.started",
            "context.prepared",
        ]
        payload = events[1]["payload"]
        assert payload["history_included"] == 2
        assert payload["estimated_tokens"] > 0
        assert "prior unique answer" not in str(payload)
        assert len(model.requests) == 1
        contents = [message.content for message in model.requests[0].messages]
        assert "prior unique answer" in contents
        assert contents[-1] == "current unique question"
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)
        await _cleanup(db, run_id, session.id)


@pytest.mark.asyncio
async def test_agent_run_api_applies_fixed_output_verification_policy(
    client,
    db,
    monkeypatch,
):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "agent_output_verification_enabled", True)
    monkeypatch.setattr(settings, "agent_output_verification_max_retries", 1)
    model = EmptyThenCorrectedModel()
    app.dependency_overrides[get_agent_model_client] = lambda: model
    run_id: str | None = None
    try:
        created = await client.post("/agent-runs", json={"message": "give an answer"})
        assert created.status_code == 202
        run_id = created.json()["id"]

        completed = await _wait_for_status(client, run_id, "completed")
        assert completed["output"] == "corrected final answer"
        events = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
        event_types = [event["type"] for event in events]
        assert event_types.count("output.validation_started") == 2
        assert event_types.count("output.validation_failed") == 1
        assert event_types.count("output.validation_passed") == 1
        assert len(model.requests) == 2
        feedback = model.requests[1].messages[-1]
        assert feedback.role == "user"
        assert "empty_output" in feedback.content
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)
        await _cleanup(db, run_id, None)


@pytest.mark.asyncio
async def test_agent_run_cancel_persists_intent_and_stops_model(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    model = BlockingModel()
    app.dependency_overrides[get_agent_model_client] = lambda: model
    run_id: str | None = None
    try:
        created = await client.post("/agent-runs", json={"message": "等待"})
        assert created.status_code == 202
        run_id = created.json()["id"]
        await asyncio.wait_for(model.started.wait(), timeout=2)

        cancelled = await client.post(f"/agent-runs/{run_id}/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["active_in_process"] is True

        terminal = await _wait_for_status(client, run_id, "cancelled")
        assert terminal["cancel_requested_at"] is not None
        assert terminal["steps"][0]["status"] == "cancelled"
        assert model.was_cancelled is True

        duplicate = await client.post(f"/agent-runs/{run_id}/cancel")
        assert duplicate.status_code == 409
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)
        await _cleanup(db, run_id, None)


@pytest.mark.asyncio
async def test_agent_tool_bundle_is_default_off_and_contains_only_read_only_tools(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", False)
    assert await get_agent_tool_bundle(db) is None

    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", True)
    bundle = await get_agent_tool_bundle(db)
    assert bundle is not None
    assert {definition.name for definition in bundle.definitions} == {
        "read_file",
        "search_files",
        "grep_code",
        "read_code_file",
        "get_git_status",
        "get_git_diff",
        "propose_patch",
    }


@pytest.mark.asyncio
async def test_agent_run_executes_injected_tool_dispatcher_to_completion(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    model = ToolCallingModel()
    dispatcher = RecordingToolDispatcher()

    async def make_dispatcher(_db, _run_id):
        return dispatcher

    bundle = AgentToolBundle(
        definitions=(
            ModelToolDefinition(
                name="safe_echo",
                description="Echo a safe value",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            ),
        ),
        dispatcher_factory=make_dispatcher,
    )
    app.dependency_overrides[get_agent_model_client] = lambda: model
    app.dependency_overrides[get_agent_tool_bundle] = lambda: bundle
    run_id: str | None = None
    try:
        created = await client.post("/agent-runs", json={"message": "use tool"})
        assert created.status_code == 202
        run_id = created.json()["id"]

        completed = await _wait_for_status(client, run_id, "completed")
        assert completed["output"] == "工具闭环完成"
        assert completed["tool_call_count"] == 1
        assert [call.name for call in dispatcher.calls] == ["safe_echo"]
        assert model.requests[0].tools == bundle.definitions
        assert model.requests[1].messages[-1].role == "tool"

        events = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
        assert [event["type"] for event in events] == [
            "run.started",
            "model.started",
            "model.completed",
            # v0.9.0 H0 §8：逐轮公开决策摘要（additive）
            "decision.summary",
            "tool.requested",
            "tool.started",
            "tool.completed",
            "model.started",
            "model.completed",
            "decision.summary",
            "run.completed",
        ]
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)
        app.dependency_overrides.pop(get_agent_tool_bundle, None)
        await _cleanup(db, run_id, None)


@pytest.mark.asyncio
async def test_agent_run_approval_api_resumes_once_without_exposing_arguments(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    model = ToolCallingModel()
    executed: list[dict] = []

    async def execute(arguments, cancellation):
        del cancellation
        executed.append(arguments)
        return {"value": arguments["value"]}

    spec = ToolSpec(
        name="safe_echo",
        version="1.0.0",
        description="Approval-gated echo",
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

    async def initial_dispatcher(run_db, run_id):
        return ValidatedToolDispatcher(
            registry(),
            policy=ToolCapabilityPolicy(),
            approval_requester=SqlToolApprovalRequester(run_db, run_id=run_id),
            execution_store=ToolExecutionRepository(run_db, run_id=run_id),
        )

    async def resumed_dispatcher(run_db, run_id, approval_id, token):
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
    app.dependency_overrides[get_agent_model_client] = lambda: model
    app.dependency_overrides[get_agent_tool_bundle] = lambda: bundle
    run_id: str | None = None
    try:
        created = await client.post("/agent-runs", json={"message": "approve tool"})
        run_id = created.json()["id"]
        await _wait_for_status(client, run_id, "waiting_approval")

        listed = await client.get(f"/agent-runs/{run_id}/approvals")
        assert listed.status_code == 200
        approvals = listed.json()
        assert len(approvals) == 1
        assert approvals[0]["status"] == "pending"
        assert "arguments_json" not in approvals[0]
        assert "ok" not in listed.text

        approved = await client.post(
            f"/agent-runs/{run_id}/approvals/{approvals[0]['id']}/approve"
        )
        assert approved.status_code == 202
        completed = await _wait_for_status(client, run_id, "completed")
        assert completed["output"] == "\u5de5\u5177\u95ed\u73af\u5b8c\u6210"
        assert executed == [{"value": "ok"}]
        decisions = (await client.get(f"/agent-runs/{run_id}/approvals")).json()
        assert decisions[0]["status"] == "consumed"

        duplicate = await client.post(
            f"/agent-runs/{run_id}/approvals/{approvals[0]['id']}/approve"
        )
        assert duplicate.status_code == 409
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)
        app.dependency_overrides.pop(get_agent_tool_bundle, None)
        await _cleanup(db, run_id, None)
