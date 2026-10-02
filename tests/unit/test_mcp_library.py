"""个人服务库、凭据引用与外部调用结果未知的隔离回归。"""
import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx2
import pytest
from mcp.shared.auth import OAuthToken
from test_documentation_mcp import mcp_protocol as mcp_protocol
from test_workbench_integrations import configured, invocation
from test_workbench_integrations import local as local
from test_workspace_features import seeded

from private_agent_core.tool_specs import ToolFailure
from private_agent_local import integration_mcp
from private_agent_local.documentation_transport import catalog, normalize_schema
from private_agent_local.integration_mcp import (
    SelectionInput,
    SessionTokens,
    SourceInput,
)
from private_agent_local.mcp_library import PrepareInput, credential_values
from private_agent_local.model_errors import CloudError
from private_agent_local.store import Store


class VaultFixture:
    persistent = True

    def __init__(self):
        self.values = {}
        self.calls = []

    async def binding(self, service_id, version, slot):
        return {"identity": "a" * 64, "service_id": service_id, "version": version, "slot": slot}

    async def get(self, *key):
        self.calls.append(("get", key))
        return self.values.get(key)

    async def set(self, service_id, version, slot, value):
        self.calls.append(("set", (service_id, version, slot)))
        self.values[(service_id, version, slot)] = value
        return f"secret://os-keyring/mcp/{'a' * 64}/{service_id}/{version}/{slot}"

    async def delete(self, *key):
        self.values.pop(key, None)

    def close(self):
        pass


@pytest.fixture
def vault(local, monkeypatch):
    from private_agent_local import mcp_credentials
    result = VaultFixture()
    monkeypatch.setattr(mcp_credentials, "get_broker", lambda owner: result)
    return result


def prepare_value(configuration, **kwargs):
    return PrepareInput(request_id=uuid.uuid4().hex, configuration=configuration, **kwargs)


def test_v9_migration_keeps_duplicate_urls_and_project_permissions(tmp_path):
    path = tmp_path / "migration.sqlite3"
    store = Store(path)
    originals = []
    for number in range(2):
        project = store.create("project", {"name": f"项目{number}", "root_path": str(tmp_path)})
        source = {"id": uuid.uuid4().hex, "version": uuid.uuid4().hex, "name": "相同地址", "transport": "https",
                  "url": "https://example.test/mcp", "command": "", "args": [], "oauth": True, "trust_process": False,
                  "enabled": True, "tools": [{"name": "tool", "readonly": True, "approval": "session"}],
                  "catalog": {"tools": [], "sha256": "old"}, "discovered_at": "2026-01-01"}
        store.update("project", project["id"], mcp_integrations=[source])
        originals.append((project["id"], source))
    store.db.execute("DROP TABLE mcp_services")
    store.db.execute("DROP TABLE mcp_service_changes")
    store.db.execute("UPDATE schema_migrations SET version=9 WHERE version=10")
    store.db.execute("PRAGMA user_version=9")
    store.db.commit()
    store.db.close()
    restored = Store(path)
    try:
        assert restored.db.execute("PRAGMA user_version").fetchone()[0] == 10
        assert restored.db.execute("SELECT count(*) FROM mcp_services").fetchone()[0] == 2
        assert list(tmp_path.glob("migration.pre-v10-*.sqlite3"))
        services = []
        for project_id, old in originals:
            binding = restored.get("project", project_id)["mcp_integrations"][0]
            assert all(binding[key] == old[key] for key in ("id", "version", "tools", "enabled", "catalog"))
            services.append(binding["service_id"])
        assert services[0] != services[1]
    finally:
        restored.db.close()


@pytest.mark.asyncio
async def test_shared_service_keeps_project_selection_and_rejects_stale_versions(local, mcp_protocol):
    app, client, _, root, body = local
    owner = app.state.desktop.runtime
    source = await configured(owner, body["project_id"])
    second = owner.store.create("project", {"name": "另一个项目", "root_path": str(root)})
    bound = owner.integrations.library.bind(second["id"], source["service_id"])
    assert not bound["enabled"] and not bound["tools"] and bound["catalog"] is None
    service = owner.integrations.library.service(source["service_id"])
    prepared = await owner.integrations.library.prepare(prepare_value(
        SourceInput(name="已修改", transport="https", url=service["url"]), service_id=service["id"], expected_version=service["version"]))
    await owner.integrations.library.commit(prepared["id"], None)
    for project_id, identifier in [(body["project_id"], source["id"]), (second["id"], bound["id"])]:
        current = owner.integrations.source(project_id, identifier)
        assert not current["enabled"] and current["needs_validation"]
    with pytest.raises(ValueError, match="最新工具目录"):
        owner.integrations.select(body["project_id"], source["id"], SelectionInput(expected_version=source["version"], enabled=True, tools=[]))
    new = owner.integrations.library.service(service["id"])
    rejected = await client.delete(f"/mcp-services/{new['id']}?expected_version={new['version']}")
    assert rejected.status_code == 409 and "另一个项目" in rejected.text


@pytest.mark.asyncio
async def test_static_credential_prepare_failure_preserves_active_configuration(local, vault):
    owner = local[0].state.desktop.runtime
    source = owner.integrations.create(local[4]["project_id"], SourceInput(name="原服务", transport="https", url="https://example.test/mcp"))
    service = owner.integrations.library.service(source["service_id"])
    value = prepare_value(SourceInput(name="新服务", transport="https", url=service["url"], auth_mode="bearer"),
                          service_id=service["id"], expected_version=service["version"], replace_credentials=True)
    change = await owner.integrations.library.prepare(value)
    reference = f"secret://os-keyring/mcp/{'a' * 64}/{service['id']}/{change['credential_revision']}/static"
    with pytest.raises(CloudError, match="凭据缺失"):
        await owner.integrations.library.commit(change["id"], reference)
    assert owner.integrations.library.service(service["id"])["version"] == service["version"]
    await vault.set(service["id"], change["credential_revision"], "static", json.dumps({"bearer": "synthetic-access-value"}))
    committed = await owner.integrations.library.commit(change["id"], reference)
    assert committed["auth_mode"] == "bearer"
    assert "synthetic-access-value" not in str(owner.integrations.library.services())
    assert "synthetic-access-value" not in str(owner.integrations.library.change(change["id"]))
    assert (await owner.integrations.library.commit(change["id"], reference))["version"] == committed["version"]


@pytest.mark.parametrize("fields", [
    {"oauth": True, "auth_mode": "bearer"}, {"auth_mode": "custom_headers", "header_names": ["Authorization"]},
    {"auth_mode": "custom_headers", "header_names": ["X-Test", "x-test"]},
    {"auth_mode": "custom_headers", "header_names": ["Host"]}, {"env_names": ["MY_KEY"]},
])
def test_invalid_https_auth_combinations_fail_before_connection(fields):
    with pytest.raises(ValueError):
        SourceInput(name="配置检查", transport="https", url="https://example.test/mcp", **fields)


@pytest.mark.parametrize("names", [["PRIVATEAGENT_LOCAL_NONCE"], ["PA_MODEL_PROVIDER_SECRETS_JSON"], ["NAME", "name"], ["A=B"]])
def test_stdio_rejects_reserved_or_duplicate_environment(names):
    with pytest.raises(ValueError):
        SourceInput(name="配置检查", transport="stdio", command=sys.executable, trust_process=True, env_names=names)


def test_static_values_reject_newline_and_missing_fields():
    source = {"auth_mode": "bearer"}
    for value in ({}, {"bearer": "value\r\nOther: injected"}, {"bearer": "ok", "extra": "unknown"}):
        with pytest.raises(CloudError):
            credential_values(source, json.dumps(value))


@pytest.mark.asyncio
async def test_oauth_session_choice_never_reads_or_writes_vault():
    vault = VaultFixture()
    storage = SessionTokens(vault, "a" * 32, "b" * 32, persistent=False)
    assert await storage.get_tokens() is None
    await storage.set_tokens(OAuthToken(access_token="synthetic-token", token_type="Bearer"))
    assert (await storage.get_tokens()).access_token == "synthetic-token"
    assert not vault.calls


@pytest.mark.asyncio
async def test_oauth_persistent_tokens_reload_and_refresh_without_webview():
    vault = VaultFixture()
    original = SessionTokens(vault, "a" * 32, "b" * 32)
    await original.set_tokens(OAuthToken(access_token="synthetic-first", refresh_token="synthetic-refresh", token_type="Bearer"))
    reopened = SessionTokens(vault, "a" * 32, "b" * 32)
    assert (await reopened.get_tokens()).refresh_token == "synthetic-refresh"
    await reopened.set_tokens(OAuthToken(access_token="synthetic-rotated", refresh_token="synthetic-refresh-next", token_type="Bearer"))
    latest = SessionTokens(vault, "a" * 32, "b" * 32)
    assert (await latest.get_tokens()).access_token == "synthetic-rotated"


@pytest.mark.asyncio
async def test_two_projects_serialize_shared_oauth_refresh_and_reuse_new_token(local, vault, mcp_protocol, monkeypatch):
    owner = local[0].state.desktop.runtime
    source = owner.integrations.create(local[4]["project_id"], SourceInput(name="共享刷新", transport="https", url="https://docs.example.test/mcp", auth_mode="oauth"))
    second_project = owner.store.create("project", {"name": "第二项目", "root_path": str(local[3])})
    second_source = owner.integrations.library.bind(second_project["id"], source["service_id"])
    vault.values[(source["service_id"], source["auth_revision"], "oauth")] = json.dumps({
        "tokens": {"access_token": "synthetic-expired", "refresh_token": "synthetic-refresh", "token_type": "Bearer", "expires_in": 0}, "client": None})
    refreshing, release = asyncio.Event(), asyncio.Event()
    providers, initial_tokens = [], []
    counters = {"active": 0, "maximum": 0, "refreshes": 0}

    class RefreshingAuth(httpx2.Auth):
        def __init__(self, storage):
            self.storage, self.first = storage, True

        async def async_auth_flow(self, request):
            token = await self.storage.get_tokens()
            if self.first:
                initial_tokens.append(token.access_token)
                self.first = False
            if token.access_token == "synthetic-expired":
                counters["active"] += 1
                counters["refreshes"] += 1
                counters["maximum"] = max(counters["maximum"], counters["active"])
                refreshing.set()
                try:
                    await release.wait()
                    token = OAuthToken(access_token="synthetic-refreshed", refresh_token="synthetic-next", token_type="Bearer")
                    await self.storage.set_tokens(token)
                finally:
                    counters["active"] -= 1
            request.headers["Authorization"] = "Bearer " + token.access_token
            yield request

    def provider(url, metadata, storage, **kwargs):
        providers.append(storage)
        return RefreshingAuth(storage)

    async def discover(bound, project_id):
        # 保留真实服务锁、共享 SessionTokens、httpx2 auth 流程及 MCP SDK，只替换令牌刷新服务。
        async with owner.integrations.connection(bound, project_id) as client:
            return await integration_mcp.catalog(client)

    monkeypatch.setattr(integration_mcp, "OAuthClientProvider", provider)
    first = asyncio.create_task(discover(source, local[4]["project_id"]))
    second = None
    try:
        await asyncio.wait_for(refreshing.wait(), 2)
        second = asyncio.create_task(discover(second_source, second_project["id"]))
        await asyncio.sleep(0)
        assert not second.done() and len(providers) == 1
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 5)
        assert all(result["tools"] for result in results)
        assert counters == {"active": 0, "maximum": 1, "refreshes": 1}
        assert initial_tokens == ["synthetic-expired", "synthetic-refreshed"]
        assert len(providers) == 2 and providers[0] is providers[1]
        assert json.loads(vault.values[(source["service_id"], source["auth_revision"], "oauth")])["tokens"]["access_token"] == "synthetic-refreshed"
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)


@pytest.mark.asyncio
async def test_stdio_environment_is_vault_only_and_arguments_remain_literal(local, vault, monkeypatch):
    owner = local[0].state.desktop.runtime
    configuration = SourceInput(name="环境变量测试", transport="stdio", command=sys.executable,
                                args=["  literal spaces  ", ""], env_names=["FIXTURE_ACCESS"], trust_process=True)
    change = await owner.integrations.library.prepare(prepare_value(configuration))
    reference = await vault.set(change["service_id"], change["credential_revision"], "static", json.dumps({"env:FIXTURE_ACCESS": "synthetic-environment"}))
    service = await owner.integrations.library.commit(change["id"], reference)
    source = owner.integrations.library.bind(local[4]["project_id"], service["id"])
    captured = []
    def process(parameters, **kwargs):
        captured.append(parameters)
        return object()
    @asynccontextmanager
    async def client(*args, **kwargs):
        yield object()
    monkeypatch.setattr(integration_mcp, "stdio_client", process)
    monkeypatch.setattr(integration_mcp, "Client", client)
    async with owner.integrations.connection(source, local[4]["project_id"]):
        pass
    assert len(captured) == 1 and captured[0].env == {"FIXTURE_ACCESS": "synthetic-environment"}
    assert captured[0].args == ["  literal spaces  ", ""]
    assert str(captured[0].cwd) == str(local[3])
    assert "synthetic-environment" not in str(owner.integrations.sources(local[4]["project_id"]))


@pytest.mark.asyncio
async def test_mixed_schema_directory_keeps_supported_tools_and_rejects_cycles():
    schema = {"type": "object", "$defs": {"query": {"type": "string"}}, "properties": {"query": {"$ref": "#/$defs/query"}}}
    good = SimpleNamespace(name="good", description="可用工具", input_schema=schema, output_schema=None)
    bad = SimpleNamespace(name="bad", description="不支持工具", input_schema={"type": "object", "properties": {"query": {"type": "string", "pattern": ".*"}}}, output_schema=None)
    async def listing(**kwargs):
        return SimpleNamespace(tools=[good, bad], next_cursor=None)
    result = await catalog(SimpleNamespace(list_tools=listing), partial=True)
    assert [item["name"] for item in result["tools"]] == ["good"]
    assert result["tools"][0]["input_schema"]["properties"]["query"] == {"type": "string"}
    assert result["unavailable_tools"][0]["name"] == "bad"
    bad.input_schema["properties"]["query"]["pattern"] = "changed"
    assert (await catalog(SimpleNamespace(list_tools=listing), partial=True))["sha256"] != result["sha256"]
    with pytest.raises(ToolFailure):
        normalize_schema({"$defs": {"loop": {"$ref": "#/$defs/loop"}}, "type": "object", "properties": {"x": {"$ref": "#/$defs/loop"}}})
    assert normalize_schema({"$ref": "#/$defs/Input", "$defs": {"Input": {"type": "object"}}}) == {"type": "object"}
    rooted = normalize_schema({"$ref": "#/$defs/Input", "title": "输入", "$defs": {"Input": {"type": "object"}}})
    assert rooted["type"] == "object" and len(rooted["allOf"]) == 2
    with pytest.raises(ToolFailure, match="作用域"):
        normalize_schema({"type": "object", "$id": "https://example.test/schema", "$defs": {}})


@pytest.mark.asyncio
async def test_unsupported_tool_cannot_be_selected(local, mcp_protocol):
    owner = local[0].state.desktop.runtime
    source = await configured(owner, local[4]["project_id"])
    source["catalog"]["unavailable_tools"] = [{"name": "bad", "reason": "不支持", "error_code": "mcp_invalid_schema"}]
    owner.integrations.save(local[4]["project_id"], source)
    with pytest.raises(ValueError, match="未知项"):
        owner.integrations.select(local[4]["project_id"], source["id"], SelectionInput(expected_version=source["version"], enabled=True,
            tools=[{"name": "bad", "readonly": True, "approval": "session"}]))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,header,key", [("bearer", "Authorization", "bearer"), ("custom_headers", "X-API-Key", "header:X-API-Key")])
async def test_static_headers_only_reach_configured_mcp_transport(local, vault, mcp_protocol, monkeypatch, mode, header, key):
    owner = local[0].state.desktop.runtime
    configuration = SourceInput(name="认证测试", transport="https", url="https://docs.example.test/mcp", auth_mode=mode,
                                header_names=[header] if mode == "custom_headers" else [])
    change = await owner.integrations.library.prepare(prepare_value(configuration))
    reference = await vault.set(change["service_id"], change["credential_revision"], "static", json.dumps({key: "synthetic-value"}))
    service = await owner.integrations.library.commit(change["id"], reference)
    source = owner.integrations.library.bind(local[4]["project_id"], service["id"])
    received = []
    original = httpx2.AsyncHTTPTransport.handle_async_request
    async def observe(self, request):
        received.append((str(request.url), request.headers.get(header)))
        return await original(self, request)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", observe)
    owner.integrations.connect(local[4]["project_id"], source["id"])
    await owner.integrations.tasks[source["id"]]
    assert owner.integrations.connection_state(source["id"])["status"] == "connected"
    assert received and all(url == "https://docs.example.test/mcp" for url, _ in received)
    assert all(value == ("Bearer " if mode == "bearer" else "") + "synthetic-value" for _, value in received)
    assert "synthetic-value" not in str(owner.integrations.sources(local[4]["project_id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["https", "stdio"])
@pytest.mark.parametrize("stored", [None, "{invalid-json"])
async def test_missing_or_invalid_static_credentials_block_before_network_or_process(local, vault, monkeypatch, transport, stored):
    owner = local[0].state.desktop.runtime
    config = (SourceInput(name="凭据检查", transport="https", url="https://example.test/mcp", auth_mode="bearer") if transport == "https"
              else SourceInput(name="凭据检查", transport="stdio", command=sys.executable, trust_process=True, env_names=["FIXTURE_ACCESS"]))
    change = await owner.integrations.library.prepare(prepare_value(config))
    field = "bearer" if transport == "https" else "env:FIXTURE_ACCESS"
    reference = await vault.set(change["service_id"], change["credential_revision"], "static", json.dumps({field: "synthetic-before-loss"}))
    service = await owner.integrations.library.commit(change["id"], reference)
    source = owner.integrations.library.bind(local[4]["project_id"], service["id"])
    key = (service["id"], service["credential_revision"], "static")
    if stored is None:
        vault.values.pop(key)
    else:
        vault.values[key] = stored
    attempted = []
    def forbidden(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("凭据无效时不得启动传输")
    monkeypatch.setattr(integration_mcp, "public_client", forbidden)
    monkeypatch.setattr(integration_mcp, "stdio_client", forbidden)
    owner.integrations.connect(local[4]["project_id"], source["id"])
    await owner.integrations.tasks[source["id"]]
    state = owner.integrations.connection_state(source["id"])
    assert state["status"] == "error" and state["error_code"] == "mcp_credentials_required"
    assert "重新保存全部认证字段" in state["error"] and not attempted
    assert stored is None or stored not in str(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,message", [(401, "mcp_auth_failed", "检查认证配置"), (403, "mcp_access_denied", "远端权限")])
async def test_sdk_authentication_errors_preserve_endpoint_status_safely(local, mcp_protocol, monkeypatch, status, code, message):
    owner = local[0].state.desktop.runtime
    source = owner.integrations.create(local[4]["project_id"], SourceInput(name="认证错误", transport="https", url="https://docs.example.test/mcp"))
    async def rejected(self, request):
        return httpx2.Response(status, text="synthetic-private-server-diagnostic", request=request)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", rejected)
    owner.integrations.connect(local[4]["project_id"], source["id"])
    await owner.integrations.tasks[source["id"]]
    state = owner.integrations.connection_state(source["id"])
    assert state["status"] == "error" and state["error_code"] == code
    assert message in state["error"]
    assert "synthetic-private-server-diagnostic" not in str(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_after_retry", [False, True])
async def test_oauth_challenge_retry_success_overwrites_401_status(local, mcp_protocol, monkeypatch, fail_after_retry):
    owner = local[0].state.desktop.runtime
    source = owner.integrations.create(local[4]["project_id"], SourceInput(name="OAuth重试", transport="https", url="https://docs.example.test/mcp", auth_mode="oauth", oauth_persistence="session"))
    attempts = []
    original = httpx2.AsyncHTTPTransport.handle_async_request

    class Challenge(httpx2.Auth):
        async def async_auth_flow(self, request):
            response = yield request
            if response.status_code == 401:
                # 通过真实 httpx2 auth 流程重发一次，验证观察 hook 不会打断 challenge。
                yield request

    async def responses(self, request):
        if request.method == "POST":
            attempts.append(request)
            if len(attempts) == 1:
                return httpx2.Response(401, text="synthetic-challenge", request=request)
        return await original(self, request)

    monkeypatch.setattr(integration_mcp, "OAuthClientProvider", lambda *args, **kwargs: Challenge())
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", responses)
    if fail_after_retry:
        async def unrelated_failure(client):
            raise RuntimeError("synthetic-unrelated-failure")
        monkeypatch.setattr(integration_mcp, "catalog", unrelated_failure)
    owner.integrations.connect(local[4]["project_id"], source["id"])
    await owner.integrations.tasks[source["id"]]
    state = owner.integrations.connection_state(source["id"])
    assert len(attempts) >= 3
    assert state["status"] == ("error" if fail_after_retry else "connected")
    assert state["error_code"] == ("mcp_connection_failed" if fail_after_retry else None)
    assert "synthetic" not in str(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disconnect", "invalid_output", "cancel"])
async def test_dispatched_write_is_unknown_and_cannot_be_replayed(local, mcp_protocol, monkeypatch, failure):
    app, _, _, root, body = local
    owner = app.state.desktop.runtime
    source = await configured(owner, body["project_id"])
    source["tools"][0].update(readonly=False, approval="always")
    owner.integrations.save(body["project_id"], source)
    run = seeded(owner, body)
    run["permission_mode"] = "workspace"
    calls = []
    async def approve(*args):
        return True
    async def invoke(*args, **kwargs):
        calls.append(args)
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "disconnect":
            raise ConnectionError("fixture disconnected after write")
        return SimpleNamespace(result_type="complete", is_error=False, structured_content={}, content=[])
    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield SimpleNamespace(session=SimpleNamespace(call_tool=invoke))
    async def directory(client):
        return source["catalog"]
    monkeypatch.setattr(owner, "approve", approve)
    monkeypatch.setattr(owner.integrations, "connection", connection)
    monkeypatch.setattr(integration_mcp, "catalog", directory)
    execution = {"id": uuid.uuid4().hex, "operation_id": uuid.uuid4().hex, "status": "running"}
    run["executions"].append(execution)
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ToolFailure):
        await owner.integrations.execute(run, root, invocation(source), execution)
    assert execution["mcp_call"]["phase"] == "dispatched"
    assert execution["error_code"] == "execution_unknown" and run["uncertain_operations"]
    with pytest.raises(ToolFailure, match="此前此工具"):
        await owner.integrations.execute(run, root, invocation(source), {})
    assert len(calls) == 1
    assert not owner.recovery.inspect(run)["can_resume"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["static", "oauth"])
async def test_catalog_reflected_credentials_never_reach_storage_or_api(local, mcp_protocol, monkeypatch, kind):
    owner = local[0].state.desktop.runtime
    source = owner.integrations.create(local[4]["project_id"], SourceInput(name="目录边界", transport="https", url="https://docs.example.test/mcp"))
    secret = "synthetic-reflected-credential"
    if kind == "static":
        owner.integrations.static_values[source["service_id"]] = {"bearer": secret}
    else:
        storage = SessionTokens(VaultFixture(), source["service_id"], source["auth_revision"], persistent=False)
        await storage.set_tokens(OAuthToken(access_token=secret, token_type="Bearer"))
        owner.integrations.tokens[source["service_id"]] = storage
    original = integration_mcp.catalog
    async def reflected(client):
        result = await original(client)
        result["tools"][0]["description"] = secret
        return result
    monkeypatch.setattr(integration_mcp, "catalog", reflected)
    owner.integrations.connect(local[4]["project_id"], source["id"])
    await owner.integrations.tasks[source["id"]]
    assert owner.integrations.connection_state(source["id"])["error_code"] == "mcp_sensitive_metadata"
    assert owner.integrations.source(local[4]["project_id"], source["id"])["catalog"] is None
    assert secret not in str(owner.store.get("project", local[4]["project_id"]))
    public = await local[1].get(f"/projects/{local[4]['project_id']}/integrations")
    assert public.status_code == 200 and secret not in public.text


@pytest.mark.asyncio
async def test_acknowledged_write_survives_connection_cleanup_error(local, mcp_protocol, monkeypatch):
    owner = local[0].state.desktop.runtime
    source = await configured(owner, local[4]["project_id"])
    source["tools"][0].update(readonly=False, approval="always")
    owner.integrations.save(local[4]["project_id"], source)
    run = seeded(owner, local[4])
    run["permission_mode"] = "workspace"
    async def approve(*args):
        return True
    async def invoke(*args, **kwargs):
        return SimpleNamespace(result_type="complete", is_error=False, structured_content={"url": "https://example.test/result"}, content=[])
    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield SimpleNamespace(session=SimpleNamespace(call_tool=invoke))
        raise ConnectionError("fixture teardown")
    async def directory(client):
        return source["catalog"]
    monkeypatch.setattr(owner, "approve", approve)
    monkeypatch.setattr(owner.integrations, "connection", connection)
    monkeypatch.setattr(integration_mcp, "catalog", directory)
    execution = {"id": uuid.uuid4().hex, "operation_id": uuid.uuid4().hex, "status": "running"}
    run["executions"].append(execution)
    result = await owner.integrations.execute(run, local[3], invocation(source), execution)
    assert result["connection_warning"] and execution["mcp_call"]["phase"] == "acknowledged"
    assert owner.store.run(run["id"])["executions"][-1]["mcp_call"]["phase"] == "acknowledged"
    assert not run.get("uncertain_operations")


@pytest.mark.asyncio
async def test_prepared_cancellation_has_no_remote_side_effect(local, mcp_protocol, monkeypatch):
    app, _, _, root, body = local
    owner = app.state.desktop.runtime
    source = await configured(owner, body["project_id"])
    source["tools"][0].update(readonly=False, approval="always")
    owner.integrations.save(body["project_id"], source)
    run = seeded(owner, body)
    run["permission_mode"] = "workspace"
    async def approve(*args):
        return True
    @asynccontextmanager
    async def connection(*args, **kwargs):
        raise asyncio.CancelledError()
        yield
    monkeypatch.setattr(owner, "approve", approve)
    monkeypatch.setattr(owner.integrations, "connection", connection)
    execution = {}
    with pytest.raises(asyncio.CancelledError):
        await owner.integrations.execute(run, root, invocation(source), execution)
    assert execution["mcp_call"]["phase"] == "prepared"
    assert not run.get("uncertain_operations") and not mcp_protocol.calls
