"""真实模型请求链中的按需定义、逐轮授权集合及配置失效回归。"""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from test_local_executor import call, close, response, setup
from test_local_model_contract import StrictProvider, run_local_request
from test_local_planning import idle_run
from test_local_recovery import control

from private_agent_local.documentation_mcp import SelectionInput, SourceInput
from private_agent_local.store import now
from private_agent_local.task_constraints import apply_steer
from private_agent_local.tool_catalog import DEFERRED_TOOLS


class SelectionProvider(StrictProvider):
    def __init__(self, *, same_batch=False):
        super().__init__()
        self.same_batch = same_batch

    async def handle(self, request):
        response = await super().handle(request)
        if response.status_code != 200:
            return response
        ordinal = len(self.payloads)
        calls = []
        if ordinal == 1:
            calls.append(("discover-sessions", "tool_search", {"query": "list_executions", "limit": 1}))
            if self.same_batch:
                calls.append(("premature-sessions", "list_executions", {}))
        elif ordinal == 2:
            calls.append(("list-sessions", "list_executions", {}))
        body = response.json()
        if calls:
            body["choices"][0]["message"] = {"role": "assistant", "content": "检查已有执行会话。", "tool_calls": [
                {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
                for identifier, name, arguments in calls]}
        return httpx.Response(200, json=body)


def payload_names(payload):
    return {tool["function"]["name"] for tool in payload["tools"]}


def model_names(owner, run, root):
    return {tool.name for tool in owner.model_tools(run, root)}


def configured_source(owner, project_id):
    source = owner.documentation.create(project_id, SourceInput(name="SDK 文档", url="https://docs.example.test/mcp"))
    source = owner.documentation.save(project_id, {**source, "discovered_at": now(), "catalog": {
        "sha256": "d" * 64, "tools": [{"name": "search_sdk", "description": "SDK documentation search",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"], "additionalProperties": False}, "output_schema": None}]}}, previous=source["version"])
    return owner.documentation.select(project_id, source["id"], SelectionInput(
        expected_version=source["version"], tools=["search_sdk"], enabled=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("same_batch", [False, True])
async def test_tool_search_changes_next_actual_provider_request_and_freezes_current_batch(tmp_path, same_batch):
    provider = SelectionProvider(same_batch=same_batch)
    run = await run_local_request(tmp_path, provider, "readonly", "1.0")
    assert run["status"] == "completed", (run["error_message"], provider.rejected_tools)
    assert provider.rejected_tools == []
    assert len(provider.payloads) == 3
    first, second, third = provider.payloads
    assert "tool_search" in payload_names(first)
    assert not DEFERRED_TOOLS.intersection(payload_names(first))
    assert "list_executions" in payload_names(second) & payload_names(third)
    schema = next(tool["function"]["parameters"] for tool in second["tools"] if tool["function"]["name"] == "list_executions")
    assert schema == {"type": "object", "properties": {}, "additionalProperties": False, "required": []}
    executions = run["executions"]
    assert [item["tool_call_id"] for item in executions] == ["discover-sessions", "list-sessions"]
    assert all(item["status"] == "completed" for item in executions)
    assert executions[1]["output"]["items"] == []
    assert run["tool_catalog"]["loaded_names"] == ["list_executions"]
    feedback = {message["tool_call_id"]: json.loads(message["content"])
                for message in second["messages"] if message["role"] == "tool"}
    assert feedback["discover-sessions"]["success"] is True
    if same_batch:
        assert feedback["premature-sessions"]["success"] is False
        assert feedback["premature-sessions"]["error_code"] == "tool_not_available"
        assert not any(item["tool_call_id"] == "premature-sessions" for item in executions)
    else:
        assert set(feedback) == {"discover-sessions"}


@pytest.mark.asyncio
@pytest.mark.parametrize("permission, collaboration", [("confirm", "default"), ("readonly", "default"), ("confirm", "plan")])
async def test_persisted_loading_cannot_restore_tools_blocked_by_current_mode(tmp_path, permission, collaboration):
    api = await setup(tmp_path)
    try:
        owner, run = idle_run(api, execution_contract_version="1.0", recovery_contract_version="1.0",
                              permission_mode=permission, collaboration_mode=collaboration, message="你好")
        run["tool_catalog"] = {"loaded_names": ["request_execution", "list_executions"]}
        exposed = model_names(owner, run, api[3])
        if permission == "confirm" and collaboration == "default":
            assert {"request_execution", "exec_command", "list_executions"} <= exposed
        else:
            assert not {"request_execution", "exec_command", "write_stdin", "apply_project_patch"}.intersection(exposed)
        if collaboration == "plan":
            assert {"request_user_input", "update_run_plan"} <= exposed
            assert not {"list_executions", "run_powershell_command", "propose_project_patch"}.intersection(exposed)
        assert {"read_code_file", "search_project_files", "list_project_directory"} <= exposed
    finally:
        await close(api[0], api[1])


@pytest.mark.asyncio
async def test_legacy_model_tools_keep_enabled_documentation_without_search(tmp_path):
    api = await setup(tmp_path)
    try:
        owner, run = idle_run(api, execution_contract_version=None, message="你好")
        configured_source(owner, run["project_id"])
        exposed = model_names(owner, run, api[3])
        assert {"run_project_command", "list_documentation_sources", "call_documentation_tool"} <= exposed
        assert not {"tool_search", "exec_command", "request_execution", "list_executions"}.intersection(exposed)
    finally:
        await close(api[0], api[1])


@pytest.mark.asyncio
async def test_documentation_enabled_mid_run_loads_and_disabled_source_immediately_disappears(tmp_path):
    api = await setup(tmp_path)
    try:
        owner, run = idle_run(api, execution_contract_version="1.0", recovery_contract_version="1.0",
                              collaboration_mode="plan", message="你好")
        assert "call_documentation_tool" not in model_names(owner, run, api[3])
        source = configured_source(owner, run["project_id"])
        assert "tool_search" in model_names(owner, run, api[3])
        result = await owner.tool(run, api[3], call("tool_search", {"query": "search_sdk", "limit": 1}))
        assert result["matches"][0]["source_version"] == source["version"]
        assert {"list_documentation_sources", "call_documentation_tool"} <= model_names(owner, run, api[3])
        owner.documentation.select(run["project_id"], source["id"], SelectionInput(
            expected_version=source["version"], tools=["search_sdk"], enabled=False))
        assert not {"list_documentation_sources", "call_documentation_tool"}.intersection(model_names(owner, run, api[3]))
        assert not run["approvals"]
    finally:
        await close(api[0], api[1])


@pytest.mark.asyncio
async def test_loaded_documentation_disabled_after_model_request_never_reaches_approval_or_remote(tmp_path, monkeypatch):
    api = await setup(tmp_path)
    try:
        owner, run = idle_run(api, execution_contract_version="1.0", permission_mode="readonly", message="你好")
        source = configured_source(owner, run["project_id"])
        requests = []
        complete = owner.cloud.complete

        async def disable_before_response(token, profile, request):
            requests.append(request)
            if len(requests) == 2:
                assert "call_documentation_tool" in {item["name"] for item in request["tools"]}
                owner.documentation.select(run["project_id"], source["id"], SelectionInput(
                    expected_version=source["version"], tools=["search_sdk"], enabled=False))
            return await complete(token, profile, request)

        monkeypatch.setattr(owner.cloud, "complete", disable_before_response)
        approve = AsyncMock(side_effect=AssertionError("已停用文档源不应请求审批"))
        remote = AsyncMock(side_effect=AssertionError("已停用文档源不应发送请求"))
        monkeypatch.setattr(owner, "approve", approve)
        monkeypatch.setattr(owner.documentation.client, "call", remote)
        api[2].responses = [
            response(call("tool_search", {"query": "search_sdk", "limit": 1})),
            response(call("call_documentation_tool", {"source_id": source["id"], "source_version": source["version"],
                "tool_name": "search_sdk", "arguments_json": '{"query":"public SDK"}'})),
            response(text="文档源已停用，未发送查询。"),
        ]
        owner.launch(run)
        await asyncio.wait_for(owner.tasks[run["id"]], 5)
        final = owner.store.run(run["id"])
        assert final["status"] == "completed", final["error_message"]
        assert len(requests) == 3
        assert "call_documentation_tool" not in {item["name"] for item in requests[2]["tools"]}
        failed = next(item for item in final["executions"] if item["tool_name"] == "call_documentation_tool")
        assert failed["status"] == "failed" and failed["error_code"] == "mcp_config_changed"
        assert not final["approvals"]
        approve.assert_not_awaited()
        remote.assert_not_awaited()
    finally:
        await close(api[0], api[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("collaboration", ["default", "plan"])
async def test_real_child_creation_inherits_loaded_names_without_releasing_network_or_plan_constraints(tmp_path, monkeypatch, collaboration):
    api = await setup(tmp_path)
    try:
        owner, parent = idle_run(api, execution_contract_version="1.0", recovery_contract_version="1.0", message="你好")
        source = configured_source(owner, parent["project_id"])
        for index, query in enumerate(("request_execution", "search_sdk")):
            result = await owner.tool(parent, api[3], {
                "id": f"discover-parent-{index}", "name": "tool_search", "arguments": {"query": query, "limit": 1}})
            assert "error" not in result
        apply_steer(parent, "不要联网", "parent-network-restriction")
        parent.update(status="interrupted", active_in_process=False)
        owner.store.save_run(parent)
        created = owner.create({**api[4], "message": parent["goal"], "execution_contract_version": "1.0",
                                "recovery_contract_version": "1.0", "collaboration_mode": collaboration},
                               parent=parent, launch=False)
        child = owner.store.run(created["id"])
        assert child["resumed_from_run_id"] == parent["id"]
        assert child["tool_catalog"] == parent["tool_catalog"]
        assert child["tool_catalog"] is not parent["tool_catalog"]
        assert child["completion_policy"]["network_forbidden"] is True
        exposed = model_names(owner, child, api[3])
        assert "list_documentation_sources" in exposed and "call_documentation_tool" not in exposed
        assert ("request_execution" in exposed) is (collaboration == "default")
        assert ("exec_command" in exposed) is (collaboration == "default")
        if collaboration == "plan":
            assert "request_user_input" in exposed and "apply_project_patch" not in exposed
        approve, remote, start = AsyncMock(), AsyncMock(), AsyncMock()
        monkeypatch.setattr(owner, "approve", approve)
        monkeypatch.setattr(owner.documentation.client, "call", remote)
        monkeypatch.setattr(owner.execution_sessions, "start", start)
        document = await owner.tool(child, api[3], call("call_documentation_tool", {
            "source_id": source["id"], "source_version": source["version"], "tool_name": "search_sdk",
            "arguments_json": '{"query":"public SDK"}'}))
        advanced = await owner.tool(child, api[3], call("request_execution", {
            "argv": ["python", "task.py"], "execution_mode": "trusted_project", "network_policy": "approved"}))
        assert document["error_code"] == advanced["error_code"] == "user_constraint"
        for action in (approve, remote, start):
            action.assert_not_awaited()
        assert not child["approvals"] and parent["tool_catalog"] == child["tool_catalog"]
    finally:
        await close(api[0], api[1])


@pytest.mark.asyncio
async def test_steer_after_search_discards_old_command_and_filters_next_model_tools(tmp_path, monkeypatch):
    api = await setup(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    try:
        owner, run = idle_run(api, execution_contract_version="1.0", recovery_contract_version="1.0",
                              permission_mode="workspace", message="你好")
        original = owner.tool

        async def search_boundary(current, root, request):
            result = await original(current, root, request)
            if request["name"] == "tool_search":
                entered.set()
                await release.wait()
            return result

        monkeypatch.setattr(owner, "tool", search_boundary)
        start = AsyncMock(side_effect=AssertionError("追加禁止命令后不应启动进程"))
        approve = AsyncMock(side_effect=AssertionError("追加禁止命令后不应请求审批"))
        monkeypatch.setattr(owner.execution_sessions, "start", start)
        monkeypatch.setattr(owner, "approve", approve)
        api[2].responses = [
            response(call("tool_search", {"query": "request_execution", "limit": 1}),
                     {"id": "old-command", "name": "exec_command", "arguments": {"argv": ["python", "task.py"]}}),
            response({"id": "new-command", "name": "exec_command", "arguments": {"argv": ["python", "task.py"]}}),
            response(text="已遵守新的约束，没有运行命令。"),
        ]
        owner.launch(run)
        await asyncio.wait_for(entered.wait(), 5)
        await control(api, run["id"], "steer", message="不要运行任何命令，仅解释已观察的信息。")
        release.set()
        await asyncio.wait_for(owner.tasks[run["id"]], 5)
        final = owner.store.run(run["id"])
        assert final["status"] == "completed", final["error_message"]
        assert final["goal_version"] == 2 and final["completion_policy"]["commands_forbidden"] is True
        assert final["tool_catalog"]["loaded_names"] == ["request_execution"]
        assert [item["tool_name"] for item in final["executions"]] == ["tool_search"]
        requests = [json.loads(content)["request"] for path, content in api[2].calls if path == "/desktop/model/complete"]
        assert len(requests) == 3
        for request in requests[1:]:
            assert not {"exec_command", "request_execution", "write_stdin"}.intersection(item["name"] for item in request["tools"])
        messages = owner.store.context.messages(run["session_id"])
        feedback = {message.tool_call_id: json.loads(message.content) for message in messages if message.role == "tool"}
        search_call = final["executions"][0]["tool_call_id"]
        assert feedback[search_call]["error_code"] == "steering_superseded"
        assert feedback[search_call].get("output") is None
        assert feedback["old-command"]["error_code"] == "steering_superseded"
        assert feedback["new-command"]["error_code"] == "tool_not_available"
        assert not final["approvals"]
        start.assert_not_awaited()
        approve.assert_not_awaited()
    finally:
        release.set()
        await close(api[0], api[1])
