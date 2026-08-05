"""Typed MCP registry, discovery, and transport contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class McpTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


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
    timeout_ms: int = 30_000
    max_output_bytes: int = 256 * 1024


@dataclass(frozen=True, slots=True)
class McpDiscovery:
    tools: tuple[dict[str, Any], ...]
    resources: tuple[dict[str, Any], ...]
    prompts: tuple[dict[str, Any], ...]
    sha256: str

