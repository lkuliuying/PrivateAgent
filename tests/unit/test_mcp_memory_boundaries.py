"""附件工具预算与远端写入未知状态的隔离回归。"""
import json
import sqlite3

import httpx
import pytest
from test_local_attachments import commit_attachment, staged
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_core.contracts import ModelMessage, ToolCall
from private_agent_local.recovery import reconcile_mcp_execution
from private_agent_local.store import SCHEMA_VERSION, Store


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["default", "plan"])
async def test_attachment_tools_follow_committed_session_history(tmp_path, mode):
    app, client, _, root, body = await setup(tmp_path)
    try:
        owner = app.state.desktop.runtime
        store = owner.store
        session = store.get("session", body["session_id"])
        run = {**body, "permission_mode": "workspace", "collaboration_mode": mode}
        def names():
            return {spec.name for spec in owner.catalog_inputs(run, root)[0]}
        assert "read_task_attachment" not in names()
        item, draft, _ = staged(tmp_path, store, body["project_id"], body["workspace_id"], session["id"])
        assert "read_task_attachment" not in names()
        commit_attachment(store, item, draft, session)
        assert "read_task_attachment" in names()
        assert store.attachments.read(item["id"], session_id=session["id"])["content"] == "原始材料"
        another = store.create("session", {"project_id": body["project_id"], "workspace_id": body["workspace_id"]})
        run["session_id"] = another["id"]
        assert "read_task_attachment" not in names()
    finally:
        await close(app, client)


@pytest.mark.parametrize("phase,readonly,unknown", [
    ("prepared", False, False), ("dispatched", False, True),
    ("acknowledged", False, False), ("dispatched", True, False),
])
def test_mcp_unknown_boundary_is_durable_and_idempotent(phase, readonly, unknown):
    run = {}
    execution = {"id": "execution", "operation_id": "operation", "status": "running",
                 "mcp_call": {"phase": phase, "readonly": readonly, "source_id": "source", "tool": "write"}}
    assert reconcile_mcp_execution(run, execution) is unknown
    assert reconcile_mcp_execution(run, execution) is unknown
    assert len(run.get("uncertain_operations", [])) == int(unknown)
    if unknown:
        assert execution["status"] == "unknown" and execution["error_code"] == "execution_unknown"


def test_newer_project_database_is_rejected_without_changing_bytes(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="不要降级写入"):
        Store(path)
    assert path.read_bytes() == original


def test_restart_blocks_unacknowledged_mcp_write(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    session = store.create("session", {})
    store.save_run({"id": "run", "session_id": session["id"], "status": "running", "executions": [
        {"id": "execution", "operation_id": "operation", "status": "running", "tool_name": "call_mcp_tool",
         "mcp_call": {"phase": "dispatched", "readonly": False, "source_id": "source", "tool": "write"}}]})
    store.db.close()
    recovered = Store(path)
    try:
        run = recovered.run("run")
        assert run["executions"][0]["error_code"] == "execution_unknown"
        assert len(run["uncertain_operations"]) == 1
    finally:
        recovered.db.close()


def test_restart_preserves_acknowledged_mcp_receipt(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    session = store.create("session", {})
    recorded = store.context.append(session["id"], "run", ModelMessage(role="assistant", tool_calls=(
        ToolCall(id="call", name="call_mcp_tool", arguments={}),)), key="call", source="model")
    output = {"result": {"content": [{"type": "text", "text": "已写入"}]}, "untrusted": True}
    store.save_run({"id": "run", "session_id": session["id"], "status": "running", "executions": [
        {"id": "execution", "operation_id": "operation", "tool_call_id": "call", "tool_name": "call_mcp_tool", "status": "running",
         "output": output, "mcp_call": {"phase": "acknowledged", "readonly": False, "context_item_id": recorded["item_id"]}}]})
    store.db.close()
    recovered = Store(path)
    try:
        execution = recovered.run("run")["executions"][0]
        assert execution["status"] == "completed" and execution["output"] == output
        messages = recovered.context.items(session["id"])
        assert len(messages) == 2 and "已写入" in messages[-1]["message"]["content"]
        assert messages[-1]["external_context"]
    finally:
        recovered.db.close()


@pytest.mark.parametrize("latest_acknowledged", [False, True])
def test_restart_never_borrows_old_receipt_for_reused_call_id(tmp_path, latest_acknowledged):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    session = store.create("session", {})
    executions = []
    for index in range(2):
        item = store.context.append(session["id"], "run", ModelMessage(role="assistant", tool_calls=(
            ToolCall(id="reused", name="call_mcp_tool", arguments={"index": index}),)), key=f"call-{index}", source="model")
        output = {"result": {"receipt": f"receipt-{index}"}, "untrusted": True}
        acknowledged = index == 0 or latest_acknowledged
        executions.append({"id": f"execution-{index}", "operation_id": f"operation-{index}", "tool_call_id": "reused",
                           "tool_name": "call_mcp_tool", "status": "completed" if index == 0 else "running",
                           "output": output if acknowledged else None,
                           "mcp_call": {"phase": "acknowledged" if acknowledged else "prepared", "readonly": False,
                                        "context_item_id": item["item_id"]}})
        if index == 0:
            store.context.append(session["id"], "run", ModelMessage(role="tool", name="call_mcp_tool",
                tool_call_id="reused", content=json.dumps(output)), key="prior-result", source="tool")
    store.save_run({"id": "run", "session_id": session["id"], "status": "running", "executions": executions})
    store.db.close()
    recovered = Store(path)
    try:
        last = json.loads(recovered.context.items(session["id"])[-1]["message"]["content"])
        assert "receipt-0" not in json.dumps(last)
        if latest_acknowledged:
            assert last["result"]["receipt"] == "receipt-1"
        else:
            assert last["error_code"] == "result_unknown"
    finally:
        recovered.db.close()


@pytest.mark.asyncio
async def test_runtime_explicit_memory_returns_receipt_without_enabling_recall(tmp_path):
    app, client, server, _, body = await setup(tmp_path)
    original = server.handle
    requests = []
    instruction = "记住：默认用中文回答"

    async def handle(request):
        if request.url.path != "/desktop/model/complete":
            return await original(request)
        model_request = json.loads(request.content)["request"]
        requests.append(model_request)
        if len(requests) == 1:
            assert "remember_memory" not in {tool["name"] for tool in model_request["tools"]}
            return httpx.Response(200, json=response(call("tool_search", {"query": "remember_memory", "limit": 1})))
        if len(requests) == 2:
            guidance = next(item["content"] for item in model_request["messages"] if item["content"].startswith("memory_authorization"))
            authorization = json.loads(guidance[guidance.index("{"):])
            return httpx.Response(200, json=response(call("remember_memory", {**authorization,
                "authorization_quote": instruction, "memory": {"scope": "project", "kind": "preference", "title": "回答语言", "content": "默认用中文回答"}})))
        return httpx.Response(200, json=response(text="已保存到当前项目，当前未启用使用。"))

    server.handle = handle
    try:
        owner = app.state.desktop.runtime
        created = owner.create({**body, "message": instruction, "permission_mode": "confirm", "execution_contract_version": "1.0"})
        await until(client, created["id"], TERMINAL)
        run = owner.store.run(created["id"])
        execution = next(item for item in run["executions"] if item["tool_name"] == "remember_memory")
        assert execution["status"] == "completed", execution
        assert execution["output"]["content"] == "默认用中文回答"
        assert execution["output"]["scope"] == "project" and not execution["output"]["effective_use"]
        assert len(owner.memories.store.list(body["project_id"])) == 1
        assert owner.memories.store.settings()["enabled"] is False
        assert run["memory_context"]["recalled_ids"] == []
    finally:
        await close(app, client)
