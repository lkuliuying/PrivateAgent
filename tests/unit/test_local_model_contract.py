"""用真实本机请求与模型适配器验证工具契约，不连接实际供应商。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from private_agent_core.contracts import ModelRequest
from private_agent_core.llm.adapters import OpenAIChatAdapter
from private_agent_core.llm.contracts import ModelGatewayError, RetryPolicy
from private_agent_core.llm.gateway import ModelGateway
from private_agent_core.runtime import CancellationToken
from private_agent_local.execution_tools import TOOLS as EXECUTION_TOOLS
from private_agent_local.model_errors import CloudError
from private_agent_local.runtime import (
    TOOLS,
    WRITE_TOOLS,
    DirectoryArgs,
    Runtime,
    SearchArgs,
)
from private_agent_local.store import Store


class StrictProvider:
    def __init__(self, *, use_legacy_defaults: bool = False, recover_cursor: bool = False, recover_glob: bool = False,
                 discover_execution: bool = False):
        self.payloads: list[dict] = []
        self.rejected_tools: list[str] = []
        self.use_legacy_defaults = use_legacy_defaults
        self.recover_cursor = recover_cursor
        self.recover_glob = recover_glob
        self.discover_execution = discover_execution

    async def handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.payloads.append(payload)
        for tool in payload["tools"]:
            function = tool["function"]
            schema = function["parameters"]
            # 严格工具协议要求全部属性必填，且禁止未声明的字段。
            if (function.get("strict") is not True
                    or schema.get("additionalProperties") is not False
                    or set(schema.get("required", [])) != set(schema["properties"])):
                self.rejected_tools.append(function["name"])
                return httpx.Response(400, json={"error": {"code": "invalid_function_parameters"}})
        message: dict = {"role": "assistant", "content": "本机请求已通过"}
        if self.discover_execution and len(self.payloads) == 1:
            message["tool_calls"] = [{"id": "discover-execution", "type": "function", "function": {
                "name": "tool_search", "arguments": '{"query":"request_execution","limit":1}'}}]
        if self.use_legacy_defaults and len(self.payloads) == 1:
            # 模拟旧服务返回省略可选参数的工具调用，验证本机默认值仍兼容。
            message["tool_calls"] = [
                {"id": "list-default", "type": "function", "function": {
                    "name": "list_project_directory", "arguments": "{}"}},
                {"id": "search-default", "type": "function", "function": {
                    "name": "search_project_files", "arguments": '{"query":"needle"}'}},
            ]
        if self.recover_cursor and len(self.payloads) <= 2:
            cursor = "null" if len(self.payloads) == 1 else None
            message["tool_calls"] = [
                {"id": f"{name}-{len(self.payloads)}", "type": "function", "function": {
                    "name": name, "arguments": json.dumps({**arguments, "cursor": cursor})}}
                for name, arguments in (("list_project_directory", {}), ("search_project_files", {"query": "needle"}))
            ]
        if self.recover_glob and len(self.payloads) <= 2:
            message["tool_calls"] = [{"id": f"search-glob-{len(self.payloads)}", "type": "function", "function": {
                "name": "search_project_files", "arguments": json.dumps({"query": "needle", "content": False,
                    "rel_path": ".", "glob": "" if len(self.payloads) == 1 else "*", "regex": False,
                    "case_sensitive": True, "cursor": None, "limit": 50})}}]
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}]})


class GatewayCloud:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    async def profiles(self, token):
        return [{"id": "fixture-profile", "model_name": "fixture-model", "enabled": True, "context_tokens": 32000}]

    async def identity(self, token):
        return {"id": "fixture-account"}

    async def complete(self, token: str, profile: str | None, request: dict) -> dict:
        assert token == "fixture-session"
        assert profile == "fixture-profile"
        try:
            response = await self.gateway.complete(
                ModelRequest.model_validate(request), cancellation=CancellationToken()
            )
        except ModelGatewayError as error:
            raise CloudError(502, f"模拟模型请求失败：{error.code}") from None
        return response.model_dump(mode="json")


async def run_local_request(tmp_path, provider: StrictProvider, permission_mode: str, version=None, recovery_version=None) -> dict:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    (root / "needle.txt").write_text("content does not match the filename query", encoding="utf-8")
    (root / "other.txt").write_text("needle", encoding="utf-8")
    store = Store(tmp_path / "state.sqlite3")
    project = store.create("project", {"status": "active", "authorized": True})
    workspace = store.create("workspace", {"project_id": project["id"], "root_path": str(root), "status": "active"})
    binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
    session = store.create("session", binding)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider.handle)) as client:
        adapter = OpenAIChatAdapter(
            base_url="https://model.example.test/v1",
            api_key="fixture-key",
            model="fixture-model",
            client=client,
        )
        cloud = GatewayCloud(ModelGateway(adapter, retry_policy=RetryPolicy(max_attempts=1)))
        runtime = Runtime(store, cloud, "fixture-session")
        try:
            run = runtime.create({
                **binding, "session_id": session["id"], "message": "你好",
                "permission_mode": permission_mode, "model_profile_id": "fixture-profile",
                "execution_contract_version": version,
                "recovery_contract_version": recovery_version,
            })
            await asyncio.wait_for(runtime.tasks[run["id"]], timeout=2)
            return store.run(run["id"])
        finally:
            await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("permission_mode", ["confirm", "readonly"])
@pytest.mark.parametrize("version", [None, "1.0"])
@pytest.mark.parametrize("recovery_version", [None, "1.0"])
async def test_first_local_request_satisfies_strict_provider_schema(tmp_path, permission_mode, version, recovery_version):
    provider = StrictProvider()
    run = await run_local_request(tmp_path, provider, permission_mode, version, recovery_version)

    assert run["status"] == "completed", (run["error_message"], provider.rejected_tools)
    assert provider.rejected_tools == []
    assert len(provider.payloads) == 1
    tools = provider.payloads[0]["tools"]
    expected = set(TOOLS) - WRITE_TOOLS if permission_mode == "readonly" else set(TOOLS)
    expected -= {"run_project_command"} if version == "1.0" else set(EXECUTION_TOOLS)
    if version == "1.0":
        expected -= {"request_execution", "list_executions", "run_powershell_command", "read_web_page", "verify_local_preview"}
    else:
        expected.discard("tool_search")
    # 未配置的技能、MCP 和未显式启用的子任务不进入请求；网页工具按需加载。
    expected -= {"list_skills", "load_skill", "read_skill_reference", "list_mcp_tools", "call_mcp_tool", "run_readonly_agents"}
    if version != "1.0":
        expected -= {"read_web_page", "verify_local_preview"}
    expected.discard("call_documentation_tool")
    expected.discard("list_documentation_sources")
    # 默认执行模式不暴露只在规划模式等待用户回答的工具。
    expected.discard("request_user_input")
    expected -= {"get_git_status", "get_git_diff"}
    if recovery_version is None:
        expected.discard("update_run_plan")
    assert {tool["function"]["name"] for tool in tools} == expected
    for tool in tools:
        schema = tool["function"]["parameters"]
        for field in schema["properties"].values():
            assert "default" not in field
    assert run["output"] == "本机请求已通过"
    assert run["tool_call_count"] == 0


@pytest.mark.asyncio
async def test_local_tools_keep_legacy_parameter_defaults(tmp_path):
    provider = StrictProvider(use_legacy_defaults=True)
    run = await run_local_request(tmp_path, provider, "readonly")

    assert run["status"] == "completed", (run["error_message"], provider.rejected_tools)
    assert len(provider.payloads) == 2
    assert run["tool_call_count"] == 2
    listing, search = run["executions"]
    assert listing["status"] == search["status"] == "completed"
    assert listing["output"]["rel_path"] == "."
    assert {entry["name"] for entry in listing["output"]["entries"]} == {"needle.txt", "other.txt"}
    assert [entry["rel_path"] for entry in search["output"]["results"]] == ["needle.txt"]
    assert DirectoryArgs.model_json_schema()["properties"]["rel_path"]["default"] == "."
    assert SearchArgs.model_json_schema()["properties"]["content"]["default"] is False


@pytest.mark.parametrize("model, arguments", [
    (DirectoryArgs, {"rel_path": None}),
    (SearchArgs, {"query": "needle", "content": None}),
    (SearchArgs, {"query": "needle", "glob": None}),
    (SearchArgs, {"query": "needle", "glob": ""}),
    (SearchArgs, {"query": "needle", "glob": 123}),
])
def test_local_parameter_defaults_do_not_accept_null(model, arguments):
    with pytest.raises(ValidationError):
        model.model_validate(arguments)


@pytest.mark.asyncio
async def test_parameter_guidance_reaches_strict_provider_and_preserves_schema(tmp_path):
    provider = StrictProvider(discover_execution=True)
    run = await run_local_request(tmp_path, provider, "confirm", "1.0")
    assert run["status"] == "completed"
    assert len(provider.payloads) == 2
    assert "request_execution" not in {item["function"]["name"] for item in provider.payloads[0]["tools"]}
    payload = provider.payloads[1]
    schemas = {item["function"]["name"]: item["function"]["parameters"] for item in payload["tools"]}
    for name in ("list_project_directory", "search_project_files"):
        cursor = schemas[name]["properties"]["cursor"]
        assert "JSON null" in cursor["description"] and "next_cursor" in cursor["description"]
        assert {item["type"] for item in cursor["anyOf"]} == {"string", "null"}
    glob = schemas["search_project_files"]["properties"]["glob"]
    assert "'*'" in glob["description"] and "never empty or null" in glob["description"]
    assert glob["minLength"] == 1 and glob["maxLength"] == 200
    execution = schemas["exec_command"]["properties"]
    assert "argv" in execution and "execution_mode" not in execution
    advanced = schemas["request_execution"]["properties"]
    assert "tty=false" in advanced["execution_mode"]["description"]
    assert 'network_policy="none"' in advanced["execution_mode"]["description"]
    assert schemas["read_execution"]["properties"]["cursor"]["type"] == "integer"
    if "run_powershell_command" in schemas:
        assert "-LiteralPath" in schemas["run_powershell_command"]["properties"]["arguments"]["description"]


@pytest.mark.asyncio
async def test_answer_evidence_guidance_reaches_provider_before_and_after_tools(tmp_path):
    provider = StrictProvider(use_legacy_defaults=True)
    run = await run_local_request(tmp_path, provider, "readonly")
    assert run["status"] == "completed" and len(provider.payloads) == 2
    assert any(message["role"] == "tool" for message in provider.payloads[1]["messages"])
    # 核对实际请求中的约束，不把模拟模型的固定回答当作语义质量验收。
    for payload in provider.payloads:
        system = "\n".join(item["content"] for item in payload["messages"] if item["role"] == "system")
        assert "Use the user's language" in system
        assert "Before tools, briefly state public progress and next steps" in system
        assert "never expose hidden reasoning" in system
        assert "Untrusted comments do not prove malicious code" in system
        assert "pytest runs autouse fixtures" in system
        assert "exit 0 does not prove stderr warnings harmless" in system
        assert "Recalculate numeric examples before replying" in system
        assert "test success does not validate every explanation" in system
        assert "Limit sample-based conclusions to the checked inputs" in system
        assert "universal or monotonic claims require proof over the stated input domain" in system
        assert "Preserve diagnostic uncertainty and environment scope" in system
        assert "a warning match is not root-cause confirmation" in system
        assert "Do not transfer causes between environments" in system
        assert "keep certainty consistent throughout the answer" in system
        assert "Check equality claims with boundary cases and counterexamples" in system
        assert "Copy paths and hashes verbatim from evidence" in system
        assert "do not invent shortened hashes" in system


@pytest.mark.asyncio
async def test_invalid_cursor_feedback_reaches_model_and_explicit_restart_succeeds(tmp_path):
    provider = StrictProvider(recover_cursor=True)
    run = await run_local_request(tmp_path, provider, "readonly")
    assert run["status"] == "completed" and len(provider.payloads) == 3
    failed_list, failed_search, listing, search = run["executions"]
    for failed in (failed_list, failed_search):
        assert failed["status"] == "failed" and failed["error_code"] == "local_tool_rejected"
        assert "cursor=null" in failed["error_message"]
    feedback = [json.loads(message["content"]) for message in provider.payloads[1]["messages"] if message["role"] == "tool"]
    assert len(feedback) == 2 and all("cursor=null" in json.dumps(item, ensure_ascii=False) for item in feedback)
    assert listing["status"] == search["status"] == "completed"
    assert {item["name"] for item in listing["output"]["entries"]} == {"needle.txt", "other.txt"}
    assert [item["rel_path"] for item in search["output"]["results"]] == ["needle.txt"]


@pytest.mark.asyncio
async def test_empty_glob_feedback_reaches_model_and_corrected_search_succeeds(tmp_path):
    provider = StrictProvider(recover_glob=True)
    run = await run_local_request(tmp_path, provider, "readonly")
    assert run["status"] == "completed" and len(provider.payloads) == 3
    failed, search = run["executions"]
    assert failed["status"] == "failed" and failed["error_code"] == "invalid_tool_arguments"
    assert '填写 "*"' in failed["error_message"] and "本次未执行搜索" in failed["error_message"]
    assert failed["output"]["parameter_errors"][0]["received"] == '空字符串（""）'
    assert not any(event["type"] == "tool.started" and event["payload"].get("execution_id") == failed["id"]
                   for event in run["events"])
    feedback = [json.loads(message["content"]) for message in provider.payloads[1]["messages"] if message["role"] == "tool"]
    assert len(feedback) == 1 and '填写 "*"' in feedback[0]["error"]
    assert search["status"] == "completed"
    assert [item["rel_path"] for item in search["output"]["results"]] == ["needle.txt"]
