"""用真实本机请求与模型适配器验证工具契约，不连接实际供应商。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from personal_assistant.agents.contracts import ModelRequest
from personal_assistant.agents.runtime import CancellationToken
from personal_assistant.llm import (
    ModelGateway,
    ModelGatewayError,
    OpenAIChatAdapter,
    RetryPolicy,
)
from private_agent_local.cloud import CloudError
from private_agent_local.runtime import (
    TOOLS,
    WRITE_TOOLS,
    DirectoryArgs,
    Runtime,
    SearchArgs,
)
from private_agent_local.store import Store


class StrictProvider:
    def __init__(self, *, use_legacy_defaults: bool = False):
        self.payloads: list[dict] = []
        self.rejected_tools: list[str] = []
        self.use_legacy_defaults = use_legacy_defaults

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
        if self.use_legacy_defaults and len(self.payloads) == 1:
            # 模拟旧服务返回省略可选参数的工具调用，验证本机默认值仍兼容。
            message["tool_calls"] = [
                {"id": "list-default", "type": "function", "function": {
                    "name": "list_project_directory", "arguments": "{}"}},
                {"id": "search-default", "type": "function", "function": {
                    "name": "search_project_files", "arguments": '{"query":"needle"}'}},
            ]
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}]})


class GatewayCloud:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

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


async def run_local_request(tmp_path, provider: StrictProvider, permission_mode: str) -> dict:
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
            })
            await asyncio.wait_for(runtime.tasks[run["id"]], timeout=2)
            return store.run(run["id"])
        finally:
            await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("permission_mode", ["confirm", "readonly"])
async def test_first_local_request_satisfies_strict_provider_schema(tmp_path, permission_mode):
    provider = StrictProvider()
    run = await run_local_request(tmp_path, provider, permission_mode)

    assert run["status"] == "completed", (run["error_message"], provider.rejected_tools)
    assert provider.rejected_tools == []
    assert len(provider.payloads) == 1
    tools = provider.payloads[0]["tools"]
    expected = set(TOOLS) - WRITE_TOOLS if permission_mode == "readonly" else set(TOOLS)
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
])
def test_local_parameter_defaults_do_not_accept_null(model, arguments):
    with pytest.raises(ValidationError):
        model.model_validate(arguments)
