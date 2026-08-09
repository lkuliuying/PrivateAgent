"""v0.5.0 B3：HTTP endpoint profile 非敏感元数据仓储与校验。

- 只保存 profile 名称、目标摘要、policy、enabled、版本和 secret reference；
  明文 API key 只经 OS keyring（Rust 侧收集）→ ``PA_HTTP_PROFILES_SECRETS_JSON``
  通道注入当前 sidecar 内存，本模块不接触明文；
- 配置校验复用 MCP 的字面 URL 防护语义（scheme/端口/凭据/私网/环回/链路本地
  默认拒绝；``allow_insecure_local`` 仅对环回放开 http；``allow_private_network``
  显式允许非全局地址）；DNS 解析层的钉住校验在 ``http_workflow`` 执行时进行；
- secret reference 使用与 MCP 同构的引用格式，仅允许 keyring 通道。
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import HttpEndpointProfile

# 与 mcp/secrets.py 同构的引用格式：secret://os-keyring/http/<name>/<slot>
HTTP_SECRET_REFERENCE_PATTERN = re.compile(
    r"^secret://os-keyring/http/[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
    r"/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)
HTTP_PROFILES_SECRETS_ENV = "PA_HTTP_PROFILES_SECRETS_JSON"

# 敏感头名（显式禁止作为固定头或 secret 目标以外的来源）
_BLOCKED_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie"}
)

_ALLOWED_SCHEMES = {"https", "http"}
_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST"})


class HttpProfileError(ValueError):
    """HTTP profile 配置/查询错误。"""


class HttpProfileNotFound(HttpProfileError):
    """profile 不存在。"""


class HttpProfileDisabled(HttpProfileError):
    """profile 已禁用。"""


class HttpProfileConflict(HttpProfileError):
    """profile 名称冲突或状态非法。"""


class HttpProfileSecretResolver(Protocol):
    def resolve(self, reference: str) -> str | None: ...


class MappingHttpSecretResolver:
    """内存映射解析器（测试/注入用）。"""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = dict(secrets)

    def resolve(self, reference: str) -> str | None:
        return self._secrets.get(reference)


def is_http_secret_reference(value: str) -> bool:
    return bool(HTTP_SECRET_REFERENCE_PATTERN.fullmatch(value))


def load_process_http_secret_resolver(
    environ: dict[str, str] | None = None,
) -> HttpProfileSecretResolver:
    """一次性消费启动环境中的 profile secret 通道（引用→明文 map）。

    通道格式与 MCP 的 PA_MCP_SECRETS_JSON 一致：JSON 对象，键为引用、值为明文。
    读取后立即从环境删除；任何畸形条目 → 整体空 map（fail closed）。
    """
    source = dict(environ) if environ is not None else __import__("os").environ
    raw = source.pop(HTTP_PROFILES_SECRETS_ENV, "")
    if not raw:
        return MappingHttpSecretResolver({})
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return MappingHttpSecretResolver({})
    secrets: dict[str, str] = {}
    if not isinstance(parsed, dict) or len(parsed) > 32:
        return MappingHttpSecretResolver({})
    for reference, value in parsed.items():
        if not isinstance(reference, str) or not is_http_secret_reference(reference):
            return MappingHttpSecretResolver({})
        if not isinstance(value, str) or not value or len(value) > 8_192:
            return MappingHttpSecretResolver({})
        if "\x00" in value:
            return MappingHttpSecretResolver({})
        secrets[reference] = value
    return MappingHttpSecretResolver(secrets)


def _validate_target(scheme: str, host: str, port: int, *, allow_insecure_local: bool) -> None:
    """字面目标校验（复用 MCP 防护语义；DNS 解析后仍会再次校验）。"""
    if scheme not in _ALLOWED_SCHEMES:
        raise HttpProfileError("scheme 仅允许 https（环回显式允许 http）")
    if not host or len(host) > 255 or any(ch.isspace() for ch in host):
        raise HttpProfileError("host 无效")
    if not 1 <= int(port) <= 65_535:
        raise HttpProfileError("port 无效")
    if scheme == "http" and not allow_insecure_local:
        raise HttpProfileError("http 仅允许在 allow_insecure_local 且目标为环回时使用")


def _validate_headers(headers: dict[str, str], secret_slots: list[str]) -> None:
    for name in headers:
        normalized = name.casefold().strip()
        if not normalized or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+\-.^_`|~]{1,128}", normalized):
            raise HttpProfileError(f"请求头名无效: {name!r}")
        if normalized in _BLOCKED_HEADERS:
            raise HttpProfileError(f"请求头被禁止: {name}")
    for header in secret_slots:
        if not isinstance(header, str):
            raise HttpProfileError("secret slot 必须是字符串")
        normalized = header.casefold().strip()
        if not normalized or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+\-.^_`|~]{1,128}", normalized):
            raise HttpProfileError(f"secret 头名无效: {header!r}")
        if normalized in _BLOCKED_HEADERS:
            raise HttpProfileError(f"secret 目标头被禁止: {header}")


def slot_from_header(header: str) -> str:
    """从请求头名派生 keyring slot（字母数字与 ._-，其余转 -）。"""
    normalized = header.casefold().strip()
    slot = re.sub(r"[^a-z0-9._-]", "-", normalized)
    return slot[:64] or "header"


def build_secret_refs(name: str, secret_slots: list[str]) -> dict[str, str]:
    """后端为声明的 secret slot 生成 keyring 引用（明文只进 OS keyring）。

    UI 只提交请求头名；引用格式与 Rust 侧 ``http_profile_reference`` 同构。
    """
    refs: dict[str, str] = {}
    for header in secret_slots:
        refs[header] = (
            f"secret://os-keyring/http/{name}/{slot_from_header(header)}"
        )
    return refs


def _validate_methods(methods: list[str]) -> None:
    if not methods:
        raise HttpProfileError("allowed_methods 不能为空")
    for method in methods:
        if method.upper() not in _ALLOWED_METHODS:
            raise HttpProfileError(f"v0.5.0 仅开放 GET/HEAD/POST：{method}")


class HttpProfileRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        name: str,
        scheme: str,
        host: str,
        port: int,
        path_prefix: str,
        allowed_methods: list[str],
        request_schema: dict | None,
        response_schema: dict | None,
        max_request_bytes: int,
        max_response_bytes: int,
        timeout_ms: int,
        headers: dict[str, str],
        secret_refs: dict[str, str],
        retry_policy: dict | None,
        allow_insecure_local: bool,
        allow_private_network: bool,
        enabled: bool,
    ) -> HttpEndpointProfile:
        existing = (
            await self.db.execute(
                select(HttpEndpointProfile.id).where(
                    HttpEndpointProfile.name == name
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HttpProfileConflict(f"endpoint profile 名称已存在: {name}")
        profile = HttpEndpointProfile(
            name=name,
            scheme=scheme.lower(),
            host=host.casefold().rstrip("."),
            port=port,
            path_prefix=path_prefix or "/",
            allowed_methods_json=[m.upper() for m in allowed_methods],
            request_schema_json=request_schema,
            response_schema_json=response_schema,
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
            timeout_ms=timeout_ms,
            headers_json=dict(headers),
            secret_refs_json=dict(secret_refs),
            retry_policy_json=retry_policy,
            allow_insecure_local=allow_insecure_local,
            allow_private_network=allow_private_network,
            enabled=enabled,
        )
        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    async def get(self, profile_id: int) -> HttpEndpointProfile | None:
        return await self.db.get(HttpEndpointProfile, profile_id)

    async def list(self, *, enabled_only: bool = False) -> list[HttpEndpointProfile]:
        stmt = select(HttpEndpointProfile).order_by(HttpEndpointProfile.name.asc())
        if enabled_only:
            stmt = stmt.where(HttpEndpointProfile.enabled.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, profile_id: int, **values: Any) -> HttpEndpointProfile:
        profile = await self.get(profile_id)
        if profile is None:
            raise HttpProfileNotFound(f"endpoint profile 不存在: {profile_id}")
        for key, value in values.items():
            if value is not None:
                setattr(profile, key, value)
        profile.version = profile.version + 1
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    async def delete(self, profile_id: int) -> None:
        profile = await self.get(profile_id)
        if profile is None:
            raise HttpProfileNotFound(f"endpoint profile 不存在: {profile_id}")
        await self.db.delete(profile)
        await self.db.commit()


class HttpProfileService:
    """配置校验 + 仓储的薄封装（API 与 executor 共用）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.repo = HttpProfileRepository(db)

    async def create(self, payload: dict[str, Any]) -> HttpEndpointProfile:
        name = payload["name"].strip()
        _validate_target(
            payload["scheme"],
            payload["host"],
            payload["port"],
            allow_insecure_local=payload.get("allow_insecure_local", False),
        )
        secret_slots = list(payload.get("secret_slots") or [])
        _validate_headers(payload.get("headers") or {}, secret_slots)
        _validate_methods(payload["allowed_methods"])
        secret_refs = build_secret_refs(name, secret_slots)
        return await self.repo.create(
            name=name,
            scheme=payload["scheme"],
            host=payload["host"],
            port=payload["port"],
            path_prefix=payload.get("path_prefix", "/"),
            allowed_methods=payload["allowed_methods"],
            request_schema=payload.get("request_schema"),
            response_schema=payload.get("response_schema"),
            max_request_bytes=int(payload.get("max_request_bytes", 65_536)),
            max_response_bytes=int(payload.get("max_response_bytes", 1_048_576)),
            timeout_ms=int(payload.get("timeout_ms", 30_000)),
            headers=payload.get("headers") or {},
            secret_refs=secret_refs,
            retry_policy=payload.get("retry_policy"),
            allow_insecure_local=payload.get("allow_insecure_local", False),
            allow_private_network=payload.get("allow_private_network", False),
            enabled=payload.get("enabled", False),
        )

    async def update(
        self, profile_id: int, payload: dict[str, Any]
    ) -> HttpEndpointProfile:
        profile = await self.repo.get(profile_id)
        if profile is None:
            raise HttpProfileNotFound(f"endpoint profile 不存在: {profile_id}")
        if "secret_slots" in payload:
            secret_slots = list(payload.pop("secret_slots") or [])
            _validate_headers(
                payload.get("headers") or profile.headers_json or {}, secret_slots
            )
            payload["secret_refs"] = build_secret_refs(profile.name, secret_slots)
        if "scheme" in payload or "host" in payload or "port" in payload:
            _validate_target(
                payload.get("scheme", profile.scheme),
                payload.get("host", profile.host),
                payload.get("port", profile.port),
                allow_insecure_local=payload.get(
                    "allow_insecure_local", profile.allow_insecure_local
                ),
            )
        if "allowed_methods" in payload:
            _validate_methods(payload["allowed_methods"])
        # payload 字段名 → ORM 列名映射（避免 setattr 静默无效）
        mapped: dict[str, Any] = {
            "scheme": payload.get("scheme"),
            "host": payload.get("host"),
            "port": payload.get("port"),
            "path_prefix": payload.get("path_prefix"),
            "allowed_methods_json": payload.get("allowed_methods"),
            "headers_json": payload.get("headers"),
            "secret_refs_json": payload.get("secret_refs"),
            "retry_policy_json": payload.get("retry_policy"),
            "request_schema_json": payload.get("request_schema"),
            "response_schema_json": payload.get("response_schema"),
            "max_request_bytes": payload.get("max_request_bytes"),
            "max_response_bytes": payload.get("max_response_bytes"),
            "timeout_ms": payload.get("timeout_ms"),
            "allow_insecure_local": payload.get("allow_insecure_local"),
            "allow_private_network": payload.get("allow_private_network"),
            "enabled": payload.get("enabled"),
        }
        values = {key: value for key, value in mapped.items() if value is not None}
        return await self.repo.update(profile_id, **values)

    async def require_enabled(self, profile_id: int) -> HttpEndpointProfile:
        profile = await self.repo.get(profile_id)
        if profile is None:
            raise HttpProfileNotFound(f"endpoint profile 不存在: {profile_id}")
        if not profile.enabled:
            raise HttpProfileDisabled(f"endpoint profile 已禁用: {profile.name}")
        return profile
