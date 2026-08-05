"""Local API authentication plus strict Host and Origin validation."""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def parse_csv_setting(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def validate_local_api_security(
    *,
    bind_host: str,
    auth_enabled: bool,
    token: str | None,
    allowed_hosts: Iterable[str],
    allowed_origins: Iterable[str],
    allow_non_loopback_bind: bool = False,
) -> None:
    """Fail closed on unsafe local API configuration before server startup."""

    normalized_host = bind_host.strip().lower()
    try:
        address = ipaddress.ip_address(normalized_host)
        is_loopback = address.is_loopback
        is_unspecified = address.is_unspecified
    except ValueError:
        is_loopback = normalized_host == "localhost"
        is_unspecified = False
    if not is_loopback:
        if not (allow_non_loopback_bind and is_unspecified):
            raise RuntimeError(
                "PA_API_HOST must be loopback unless an authenticated container "
                "wildcard bind is explicitly enabled"
            )
        if not auth_enabled:
            raise RuntimeError(
                "authenticated container wildcard bind requires API authentication"
            )

    host_set = {item.strip().lower() for item in allowed_hosts if item.strip()}
    if not host_set or "*" in host_set:
        raise RuntimeError("PA_API_ALLOWED_HOSTS must be explicit and non-empty")

    origin_set = {item.strip() for item in allowed_origins if item.strip()}
    if not origin_set or "*" in origin_set:
        raise RuntimeError("PA_API_ALLOWED_ORIGINS must be explicit and non-empty")

    if auth_enabled and (token is None or len(token) < 32):
        raise RuntimeError(
            "PA_API_TOKEN must contain at least 32 characters when API auth is enabled"
        )


def _single_header(scope: Scope, name: bytes) -> str | None:
    values = [value for key, value in scope.get("headers", ()) if key.lower() == name]
    if len(values) != 1:
        return None
    try:
        return values[0].decode("latin-1")
    except UnicodeDecodeError:
        return None


def _header_count(scope: Scope, name: bytes) -> int:
    return sum(1 for key, _ in scope.get("headers", ()) if key.lower() == name)


def _host_name(host_header: str) -> str | None:
    try:
        return urlsplit(f"//{host_header}").hostname
    except ValueError:
        return None


class LocalApiSecurityMiddleware:
    """Authenticate every non-preflight HTTP request with one startup token."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        auth_enabled: bool,
        token: str | None,
        allowed_hosts: Iterable[str],
        allowed_origins: Iterable[str],
    ) -> None:
        self.app = app
        self.auth_enabled = auth_enabled
        self.token = token
        self.allowed_hosts = {
            item.strip().lower() for item in allowed_hosts if item.strip()
        }
        self.allowed_origins = {
            item.strip() for item in allowed_origins if item.strip()
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host_header = _single_header(scope, b"host")
        host_name = _host_name(host_header) if host_header is not None else None
        if host_name is None or host_name.lower() not in self.allowed_hosts:
            await self._reject(scope, receive, send, 400, "Invalid Host header")
            return

        if _header_count(scope, b"origin") > 1:
            await self._reject(scope, receive, send, 400, "Invalid Origin header")
            return
        origin = _single_header(scope, b"origin")
        if origin is not None and origin not in self.allowed_origins:
            await self._reject(scope, receive, send, 403, "Origin is not allowed")
            return

        # CORS preflight cannot carry the eventual Authorization header. The
        # outer CORSMiddleware validates origin, method, and requested headers.
        if scope.get("method") == "OPTIONS" and _single_header(
            scope, b"access-control-request-method"
        ):
            await self.app(scope, receive, send)
            return

        if self.auth_enabled:
            if self.token is None:
                await self._reject(
                    scope,
                    receive,
                    send,
                    503,
                    "Local API authentication is not configured",
                )
                return
            authorization = _single_header(scope, b"authorization")
            scheme, separator, supplied = (authorization or "").partition(" ")
            valid = (
                separator == " "
                and scheme.lower() == "bearer"
                and bool(supplied)
                and secrets.compare_digest(supplied, self.token)
            )
            if not valid:
                response = JSONResponse(
                    {"detail": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse({"detail": detail}, status_code=status_code)
        await response(scope, receive, send)
