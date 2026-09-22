"""本机模型发现与推理，复用共享模型适配器。"""
from __future__ import annotations

import httpx

from private_agent_core.contracts import ModelRequest
from private_agent_core.llm.adapters import OllamaChatAdapter, OpenAIChatAdapter
from private_agent_core.llm.contracts import ModelGatewayError, RetryPolicy
from private_agent_core.llm.gateway import ModelGateway
from private_agent_core.runtime import CancellationToken

from .connections import ModelConfig
from .direct_models import ConfiguredModels
from .model_errors import MODEL_ERROR_MESSAGES, CloudError
from .model_transport import MODEL_ACCOUNTING, BoundedTransport


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
                 "native_tool_calls": True, "supports_streaming": p.supports_streaming, "supports_structured_output": True,
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
        return await self._complete(profile, request)

    async def complete_stream(self, profile, request, *, on_delta):
        return await self._complete(profile, request, on_delta=on_delta)

    async def _complete(self, profile, request, *, on_delta=None):
        p = self.profile
        accounting = MODEL_ACCOUNTING.get()
        if accounting is not None:
            accounting.update(tracked=True, protocol=p.model_protocol)
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
            parsed = ModelRequest.model_validate(request)
            if on_delta is None or not p.supports_streaming:
                result = await gateway.complete(parsed, cancellation=CancellationToken())
            else:
                result = await gateway.complete_stream(parsed, cancellation=CancellationToken(), on_delta=on_delta)
            response = result.model_dump(mode="json")
            response["usage"] = result.usage.model_dump(mode="json", exclude_unset=True)
            response["transport_metrics"] = {"protocol": p.model_protocol, "provider_requests": 1,
                                             "provider_retries": 0, "missing_reason": None}
            # 旧供应商未返回 usage 时适配器会填零；不能据此伪造已计量的零占用。
            if not result.usage.input_tokens:
                response["usage"] = {}
            return response
        except ModelGatewayError as error:
            if error.code == "invalid_response" and isinstance(error.__cause__, ValueError) and "ended without" in str(error.__cause__):
                raise CloudError(502, "模型响应中断", code="model_stream_interrupted") from None
            raise CloudError(502, MODEL_ERROR_MESSAGES.get(error.code, "本地模型请求失败"), code=f"model_{error.code}") from None

    async def close(self):
        await self.client.aclose()



def model_service(profile: ModelConfig, *, secrets=None):
    # 旧启动参数仅做格式校验，执行统一读取本机模型目录。
    return ConfiguredModels(secrets=secrets)
