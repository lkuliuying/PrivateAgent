"""服务器认证与本机模型推理解耦，复用共享模型适配器。"""
from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from private_agent_core.contracts import ModelRequest
from private_agent_core.llm.adapters import OllamaChatAdapter, OpenAIChatAdapter
from private_agent_core.llm.contracts import ModelGatewayError, RetryPolicy
from private_agent_core.llm.gateway import ModelGateway
from private_agent_core.runtime import CancellationToken

from .cloud import MODEL_ERROR_MESSAGES, Cloud, CloudError
from .connections import ModelConfig


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


class LocalInference:
    def __init__(self, profile: ModelConfig, *, transport=None):
        self.profile = profile
        self.client = httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False,
                                       headers={"Accept-Encoding": "identity"},
                                       transport=BoundedTransport(transport or httpx.AsyncHTTPTransport()))

    async def profiles(self) -> list[dict]:
        p = self.profile
        return [{"id": "local-model", "provider": p.model_protocol, "model_name": p.model_name,
                 "display_name": p.model_name or "请配置本地模型", "is_default": True, "is_local": True,
                 "native_tool_calls": True, "supports_streaming": False, "supports_structured_output": True,
                 "supports_vision": False, "context_tokens": p.context_tokens, "reasoning_efforts": [],
                 "usage_reporting": True, "enabled": bool(p.model_name)}]

    async def discover(self) -> list[dict]:
        path, key, name = ("/api/tags", "models", "name") if self.profile.model_protocol == "ollama" else ("/models", "data", "id")
        try:
            response = await self.client.get(f"{self.profile.model_endpoint}{path}", timeout=15)
            response.raise_for_status()
            body = response.json()
            items = body.get(key) if isinstance(body, dict) else None
            if not isinstance(items, list) or len(items) > 1000:
                raise ValueError
            models = []
            seen = set()
            for item in items:
                model_id = item.get(name) if isinstance(item, dict) else None
                if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200:
                    raise ValueError
                model_id = model_id.strip()
                if model_id not in seen:
                    seen.add(model_id)
                    # 列表协议不保证返回窗口容量，未知时由现有模型配置表单补充。
                    models.append({"model_id": model_id, "context_tokens": None,
                                   "max_output_tokens": None, "metadata_source": "unknown"})
            return models
        except (httpx.HTTPError, ValueError, ModelGatewayError):
            raise CloudError(502, "无法读取本机模型列表，请检查服务地址、协议及服务状态", code="model_discovery_failed") from None

    async def complete(self, profile: str | None, request: dict) -> dict:
        p = self.profile
        if profile not in {None, "local-model"} or not p.model_name:
            raise CloudError(422, "请先在模型设置中填写本地模型名称", code="model_not_configured")
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
    """只替换推理服务，身份验证与 SQLite 账号归属始终来自服务器。"""
    local_inference = True

    def __init__(self, origin: str, profile: ModelConfig, *, transport=None, model_transport=None):
        super().__init__(origin, transport=transport)
        self.models = LocalInference(profile, transport=model_transport)

    async def profiles(self, token: str) -> list[dict]:
        return await self.models.profiles()

    async def complete(self, token: str, profile: str | None, request: dict) -> dict:
        return await self.models.complete(profile, request)

    async def close(self):
        try:
            await self.models.close()
        finally:
            await super().close()


class ConfiguredModels(Cloud):
    """每次请求读取账号模型配置；本机推理不接收账号令牌或供应商密钥。"""

    def __init__(self, origin: str, *, transport=None, model_transport=None):
        super().__init__(origin, transport=transport)
        self.model_transport = model_transport

    async def complete(self, token: str, profile: str | None, request: dict) -> dict:
        # 供应商读取可能校正默认模型，必须先于读取 Profile，且不得按协议猜测供应商。
        providers = await self.request("GET", "/model-providers", token)
        profiles = await self.profiles(token)
        selected = [item for item in profiles if item.get("id") == profile] if profile else [
            item for item in profiles if item.get("is_default") is True]
        if len(selected) != 1 or selected[0].get("enabled") is not True:
            raise CloudError(422, "所选模型不可用，请在模型配置中选择并启用模型", code="model_not_configured")
        selected = selected[0]
        if not isinstance(providers, list) or len(providers) > 1000:
            raise CloudError(502, "服务器供应商配置响应无效", code="model_invalid_configuration")
        matches = [item for item in providers if isinstance(item, dict)
                   and isinstance(item.get("models"), list)
                   and any(isinstance(model, dict) and model.get("profile_id") == selected["id"] for model in item["models"])]
        if len(matches) != 1:
            raise CloudError(422, "模型缺少唯一的供应商配置，请重新保存模型配置", code="model_invalid_configuration")
        provider = matches[0]
        protocol = provider.get("protocol")
        model = next(item for item in provider["models"] if isinstance(item, dict) and item.get("profile_id") == selected["id"])
        if (provider.get("enabled") is not True or protocol != selected.get("provider")
                or (selected.get("provider_id") and provider.get("id") != selected["provider_id"])
                or model.get("model_id") != selected.get("model_name")):
            raise CloudError(422, "模型与供应商配置不一致或已禁用，请刷新模型设置", code="model_invalid_configuration")
        endpoint = provider.get("base_url")
        try:
            if not isinstance(endpoint, str):
                raise ValueError
            url = urlsplit(endpoint)
            local = url.hostname in {"127.0.0.1", "localhost", "::1"}
            if not url.hostname or url.scheme not in {"http", "https"} or url.username or url.password or url.query or url.fragment:
                raise ValueError
            if protocol == "ollama" or selected.get("is_local") is True or local:
                if protocol not in {"ollama", "openai"} or provider.get("api_format") != {
                    "ollama": "ollama_chat", "openai": "chat_completions"}.get(protocol):
                    raise ValueError
                config = ModelConfig(inference_mode="local", model_protocol=protocol, model_endpoint=endpoint,
                                     model_name=selected.get("model_name"), context_tokens=selected.get("context_tokens"))
            else:
                config = None
        except (ValueError, TypeError):
            raise CloudError(422, "模型配置无效；本机模型仅支持回环地址的 Ollama 或 OpenAI 兼容接口", code="model_invalid_configuration") from None
        if config is None:
            result = await super().complete(token, selected["id"], request)
        else:
            if provider.get("api_key_configured"):
                raise CloudError(422, "本机模型暂不支持需要密钥的接口，请使用无密钥回环服务", code="model_invalid_configuration")
            models = LocalInference(config, transport=self.model_transport)
            try:
                result = await models.complete(None, request)
            finally:
                await models.close()
        # 固定本轮实际解析的模型，后续工具轮次与用量统计不随默认模型漂移。
        return {**result, "model_profile_id": selected["id"]}


def model_service(origin: str, profile: ModelConfig):
    if profile.inference_mode == "auto":
        return ConfiguredModels(origin)
    if profile.inference_mode == "local":
        return ConnectedLocalModels(origin, profile)
    return Cloud(origin)
