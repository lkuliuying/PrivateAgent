"""M3：当前会话归档搜索工具的有界契约、排序与执行层限制。"""
import json

import pytest
from pydantic import ValidationError
from test_local_context_history import history_store
from test_local_executor import close, response, setup, until

from private_agent.agent.runtime import TERMINAL
from private_agent.contracts.runtime import (
    ModelMessage,
    ModelToolDefinition,
    ProviderState,
)
from private_agent.tools import tool_catalog
from private_agent.tools.tool_catalog import DEFERRED_TOOLS, ToolCatalog
from private_agent.tools.tool_registry import REGISTRY, SearchHistoryArgs

QUERY = {"query": "认证 配置"}


def append(store, session, content, *, key, role="user", source="user", name=None, **extra):
    return store.context.append(session, "run", ModelMessage(role=role, content=content,
                                                             name=name, **extra), key=key, source=source)


@pytest.mark.parametrize("arguments", [
    {"query": ""}, {"query": "   "}, {"query": None}, {"query": 123}, {"query": "x" * 201},
    {"query": "ok", "limit": 0}, {"query": "ok", "limit": 11}, {"query": "ok", "limit": "5"},
    {"query": "ok", "role": "system"}, {"query": "ok", "tool_name": "Read_File"},
    {"query": "ok", "extra": True},
])
def test_search_history_arguments_reject_invalid_input(arguments):
    with pytest.raises(ValidationError):
        SearchHistoryArgs.model_validate(arguments)


def test_search_finds_chinese_identifiers_paths_and_tool_names(tmp_path):
    store, session = history_store(tmp_path)
    try:
        chinese = append(store, session, "早期关键发现：认证模块在启动时读取本机配置文件", key="chinese")
        english = append(store, session, "service reads config/auth.json at startup", key="english", role="assistant", source="model")
        tool = append(store, session, json.dumps({"success": False, "error": "file_not_found", "path": "src/auth.py"}),
                      key="tool", role="tool", source="tool", name="read_code_file", tool_call_id="call-1")
        append(store, session, "无关内容", key="noise")
        for query, expected in [("认证", chinese), ("config", english), ("auth.json", english),
                                ("file_not_found", None), ("src/auth.py", None)]:
            result = store.context.search(session, query)
            found = {item["item_id"] for item in result["items"]}
            if expected is not None:
                assert expected["item_id"] in found, query
            else:
                assert tool["item_id"] in found, query
            assert result["scanned_items"] >= 1
        by_tool = store.context.search(session, "auth", tool_name="read_code_file")
        assert [item["item_id"] for item in by_tool["items"]] == [tool["item_id"]]
        assert by_tool["items"][0]["trust"] == "local"
        assert by_tool["items"][0]["read_tool"] == "read_context_content"
        assert store.context.search(session, "auth", role="user")["items"] == []
        assert store.context.search(session, "完全不存在的词")["items"] == []
        # 排序稳定，可重复。
        first = [item["item_id"] for item in store.context.search(session, "auth")["items"]]
        second = [item["item_id"] for item in store.context.search(session, "auth")["items"]]
        assert first == second and first
    finally:
        store.db.close()


def test_search_is_bounded_filtered_and_session_scoped(tmp_path):
    store, session = history_store(tmp_path)
    try:
        for index in range(12):
            append(store, session, f"认证 记录 {index} " + "x" * 600, key=f"item-{index}")
        secret = append(store, session, "认证 api_key=synthetic-fixture-value", key="secret")
        state = append(store, session, "", key="state", role="assistant", source="model",
                       provider_state=ProviderState(route="a" * 64, output_json=json.dumps({"handoff": "opaque-marker"})))
        other = store.create("session", {})["id"]
        foreign = store.context.append(other, "run", ModelMessage(role="user", content="认证 跨会话标记"), key="foreign", source="user")
        result = store.context.search(session, "认证", limit=10)
        assert len(result["items"]) == 10 and result["truncated"] is True
        assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 8 * 1024
        ids = {item["item_id"] for item in result["items"]}
        assert secret["item_id"] not in ids and state["item_id"] not in ids
        assert foreign["item_id"] not in ids
        assert store.context.search(session, "opaque-marker")["items"] == []
        assert store.context.search(session, "跨会话标记")["items"] == []
        excerpt = result["items"][0]
        assert excerpt["truncated"] is True and len(excerpt["excerpt"]) <= 400
        # provider_state 不进入任何结果字段或序列化内容。
        assert "opaque-marker" not in json.dumps(result, ensure_ascii=False)
        with pytest.raises(ValueError, match="200"):
            store.context.search(session, "x" * 201)
        with pytest.raises(ValueError, match="1～10"):
            store.context.search(session, "认证", limit=11)
        with pytest.raises(ValueError, match="角色"):
            store.context.search(session, "认证", role="system")
        with pytest.raises(ValueError, match="工具名"):
            store.context.search(session, "认证", tool_name="../etc/passwd")
    finally:
        store.db.close()


def run_state(**changes):
    return {"permission_mode": "confirm", "execution_contract_version": "1.0", **changes}


def test_search_history_is_deferred_and_discoverable():
    catalog = ToolCatalog(REGISTRY)
    eligible = tuple(spec for spec in REGISTRY if spec.name not in {"request_user_input", "update_run_plan", "tool_search"})
    run = run_state()
    initial = {definition.name for definition in catalog.definitions(run, eligible, {})}
    assert "search_context_history" in DEFERRED_TOOLS and "search_context_history" not in initial
    result = catalog.search(run, eligible, {}, {"query": "历史 归档 搜索", "limit": 5})
    assert "search_context_history" in result["loaded_tools"]
    after = {definition.name for definition in catalog.definitions(run, eligible, {})}
    assert "search_context_history" in after
    # 名称与关键词都能命中，未命中时不会加载工具。
    run = run_state()
    tool_catalog.ToolCatalog(REGISTRY).search(run, eligible, {}, {"query": "search_context_history", "limit": 1})
    assert "search_context_history" in run["tool_catalog"]["loaded_names"]
    run = run_state()
    assert catalog.search(run, eligible, {}, {"query": "zzzznone", "limit": 1})["matches"] == []
    assert run["tool_catalog"] == {"loaded_names": []}


def tool_outputs(store, session, name):
    return [json.loads(item["message"]["content"]) for item in store.context.items(session)
            if item["role"] == "tool" and item["message"].get("name") == name]


def test_native_public_text_is_searchable_but_internal_state_is_not(tmp_path):
    """F4：原生助手的公开正文可被搜索命中，不透明状态仍不可搜、不泄漏。"""
    store, session = history_store(tmp_path)
    try:
        item = store.context.append(session, "run", ModelMessage(
            role="assistant", content="NATIVE_PUBLIC_CONTRACT 保持公开可读",
            provider_state=ProviderState(route="a" * 64,
                                         output_json=json.dumps({"internal": "OPAQUE_STATE_MARKER"}))),
            key="native", source="model")
        # 分页续读能读到公开正文；搜索也必须命中同一条。
        assert "NATIVE_PUBLIC_CONTRACT" in store.context.read(session, item["item_id"], 0, 500)["content"]
        result = store.context.search(session, "NATIVE_PUBLIC_CONTRACT")
        assert [entry["item_id"] for entry in result["items"]] == [item["item_id"]]
        assert "NATIVE_PUBLIC_CONTRACT" in result["items"][0]["excerpt"]
        # 不透明状态不参与匹配、排序、摘录或序列化。
        assert store.context.search(session, "OPAQUE_STATE_MARKER")["items"] == []
        assert "OPAQUE_STATE_MARKER" not in json.dumps(result, ensure_ascii=False)
        assert "provider_state" not in json.dumps(result, ensure_ascii=False)
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_search_history_executes_read_only_in_current_session(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    try:
        early = owner.store.context.append(body["session_id"], "prior",
            ModelMessage(role="user", content="早期证据：认证模块读取本机配置"), key="early", source="user")
        server.responses = [response({"id": "search-1", "name": "tool_search",
                                      "arguments": {"query": "历史 归档", "limit": 3}}),
                            response({"id": "search-2", "name": "search_context_history",
                                      "arguments": {"query": "认证 配置", "limit": 3}}),
                            response(text="已找到早期证据")]
        run = (await client.post("/agent-runs", json={**body, "execution_contract_version": "1.0"})).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "completed", final.get("error_message")
        requests = [json.loads(payload)["request"] for path, payload in server.calls if path == "/desktop/model/complete"]
        names = [[tool["name"] for tool in request["tools"]] for request in requests]
        assert "search_context_history" not in names[0]
        assert "search_context_history" in names[1]
        outputs = tool_outputs(owner.store, body["session_id"], "search_context_history")
        assert outputs and outputs[0]["success"] is True
        found = outputs[0]["output"]
        assert found["items"][0]["item_id"] == early["item_id"]
        assert found["items"][0]["role"] == "user"
        assert found["notice"]
        assert "provider_state" not in json.dumps(outputs, ensure_ascii=False)
    finally:
        await close(app, client)


@pytest.mark.asyncio
async def test_search_history_is_blocked_when_path_scope_is_limited(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    try:
        server.responses = [response({"id": "search-1", "name": "tool_search",
                                      "arguments": {"query": "search_context_history", "limit": 1}}),
                            response({"id": "search-2", "name": "search_context_history",
                                      "arguments": {"query": "认证", "limit": 3}}),
                            response(text="范围内无法核对历史")]
        run = (await client.post("/agent-runs", json={**body, "execution_contract_version": "1.0",
                                                      "message": "只允许访问 src/，报告内容"})).json()
        final = await until(client, run["id"], TERMINAL)
        assert final["status"] == "completed", final.get("error_message")
        outputs = tool_outputs(owner.store, body["session_id"], "search_context_history")
        assert outputs and outputs[0]["success"] is False
        assert "限定访问路径" in json.dumps(outputs, ensure_ascii=False)
        assert owner.store.get("project", body["project_id"])["id"] == body["project_id"]
    finally:
        await close(app, client)


def test_search_tool_schema_stays_out_of_unrelated_requests():
    """新工具按需加载，不进入无关任务的请求定义，也不改变既有工具入参。"""
    eligible = tuple(spec for spec in REGISTRY if spec.name not in {"request_user_input", "update_run_plan", "tool_search"})
    definitions = ToolCatalog(REGISTRY).definitions(run_state(), eligible, {})
    assert all(isinstance(item, ModelToolDefinition) for item in definitions)
    assert "read_context_content" in {item.name for item in definitions}


def test_search_history_schema_keeps_strict_provider_contract():
    """严格函数协议：全部属性必填、禁止额外字段、不向模型暴露默认值。"""
    spec = REGISTRY["search_context_history"]
    schema = spec.definition().input_schema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert all("default" not in field for field in schema["properties"].values())
    # 输出上限在框架层再次强制，与实现内的 8 KiB 预算一致。
    assert spec.max_output_bytes == 8 * 1024 and spec.effect == "read" and spec.approval == "auto"
    assert "read_context_content" in spec.description and "No regex" in spec.description
