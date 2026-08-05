"""Process-local MCP credential references supplied by the trusted desktop shell."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, MutableMapping
from typing import Protocol

MCP_SECRETS_ENV = "PA_MCP_SECRETS_JSON"
_SECRET_REFERENCE = re.compile(
    r"^secret://os-keyring/mcp/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)
_MAX_SECRETS = 32
_MAX_SECRET_LENGTH = 8_192
_MAX_ENCODED_LENGTH = 24 * 1_024


def is_mcp_secret_reference(value: str) -> bool:
    return bool(_SECRET_REFERENCE.fullmatch(value))


class McpSecretResolver(Protocol):
    """Resolve an allowlisted reference without exposing enumeration or values."""

    def resolve(self, reference: str) -> str | None: ...


class MappingMcpSecretResolver:
    """Small in-memory resolver used for process injection and deterministic tests."""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def resolve(self, reference: str) -> str | None:
        return self._values.get(reference)


def load_process_mcp_secret_resolver(
    environ: MutableMapping[str, str] | None = None,
) -> MappingMcpSecretResolver:
    """Consume the desktop-injected map once and remove it from the environment."""

    source = os.environ if environ is None else environ
    raw = source.pop(MCP_SECRETS_ENV, "")
    if not raw or len(raw) > _MAX_ENCODED_LENGTH:
        return MappingMcpSecretResolver()
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return MappingMcpSecretResolver()
    if not isinstance(payload, dict) or len(payload) > _MAX_SECRETS:
        return MappingMcpSecretResolver()

    values: dict[str, str] = {}
    for reference, secret in payload.items():
        if (
            not isinstance(reference, str)
            or not is_mcp_secret_reference(reference)
            or not isinstance(secret, str)
            or not secret
            or len(secret) > _MAX_SECRET_LENGTH
            or "\0" in secret
        ):
            return MappingMcpSecretResolver()
        values[reference] = secret
    return MappingMcpSecretResolver(values)


process_mcp_secret_resolver = load_process_mcp_secret_resolver()
