"""用隔离 ASGI、SQLite 和合成模型验证结构化交付及事实门禁。"""
import asyncio
import json

import pytest
from test_local_executor import close, response, setup, until
from test_local_recovery import control, waiting_model

from private_agent_local.output import (
    parse_structured_output,
    validate_output_schema,
    verify_structured_output,
)
from private_agent_local.runtime import TERMINAL

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}},
          "required": ["summary"], "additionalProperties": False}


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    values[2].profiles[0]["supports_structured_output"] = True
    try:
        yield values
    finally:
        await close(values[0], values[1])


def requests(server):
    return [json.loads(body)["request"] for path, body in server.calls if path == "/desktop/model/complete"]


@pytest.mark.asyncio
async def test_schema_result_is_validated_and_persisted_with_terminal(api):
    app, client, server, root, body = api
    server.responses = [response(text='{"summary":"项目说明"}')]
    created = await client.post("/agent-runs", json={**body, "message": "解释项目结构", "output_schema": SCHEMA})
    assert created.status_code == 201
    run = await until(client, created.json()["id"], TERMINAL)
    assert run["status"] == "completed"
    assert run["structured_output"] == {"summary": "项目说明"}
    assert json.loads(run["output"]) == run["structured_output"]
    assert requests(server)[0]["output_format"]["json_schema"] == SCHEMA
    events = (await client.get(f"/agent-runs/{run['id']}/events")).json()["items"]
    terminal = next(item for item in events if item["type"] == "run.completed")
    assert terminal["payload"]["structured_output"] == run["structured_output"]
    assert terminal["payload"]["final_output_attempt_id"] == run["final_output_attempt_id"]


@pytest.mark.asyncio
async def test_schema_mismatch_uses_existing_bounded_correction_loop(api):
    app, client, server, root, body = api
    server.responses = [response(text='{"summary":42}'), response(text='{"summary":"已修正"}')]
    created = await client.post("/agent-runs", json={**body, "message": "解释项目结构", "output_schema": SCHEMA})
    run = await until(client, created.json()["id"], TERMINAL)
    assert run["status"] == "completed"
    assert run["structured_output"] == {"summary": "已修正"}
    calls = requests(server)
    assert len(calls) == 2
    assert calls[1]["output_format"]["json_schema"] == SCHEMA
    assert "JSON Schema" in json.dumps(calls[1]["messages"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_repeated_invalid_json_never_publishes_structured_success(api):
    app, client, server, root, body = api
    server.responses = [response(text="```json\n{}\n```") for _ in range(3)]
    created = await client.post("/agent-runs", json={**body, "message": "解释项目结构", "output_schema": SCHEMA})
    run = await until(client, created.json()["id"], TERMINAL)
    assert run["status"] == "failed"
    assert run["structured_output"] is None and run["final_output_attempt_id"] is None
    assert len(requests(server)) == 3


@pytest.mark.asyncio
async def test_valid_json_does_not_bypass_file_evidence(api):
    app, client, server, root, body = api
    server.responses = [response(text='{"summary":"已创建 hello.py"}') for _ in range(3)]
    created = await client.post("/agent-runs", json={**body, "message": "创建 hello.py", "output_schema": SCHEMA})
    run = await until(client, created.json()["id"], TERMINAL)
    assert run["status"] == "failed" and run["goal_outcome"] == "unmet"
    assert run["structured_output"] is None and not (root / "hello.py").exists()


@pytest.mark.asyncio
async def test_unsupported_model_is_rejected_before_request(api):
    app, client, server, root, body = api
    server.profiles[0]["supports_structured_output"] = False
    created = await client.post("/agent-runs", json={**body, "output_schema": SCHEMA})
    run = await until(client, created.json()["id"], TERMINAL)
    assert run["status"] == "failed" and run["error_code"] == "model_structured_output_unsupported"
    assert requests(server) == [] and run["tool_call_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [
    {"type": "array"},
    {"type": "object", "properties": {"x": {"$ref": "https://example.test/schema"}}},
    {"type": "object", "description": "x" * 65536},
    {"type": "object", "properties": {"x": {"type": "unsupported"}}},
    {"type": "object", "properties": {"x": {"type": "string", "pattern": "(a+)+$"}}},
    {"type": "object", "properties": {"x": {"type": "array", "uniqueItems": True}}},
    {"type": "object", "properties": {"x": {"$ref": "#/$defs/missing"}}},
    {"type": "object", "$schema": "http://json-schema.org/draft-07/schema#"},
    {"type": "object", "properties": {"x": {"$schema": "https://example.test/schema"}}},
    {"type": "object", "default": {"pattern": "(a+)+$"}, "properties": {"x": {"$ref": "#/default"}}},
    {"type": "object", "$defs": {"a": {"$anchor": "same"}, "b": {"$anchor": "same"}}},
])
async def test_invalid_schema_rejected_at_creation(api, schema):
    app, client, server, root, body = api
    result = await client.post("/agent-runs", json={**body, "output_schema": schema})
    assert result.status_code == 422 and requests(server) == []


@pytest.mark.asyncio
async def test_duplicate_request_cannot_change_output_schema(api):
    app, client, server, root, body = api
    server.responses = [response(text='{"summary":"结果"}')]
    request = {**body, "message": "解释项目结构", "client_request_id": "output-schema", "output_schema": SCHEMA}
    created = await client.post("/agent-runs", json=request)
    await until(client, created.json()["id"], TERMINAL)
    repeated = await client.post("/agent-runs", json=request)
    changed = await client.post("/agent-runs", json={**request, "output_schema": {"type": "object"}})
    assert repeated.json()["id"] == created.json()["id"]
    assert changed.status_code == 422 and len(requests(server)) == 1


@pytest.mark.parametrize("text", [
    "", "[]", "null", '{"summary":NaN}', '{"summary":Infinity}',
    '{"summary":"one","summary":"two"}', '{"summary":1e400}',
    '{"summary":"ok","extra":1}', '```json\n{"summary":"ok"}\n```',
])
def test_non_json_or_ambiguous_output_is_rejected(text):
    with pytest.raises(ValueError):
        parse_structured_output(text, SCHEMA)


def test_unresolvable_schema_stops_without_exposing_instance():
    result = verify_structured_output('{"hidden":"private-value"}', {
        "type": "object", "properties": {"hidden": {"$ref": "#/$defs/missing"}}})
    assert result.code == "output_schema_invalid" and not result.retryable
    assert "private-value" not in result.model_dump_json()


def test_schema_keyword_named_fields_and_local_refs_are_supported():
    schema = validate_output_schema({"type": "object", "$defs": {"value": {"type": "string"}},
        "properties": {"pattern": {"$ref": "#/$defs/value"}}, "required": ["pattern"]})
    assert parse_structured_output('{"pattern":"字段名称不是正则约束"}', schema)["pattern"]


def test_recursive_refs_and_large_results_fail_with_bounded_work():
    schema = validate_output_schema({"type": "object", "$defs": {"loop": {"$ref": "#/$defs/loop"}},
        "properties": {"value": {"$ref": "#/$defs/loop"}}})
    assert verify_structured_output('{"value":1}', schema).code == "output_schema_mismatch"
    with pytest.raises(ValueError, match="节点数"):
        parse_structured_output(json.dumps({"value": [0] * 4096}), {"type": "object"})


def test_nested_dialect_cannot_reset_validation_budget(monkeypatch):
    monkeypatch.setattr("private_agent_local.output.MAX_VALIDATION_STEPS", 2)
    schema = validate_output_schema({"type": "object", "properties": {"value": {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "string"}}})
    with pytest.raises(ValueError, match="计算预算"):
        parse_structured_output('{"value":"正确类型也受预算约束"}', schema)
    assert "$schema" in schema["properties"]["value"]


def test_local_anchor_is_validated_before_model_execution():
    schema = validate_output_schema({"type": "object", "$defs": {"text": {"$anchor": "text", "type": "string"}},
        "properties": {"value": {"$ref": "#text"}}})
    assert parse_structured_output('{"value":"本地锚点"}', schema) == {"value": "本地锚点"}


@pytest.mark.parametrize("branch", [False, {"type": "integer"}])
def test_many_failing_branches_cannot_amplify_large_error_context(branch, monkeypatch):
    monkeypatch.setattr("private_agent_local.output.MAX_VALIDATION_BYTES", 1024)
    schema = validate_output_schema({"type": "object", "properties": {"value": {"anyOf": [branch] * 24}}})
    with pytest.raises(ValueError, match="计算预算"):
        parse_structured_output(json.dumps({"value": "x" * 64}), schema)


@pytest.mark.asyncio
async def test_structured_result_rolls_back_with_message_failure(api, monkeypatch):
    app, client, server, root, body = api
    store = app.state.desktop.runtime.store
    original = store.create

    def create(kind, data):
        if kind == "message" and data.get("role") == "assistant":
            raise OSError("模拟交付消息写入失败")
        return original(kind, data)

    monkeypatch.setattr(store, "create", create)
    server.responses = [response(text='{"summary":"结果"}')]
    created = await client.post("/agent-runs", json={**body, "message": "解释项目结构", "output_schema": SCHEMA})
    run = await until(client, created.json()["id"], TERMINAL)
    assert run["status"] == "failed" and run["output"] is None
    assert run["structured_output"] is None and run["final_output_attempt_id"] is None
    events = (await client.get(f"/agent-runs/{run['id']}/events")).json()["items"]
    assert not any(item["type"] == "run.completed" for item in events)


@pytest.mark.asyncio
async def test_continuation_inherits_schema_without_inheriting_result(api):
    app, client, server, root, body = api
    server.responses = [response(text='{"summary":"第一次结果"}')]
    created = await client.post("/agent-runs", json={**body, "message": "解释项目结构", "output_schema": SCHEMA})
    await until(client, created.json()["id"], TERMINAL)
    owner = app.state.desktop.runtime
    parent = owner.store.run(created.json()["id"])
    child = owner.create(body, parent=parent, launch=False)
    assert child["output_schema"] == SCHEMA
    assert child["structured_output"] is None and child["final_output_attempt_id"] is None
    assert child["resumed_from_run_id"] == parent["id"]


@pytest.mark.asyncio
async def test_cancel_and_resume_keep_schema_and_do_not_publish_cancelled_result(api):
    app, client, server, root, body = api
    created = await client.post("/agent-runs", json={**body, "message": "解释项目结构",
        "recovery_contract_version": "1.0", "output_schema": SCHEMA})
    run_id = created.json()["id"]
    await waiting_model(api, run_id)
    await control(api, run_id, "cancel")
    stopped = await until(client, run_id, TERMINAL)
    assert stopped["status"] == "cancelled"
    assert stopped["structured_output"] is None and stopped["final_output_attempt_id"] is None
    server.responses = [response(text='{"summary":"恢复后的交付"}')]
    _, resumed = await control(api, run_id, "resume")
    final = await until(client, resumed["result_run_id"], TERMINAL)
    assert final["resumed_from_run_id"] == run_id
    assert final["status"] == "completed" and final["structured_output"] == {"summary": "恢复后的交付"}
    assert all(item["output_format"]["json_schema"] == SCHEMA for item in requests(server))
    events = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
    assert not any(event["type"] == "run.completed" for event in events)


@pytest.mark.asyncio
async def test_steering_discards_late_structured_answer(api, monkeypatch):
    app, client, server, root, body = api
    entered, release, calls = asyncio.Event(), asyncio.Event(), []

    async def complete(token, profile, request):
        calls.append(request)
        if len(calls) == 1:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                return response(text='{"summary":"旧回答"}')
        return response(text='{"summary":"按新约束解释"}')

    monkeypatch.setattr(app.state.desktop.runtime.cloud, "complete", complete)
    created = await client.post("/agent-runs", json={**body, "message": "解释项目结构",
        "recovery_contract_version": "1.0", "output_schema": SCHEMA})
    run_id = created.json()["id"]
    await asyncio.wait_for(entered.wait(), 2)
    await control(api, run_id, "steer", message="只解释目录职责，不运行命令")
    final = await until(client, run_id, TERMINAL)
    assert final["status"] == "completed" and final["structured_output"] == {"summary": "按新约束解释"}
    assert len(calls) == 2 and all(item["output_format"]["json_schema"] == SCHEMA for item in calls)
    events = (await client.get(f"/agent-runs/{run_id}/events")).json()["items"]
    discarded = next(event for event in events if event["type"] == "model.response_discarded")
    terminal = next(event for event in events if event["type"] == "run.completed")
    assert discarded["sequence"] < terminal["sequence"]
    assert terminal["payload"]["structured_output"] == {"summary": "按新约束解释"}
