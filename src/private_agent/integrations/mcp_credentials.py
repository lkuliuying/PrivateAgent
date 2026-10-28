"""MCP 凭据只经私有管道访问系统库；HTTP 兼容模式仅保留会话 OAuth。"""
from __future__ import annotations

import asyncio
import hashlib
import re
import uuid

MAX_SECRET_BYTES = 64 * 1024
MAX_PENDING = 16
MAX_SESSION_SLOTS = 32
ERRORS = {
    "credential_scope_invalid": "MCP 凭据范围无效",
    "credential_store_failed": "系统凭据操作未完成，请重新连接后核对配置",
    "credential_transport_closed": "MCP 私有凭据通道已关闭，请重新连接",
    "credential_timeout": "MCP 凭据操作超时，结果未确认，请核对后重试",
    "credential_busy": "MCP 凭据操作过多，请稍后重试",
    "persistent_credentials_unavailable": "当前连接不支持系统凭据库；静态秘密请使用桌面私有管道配置",
}


class McpCredentialError(ValueError):
    def __init__(self, code: str):
        self.code = code if code in ERRORS else "credential_store_failed"
        super().__init__(ERRORS[self.code])


def validate_binding(binding: dict) -> dict:
    if not isinstance(binding, dict) or set(binding) != {"identity", "service_id", "version", "slot"}:
        raise McpCredentialError("credential_scope_invalid")
    for key, length in (("identity", 64), ("service_id", 32), ("version", 32)):
        if not isinstance(binding[key], str) or not re.fullmatch(r"[a-f0-9]{" + str(length) + "}", binding[key]):
            raise McpCredentialError("credential_scope_invalid")
    if not isinstance(binding["slot"], str) or binding["slot"] not in {"static", "oauth"}:
        raise McpCredentialError("credential_scope_invalid")
    return dict(binding)


def credential_reference(binding: dict) -> str:
    value = validate_binding(binding)
    return "secret://os-keyring/mcp/" + "/".join(value[key] for key in ("identity", "service_id", "version", "slot"))


def _validate_value(value: str):
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_SECRET_BYTES or "\0" in value:
        raise McpCredentialError("credential_scope_invalid")


class CredentialTransport:
    """请求与回应独立于 WebView HTTP 帧；取消或超时后迟到回应只会丢弃。"""
    def __init__(self, send, *, timeout: float = 10):
        self.send, self.timeout = send, timeout
        self.pending: dict[str, asyncio.Future] = {}
        self.closed = False

    async def request(self, operation: str, binding: dict, value: str | None = None) -> dict:
        binding = validate_binding(binding)
        if operation not in {"bind", "get", "set", "delete"} or (value is not None) != (operation == "set"):
            raise McpCredentialError("credential_scope_invalid")
        if value is not None:
            _validate_value(value)
        if self.closed:
            raise McpCredentialError("credential_transport_closed")
        if len(self.pending) >= MAX_PENDING:
            raise McpCredentialError("credential_busy")
        request_id = "mcp-" + uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        params = {"operation": operation, "binding": binding}
        if value is not None:
            params["value"] = value
        try:
            async with asyncio.timeout(self.timeout):
                await self.send({"id": request_id, "method": "mcp_credential", "params": params})
                return await future
        except TimeoutError:
            raise McpCredentialError("credential_timeout") from None
        except (ConnectionError, OSError):
            raise McpCredentialError("credential_transport_closed") from None
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # 管道关闭可能早于写入结束；消费未被等待的异常，避免日志附带任务对象。
                future.exception()

    def receive(self, frame: dict) -> bool:
        if frame.get("method") != "mcp_credential_result":
            return False
        request_id = frame.get("id")
        if not isinstance(request_id, str) or not re.fullmatch(r"mcp-[a-f0-9]{32}", request_id):
            raise McpCredentialError("credential_scope_invalid")
        future = self.pending.get(request_id)
        if future is None or future.done():
            return True
        if set(frame) - {"id", "method", "result", "error"} or ("result" in frame) == ("error" in frame):
            future.set_exception(McpCredentialError("credential_store_failed"))
        elif "error" in frame:
            future.set_exception(McpCredentialError(frame["error"] if isinstance(frame["error"], str) else "credential_store_failed"))
        elif not isinstance(frame["result"], dict):
            future.set_exception(McpCredentialError("credential_store_failed"))
        else:
            future.set_result(frame["result"])
        return True

    def close(self):
        self.closed = True
        for future in self.pending.values():
            if not future.done():
                future.set_exception(McpCredentialError("credential_transport_closed"))


class McpCredentials:
    def __init__(self, identity: str, transport: CredentialTransport | None = None):
        validate_binding({"identity": identity, "service_id": "0" * 32, "version": "0" * 32, "slot": "oauth"})
        self.identity, self.transport = identity, transport
        self._session: dict[tuple[str, str, str], str] = {}
        self.closed = False

    @property
    def persistent(self) -> bool:
        return self.transport is not None and not self.transport.closed and not self.closed

    def _binding(self, service_id: str, version: str, slot: str) -> dict:
        if self.closed:
            raise McpCredentialError("credential_transport_closed")
        binding = validate_binding({"identity": self.identity, "service_id": service_id, "version": version, "slot": slot})
        if self.transport is None and slot == "static":
            raise McpCredentialError("persistent_credentials_unavailable")
        return binding

    async def binding(self, service_id: str, version: str, slot: str) -> dict:
        binding = self._binding(service_id, version, slot)
        if self.transport:
            await self.transport.request("bind", binding)
        return binding

    async def get(self, service_id: str, version: str, slot: str) -> str | None:
        binding = self._binding(service_id, version, slot)
        if self.transport:
            result = await self.transport.request("get", binding)
            if set(result) != {"value"}:
                raise McpCredentialError("credential_store_failed")
            value = result["value"]
            if value is not None:
                _validate_value(value)
            return value
        return self._session.get((service_id, version, slot))

    async def set(self, service_id: str, version: str, slot: str, value: str) -> str:
        binding = self._binding(service_id, version, slot)
        _validate_value(value)
        reference = credential_reference(binding)
        if self.transport:
            result = await self.transport.request("set", binding, value)
            if result != {"reference": reference}:
                raise McpCredentialError("credential_store_failed")
        else:
            key = (service_id, version, slot)
            if key not in self._session and len(self._session) >= MAX_SESSION_SLOTS:
                raise McpCredentialError("credential_busy")
            self._session[key] = value
            reference = reference.replace("secret://os-keyring/", "secret://session/")
        return reference

    async def delete(self, service_id: str, version: str, slot: str):
        binding = self._binding(service_id, version, slot)
        if self.transport:
            await self.transport.request("delete", binding)
        else:
            self._session.pop((service_id, version, slot), None)

    def close(self):
        self.closed = True
        self._session.clear()


def get_broker(owner) -> McpCredentials:
    broker = getattr(owner, "mcp_credentials", None)
    if broker is None:
        authority, owner_id = getattr(owner, "authority", None), getattr(owner, "owner_id", None)
        source = f"{authority}\0{owner_id}" if authority is not None and owner_id is not None else str(owner.store.path.resolve())
        broker = McpCredentials(hashlib.sha256(source.encode()).hexdigest())
        owner.mcp_credentials = broker
    return broker
