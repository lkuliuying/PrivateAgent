"""Official MCP SDK v2 adapter with bounded discovery, execution, and teardown."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO, cast
from urllib.parse import urlsplit

import httpcore2
import httpx2
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from .contracts import McpDiscovery, McpServerConfig, McpTransport
from .secrets import McpSecretResolver, process_mcp_secret_resolver
from .validation import validate_mcp_config

_MAX_DISCOVERY_ITEMS = 512
_MAX_DISCOVERY_PAGES = 32
_MAX_DISCOVERY_BYTES = 2 * 1024 * 1024


class McpClientError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class McpClient(Protocol):
    async def discover(self, config: McpServerConfig) -> McpDiscovery: ...

    async def call_tool(
        self,
        config: McpServerConfig,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], int]: ...


@dataclass(frozen=True, slots=True)
class _ResolvedSecrets:
    stdio_env: dict[str, str]
    http_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class _ResolvedHttpTarget:
    hostname: str
    port: int
    addresses: tuple[str, ...]


class _PinnedNetworkBackend(httpcore2.AsyncNetworkBackend):
    """Connect only to the address set that passed the MCP DNS policy check."""

    def __init__(
        self,
        target: _ResolvedHttpTarget,
        *,
        backend: httpcore2.AsyncNetworkBackend | None = None,
    ) -> None:
        self._target = target
        self._backend = backend or httpcore2.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore2.AsyncNetworkStream:
        normalized_host = host.casefold().rstrip(".")
        if normalized_host != self._target.hostname or port != self._target.port:
            raise httpcore2.ConnectError("MCP transport attempted an unvalidated target")

        last_error: Exception | None = None
        for address in self._target.addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore2.ConnectError("MCP transport has no validated target address")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options=None,
    ) -> httpcore2.AsyncNetworkStream:
        del path, timeout, socket_options
        raise httpcore2.ConnectError("MCP HTTP transport forbids Unix sockets")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def _resolve_secrets(
    config: McpServerConfig,
    resolver: McpSecretResolver,
) -> _ResolvedSecrets:
    stdio_env: dict[str, str] = {}
    http_headers: dict[str, str] = {}
    for target, reference in (config.secret_refs or {}).items():
        secret = resolver.resolve(reference)
        if not secret:
            raise McpClientError("MCP credential is unavailable", code="credential_unavailable")
        if config.transport == McpTransport.STDIO:
            if "\0" in secret:
                raise McpClientError("MCP credential is invalid", code="credential_invalid")
            stdio_env[target.removeprefix("env:")] = secret
            continue

        if any(
            ord(character) < 0x21 or ord(character) > 0x7E
            for character in secret
        ):
            raise McpClientError("MCP HTTP credential is invalid", code="credential_invalid")
        if target == "http-bearer":
            http_headers["Authorization"] = f"Bearer {secret}"
        else:
            http_headers[target.removeprefix("http-header:")] = secret
    return _ResolvedSecrets(stdio_env=stdio_env, http_headers=http_headers)


async def _validate_resolved_http_target(
    config: McpServerConfig,
) -> _ResolvedHttpTarget:
    """Resolve once, validate every result, and return the address set to pin."""

    assert config.url is not None
    parsed = urlsplit(config.url)
    assert parsed.hostname is not None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise McpClientError("MCP server DNS resolution failed", code="dns_error") from exc
    if not addresses:
        raise McpClientError("MCP server DNS resolution returned no address", code="dns_error")
    resolved = {item[4][0].split("%", 1)[0] for item in addresses}
    if not config.allow_private_network and any(
        not ipaddress.ip_address(address).is_global for address in resolved
    ):
        raise McpClientError(
            "MCP server resolved to a private or special network",
            code="unsafe_target",
        )
    ordered = tuple(
        str(address)
        for address in sorted(
            (ipaddress.ip_address(item) for item in resolved),
            key=lambda item: (item.version, int(item)),
        )
    )
    return _ResolvedHttpTarget(
        hostname=parsed.hostname.casefold().rstrip("."),
        port=port,
        addresses=ordered,
    )


def _pinned_http_transport(
    target: _ResolvedHttpTarget,
    *,
    limits: httpx2.Limits,
) -> httpx2.AsyncHTTPTransport:
    """Bind HTTPX's TCP layer to the already validated DNS result.

    HTTPX still owns HTTP and TLS, so certificate validation and SNI use the
    original URL hostname.  The small pool hook is intentionally isolated and
    protected by the exact httpx2/httpcore2 dependency pins.
    """

    transport = httpx2.AsyncHTTPTransport(
        trust_env=False,
        limits=limits,
        retries=0,
    )
    pool = getattr(transport, "_pool", None)
    if not isinstance(pool, httpcore2.AsyncConnectionPool):
        raise TypeError("Unsupported httpx2 transport internals")
    pool._network_backend = _PinnedNetworkBackend(target)
    return transport


@asynccontextmanager
async def _client_context(
    config: McpServerConfig,
    secrets: _ResolvedSecrets,
) -> AsyncIterator[Client]:
    if config.transport == McpTransport.STDIO:
        assert config.command is not None
        transport = stdio_client(
            StdioServerParameters(
                command=config.command,
                args=list(config.args),
                env={**dict(config.env or {}), **secrets.stdio_env},
                cwd=Path(config.working_directory) if config.working_directory else None,
            ),
            # Windows subprocess creation requires a native file descriptor here.
            # DEVNULL also keeps untrusted server stderr out of application logs.
            errlog=cast(TextIO, subprocess.DEVNULL),
        )
        async with Client(
            transport,
            raise_exceptions=True,
            read_timeout_seconds=config.timeout_ms / 1_000,
            cache=None,
        ) as client:
            yield client
        return
    assert config.url is not None
    target = await _validate_resolved_http_target(config)
    timeout_seconds = config.timeout_ms / 1_000
    limits = httpx2.Limits(max_connections=4, max_keepalive_connections=2)
    async with httpx2.AsyncClient(
        headers=secrets.http_headers,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx2.Timeout(timeout_seconds),
        transport=_pinned_http_transport(target, limits=limits),
    ) as http_client:
        transport = streamable_http_client(config.url, http_client=http_client)
        async with Client(
            transport,
            raise_exceptions=True,
            read_timeout_seconds=timeout_seconds,
            cache=None,
        ) as client:
            yield client


def _tool_view(tool: Any) -> dict[str, Any]:
    return {
        "name": str(tool.name),
        "title": str(tool.title)[:512] if tool.title else None,
        "description": str(tool.description)[:8_000] if tool.description else None,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
    }


def _resource_view(resource: Any) -> dict[str, Any]:
    return {
        "uri": str(resource.uri)[:2_048],
        "name": str(resource.name)[:512],
        "title": str(resource.title)[:512] if resource.title else None,
        "description": str(resource.description)[:8_000] if resource.description else None,
        "mime_type": str(resource.mime_type)[:255] if resource.mime_type else None,
    }


def _prompt_view(prompt: Any) -> dict[str, Any]:
    return {
        "name": str(prompt.name),
        "title": str(prompt.title)[:512] if prompt.title else None,
        "description": str(prompt.description)[:8_000] if prompt.description else None,
        "arguments": [
            {
                "name": str(argument.name)[:512],
                "title": str(argument.title)[:512] if argument.title else None,
                "description": str(argument.description)[:2_000] if argument.description else None,
                "required": bool(argument.required),
            }
            for argument in (prompt.arguments or [])[:128]
        ],
    }


async def _list_all(call, item_attribute: str) -> list[Any]:
    items: list[Any] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(_MAX_DISCOVERY_PAGES):
        page = await call(cursor=cursor, cache_mode="reload")
        items.extend(getattr(page, item_attribute))
        if len(items) > _MAX_DISCOVERY_ITEMS:
            raise McpClientError("MCP discovery item limit exceeded", code="discovery_limit")
        cursor = page.next_cursor
        if cursor is None:
            return items
        if cursor in seen_cursors:
            raise McpClientError("MCP discovery cursor loop", code="protocol_error")
        seen_cursors.add(cursor)
    raise McpClientError("MCP discovery page limit exceeded", code="discovery_limit")


class OfficialMcpClient:
    def __init__(self, *, secret_resolver: McpSecretResolver | None = None) -> None:
        self._secret_resolver = (
            process_mcp_secret_resolver if secret_resolver is None else secret_resolver
        )

    async def discover(self, config: McpServerConfig) -> McpDiscovery:
        validate_mcp_config(config, require_active=True)
        secrets = _resolve_secrets(config, self._secret_resolver)
        try:
            async with asyncio.timeout(config.timeout_ms / 1_000):
                async with _client_context(config, secrets) as client:
                    tools, resources, prompts = await asyncio.gather(
                        _list_all(client.list_tools, "tools"),
                        _list_all(client.list_resources, "resources"),
                        _list_all(client.list_prompts, "prompts"),
                    )
        except McpClientError:
            raise
        except TimeoutError as exc:
            raise McpClientError("MCP discovery timed out", code="timeout") from exc
        except Exception as exc:
            raise McpClientError("MCP discovery failed", code="connection_error") from exc

        payload = {
            "tools": [_tool_view(item) for item in tools],
            "resources": [_resource_view(item) for item in resources],
            "prompts": [_prompt_view(item) for item in prompts],
        }
        encoded = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > _MAX_DISCOVERY_BYTES:
            raise McpClientError("MCP discovery payload limit exceeded", code="discovery_limit")
        return McpDiscovery(
            tools=tuple(payload["tools"]),
            resources=tuple(payload["resources"]),
            prompts=tuple(payload["prompts"]),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )

    async def call_tool(
        self,
        config: McpServerConfig,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        validate_mcp_config(config, require_active=True)
        if name not in config.allowed_tools:
            raise McpClientError("MCP tool is not allowlisted", code="tool_not_allowed")
        secrets = _resolve_secrets(config, self._secret_resolver)
        try:
            async with asyncio.timeout(config.timeout_ms / 1_000):
                async with _client_context(config, secrets) as client:
                    result = await client.call_tool(name, arguments)
        except TimeoutError as exc:
            raise McpClientError("MCP tool call timed out", code="timeout") from exc
        except Exception as exc:
            raise McpClientError("MCP tool call failed", code="connection_error") from exc
        if result.is_error:
            raise McpClientError("MCP server returned a tool error", code="server_tool_error")
        if result.result_type != "complete":
            raise McpClientError("MCP tool requested unsupported interaction", code="input_required")

        output = (
            result.structured_content
            if isinstance(result.structured_content, dict)
            else {
                "content": [
                    item.model_dump(by_alias=True, exclude_none=True, exclude={"meta"})
                    for item in result.content
                ]
            }
        )
        encoded = json.dumps(
            output, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > config.max_output_bytes:
            raise McpClientError("MCP tool output limit exceeded", code="output_too_large")
        return output, len(encoded)
