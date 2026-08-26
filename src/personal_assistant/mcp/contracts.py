"""Typed MCP registry, discovery, and transport contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class McpTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class McpApprovalMode(StrEnum):
    """逐 server/逐工具审批模式（专项计划 §12.2）。

    auto 仅对只读、无副作用且**显式配置**的工具生效；MCP 自报只读不能单独
    成为授权依据。deny 不暴露、不调用。
    """

    AUTO = "auto"
    PROMPT = "prompt"
    WRITES = "writes"
    ALWAYS = "always"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    id: str
    name: str
    transport: McpTransport
    command: str | None = None
    args: tuple[str, ...] = ()
    working_directory: str | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    secret_refs: dict[str, str] | None = None
    allow_insecure_local: bool = False
    allow_private_network: bool = False
    trusted: bool = False
    enabled: bool = False
    allowed_tools: frozenset[str] = frozenset()
    # §12.2：server 默认审批模式与逐工具覆盖（工具名 → 模式）。
    approval_default: McpApprovalMode = McpApprovalMode.PROMPT
    approval_overrides: dict[str, McpApprovalMode] | None = None
    timeout_ms: int = 30_000
    max_output_bytes: int = 256 * 1024


@dataclass(frozen=True, slots=True)
class McpDiscovery:
    tools: tuple[dict[str, Any], ...]
    resources: tuple[dict[str, Any], ...]
    prompts: tuple[dict[str, Any], ...]
    sha256: str

