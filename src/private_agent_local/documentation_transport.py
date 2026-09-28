"""公开技术文档 MCP 的受控 HTTP 传输，不提供进程、凭据或本机资源能力。"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

import httpcore2
import httpx2
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from private_agent_core.tool_specs import ToolFailure

from .files import digest

TIMEOUT = 20
MAX_WIRE_BYTES = 512 * 1024
MAX_OUTPUT_BYTES = 128 * 1024


def endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.query or parsed.fragment
                or port not in {None, 443} or any(character.isspace() for character in value) or "\\" in value):
            raise ValueError
        if host.casefold() == "localhost" or host.endswith(".localhost"):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError
        return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", "", ""))
    except ValueError as error:
        raise ToolFailure("mcp_invalid_endpoint", "文档服务须使用公开 HTTPS 地址，不含凭据、查询参数或特殊端口") from error


class PinnedBackend(httpcore2.AsyncNetworkBackend):
    def __init__(self, hostname, addresses):
        self.hostname, self.addresses = hostname, addresses
        self.backend = httpcore2.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host.casefold().rstrip(".") != self.hostname or port != 443:
            raise ToolFailure("mcp_unsafe_target", "文档连接目标不在已校验范围内")
        for index, address in enumerate(self.addresses):
            try:
                return await self.backend.connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                                      socket_options=socket_options)
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout):
                if index == len(self.addresses) - 1:
                    raise

    async def connect_unix_socket(self, *args, **kwargs):
        raise ToolFailure("mcp_unsafe_target", "文档连接不支持本机套接字")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)


class BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_WIRE_BYTES:
                raise ToolFailure("mcp_output_too_large", "文档服务响应超过大小限制")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class BoundedTransport(httpx2.AsyncHTTPTransport):
    async def handle_async_request(self, request):
        response = await super().handle_async_request(request)
        if 300 <= response.status_code < 400 or response.headers.get("content-encoding", "identity") != "identity":
            await response.aclose()
            raise ToolFailure("mcp_unsafe_response", "文档服务返回重定向或不支持的压缩响应")
        response.stream = BoundedStream(response.stream)
        return response


@asynccontextmanager
async def connection(url):
    url = endpoint(url)
    hostname = urlsplit(url).hostname.casefold().rstrip(".")
    try:
        async with asyncio.timeout(TIMEOUT):
            addresses = await asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            resolved = sorted({item[4][0] for item in addresses})
            if not resolved or any(not ipaddress.ip_address(address).is_global for address in resolved):
                raise ToolFailure("mcp_unsafe_target", "文档服务解析到内网或特殊地址，连接已拒绝")
            transport = BoundedTransport(trust_env=False, retries=0, limits=httpx2.Limits(max_connections=2))
            # httpx2/httpcore2 在项目中固定版本；TLS 和 SNI 保持原始域名，只固定已校验的 TCP 地址。
            transport._pool._network_backend = PinnedBackend(hostname, resolved)
            async with httpx2.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                         headers={"Accept-Encoding": "identity"}, timeout=TIMEOUT) as http:
                async with Client(streamable_http_client(url, http_client=http), raise_exceptions=True,
                                  read_timeout_seconds=TIMEOUT, cache=None) as client:
                    yield client
    except ToolFailure:
        raise
    except TimeoutError as error:
        raise ToolFailure("mcp_timeout", "文档服务连接或检索超时", retryable=True) from error
    except Exception as error:
        pending = [error]
        while pending:
            current = pending.pop()
            if isinstance(current, ToolFailure):
                raise current from error
            if isinstance(current, ExceptionGroup):
                pending.extend(current.exceptions)
        raise ToolFailure("mcp_connection_failed", "文档服务连接失败，请检查地址或稍后重试", retryable=True) from error


def encoded(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ToolFailure("mcp_invalid_data", "文档服务数据不是有效 JSON") from error


def check_schema(schema):
    if not isinstance(schema, dict) or len(encoded(schema)) > 16000:
        raise ToolFailure("mcp_invalid_schema", "文档工具参数结构无效或过大")
    def visit(value, depth=0):
        if depth > 16:
            raise ToolFailure("mcp_invalid_schema", "文档工具参数结构过深")
        if isinstance(value, dict):
            if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef", "pattern", "patternProperties")):
                raise ToolFailure("mcp_invalid_schema", "首版文档工具不支持引用或正则表达式结构")
            for child in value.values():
                visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)
    visit(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise ToolFailure("mcp_invalid_schema", "文档工具参数结构无效") from error


async def catalog(client):
    items, seen, cursor = [], set(), None
    for _ in range(8):
        page = await client.list_tools(cursor=cursor, cache_mode="reload")
        for tool in page.tools:
            if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", tool.name) or tool.name in seen:
                raise ToolFailure("mcp_invalid_catalog", "文档工具名称无效或重复")
            check_schema(tool.input_schema)
            if tool.input_schema.get("type") != "object":
                raise ToolFailure("mcp_invalid_schema", "文档工具参数必须为对象")
            if tool.output_schema is not None:
                check_schema(tool.output_schema)
            seen.add(tool.name)
            items.append({"name": tool.name, "description": (tool.description or "")[:2000],
                          "input_schema": tool.input_schema, "output_schema": tool.output_schema})
        if len(items) > 128 or len(encoded(items)) > MAX_OUTPUT_BYTES:
            raise ToolFailure("mcp_catalog_too_large", "文档工具目录超过上限")
        if page.next_cursor is None:
            items.sort(key=lambda item: item["name"])
            return {"tools": items, "sha256": digest(encoded(items))}
        cursor = page.next_cursor
    raise ToolFailure("mcp_invalid_catalog", "文档工具目录分页未结束")


class DocumentationClient:
    async def discover(self, url):
        async with connection(url) as client:
            return await catalog(client)

    async def call(self, source, tool, arguments, guard):
        async with connection(source["url"]) as client:
            current = await catalog(client)
            if current["sha256"] != source["catalog"]["sha256"]:
                raise ToolFailure("mcp_catalog_changed", "文档服务工具已变化，请重新发现并选择工具")
            await guard()
            # 原始会话返回额外交互请求供本地拒绝，禁止 SDK 自动进行模型采样或询问信息后重试。
            result = await client.session.call_tool(tool["name"], arguments, allow_input_required=True)
            if result.result_type != "complete":
                raise ToolFailure("mcp_interaction_rejected", "文档工具要求额外交互，本次未继续")
            if result.is_error:
                raise ToolFailure("mcp_tool_failed", "文档服务检索失败，请调整查询条件")
            output = {"content": [item.model_dump(by_alias=True, exclude_none=True, exclude={"meta"}) for item in result.content],
                      "structured_content": result.structured_content}
            if len(encoded(output)) > MAX_OUTPUT_BYTES:
                raise ToolFailure("mcp_output_too_large", "检索结果过大，请缩小查询或使用远端分页参数")
            if tool["output_schema"] is not None and not Draft202012Validator(tool["output_schema"]).is_valid(result.structured_content):
                raise ToolFailure("mcp_invalid_output", "文档结果不符合已确认的输出结构")
            return output
