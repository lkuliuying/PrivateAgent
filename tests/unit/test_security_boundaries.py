"""合成凭据在模型、文档检索与持续输出边界的隔离回归。"""
import copy
import json
from types import SimpleNamespace

import pytest
from test_direct_models import configure, desktop
from test_local_execution_sessions import finished, start
from test_local_execution_sessions import session as session

from private_agent_core.contracts import (
    ModelMessage,
    ModelRequest,
    ModelToolDefinition,
    ProviderState,
)
from private_agent_core.tool_specs import ToolFailure
from private_agent_local.direct_models import ConfiguredModels
from private_agent_local.documentation_mcp import DocumentationMcp
from private_agent_local.secret_filter import REDACTED
from private_agent_local.store import now


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "claude", "ollama"])
async def test_provider_requests_filter_content_but_preserve_auth_and_original(tmp_path, protocol):
    async with desktop(tmp_path, protocol) as (models, _, client, _, calls):
        profile = await configure(client, protocol)
        models.secrets["synthetic-extra"] = "fixture-sensitive-content"
        request = {"messages": [{"role": "user", "content": "检查 fixture-sensitive-content 与 token=synthetic-public-key。把词法分析代码改成 token=next_token，并解释含义。"}]}
        original = copy.deepcopy(request)
        await models.complete(models.token, profile, request)
        sent = calls[-1].content.decode()
        assert "fixture-sensitive-content" not in sent and "synthetic-public-key" not in sent
        assert REDACTED in sent
        assert "token=next_token" in sent
        decoded = json.loads(calls[-1].content)
        assert "并解释含义" in json.dumps(decoded, ensure_ascii=False)
        assert request == original


@pytest.mark.asyncio
async def test_native_continuation_filters_public_content_and_preserves_opaque_state():
    key = "fixture-native-private-value"
    models = ConfiguredModels(secrets={"fixture": key})
    items = [{"id": "r1", "type": "reasoning", "encrypted_content": "opaque-" + key,
              "summary": [{"type": "summary_text", "text": "摘要 " + key}]},
             {"id": "m1", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": key}]}]
    state = ProviderState(route="a" * 64, output_json=json.dumps(items))
    request = ModelRequest(messages=(ModelMessage(role="assistant", content=key, provider_state=state),),
                           tools=(ModelToolDefinition(name="inspect", description="原始结构", input_schema={"type": "object", "properties": {"token": {"type": "string"}}}),))
    try:
        filtered = models._safe_request(request)
        assert filtered.messages[0].content == REDACTED
        safe_items = json.loads(filtered.messages[0].provider_state.output_json)
        assert safe_items[0]["encrypted_content"] == items[0]["encrypted_content"]
        assert safe_items[0]["summary"][0]["text"] == "摘要 " + REDACTED
        assert safe_items[1]["content"][0]["text"] == REDACTED
        assert filtered.tools == request.tools
        assert request.messages[0].content == key
        assert request.messages[0].provider_state == state
    finally:
        await models.close()


def documentation_fixture(tmp_path, *, rotate=False):
    key = "fixture-documentation-private"
    state = SimpleNamespace(approvals=0, calls=0)
    cloud = SimpleNamespace(secrets={} if rotate else {"fixture": key})

    async def identity(_token):
        return {"id": 1}

    async def approve(*_args):
        state.approvals += 1
        if rotate:
            cloud.secrets["fixture"] = key
        return True

    async def call(_source, _tool, _arguments, guard):
        await guard()
        state.calls += 1
        return {"content": []}

    source = {"id": "a" * 32, "version": "b" * 32, "url": "https://docs.example.test/mcp", "enabled": True,
              "tools": ["search"], "discovered_at": now(), "catalog": {"sha256": "c" * 64,
              "tools": [{"name": "search", "input_schema": {"type": "object"}}]}}
    cloud.identity = identity
    owner = SimpleNamespace(cloud=cloud, token="fixture-session", approve=approve,
                            store=SimpleNamespace(get=lambda *_args: {"documentation_mcp": [source]}),
                            controls=SimpleNamespace(guard=lambda *_args: None), root=lambda *_args: tmp_path,
                            event=lambda *_args, **_kwargs: None)
    return DocumentationMcp(owner, SimpleNamespace(call=call)), state, key


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["known", "assignment", "nested", "key_name"])
async def test_mcp_sensitive_json_is_blocked_before_approval_and_network(tmp_path, kind):
    documentation, state, key = documentation_fixture(tmp_path)
    arguments = {"known": {"query": key}, "assignment": {"query": "password=synthetic-value"},
                 "nested": {"query": {"token": "synthetic-value"}}, "key_name": {key: "public"}}[kind]
    original = copy.deepcopy(arguments)
    call = {"name": "call_documentation_tool", "arguments": {"source_id": "a" * 32, "source_version": "b" * 32,
            "tool_name": "search", "arguments_json": json.dumps(arguments)}}
    with pytest.raises(ToolFailure) as failure:
        await documentation.execute({"project_id": 1, "workspace_id": 1}, tmp_path, call, {})
    assert failure.value.code == "mcp_sensitive_arguments"
    assert state.approvals == state.calls == 0
    assert key not in str(failure.value) and "synthetic-value" not in str(failure.value)
    assert arguments == original


@pytest.mark.asyncio
async def test_mcp_rechecks_credentials_changed_during_approval(tmp_path):
    documentation, state, key = documentation_fixture(tmp_path, rotate=True)
    call = {"name": "call_documentation_tool", "arguments": {"source_id": "a" * 32, "source_version": "b" * 32,
            "tool_name": "search", "arguments_json": json.dumps({"query": key})}}
    with pytest.raises(ToolFailure) as failure:
        await documentation.execute({"project_id": 1, "workspace_id": 1}, tmp_path, call, {})
    assert failure.value.code == "mcp_sensitive_arguments"
    assert state.approvals == 1 and state.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_real_process_split_secret_never_reaches_execution_sqlite(session, cancel):
    owner, run, root = session
    key = "fixture-command-private-731"
    owner.cloud.secrets = {"fixture": key}
    code = ("import sys,time; "
            f"sys.stdout.write({key[:12]!r}); sys.stdout.flush(); time.sleep(0.1); "
            f"sys.stdout.write({key[12:]!r}); sys.stdout.flush(); "
            "sys.stderr.write('password=synthetic-stderr'); sys.stderr.flush(); "
            f"time.sleep({10 if cancel else 0.05})")
    result = await start(session, code, yield_time_ms=300)
    if cancel:
        await owner.execution_sessions.stop_matching(lambda record: record["execution_id"] == result["execution_id"])
    final = await finished(session, result["execution_id"])
    chunks = "".join(chunk["data"] for chunk in final["chunks"])
    assert key not in chunks and "synthetic-stderr" not in chunks
    assert REDACTED in chunks
    rows = owner.store.db.execute("SELECT data FROM execution_chunks WHERE execution_id=?", (result["execution_id"],)).fetchall()
    assert rows and all(key not in row[0] and "synthetic-stderr" not in row[0] for row in rows)
    record = owner.store.execution_sessions.get(result["execution_id"], run["session_id"])
    assert key not in json.dumps(record)
    assert final["stopped"]
    assert not list(root.iterdir())
    events = owner.store.events(run["id"])
    output_events = [event for event in events if event["type"] == "execution.output"]
    assert output_events and all(isinstance(event["payload"]["received_at_unix_ms"], (int, float)) for event in output_events)
