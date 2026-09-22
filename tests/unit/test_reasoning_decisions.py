"""推理状态跨运行主链、历史压缩及公开输出的边界回归。"""
import json

import httpx
import pytest
from test_agent_runtime import RecordingTools, ScriptedModel, model_tool, user_message
from test_direct_models import configuration, desktop
from test_local_context_history import history_store
from test_local_executor import TERMINAL, until
from test_responses_adapter import (
    OPAQUE,
    adapter,
    function,
    message,
    reasoning,
    response,
    sse,
)

from private_agent_core.contracts import (
    AgentEventType,
    AgentRunLimits,
    AgentRunStatus,
    ModelMessage,
    ModelResponse,
    ToolCall,
)
from private_agent_core.runtime import AgentRuntime
from private_agent_local.store import Store


@pytest.mark.asyncio
async def test_commentary_continues_with_state_then_executes_tools_and_finishes():
    first = adapter()._response(response(reasoning(), message("需要先检查目录", "commentary")))
    second = adapter()._response(response(reasoning("rs_2"), message("读取目录以核实", "commentary", "msg_2"), function()))
    model, tools, deltas = ScriptedModel(first, second, ModelResponse(text="已核实", phase="final_answer")), RecordingTools(), []

    async def receive(delta):
        deltas.append(delta)

    result = await AgentRuntime(model, tools, model_output_sink=receive).run([user_message()], tool_definitions=(model_tool("read"),))
    assert result.status == AgentRunStatus.COMPLETED and result.output == "已核实"
    assert len(model.requests) == 3 and len(tools.calls) == 1
    assert model.requests[1].messages[-1] == first.as_message()
    assert second.as_message() in model.requests[2].messages
    assert deltas == ["已核实"]
    decisions = [event.payload for event in result.events if event.type == AgentEventType.DECISION_SUMMARY]
    assert any("读取目录以核实" in json.dumps(item, ensure_ascii=False) for item in decisions)
    assert OPAQUE not in result.model_dump_json()


@pytest.mark.asyncio
async def test_repeated_commentary_is_bounded_by_existing_step_limit():
    model = ScriptedModel(*(ModelResponse(text="继续检查", phase="commentary") for _ in range(3)))
    result = await AgentRuntime(model, RecordingTools()).run([user_message()], limits=AgentRunLimits(max_steps=2))
    assert result.status == AgentRunStatus.LIMIT_EXCEEDED
    assert len(model.requests) == 2 and result.output is None


@pytest.mark.parametrize("reason", ["length", "max_tokens", "incomplete", "failed", "content_filter"])
@pytest.mark.asyncio
async def test_incomplete_legacy_tool_calls_are_never_executed(reason):
    model = ScriptedModel(ModelResponse(tool_calls=(ToolCall(id="c", name="read", arguments={}),), finish_reason=reason))
    tools = RecordingTools()
    result = await AgentRuntime(model, tools).run([user_message()], tool_definitions=(model_tool("read"),))
    assert result.status == AgentRunStatus.FAILED and tools.calls == []
    assert not any(event.type == AgentEventType.MODEL_COMPLETED for event in result.events)


def test_restart_and_compaction_preserve_native_tail_and_full_tool_results(tmp_path):
    store, session = history_store(tmp_path)
    original = "必须保留的用户约束"
    store.context.append(session, "run", ModelMessage(role="user", content=original), key="goal", source="user")
    for index in range(4):
        answer = adapter()._response(response(reasoning(f"rs_{index}"), function(f"call_{index}")))
        store.context.append(session, "run", answer.as_message(), key=f"a{index}", source="model")
        tool = ModelMessage(role="tool", name="read", tool_call_id=f"call_{index}", content="证据" * 4000)
        store.context.append(session, "run", tool, key=f"t{index}", source="tool")
    before = store.context.messages(session)
    assert before[-1].content == tool.content
    checkpoint = store.context.compact(session, store.context.begin(session, "compact"))
    store.context.save_checkpoint(session, checkpoint)
    path = store.path
    store.db.close()
    store = Store(path)
    try:
        restored = store.context.messages(session)
        assert restored[-4:] == before[-4:]
        assert restored[0].content == original
        assert OPAQUE not in json.dumps(checkpoint["summary"])
        native = [item for item in store.context.items(session) if item["message"].get("provider_state")][-1]
        public = store.context.read(session, native["item_id"], 0, 6000)
        assert "provider_state" not in public["content"] and OPAQUE not in public["content"]
        assert json.loads(public["content"])["tool_calls"][0]["id"] == "call_3"
    finally:
        store.db.close()


async def configure_responses(client, models, streaming):
    saved = await client.put("/model-providers/provider", json=configuration(api_format="responses"))
    assert saved.status_code == 200, saved.text
    identifier = saved.json()["models"][0]["profile_id"]
    secret = await client.put("/model-providers/provider/runtime-secret", json={"secret": "fixture-provider-secret"})
    assert secret.status_code == 200
    models.catalog.data["profiles"][identifier]["supports_streaming"] = streaming
    models.catalog.save()
    return identifier


async def start_run(client, tmp_path, recovery_version=None):
    root = tmp_path / "project"
    root.mkdir()
    (root / "fixture.txt").write_text("fixture", encoding="utf-8")
    project = (await client.post("/projects", json={"name": "推理测试", "root_path": str(root)})).json()
    workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
    binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
    session = (await client.post("/sessions", json={**binding, "title": "推理测试", "kind": "coding"})).json()
    created = await client.post("/agent-runs", json={**binding, "session_id": session["id"], "message": "列出目录", "permission_mode": "readonly",
        **({"recovery_contract_version": recovery_version} if recovery_version else {})})
    assert created.status_code == 201, created.text
    return await until(client, created.json()["id"], TERMINAL), session["id"]


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("recovery_version", [None, "1.0"])
@pytest.mark.asyncio
async def test_responses_local_agent_three_rounds_and_public_redaction(tmp_path, streaming, recovery_version):
    inputs = []
    first = response(reasoning(), message("先确认项目目录", "commentary"))
    second = response(reasoning("rs_2"), function("call_2", "list_project_directory", '{"rel_path":"."}'))
    third = response(message("检查完毕", "commentary", "msg_progress"), message("目录包含 fixture.txt"))

    def upstream(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        inputs.append(body["input"])
        data = [first, second, third][len(inputs) - 1]
        if streaming:
            return httpx.Response(200, content=sse({"type": "response.completed", "response": data}))
        return httpx.Response(200, json=data)

    async with desktop(tmp_path, handle=upstream) as (models, app, client, accounts, calls):
        identifier = await configure_responses(client, models, streaming)
        final, session = await start_run(client, tmp_path, recovery_version)
        assert final["status"] == "completed", final
        assert final["output"] == "目录包含 fixture.txt"
        assert final["model_profile_id"] == identifier and len(calls) == 3 and accounts == []
        assert all(item in inputs[1] for item in first["output"])
        assert all(item in inputs[2] for item in second["output"])
        assert any(item.get("type") == "function_call_output" and item["call_id"] == "call_2" for item in inputs[2])
        store = app.state.desktop.runtime.store
        assert any(item.provider_state for item in store.context.messages(session))
        exported = await client.get("/local-history/export")
        assert exported.status_code == 200
        assert OPAQUE not in exported.text and OPAQUE not in json.dumps(final)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_local_incomplete_response_does_not_execute_tools(tmp_path, streaming):
    def upstream(_):
        data = response(function("call_1", "list_project_directory", '{"rel_path":"."}'), status="incomplete")
        return httpx.Response(200, content=sse({"type": "response.incomplete", "response": data})) if streaming else httpx.Response(200, json=data)

    async with desktop(tmp_path, handle=upstream) as (models, app, client, _, calls):
        await configure_responses(client, models, streaming)
        final, _ = await start_run(client, tmp_path)
        assert final["status"] == "failed", final
        run = app.state.desktop.runtime.store.run(final["id"])
        assert run["executions"] == [] and len(calls) == 1
        assert "model_incomplete_response" in json.dumps(final)


@pytest.mark.asyncio
async def test_active_run_stops_when_api_format_changes(tmp_path):
    def upstream(_):
        models.catalog.data["providers"]["provider"]["api_format"] = "chat_completions"
        return httpx.Response(200, json=response(reasoning(), message("继续检查", "commentary")))

    async with desktop(tmp_path, handle=upstream) as (models, _, client, _, calls):
        await configure_responses(client, models, False)
        final, _ = await start_run(client, tmp_path)
        assert final["status"] == "failed", final
        assert len(calls) == 1 and "model_not_configured" in json.dumps(final)
