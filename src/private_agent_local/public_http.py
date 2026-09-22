"""公开 HTTPS 传输：每次连接校验 DNS，不转发环境代理和重定向。"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx2

from private_agent_core.tool_specs import ToolFailure

from .documentation_transport import BoundedTransport, PinnedBackend


def public_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.port not in {None, 443} or parsed.username or parsed.password or parsed.fragment or "\\" in value or any(c.isspace() for c in value):
            raise ValueError
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
        return host
    except ValueError as error:
        raise ToolFailure("public_url_required", "仅支持无凭据的公开 HTTPS 地址，端口须为 443") from error


class ClosingStream(httpx2.AsyncByteStream):
    def __init__(self, stream, transport):
        self.stream, self.transport = stream, transport

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            await self.transport.aclose()


class PublicTransport(httpx2.AsyncBaseTransport):
    async def handle_async_request(self, request):
        host = public_url(str(request.url))
        async with asyncio.timeout(20):
            rows = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = sorted({row[4][0] for row in rows})
        if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
            raise ToolFailure("private_target_blocked", "目标解析到内网或特殊地址，连接已拒绝")
        transport = BoundedTransport(trust_env=False, retries=0)
        transport._pool._network_backend = PinnedBackend(host, addresses)
        try:
            response = await transport.handle_async_request(request)
            response.stream = ClosingStream(response.stream, transport)
            return response
        except BaseException:
            await transport.aclose()
            raise


def public_client(**kwargs):
    return httpx2.AsyncClient(transport=PublicTransport(), follow_redirects=False, trust_env=False,
                             headers={"Accept-Encoding": "identity"}, timeout=25, **kwargs)
