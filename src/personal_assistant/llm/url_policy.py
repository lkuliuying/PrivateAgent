"""Default-deny policy for user-configured remote model endpoints."""

from __future__ import annotations

import ipaddress

import httpx


class UnsafeModelEndpointError(ValueError):
    pass


def validate_remote_base_url(
    raw_url: str,
    *,
    allow_http: bool = False,
    allow_private_network: bool = False,
) -> str:
    """Validate a configured remote endpoint before an HTTP client sees it.

    This blocks literal private targets and local hostnames.  Connection-time DNS
    pinning remains a later transport-hardening task.
    """

    try:
        url = httpx.URL(raw_url)
    except Exception as exc:  # noqa: BLE001
        raise UnsafeModelEndpointError("模型服务地址不是有效 URL") from exc

    if url.scheme not in ({"https", "http"} if allow_http else {"https"}):
        raise UnsafeModelEndpointError("远程模型服务默认必须使用 HTTPS")
    if not url.host:
        raise UnsafeModelEndpointError("模型服务地址缺少主机名")
    if url.username or url.password:
        raise UnsafeModelEndpointError("模型服务地址不得内嵌用户名或密码")
    if url.query or url.fragment:
        raise UnsafeModelEndpointError("模型服务基础地址不得包含 query 或 fragment")

    host = url.host.casefold().rstrip(".")
    if not allow_private_network:
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            raise UnsafeModelEndpointError("远程模型服务不得指向本地主机")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise UnsafeModelEndpointError("远程模型服务不得指向私网或保留地址")

    return str(url).rstrip("/")

