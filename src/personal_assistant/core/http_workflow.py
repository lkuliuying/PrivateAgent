"""v0.5.0 B3：HTTP/API 可信执行适配模块。

``call_allowlisted_api``（契约见 ``agents/workflow_contracts.py``）只允许引用
用户已保存并启用的 endpoint profile；模型不能提供任意 URL。安全边界
（威胁清单 docs/v0.5.0-b0-contracts-20260809.md §4.3）：

- 目标固定：scheme/host/port/path 前缀由 profile 决定，模型只能提供
  profile 内的相对 path；
- 复用 MCP 的 DNS 钉住实现（``mcp/client.py``）：解析一次、全部结果必须
  为全局地址（或 profile 显式允许私网/环回）、连接只允许已验证地址集；
- ``trust_env=False``（不跟随环境代理）、``follow_redirects=False``；
- 方法仅 GET/HEAD/POST；POST 必须携带幂等键（executor 强制）；
- 请求体按 profile 固定 Schema 校验；响应有界、脱敏，状态码/Schema/大小/
  重试/幂等验证通过后才返回模型；
- secret 只经 OS keyring 通道（``PA_HTTP_PROFILES_SECRETS_JSON``）注入
  当前进程内存，不落库、不进日志/参数/输出。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.runtime import CancellationToken
from ..agents.tools import (
    ToolSpec,
    VersionedToolRegistry,
)
from ..agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME
from .http_profiles import (
    HttpProfileSecretResolver,
    HttpProfileService,
    is_http_secret_reference,
    load_process_http_secret_resolver,
)

_HTTP_CONTRACT = WORKFLOW_CONTRACT_BY_NAME["call_allowlisted_api"]

process_http_secret_resolver: HttpProfileSecretResolver = (
    load_process_http_secret_resolver()
)

_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST"})
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_SENSITIVE_RESPONSE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "set-cookie", "cookie", "www-authenticate"}
)
_RESPONSE_HEADER_LIMIT = 32


def _profile_secret_headers(profile, resolver: HttpProfileSecretResolver) -> dict[str, str]:
    """解析 keyring 引用为请求头（缺失引用 → 失败关闭）。"""
    headers: dict[str, str] = {}
    for header, reference in (profile.secret_refs_json or {}).items():
        if not is_http_secret_reference(reference):
            raise RuntimeError("profile secret 引用格式无效，已拒绝执行")
        secret = resolver.resolve(reference)
        if not secret:
            raise RuntimeError(f"keyring secret 不可用：{reference}")
        if not all(0x21 <= ord(ch) <= 0x7E for ch in secret):
            raise RuntimeError("keyring secret 包含不可打印字符，已拒绝注入")
        headers[header] = secret
    return headers


def _sanitize_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in headers.items():
        if name.casefold() in _SENSITIVE_RESPONSE_HEADERS:
            continue
        out[name] = value[:256]
        if len(out) >= _RESPONSE_HEADER_LIMIT:
            break
    return out


def _parse_response_body(raw: bytes, *, max_bytes: int) -> tuple[Any, bool]:
    truncated = len(raw) > max_bytes
    bounded = raw[:max_bytes]
    try:
        text = bounded.decode("utf-8")
    except UnicodeDecodeError:
        return "[non-utf8 body omitted]", truncated
    try:
        return json.loads(text), truncated
    except ValueError:
        return text, truncated


def _schema_validator(schema: dict | None) -> Draft202012Validator | None:
    if not schema:
        return None
    return Draft202012Validator(schema)


def _build_mcp_config(profile, target_url: str, *, resolver) -> Any:
    """把 profile 转成 MCP 配置以复用 DNS 钉住实现（仅读取 url/allow 字段）。"""
    from ..mcp.contracts import McpServerConfig, McpTransport

    del resolver
    return McpServerConfig(
        id=f"http-profile-{profile.id}",
        name=profile.name,
        transport=McpTransport.STREAMABLE_HTTP,
        url=target_url,
        allow_insecure_local=bool(profile.allow_insecure_local),
        allow_private_network=bool(profile.allow_private_network),
        trusted=True,
        enabled=True,
        timeout_ms=int(profile.timeout_ms),
        max_output_bytes=int(profile.max_response_bytes),
    )


async def call_allowlisted_api_trusted(
    db: AsyncSession,
    profile_id: int,
    method: str,
    path: str,
    *,
    query_params: Mapping[str, str] | None = None,
    body: Any = None,
    idempotency_key: str | None = None,
    cancellation: CancellationToken,
    resolver: HttpProfileSecretResolver | None = None,
) -> dict[str, Any]:
    """按已启用 endpoint profile 调用固定目标，全部验证通过后返回有界结果。"""
    if cancellation.is_cancelled:
        raise RuntimeError("工具执行已取消")
    service = HttpProfileService(db)
    profile = await service.require_enabled(profile_id)
    method = method.upper()
    if method not in _ALLOWED_METHODS or method not in {
        m.upper() for m in (profile.allowed_methods_json or [])
    }:
        raise RuntimeError(f"方法 {method} 不在 profile 允许范围内")
    if method == "POST" and not idempotency_key:
        raise RuntimeError("POST 请求必须携带 idempotency_key")

    base_url = f"{profile.scheme}://{profile.host}:{profile.port}"
    path_prefix = (profile.path_prefix or "/").rstrip("/")
    target_path = f"{path_prefix}/{path.lstrip('/')}" if path else path_prefix
    target_url = f"{base_url}{target_path}"
    parsed = urlsplit(target_url)
    if parsed.hostname is None or parsed.port is None:
        raise RuntimeError("profile 目标 URL 无效")

    if profile.request_schema_json and body is not None:
        validator = _schema_validator(profile.request_schema_json)
        if validator is not None:
            error = next(validator.iter_errors(body), None)
            if error is not None:
                raise RuntimeError(f"请求体不符合 profile Schema：{error.message}")

    # DNS 解析一次 + 全部结果校验 + 连接钉住（复用 MCP 实现）
    from ..mcp.client import _pinned_http_transport, _validate_resolved_http_target

    config = _build_mcp_config(profile, target_url, resolver=resolver)
    target = await _validate_resolved_http_target(config)

    import httpx2

    secret_headers = _profile_secret_headers(profile, resolver or process_http_secret_resolver)
    headers = {**dict(profile.headers_json or {}), **secret_headers}

    retry_policy = profile.retry_policy_json or {}
    max_attempts = max(1, min(int(retry_policy.get("max_attempts", 1) or 1), 3))
    request_body = json.dumps(body).encode("utf-8") if body is not None else None
    if request_body is not None and len(request_body) > int(profile.max_request_bytes):
        raise RuntimeError("请求体超过 profile 大小上限")

    started = asyncio.get_running_loop().time()
    attempts = 0
    response = None
    while attempts < max_attempts:
        if cancellation.is_cancelled:
            raise RuntimeError("工具执行已取消")
        attempts += 1
        try:
            timeout = float(profile.timeout_ms) / 1000.0
            limits = httpx2.Limits(max_connections=4, max_keepalive_connections=2)
            async with httpx2.AsyncClient(
                headers=headers,
                follow_redirects=False,
                trust_env=False,
                timeout=timeout,
                transport=_pinned_http_transport(target, limits=limits),
            ) as client:
                response = await client.request(
                    method,
                    target_url,
                    params=dict(query_params) if query_params else None,
                    content=request_body,
                )
        except httpx2.HTTPError as exc:
            if method in {"GET", "HEAD"} and attempts < max_attempts:
                await asyncio.sleep(min(0.5 * attempts, 2.0))
                continue
            raise RuntimeError(f"HTTP 请求失败：{type(exc).__name__}") from exc
        if (
            response.status_code in _RETRYABLE_STATUS
            and attempts < max_attempts
            and (method in {"GET", "HEAD"} or idempotency_key)
        ):
            await asyncio.sleep(min(0.5 * attempts, 2.0))
            continue
        break

    assert response is not None
    elapsed_ms = int((asyncio.get_running_loop().time() - started) * 1000)
    raw = response.content or b""
    body_value, truncated = _parse_response_body(
        raw, max_bytes=int(profile.max_response_bytes)
    )
    validator = _schema_validator(profile.response_schema_json)
    schema_valid = True
    if validator is not None and not truncated:
        schema_valid = next(validator.iter_errors(body_value), None) is None

    return {
        "profile_id": profile_id,
        "method": method,
        "path": target_path,
        "status_code": int(response.status_code),
        "headers": _sanitize_response_headers(response.headers),
        "body": body_value,
        "truncated": truncated,
        "schema_valid": schema_valid,
        "elapsed_ms": elapsed_ms,
        "attempts": attempts,
        "idempotency_replayed": attempts > 1 and bool(idempotency_key),
    }


def build_http_tool_registry(
    db: AsyncSession,
    *,
    legacy_registry=None,
    resolver: HttpProfileSecretResolver | None = None,
) -> VersionedToolRegistry:
    """Build the versioned registry containing the audited HTTP tool."""
    from .tools import default_registry

    source = legacy_registry or default_registry
    if source.get(_HTTP_CONTRACT.name) is not None:
        raise RuntimeError(
            f"内建工具冲突：{_HTTP_CONTRACT.name} 已存在于 legacy 注册表"
        )
    registry = VersionedToolRegistry()
    registry.register(_build_http_tool_spec(db, resolver=resolver))
    return registry


def _build_http_tool_spec(
    db: AsyncSession,
    *,
    resolver: HttpProfileSecretResolver | None = None,
) -> ToolSpec:
    async def execute(arguments: dict[str, Any], cancellation: CancellationToken) -> Any:
        return await call_allowlisted_api_trusted(
            db,
            arguments["profile_id"],
            arguments["method"],
            arguments["path"],
            query_params=arguments.get("query_params"),
            body=arguments.get("body"),
            idempotency_key=arguments.get("idempotency_key"),
            cancellation=cancellation,
            resolver=resolver,
        )

    return ToolSpec(
        name=_HTTP_CONTRACT.name,
        version=_HTTP_CONTRACT.version,
        description=_HTTP_CONTRACT.description,
        input_schema=_HTTP_CONTRACT.input_schema,
        output_schema=_HTTP_CONTRACT.output_schema,
        risk_level=_HTTP_CONTRACT.risk_level,
        required_capabilities=_HTTP_CONTRACT.required_capabilities,
        timeout_ms=_HTTP_CONTRACT.timeout_ms,
        max_input_bytes=_HTTP_CONTRACT.max_input_bytes,
        max_output_bytes=_HTTP_CONTRACT.max_output_bytes,
        idempotency=_HTTP_CONTRACT.idempotency,
        supports_cancellation=_HTTP_CONTRACT.supports_cancellation,
        redaction_policy=_HTTP_CONTRACT.redaction_policy,
        executor=execute,
    )
