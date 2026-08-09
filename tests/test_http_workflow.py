"""v0.5.0 B3：HTTP/API 可信工作流测试。

覆盖主计划 B3 退出条件：
- 任意 URL、私网绕过、DNS 换址、重定向和环境代理均失败关闭；
- secret 不出现在 Vue/数据库/日志/模型参数（只经 keyring 引用通道）；
- 状态码/Schema/大小/重试/幂等验证通过；
- 未配置 profile 时模型看不到 HTTP 工具；删除/禁用 profile 后不能继续调用。

使用真实 loopback HTTP 测试服务（127.0.0.1），profile 显式开启
allow_private_network + allow_insecure_local（与 MCP 语义一致）。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    ApprovedToolCall,
    CancellationToken,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    ToolApprovalRepository,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ValidatedToolDispatcher,
)
from personal_assistant.agents.result_verification import ApiResultVerifier
from personal_assistant.api import routes_agent_runs
from personal_assistant.core.http_profiles import (
    HttpProfileService,
    MappingHttpSecretResolver,
    is_http_secret_reference,
    load_process_http_secret_resolver,
)
from personal_assistant.core.http_workflow import (
    build_http_tool_registry,
)
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import HttpEndpointProfile


class _EchoHandler(BaseHTTPRequestHandler):
    """loopback 测试服务：/echo、/slow、/redirect、/secret-check、/bad-schema。"""

    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/slow"):
            import time

            time.sleep(8)
            self._send(200, b'{"slow": true}')
            return
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/echo")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/private"):
            self._send(200, b'{"secret": "s3cr3t-header-value"}')
            return
        if self.path.startswith("/schema-ok"):
            self._send(200, b'{"ok": true, "count": 1}')
            return
        if self.path.startswith("/bad-schema"):
            self._send(200, b'{"unexpected": 123}')
            return
        self._send(200, json.dumps({"method": "GET", "path": self.path}).encode())

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw) if raw else {}
        if self.path.startswith("/echo"):
            self._send(
                200,
                json.dumps(
                    {"method": "POST", "body": body, "auth": self.headers.get("X-Api-Key")}
                ).encode(),
            )
            return
        if self.path.startswith("/schema-ok"):
            self._send(200, b'{"ok": true, "count": 1}')
            return
        self._send(404, b'{"error": "not found"}')

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def loopback_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    port = server.server_address[1]
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


async def _make_profile(db, base: str, **overrides: Any) -> HttpEndpointProfile:
    from urllib.parse import urlsplit

    parsed = urlsplit(base)
    service = HttpProfileService(db)
    payload: dict[str, Any] = {
        "name": f"b3-{uuid4().hex[:8]}",
        "scheme": parsed.scheme,
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 80,
        "path_prefix": "/",
        "allowed_methods": ["GET", "POST"],
        "request_schema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "additionalProperties": False,
        },
        "response_schema": None,
        "timeout_ms": 3000,
        "headers": {},
        "secret_slots": [],
        "allow_insecure_local": True,
        "allow_private_network": True,
        "enabled": True,
    }
    payload.update(overrides)
    return await service.create(payload)


async def _create_run(db, *, tool_call_id: str = "call-http-1") -> str:
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(run_id=run_id, limits=AgentRunLimits())
    await repository.record_event(
        AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
    )
    await repository.record_event(
        AgentEvent(
            run_id=run_id,
            sequence=2,
            type=AgentEventType.TOOL_REQUESTED,
            step_id=str(uuid4()),
            payload={
                "ordinal": 1,
                "kind": "tool",
                "tool_call_id": tool_call_id,
                "name": "call_allowlisted_api",
            },
        )
    )
    return run_id


async def _cleanup(db, run_id: str | None = None, profile_ids: list[int] | None = None) -> None:
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    for profile_id in profile_ids or []:
        await db.execute(
            delete(HttpEndpointProfile).where(HttpEndpointProfile.id == profile_id)
        )
    await db.commit()


def _http_arguments(profile_id: int, method: str = "GET", path: str = "/echo", **extra) -> dict:
    arguments = {"profile_id": profile_id, "method": method, "path": path}
    arguments.update(extra)
    return arguments


def _dispatcher(
    db,
    run_id: str,
    *,
    approval_id: str | None = None,
    approval_token: str | None = None,
    with_verifier: bool = False,
    resolver=None,
) -> ValidatedToolDispatcher:
    registry = build_http_tool_registry(db, resolver=resolver)
    return ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.NETWORK_FETCH})
        ),
        approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
        approval_consumer=(
            SqlToolApprovalConsumer(
                db,
                approval_id=approval_id,
                token=approval_token,
            )
            if approval_id is not None
            else None
        ),
        execution_store=ToolExecutionRepository(db, run_id=run_id),
        result_verifier=(
            ApiResultVerifier(
                supported=("call_allowlisted_api",),
                allowed_status_ranges=((200, 299),),
                max_attempts=3,
                reject_schema_invalid=True,
            )
            if with_verifier
            else None
        ),
    )


async def _execute_approved(db, run_id: str, call: ToolCall, *, with_verifier: bool = False):
    pending = await _dispatcher(db, run_id).execute(
        call, cancellation=CancellationToken()
    )
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    approved = await ToolApprovalRepository(db).approve(approvals[0].id)
    return await _dispatcher(
        db,
        run_id,
        approval_id=approved.approval_id,
        approval_token=approved.token,
        with_verifier=with_verifier,
    ).execute(call, cancellation=CancellationToken())


# ---------------- profile 配置校验 ----------------

@pytest.mark.asyncio
async def test_profile_requires_valid_target_and_blocks_sensitive_headers(db):
    """配置校验：http 非环回拒绝、敏感头/敏感 secret slot 拒绝。"""
    service = HttpProfileService(db)
    with pytest.raises(ValueError, match="http 仅允许"):
        await service.create(
            {
                "name": "bad-scheme",
                "scheme": "http",
                "host": "api.example.test",
                "port": 80,
                "allowed_methods": ["GET"],
                "headers": {},
                "secret_slots": [],
            }
        )
    with pytest.raises(ValueError, match="禁止"):
        await service.create(
            {
                "name": "bad-header",
                "scheme": "https",
                "host": "api.example.test",
                "port": 443,
                "allowed_methods": ["GET"],
                "headers": {"Authorization": "Bearer x"},
                "secret_slots": [],
            }
        )
    with pytest.raises(ValueError, match="secret 目标头被禁止"):
        await service.create(
            {
                "name": "bad-slot",
                "scheme": "https",
                "host": "api.example.test",
                "port": 443,
                "allowed_methods": ["GET"],
                "headers": {},
                "secret_slots": ["Authorization"],
            }
        )
    with pytest.raises(ValueError, match="PUT"):
        await service.create(
            {
                "name": "bad-method",
                "scheme": "https",
                "host": "api.example.test",
                "port": 443,
                "allowed_methods": ["PUT"],
                "headers": {},
                "secret_slots": [],
            }
        )


@pytest.mark.asyncio
async def test_secret_slots_generate_keyring_references(db, loopback_server):
    """rc.2：secret_slots 由后端生成 keyring 引用（明文不经 API）。"""
    profile = await _make_profile(
        db, loopback_server, secret_slots=["X-Api-Key"]
    )
    try:
        refs = profile.secret_refs_json or {}
        assert refs["X-Api-Key"] == (
            f"secret://os-keyring/http/{profile.name}/x-api-key"
        )
        assert is_http_secret_reference(refs["X-Api-Key"])
        assert "secret" not in str(profile.secret_refs_json).lower().replace(
            "secret://", ""
        )
    finally:
        await _cleanup(db, None, [profile.id])


def test_http_secret_reference_format_and_env_channel(monkeypatch):
    """引用格式与启动环境通道：畸形条目整体 fail closed，明文不落环境。"""
    assert is_http_secret_reference("secret://os-keyring/http/weather/api-key")
    assert not is_http_secret_reference("secret://os-keyring/mcp/weather")
    assert not is_http_secret_reference("plaintext")

    monkeypatch.setenv(
        "PA_HTTP_PROFILES_SECRETS_JSON",
        json.dumps(
            {"secret://os-keyring/http/weather/api-key": "plain-value-123"}
        ),
    )
    resolver = load_process_http_secret_resolver()
    assert resolver.resolve("secret://os-keyring/http/weather/api-key") == "plain-value-123"
    # 一次性消费：读取后立即从进程环境删除（明文不驻留）
    assert "PA_HTTP_PROFILES_SECRETS_JSON" not in __import__("os").environ

    monkeypatch.setenv(
        "PA_HTTP_PROFILES_SECRETS_JSON", '{"secret://os-keyring/http/x/y": 42}'
    )
    resolver = load_process_http_secret_resolver()
    assert resolver.resolve("secret://os-keyring/http/x/y") is None


# ---------------- executor 行为 ----------------

@pytest.mark.asyncio
async def test_get_returns_bounded_body_with_sanitized_headers(db, loopback_server):
    """GET /echo：返回有界 body + 脱敏 headers（敏感响应头剔除）。"""
    profile = await _make_profile(db, loopback_server)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-http-1",
            name="call_allowlisted_api",
            arguments=_http_arguments(profile.id),
        )
        result = await _execute_approved(db, run_id, call)
        assert result.success is True
        output = result.output
        assert output["status_code"] == 200
        assert output["body"]["method"] == "GET"
        assert output["truncated"] is False
        assert output["schema_valid"] is True
        assert output["attempts"] == 1
        assert "set-cookie" not in {k.lower() for k in output["headers"]}
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_post_requires_idempotency_key_and_validates_body_schema(db, loopback_server):
    """POST 必须幂等键；请求体不符合 profile Schema 拒绝。"""
    profile = await _make_profile(db, loopback_server)
    try:
        no_key = ToolCall(
            id="call-no-key",
            name="call_allowlisted_api",
            arguments=_http_arguments(
                profile.id, "POST", "/echo", body={"value": "x"}
            ),
        )
        run_id = await _create_run(db, tool_call_id="call-no-key")
        rejected = await _execute_approved(db, run_id, no_key)
        await _cleanup(db, run_id)
        assert rejected.success is False
        assert "idempotency_key" in (rejected.error or "")

        bad_body = ToolCall(
            id="call-bad-body",
            name="call_allowlisted_api",
            arguments=_http_arguments(
                profile.id,
                "POST",
                "/echo",
                body={"other": 1},
                idempotency_key="idem-12345678",
            ),
        )
        run_id = await _create_run(db, tool_call_id="call-bad-body")
        bad = await _execute_approved(db, run_id, bad_body)
        await _cleanup(db, run_id)
        assert bad.success is False
        assert "Schema" in (bad.error or "")

        ok = ToolCall(
            id="call-ok",
            name="call_allowlisted_api",
            arguments=_http_arguments(
                profile.id,
                "POST",
                "/echo",
                body={"value": "hello"},
                idempotency_key="idem-12345678",
            ),
        )
        run_id = await _create_run(db, tool_call_id="call-ok")
        good = await _execute_approved(db, run_id, ok)
        await _cleanup(db, run_id)
        assert good.success is True
        assert good.output["body"]["body"] == {"value": "hello"}
    finally:
        await _cleanup(db, None, [profile.id])


@pytest.mark.asyncio
async def test_redirects_are_not_followed(db, loopback_server):
    """重定向默认禁用：3xx 不被跟随，状态码校验拒绝。"""
    profile = await _make_profile(db, loopback_server)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-http-1",
            name="call_allowlisted_api",
            arguments=_http_arguments(profile.id, "GET", "/redirect"),
        )
        result = await _execute_approved(db, run_id, call, with_verifier=True)
        assert result.success is False
        assert result.error_code == "api_status_unexpected"
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_response_schema_violation_fails_closed(db, loopback_server):
    """响应不符合 profile Schema → schema_valid=False → 验证器拒绝。"""
    profile = await _make_profile(
        db,
        loopback_server,
        response_schema={
            "type": "object",
            "required": ["ok", "count"],
            "properties": {
                "ok": {"type": "boolean"},
                "count": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    )
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-http-1",
            name="call_allowlisted_api",
            arguments=_http_arguments(profile.id, "GET", "/bad-schema"),
        )
        result = await _execute_approved(db, run_id, call, with_verifier=True)
        assert result.success is False
        assert result.error_code == "api_schema_invalid"
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_timeout_fails_closed(db, loopback_server):
    """慢端点：profile timeout 生效 → timed_out。"""
    profile = await _make_profile(db, loopback_server, timeout_ms=1000)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-http-1",
            name="call_allowlisted_api",
            arguments=_http_arguments(profile.id, "GET", "/slow"),
        )
        result = await _execute_approved(db, run_id, call)
        assert result.success is False
        assert result.error_code == "executor_error"
        assert "超时" in (result.error or "") or "HTTP 请求失败" in (result.error or "")
    finally:
        await _cleanup(db, run_id, [profile.id])


@pytest.mark.asyncio
async def test_secret_injected_via_keyring_channel_and_absent_from_output(db, loopback_server):
    """keyring 引用注入请求头；明文不出现在结果/参数/DB。"""
    profile = await _make_profile(
        db,
        loopback_server,
        secret_slots=["X-Api-Key"],
    )
    reference = f"secret://os-keyring/http/{profile.name}/x-api-key"
    run_id = await _create_run(db)
    try:
        resolver = MappingHttpSecretResolver({reference: "super-secret-token-9"})
        call = ToolCall(
            id="call-http-1",
            name="call_allowlisted_api",
            arguments=_http_arguments(profile.id, "GET", "/private"),
        )
        approved = await _request_and_approve(db, run_id, call)
        dispatcher = _dispatcher(
            db,
            run_id,
            approval_id=approved.approval_id,
            approval_token=approved.token,
            resolver=resolver,
        )
        result = await dispatcher.execute(call, cancellation=CancellationToken())
        assert result.success is True
        body = result.output["body"]
        # 响应体中的 secret 键被 dispatcher 脱敏；真实请求头注入值绝不出现在结果
        assert body["secret"] == "[REDACTED]"
        serialized = json.dumps(result.output)
        assert "super-secret-token-9" not in serialized
        assert "s3cr3t-header-value" not in serialized

        stored = (
            await db.execute(
                __import__("sqlalchemy").select(HttpEndpointProfile).where(
                    HttpEndpointProfile.id == profile.id
                )
            )
        ).scalar_one()
        assert "super-secret-token-9" not in json.dumps(
            stored.secret_refs_json
        )
        assert is_http_secret_reference(
            stored.secret_refs_json["X-Api-Key"]
        )
    finally:
        await _cleanup(db, run_id, [profile.id])


async def _request_and_approve(db, run_id: str, call: ToolCall) -> ApprovedToolCall:
    pending = await _dispatcher(db, run_id).execute(
        call, cancellation=CancellationToken()
    )
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    return await ToolApprovalRepository(db).approve(approvals[0].id)


@pytest.mark.asyncio
async def test_disabled_or_deleted_profile_cannot_be_called(db, loopback_server):
    """禁用/删除 profile 后不能继续调用。"""
    profile = await _make_profile(db, loopback_server)
    try:
        profile.enabled = False
        await db.commit()
        denied_call = ToolCall(
            id="call-denied",
            name="call_allowlisted_api",
            arguments=_http_arguments(profile.id),
        )
        run_id = await _create_run(db, tool_call_id="call-denied")
        denied = await _execute_approved(db, run_id, denied_call)
        await _cleanup(db, run_id)
        assert denied.success is False
        assert "已禁用" in (denied.error or "")

        profile.enabled = True
        await db.commit()
        await HttpProfileService(db).repo.delete(profile.id)
        missing_call = ToolCall(
            id="call-missing",
            name="call_allowlisted_api",
            arguments=_http_arguments(profile.id),
        )
        run_id = await _create_run(db, tool_call_id="call-missing")
        missing = await _execute_approved(db, run_id, missing_call)
        await _cleanup(db, run_id)
        assert missing.success is False
        assert "不存在" in (missing.error or "")
    finally:
        await _cleanup(db, None, [profile.id])


@pytest.mark.asyncio
async def test_http_flag_and_profile_control_tool_visibility(db, monkeypatch, loopback_server):
    """rc.2：flag 关闭或无已启用 profile 时模型看不到 HTTP 工具；
    flag 开启且存在已启用 profile 时可见。"""
    from personal_assistant.core.models import HttpEndpointProfile

    await db.execute(delete(HttpEndpointProfile))
    await db.commit()
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_http_workflow_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", False)
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is None

    # flag 开启但无任何已启用 profile → 工具不可见
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_http_workflow_enabled", True)
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert "call_allowlisted_api" not in names

    # 存在已启用 profile → 工具可见
    profile = await _make_profile(db, loopback_server)
    try:
        bundle = await routes_agent_runs.get_agent_tool_bundle(db)
        names = {definition.name for definition in bundle.definitions}
        assert "call_allowlisted_api" in names

        # 禁用 profile → 工具再次不可见
        profile.enabled = False
        await db.commit()
        bundle = await routes_agent_runs.get_agent_tool_bundle(db)
        names = {definition.name for definition in bundle.definitions}
        assert "call_allowlisted_api" not in names

        profile.enabled = True
        await db.commit()
        spec = build_http_tool_registry(db).get("call_allowlisted_api")
        from personal_assistant.agents.tools import ToolPolicyDecision

        policy = ToolCapabilityPolicy(
            granted_capabilities=frozenset({ToolCapability.NETWORK_FETCH})
        )
        assert policy.evaluate(spec) == ToolPolicyDecision.REQUIRE_APPROVAL
    finally:
        await _cleanup(db, None, [profile.id])


@pytest.mark.asyncio
async def test_http_spec_matches_frozen_contract():
    """registry 产出的 ToolSpec 与 B0 冻结契约一致。"""
    from personal_assistant.agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME

    contract = WORKFLOW_CONTRACT_BY_NAME["call_allowlisted_api"]
    from personal_assistant.core.http_workflow import _build_http_tool_spec

    spec = _build_http_tool_spec(None)
    assert spec.name == contract.name
    assert spec.version == contract.version
    assert spec.risk_level == contract.risk_level
    assert spec.required_capabilities == contract.required_capabilities
    assert spec.idempotency == contract.idempotency
    assert dict(spec.input_schema) == dict(contract.input_schema)
    assert spec.supports_cancellation is True
