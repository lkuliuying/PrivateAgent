"""无云端账号的本地模型服务，复用共享模型适配器和执行核心。"""
from __future__ import annotations

import secrets

import httpx

from private_agent_core.contracts import ModelRequest
from private_agent_core.llm.adapters import OllamaChatAdapter, OpenAIChatAdapter
from private_agent_core.llm.contracts import ModelGatewayError, RetryPolicy
from private_agent_core.llm.gateway import ModelGateway
from private_agent_core.runtime import CancellationToken

from .cloud import MODEL_ERROR_MESSAGES, Cloud, CloudError
from .connections import ConnectionProfile
from .store import now


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > 2 * 1024 * 1024:
                raise ModelGatewayError("模型响应超过大小限制", code="invalid_response", provider="local")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport):
        self.transport = transport

    async def handle_async_request(self, request):
        response = await self.transport.handle_async_request(request)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise ModelGatewayError("本地模型必须返回未压缩的有界响应", code="invalid_response", provider="local")
        if response.is_stream_consumed:
            if len(response.content) > 2 * 1024 * 1024:
                raise ModelGatewayError("模型响应超过大小限制", code="invalid_response", provider="local")
        else:
            response.stream = BoundedStream(response.stream)
        return response

    async def aclose(self):
        await self.transport.aclose()


class LocalModels:
    origin = "local://device"
    is_local = True
    local_inference = True

    def __init__(self, profile: ConnectionProfile, *, transport=None):
        if profile.mode != "local":
            raise ValueError("本地模型服务仅接受本地连接配置")
        self.profile = profile
        self.token = secrets.token_urlsafe(48)
        self.user = {"id": 1, "email": "", "username": "本机用户", "display_name": "本机用户", "role": "user",
                     "status": "active", "last_login_at": None, "created_at": now()}
        self.client = httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False,
                                       headers={"Accept-Encoding": "identity"},
                                       transport=BoundedTransport(transport or httpx.AsyncHTTPTransport()))

    async def identity(self, token: str) -> dict:
        if not secrets.compare_digest(token, self.token):
            raise CloudError(401, "本机会话已失效，请重新进入", code="local_auth_required")
        return self.user

    def revoke_identity(self):
        self.token = secrets.token_urlsafe(48)

    async def profiles(self, token: str) -> list[dict]:
        await self.identity(token)
        p = self.profile
        return [{"id": "local-model", "provider": p.model_protocol, "model_name": p.model_name,
                 "display_name": p.model_name or "请配置本地模型", "is_default": True, "is_local": True,
                 "native_tool_calls": True, "supports_streaming": False, "supports_structured_output": True,
                 "supports_vision": False, "context_tokens": p.context_tokens, "reasoning_efforts": [],
                 "usage_reporting": True, "enabled": bool(p.model_name)}]

    async def complete(self, token: str, profile: str | None, request: dict) -> dict:
        await self.identity(token)
        p = self.profile
        if profile not in {None, "local-model"} or not p.model_name:
            raise CloudError(422, "请先在连接设置中填写本地模型名称", code="model_not_configured")
        if p.model_protocol == "ollama":
            if p.context_tokens is None:
                raise CloudError(422, "请填写 Ollama 请求的上下文容量", code="model_not_configured")
            adapter = OllamaChatAdapter(base_url=p.model_endpoint, model=p.model_name, context_length=p.context_tokens, client=self.client)
        else:
            adapter = OpenAIChatAdapter(base_url=p.model_endpoint, api_key="", model=p.model_name, require_api_key=False,
                                        allow_http=True, allow_private_network=True, client=self.client)
        gateway = ModelGateway(adapter, request_timeout_seconds=180, retry_policy=RetryPolicy(max_attempts=1))
        try:
            result = await gateway.complete(ModelRequest.model_validate(request), cancellation=CancellationToken())
            response = result.model_dump(mode="json")
            # 旧供应商未返回 usage 时适配器会填零；不能据此伪造已计量的零占用。
            if not result.usage.input_tokens:
                response["usage"] = {}
            return response
        except ModelGatewayError as error:
            raise CloudError(502, MODEL_ERROR_MESSAGES.get(error.code, "本地模型请求失败"), code=f"model_{error.code}") from None

    async def close(self):
        await self.client.aclose()


class ConnectedLocalModels(Cloud):
    """账号仍由原服务验证，仅把推理切到本机，SQLite 数据所有者保持不变。"""
    local_inference = True

    def __init__(self, profile: ConnectionProfile, *, transport=None, model_transport=None):
        super().__init__(profile.server_origin, transport=transport)
        self.models = LocalModels(profile.model_copy(update={"mode": "local"}), transport=model_transport)

    async def profiles(self, token: str) -> list[dict]:
        return await self.models.profiles(self.models.token)

    async def complete(self, token: str, profile: str | None, request: dict) -> dict:
        return await self.models.complete(self.models.token, profile, request)

    async def close(self):
        await self.models.close()
        await super().close()


def model_service(profile: ConnectionProfile):
    if profile.mode == "local":
        return LocalModels(profile)
    if profile.inference_mode == "local":
        return ConnectedLocalModels(profile)
    return Cloud(profile.server_origin)
