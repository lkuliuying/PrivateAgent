"""Fail-closed validation for user-controlled MCP transport configuration."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import McpServerConfig, McpTransport
from .secrets import is_mcp_secret_reference

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_HTTP_HEADER_TARGET = re.compile(r"^http-header:([!#$%&'*+.^_`|~0-9A-Za-z-]{1,64})$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
_SENSITIVE_NAME = re.compile(r"(?i)(?:api.?key|auth|bearer|cookie|pass|secret|token)")
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:api.?key|password|secret|token)\s*[:=]\s*\S+)"
)
_SHELL_EXECUTABLES = {
    "bash",
    "cmd",
    "cmd.exe",
    "fish",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "wsl",
    "wsl.exe",
    "zsh",
}
_BLOCKED_HTTP_SECRET_HEADERS = {
    "authorization",
    "connection",
    "content-length",
    "cookie",
    "host",
    "origin",
    "proxy-authenticate",
    "proxy-authorization",
    "referer",
    "set-cookie",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "user-agent",
}


class UnsafeMcpConfigurationError(ValueError):
    pass


def _validate_text(value: str, *, label: str, max_length: int) -> str:
    if not value or len(value) > max_length or "\0" in value or "\n" in value or "\r" in value:
        raise UnsafeMcpConfigurationError(f"invalid MCP {label}")
    return value


def _validate_http_url(config: McpServerConfig) -> None:
    assert config.url is not None
    try:
        parsed = urlsplit(config.url)
    except ValueError as exc:
        raise UnsafeMcpConfigurationError("invalid MCP server URL") from exc
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise UnsafeMcpConfigurationError("MCP HTTP transport requires an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise UnsafeMcpConfigurationError("MCP server URL cannot embed credentials or a fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeMcpConfigurationError("invalid MCP server URL port") from exc
    if port is not None and not 1 <= port <= 65_535:
        raise UnsafeMcpConfigurationError("invalid MCP server URL port")

    host = parsed.hostname.casefold().rstrip(".")
    is_local_name = host == "localhost" or host.endswith(".localhost")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    is_loopback = bool(address and address.is_loopback) or is_local_name
    is_private = bool(
        address
        and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    )
    if parsed.scheme == "http" and not (config.allow_insecure_local and is_loopback):
        raise UnsafeMcpConfigurationError("MCP HTTP requires HTTPS unless loopback HTTP is explicit")
    if (is_private or is_local_name or host.endswith(".local")) and not config.allow_private_network:
        raise UnsafeMcpConfigurationError("MCP server cannot target a private network by default")


def validate_mcp_config(config: McpServerConfig, *, require_active: bool = False) -> None:
    _validate_text(config.name, label="name", max_length=128)
    if not 100 <= config.timeout_ms <= 600_000:
        raise UnsafeMcpConfigurationError("MCP timeout_ms must be between 100 and 600000")
    if not 128 <= config.max_output_bytes <= 10 * 1024 * 1024:
        raise UnsafeMcpConfigurationError("MCP max_output_bytes is outside the allowed range")
    if require_active and (not config.trusted or not config.enabled):
        raise UnsafeMcpConfigurationError("MCP server must be explicitly trusted and enabled")
    if config.enabled and not config.trusted:
        raise UnsafeMcpConfigurationError("an untrusted MCP server cannot be enabled")

    for tool_name in config.allowed_tools:
        if not _TOOL_NAME.fullmatch(tool_name):
            raise UnsafeMcpConfigurationError("invalid MCP tool allowlist entry")

    env = config.env or {}
    if len(env) > 64:
        raise UnsafeMcpConfigurationError("too many MCP environment variables")
    for name, value in env.items():
        if not _ENV_NAME.fullmatch(name) or _SENSITIVE_NAME.search(name):
            raise UnsafeMcpConfigurationError("MCP plaintext environment cannot contain secret fields")
        _validate_text(value, label="environment value", max_length=8_192)
        if _SENSITIVE_VALUE.search(value):
            raise UnsafeMcpConfigurationError("MCP plaintext environment appears to contain a secret")

    secret_refs = config.secret_refs or {}
    if len(secret_refs) > 32:
        raise UnsafeMcpConfigurationError("too many MCP secret references")
    normalized_env_targets: set[str] = set()
    for target, reference in secret_refs.items():
        if not is_mcp_secret_reference(reference):
            raise UnsafeMcpConfigurationError("MCP secrets must use fixed OS-keyring references")
        if config.transport == McpTransport.STDIO:
            env_name = target.removeprefix("env:")
            if not _ENV_NAME.fullmatch(env_name):
                raise UnsafeMcpConfigurationError("invalid MCP secret environment target")
            if not _SENSITIVE_NAME.search(env_name):
                raise UnsafeMcpConfigurationError("MCP secret environment target must be credential-specific")
            if env_name in env or env_name in normalized_env_targets:
                raise UnsafeMcpConfigurationError("duplicate MCP environment target")
            normalized_env_targets.add(env_name)
            continue

        if target == "http-bearer":
            continue
        matched_header = _HTTP_HEADER_TARGET.fullmatch(target)
        if matched_header is None:
            raise UnsafeMcpConfigurationError("invalid MCP HTTP secret target")
        header_name = matched_header.group(1).casefold()
        if (
            header_name in _BLOCKED_HTTP_SECRET_HEADERS
            or header_name.startswith(("mcp-", "sec-", "x-forwarded-"))
            or header_name == "x-real-ip"
            or (header_name != "api-key" and not header_name.startswith("x-"))
            or not _SENSITIVE_NAME.search(header_name)
        ):
            raise UnsafeMcpConfigurationError("unsafe MCP HTTP secret header")

    if config.transport == McpTransport.STDIO:
        if config.url is not None or not config.command:
            raise UnsafeMcpConfigurationError("stdio MCP requires command and forbids URL")
        command = _validate_text(config.command, label="command", max_length=2_048)
        if Path(command).name.casefold() in _SHELL_EXECUTABLES:
            raise UnsafeMcpConfigurationError("MCP stdio cannot launch a command shell")
        executable = Path(command)
        if not executable.is_absolute() or not executable.is_file():
            raise UnsafeMcpConfigurationError(
                "MCP stdio command must be an existing absolute executable path"
            )
        if len(config.args) > 64:
            raise UnsafeMcpConfigurationError("too many MCP stdio arguments")
        for argument in config.args:
            _validate_text(argument, label="argument", max_length=2_048)
            if _SENSITIVE_VALUE.search(argument):
                raise UnsafeMcpConfigurationError("MCP stdio arguments appear to contain a secret")
        if config.working_directory is not None:
            working_directory = Path(config.working_directory)
            if not working_directory.is_absolute() or not working_directory.is_dir():
                raise UnsafeMcpConfigurationError("MCP working directory must be an existing absolute directory")
    elif config.transport == McpTransport.STREAMABLE_HTTP:
        if config.command is not None or config.args or config.working_directory is not None or not config.url:
            raise UnsafeMcpConfigurationError("Streamable HTTP MCP requires URL and forbids process fields")
        _validate_http_url(config)
    else:  # pragma: no cover - StrEnum construction normally catches this first.
        raise UnsafeMcpConfigurationError("unsupported MCP transport")
