"""通用 MCP、公开网络、预览代理与只读子任务的实际协议边界。"""
import asyncio
import json
import sys

import httpx2
import pytest
from test_documentation_mcp import mcp_protocol as mcp_protocol
from test_local_executor import call, close, response, setup, until
from test_workspace_features import seeded

from private_agent_core.tool_specs import ToolFailure
from private_agent_local.browser_tools import PageText, PreviewProxy, preview_origin
from private_agent_local.integration_mcp import SelectionInput, SourceInput
from private_agent_local.public_http import PublicTransport, public_url
from private_agent_local.runtime import TERMINAL
from private_agent_local.secret_filter import SecretFilter


@pytest.fixture
async def local(tmp_path):
    value = await setup(tmp_path)
    try:
        yield value
    finally:
        await close(value[0], value[1])


async def configured(owner, project_id):
    service = owner.integrations
    source = service.create(project_id, SourceInput(name="协议夹具", transport="https", url="https://docs.example.test/mcp"))
    service.connect(project_id, source["id"])
    await service.tasks[source["id"]]
    assert service.connection_state(source["id"])["status"] == "connected"
    source = service.source(project_id, source["id"])
    return service.select(project_id, source["id"], SelectionInput(expected_version=source["version"], enabled=True,
                          tools=[{"name": "search_docs", "readonly": True, "approval": "session"}]))


def invocation(source):
    return call("call_mcp_tool", {"source_id": source["id"], "source_version": source["version"], "tool_name": "search_docs", "arguments_json": json.dumps({"query": "Vue"})})


@pytest.mark.asyncio
async def test_general_mcp_discovery_approval_reuse_and_revocation(local, mcp_protocol, monkeypatch):
    app, _, _, root, body = local
    owner = app.state.desktop.runtime
    source = await configured(owner, body["project_id"])
    run = seeded(owner, body)
    approved = []

    async def approve(*args):
        approved.append(args)
        return True

    monkeypatch.setattr(owner, "approve", approve)
    for _ in range(2):
        result = await owner.integrations.execute(run, root, invocation(source), {})
        assert result["untrusted"] and result["result"]["structured_content"]["url"].startswith("https://")
    assert len(approved) == 1 and len(mcp_protocol.calls) == 2
    matches = owner.tool_catalog.search(run, *owner.catalog_inputs(run, root), {"query": "search_docs", "limit": 5})
    assert any(item["kind"] == "mcp" for item in matches["matches"])
    owner.integrations.select(body["project_id"], source["id"], SelectionInput(expected_version=source["version"], enabled=False, tools=[]))
    with pytest.raises(ToolFailure, match="配置已变化"):
        await owner.integrations.execute(run, root, invocation(source), {})
    assert len(mcp_protocol.calls) == 2


@pytest.mark.asyncio
async def test_mcp_catalog_change_and_write_constraints_prevent_invocation(local, mcp_protocol, monkeypatch):
    app, _, _, root, body = local
    owner = app.state.desktop.runtime
    source = await configured(owner, body["project_id"])
    run = seeded(owner, body)

    async def approve(*args):
        return True

    monkeypatch.setattr(owner, "approve", approve)
    mcp_protocol.changed = True
    with pytest.raises(ToolFailure, match="服务工具已变化"):
        await owner.integrations.execute(run, root, invocation(source), {})
    mcp_protocol.changed = False
    source["tools"][0].update(readonly=False, approval="always")
    owner.integrations.save(body["project_id"], source)
    run.update(permission_mode="workspace", completion_policy={"writes_forbidden": True})
    with pytest.raises(ToolFailure, match="外部写入"):
        await owner.integrations.execute(run, root, invocation(source), {})
    assert not mcp_protocol.calls


@pytest.mark.asyncio
async def test_mcp_rechecks_configuration_after_discovery(local, mcp_protocol, monkeypatch):
    from private_agent_local import integration_mcp
    app, _, _, root, body = local
    owner = app.state.desktop.runtime
    source = await configured(owner, body["project_id"])
    run = seeded(owner, body)
    original = integration_mcp.catalog

    async def changed(client):
        result = await original(client)
        owner.integrations.select(body["project_id"], source["id"], SelectionInput(expected_version=source["version"], enabled=False, tools=[]))
        return result

    async def approve(*args):
        return True

    monkeypatch.setattr(owner, "approve", approve)
    monkeypatch.setattr(integration_mcp, "catalog", changed)
    with pytest.raises(ToolFailure, match="配置已经变化"):
        await owner.integrations.execute(run, root, invocation(source), {})
    assert not mcp_protocol.calls


@pytest.mark.parametrize("url", ["http://example.com", "https://127.0.0.1", "https://10.0.0.2", "https://[::1]", "https://localhost", "https://example.com:444", "https://user:pass@example.com", "https://example.com/#fragment"])
def test_public_http_rejects_private_or_credential_urls(url):
    with pytest.raises(ToolFailure):
        public_url(url)


@pytest.mark.asyncio
async def test_public_transport_rejects_dns_rebinding(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ToolFailure, match="内网"):
        await PublicTransport().handle_async_request(httpx2.Request("GET", "https://example.test/page"))


def test_stdio_requires_explicit_trust_and_direct_executable():
    with pytest.raises(ValueError, match="信任"):
        SourceInput(name="test", transport="stdio", command=sys.executable)
    value = SourceInput(name="test", transport="stdio", command=sys.executable, trust_process=True, args=["-V"])
    assert value.command == sys.executable


@pytest.mark.asyncio
async def test_stdio_process_discovers_and_calls_through_real_sdk(local, monkeypatch):
    app, _, _, root, body = local
    script = root / "mcp_fixture.py"
    script.write_text('''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "search_docs", "description": "Fixture", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "stdio:" + request["params"]["arguments"]["query"]}], "isError": False}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Method not found"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
''', encoding="utf-8")
    owner = app.state.desktop.runtime
    service = owner.integrations
    source = service.create(body["project_id"], SourceInput(name="stdio 夹具", transport="stdio", command=sys.executable, args=["-B", str(script)], trust_process=True))
    service.connect(body["project_id"], source["id"])
    await service.tasks[source["id"]]
    assert service.connection_state(source["id"])["status"] == "connected"
    source = service.source(body["project_id"], source["id"])
    source = service.select(body["project_id"], source["id"], SelectionInput(expected_version=source["version"], enabled=True, tools=[{"name": "search_docs", "readonly": True, "approval": "always"}]))

    async def approve(*args):
        return True

    monkeypatch.setattr(owner, "approve", approve)
    result = await service.execute(seeded(owner, body), root, invocation(source), {})
    assert result["result"]["content"][0]["text"] == "stdio:Vue"


@pytest.mark.parametrize("url", ["file:///C:/private.txt", "http://example.com:3000", "http://127.0.0.1:80", "http://user@localhost:3000", "https://localhost:3000"])
def test_local_preview_origin_rejects_unsafe_addresses(url):
    with pytest.raises(ValueError):
        preview_origin(url)


def test_web_parser_excludes_scripts_and_resolves_source_links():
    parser = PageText("https://example.test/docs/")
    parser.feed('<h1>资料</h1><script>secret-script()</script><style>.x {}</style><a href="../api">接口</a>')
    assert parser.text == ["资料", "接口"]
    assert parser.links == ["https://example.test/api"]


@pytest.mark.asyncio
async def test_preview_proxy_blocks_writes_cross_origin_and_allows_get():
    requests = []

    async def page(reader, writer):
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await asyncio.start_server(page, "127.0.0.1", 0)
    origin = f"http://127.0.0.1:{upstream.sockets[0].getsockname()[1]}"
    proxy = PreviewProxy(origin, SecretFilter())
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        for method, url, expected in [("GET", origin + "/", b"200 OK"), ("POST", origin + "/write", b"403"), ("GET", "http://127.0.0.1:1024/", b"403"), ("CONNECT", "example.com:443", b"403")]:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(f"{method} {url} HTTP/1.1\r\nHost: example\r\n\r\n".encode())
            await writer.drain()
            assert expected in await asyncio.wait_for(reader.read(), 3)
            writer.close()
            await writer.wait_closed()
        assert len(requests) == 1
    finally:
        server.close()
        upstream.close()
        await server.wait_closed()
        await upstream.wait_closed()
        await proxy.close()


@pytest.mark.asyncio
async def test_removed_subagents_reject_enablement_without_creating_a_run(local):
    app, client, server, _, body = local
    result = await client.post("/agent-runs", json={**body, "allow_subagents": True})
    assert result.status_code == 422
    assert not app.state.desktop.runtime.store.runs()
    assert not [item for item in server.calls if item[0] == "/desktop/model/complete"]


@pytest.mark.asyncio
async def test_legacy_subagent_permission_is_not_exposed_or_restored(local):
    app, client, server, root, body = local
    owner = app.state.desktop.runtime
    created = (await client.post("/agent-runs", json={**body, "permission_mode": "readonly", "execution_contract_version": "1.0", "recovery_contract_version": "1.0"})).json()
    await until(client, created["id"], {"running"})
    await owner.cancel(created["id"])
    parent = owner.store.run(created["id"])
    parent["allow_subagents"] = True
    owner.store.save_run(parent)
    assert "run_readonly_agents" not in {tool.name for tool in owner.model_tools(parent, root)}
    report = owner.recovery.inspect(parent)
    server.responses = [response(text="恢复后汇总")]
    server.block.set()
    resumed = await owner.controls.request(created["id"], "resume", {"request_id": "resume-legacy-parent", "expected_state_version": report["state_version"], "checkpoint_id": report["checkpoint_id"]})
    await until(client, resumed["result_run_id"], TERMINAL)
    assert owner.store.run_state(resumed["result_run_id"])["allow_subagents"] is False
    assert not owner.agents.children(resumed["result_run_id"])


@pytest.mark.asyncio
async def test_finished_run_automatically_launches_one_durable_queued_turn(local):
    app, client, server, _, body = local
    owner = app.state.desktop.runtime
    created = (await client.post("/agent-runs", json={**body, "permission_mode": "readonly", "execution_contract_version": "1.0", "recovery_contract_version": "1.0"})).json()
    await until(client, created["id"], {"running"})
    queued = await client.post(f"/sessions/{body['session_id']}/turn-queue", json={"run_id": created["id"], "request_id": "queued-runtime", "message": "只回答后续问题"})
    assert queued.status_code == 200, queued.text
    server.responses = [response(text="第一轮结果"), response(text="后续结果")]
    server.block.set()
    async with asyncio.timeout(5):
        while owner.turn_queue.get(body["session_id"])["state"] == "pending":
            await asyncio.sleep(.01)
    result = owner.turn_queue.get(body["session_id"])
    assert result["state"] == "launched", result
    final = await until(client, result["result_run_id"], TERMINAL)
    assert final["status"] == "completed" and final["output"] == "后续结果"
    assert len(owner.store.runs()) == 2


@pytest.mark.asyncio
async def test_oauth_callback_requires_matching_state(local):
    app, _, _, _, _ = local
    service = app.state.desktop.runtime.integrations
    future = asyncio.get_running_loop().create_future()
    service.flows["source"] = {"state": "expected-state", "callback": future}
    server = await asyncio.start_server(service.receive_callback, "127.0.0.1", 0)
    try:
        for state, expected in [("wrong", b"400"), ("expected-state", b"200")]:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
            writer.write(f"GET /callback/source?code=synthetic-code&state={state} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
            await writer.drain()
            assert expected in await asyncio.wait_for(reader.read(), 2)
            assert future.done() == (state == "expected-state")
            writer.close()
            await writer.wait_closed()
        assert future.result().code == "synthetic-code"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_real_browser_records_dom_assertions_and_owned_screenshot(local):
    from private_agent_local.browser_tools import PreviewArgs, browser_binary
    if browser_binary() is None:
        pytest.skip("未安装可用于预览验证的浏览器")
    app, client, _, _, body = local
    owner = app.state.desktop.runtime
    run = seeded(owner, body)
    html = b'<html><body><label>Name<input id="name"></label><button id="go" onclick="document.querySelector(\'#result\').textContent=document.querySelector(\'#name\').value">Show</button><p id="result">Ready</p></body></html>'

    async def page(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: " + str(len(html)).encode() + b"\r\nConnection: close\r\n\r\n" + html)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(page, "127.0.0.1", 0)
    try:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
        result = await asyncio.wait_for(owner.browser.preview(run, PreviewArgs(url=url, actions=[
            {"action": "fill", "selector": "#name", "value": "Fixture"}, {"action": "click", "selector": "#go"},
            {"action": "assert_text", "selector": "#result", "value": "Fixture"},
            {"action": "assert_text", "selector": "#result", "value": "Missing"},
        ])), 60)
        assert result["checks"][-2]["passed"] is True
        assert result["checks"][-1]["passed"] is False
        image = await client.get(f"/agent-runs/{run['id']}/browser-evidence/{result['screenshot_id']}")
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        assert (await client.get(f"/agent-runs/{run['id']}/browser-evidence/{'0' * 32}")).status_code != 200
        run["status"] = "completed"
        owner.store.save_run(run)
        screenshot = owner.store.path.parent / "browser-artifacts" / f"{result['screenshot_id']}.png"
        owner.browser.prune()
        assert screenshot.exists()
        assert (await client.delete(f"/sessions/{body['session_id']}")).status_code == 200
        assert not screenshot.exists()
    finally:
        server.close()
        await server.wait_closed()
