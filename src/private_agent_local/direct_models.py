"""用户电脑直连模型供应商，本机会话仅用于目录授权。"""
from __future__ import annotations

import asyncio
import hmac
import json
import sqlite3
from pathlib import Path

import httpx

from private_agent_core.contracts import ModelRequest, ModelResponse
from private_agent_core.llm.adapters import (
    ClaudeMessagesAdapter,
    OllamaChatAdapter,
    OpenAIChatAdapter,
)
from private_agent_core.llm.contracts import ModelGatewayError, RetryPolicy
from private_agent_core.llm.gateway import ModelGateway
from private_agent_core.llm.responses import OpenAIResponsesAdapter
from private_agent_core.model_metadata import (
    discover_model_metadata,
    ollama_show_metadata,
)
from private_agent_core.model_probe import run_probe
from private_agent_core.runtime import CancellationToken

from .identity import LOCAL_OWNER_ID
from .model_catalog import (
    DiscoveryInput,
    ModelCatalog,
    ModelParameters,
    endpoint_url,
    valid_format,
)
from .model_errors import MODEL_ERROR_MESSAGES, CloudError
from .model_evaluation import verify_evaluation
from .model_transport import MODEL_ACCOUNTING, BoundedTransport
from .secret_filter import SecretFilter


class ConfiguredModels:
    local_inference = True

    async def identity(self, token: str) -> dict:
        self.authorized(token)
        return {"id": LOCAL_OWNER_ID}

    def __init__(self, *, model_transport=None, secrets=None):
        limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
        self.model_client = httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False,
            headers={"Accept-Encoding": "identity"}, transport=BoundedTransport(model_transport or httpx.AsyncHTTPTransport(limits=limits)))
        self.catalog: ModelCatalog | None = None
        self.token = ""
        self.secrets: dict[str, str] = dict(secrets or {})
        self.secret_filter = SecretFilter(lambda: (*self.secrets.values(), self.token))
        self.probes: dict[str, asyncio.Task] = {}
        self.limit = asyncio.Semaphore(8)
        self.evaluation_binding = None

    async def bind_models(self, directory: Path, scope: str, token: str):
        await self.release_models()
        self.catalog = ModelCatalog(directory / "model-settings.sqlite3", scope)
        self.token = token

    async def release_models(self):
        tasks = list(self.probes.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.probes.clear()
        if self.catalog:
            self.catalog.close()
            self.catalog = None
        self.token = ""
        self.evaluation_binding = None

    def authorized(self, token: str) -> ModelCatalog:
        if not self.catalog or not hmac.compare_digest(self.token, token):
            raise CloudError(401, "本机模型目录尚未就绪，请重新连接", code="local_identity_required")
        return self.catalog

    def provider_output(self, token: str, provider: dict) -> dict:
        catalog = self.authorized(token)
        return {**provider, "api_key_configured": bool(self.secrets.get(catalog.reference(provider["id"])["reference"]))}

    def set_secret(self, token: str, provider_id: str, secret: str):
        catalog = self.authorized(token)
        if not secret.strip() or len(secret) > 16_384 or any(char in secret for char in "\r\n\0"):
            raise ValueError("模型密钥为空、过长或含无效字符")
        self.secrets[catalog.reference(provider_id)["reference"]] = secret.strip()

    def clear_secret(self, token: str, provider_id: str):
        catalog = self.authorized(token)
        self.secrets.pop(catalog.reference(provider_id)["reference"], None)

    async def profiles(self, token: str) -> list[dict]:
        return self.profile_list(token, enabled_only=True)

    def profile_list(self, token: str, enabled_only=False) -> list[dict]:
        catalog = self.authorized(token)
        parameters = ModelParameters.model_validate(catalog.data["parameters"])
        profiles = catalog.profiles(enabled_only)
        for profile in profiles:
            provider = catalog.data["providers"].get(profile.get("provider_id"), {})
            profile["api_format"] = provider.get("api_format")
            profile["endpoint"] = provider.get("base_url")
            if profile["provider"] == "ollama" and profile["context_tokens"] is not None:
                # 上下文预算必须与实际发给 Ollama 的 num_ctx 保持一致。
                profile["context_tokens"] = min(profile["context_tokens"], parameters.llm_context_length)
        return profiles

    def selection(self, token: str, identifier: str | None) -> tuple[dict, dict, str]:
        catalog = self.authorized(token)
        profiles = self.profile_list(token, enabled_only=True)
        matches = [p for p in profiles if (p["id"] == identifier if identifier else p["is_default"])]
        if len(matches) != 1:
            raise CloudError(422, "请在此电脑的模型设置中添加并启用模型；旧服务器密钥需重新保存", code="model_not_configured")
        selected = matches[0]
        try:
            provider = catalog.provider(selected["provider_id"])
            matches = [model for model in provider["models"] if model.get("profile_id") == selected["id"]]
            if (provider["enabled"] is not True or provider["protocol"] != selected["provider"] or len(matches) != 1
                    or matches[0]["model_id"] != selected["model_name"] or not valid_format(provider["protocol"], provider["api_format"])):
                raise ValueError
            endpoint_url(provider["base_url"], provider["protocol"])
        except (KeyError, TypeError, ValueError):
            raise CloudError(422, "模型与供应商配置不一致，请重新保存本机配置", code="model_invalid_configuration") from None
        secret = self.secrets.get(catalog.reference(provider["id"])["reference"], "")
        return selected, dict(provider), secret

    async def describe(self, token, profile):
        verify_evaluation(self, token, profile)
        selected, provider, secret = self.selection(token, profile)
        return {"profile": selected, "route": "direct_provider",
                "model_version": selected.get("model_version"), "version_source": "unknown", "protocol": provider["protocol"],
                "version_unknown_reason": "provider_configuration_has_no_immutable_version",
                "provider": {"id": provider["id"], "protocol": provider["protocol"], "endpoint": provider["base_url"]},
                "parameters": ModelParameters.model_validate(self.authorized(token).data["parameters"]).model_dump(),
                "declared_max_output_tokens": next(m.get("max_output_tokens") for m in provider["models"] if m["profile_id"] == selected["id"]),
                "request_budget_protocol": "direct-1.0", "max_provider_attempts": 1,
                "credential_state": "ready" if secret or selected["is_local"] else "missing",
                "stream_selection": "stream" if selected["supports_streaming"] else "complete_before_request",
                "proxy_capabilities": {}, "capability_source": "declared_not_inference_verified"}

    async def complete(self, token, profile, request):
        return await self._complete(token, profile, request)

    async def compact_context(self, token, profile, request):
        # 与主任务使用同一认证和模型路由；摘要请求不具备工具执行能力。
        if request.get("tools"):
            raise ValueError("摘要请求不能包含工具")
        return await self._complete(token, profile, request)

    async def complete_stream(self, token, profile, request, *, on_delta):
        return await self._complete(token, profile, request, on_delta=on_delta)

    async def complete_stream_messages(self, token, profile, request, *, on_delta, on_message_delta):
        return await self._complete(token, profile, request, on_delta=on_delta, on_message_delta=on_message_delta)

    def _safe_request(self, request: ModelRequest) -> ModelRequest:
        messages = []
        for message in request.messages:
            content = self.secret_filter.redact_text(message.content)
            calls = tuple(call.model_copy(update={"arguments": self.secret_filter.redact_value(call.arguments)})
                          for call in message.tool_calls)
            state = message.provider_state
            if state is not None:
                try:
                    # 只更新公开文本和工具参数，供应商不透明推理内容保持原样。
                    state = state.model_copy(update={"output_json": self.secret_filter.redact_provider_output(state.output_json)})
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                    raise CloudError(422, "模型续接内容无法安全过滤，请开启新会话", code="model_sensitive_context") from None
            messages.append(message.model_copy(update={"content": content, "tool_calls": calls, "provider_state": state}))
        return request.model_copy(update={"messages": tuple(messages)})

    async def _complete(self, token, profile, request, *, on_delta=None, on_message_delta=None):
        accounting = MODEL_ACCOUNTING.get()
        if accounting is not None:
            accounting["tracked"] = True
        verify_evaluation(self, token, profile)
        selected, provider, secret = self.selection(token, profile)
        if accounting is not None:
            accounting["protocol"] = provider["protocol"]
        if request.get("tools") and not selected["native_tool_calls"]:
            raise CloudError(422, "模型未声明原生工具能力", code="model_unsupported_capability")
        if request.get("reasoning_effort") and (provider["protocol"] != "openai" or request["reasoning_effort"] not in (selected.get("reasoning_efforts") or [])):
            raise CloudError(422, "当前直连适配器不支持所选推理参数", code="model_unsupported_capability")
        if request.get("output_format") and not selected["supports_structured_output"]:
            raise CloudError(422, "模型未声明结构化输出能力", code="model_unsupported_capability")
        parameters = ModelParameters.model_validate(self.authorized(token).data["parameters"])
        protocol = provider["protocol"]
        endpoint_url(provider["base_url"], protocol)
        common = {"base_url": provider["base_url"], "model": selected["model_name"], "client": self.model_client,
                  "temperature": parameters.llm_temperature}
        if protocol == "ollama":
            if selected["context_tokens"] is None:
                raise CloudError(422, "请在模型设置中填写 Ollama 上下文容量", code="model_not_configured")
            adapter = OllamaChatAdapter(**common, context_length=min(selected["context_tokens"], parameters.llm_context_length))
        elif protocol == "claude":
            adapter = ClaudeMessagesAdapter(**common, api_key=secret)
        else:
            adapter_type = OpenAIResponsesAdapter if provider["api_format"] == "responses" else OpenAIChatAdapter
            adapter = adapter_type(**common, api_key=secret, require_api_key=not selected["is_local"],
                                   allow_http=selected["is_local"], allow_private_network=selected["is_local"])
        gateway = ModelGateway(adapter, request_timeout_seconds=180, retry_policy=RetryPolicy(max_attempts=1))
        try:
            parsed = self._safe_request(ModelRequest.model_validate(request))
            async with asyncio.timeout(190), self.limit:
                if on_delta is None or not selected["supports_streaming"]:
                    result = await gateway.complete(parsed, cancellation=CancellationToken())
                else:
                    result = await gateway.complete_stream(parsed, cancellation=CancellationToken(), on_delta=on_delta,
                                                           on_message_delta=on_message_delta)
            response = result.model_dump(mode="json")
            response["usage"] = result.usage.model_dump(mode="json", exclude_unset=True)
            response["model_profile_id"] = selected["id"]
            response["transport_metrics"] = {"protocol": protocol, "provider_requests": 1, "provider_retries": 0, "missing_reason": None}
            if not result.usage.input_tokens:
                response["usage"] = {}
            return response
        except ModelGatewayError as error:
            code = error.code
            cause = error.__cause__
            if isinstance(cause, (httpx.ReadError, httpx.RemoteProtocolError)):
                code = "stream_interrupted"
            elif code == "invalid_response" and not isinstance(cause, json.JSONDecodeError) and isinstance(cause, (ValueError, TypeError, KeyError)):
                # 已识别的完整性错误属于断流；其余已解析 JSON 的结构错误属于协议错误。
                code = "stream_interrupted" if "ended without" in str(cause) else "protocol_error"
            raise CloudError(502, MODEL_ERROR_MESSAGES.get(code, "本机模型请求失败"), code=f"model_{code}") from None
        except TimeoutError:
            raise CloudError(504, "模型服务响应超时，请稍后重试", code="model_timeout") from None

    async def discover(self, token: str, data: DiscoveryInput) -> list[dict]:
        catalog = self.authorized(token)
        base_url = endpoint_url(data.base_url, data.protocol)
        secret = data.api_key.get_secret_value().strip() if data.api_key else ""
        if data.provider_id and not secret:
            saved = catalog.provider(data.provider_id)
            if saved["base_url"] != base_url or saved["protocol"] != data.protocol:
                raise ValueError("地址或协议已修改，请重新输入该地址的密钥后获取模型")
            reference = catalog.reference(data.provider_id)["reference"]
            if data.credential_reference and data.credential_reference != reference:
                raise ValueError("模型凭据不属于当前供应商")
            secret = self.secrets.get(reference, "")
        if any(char in secret for char in "\r\n\0"):
            raise ValueError("模型密钥含无效字符")
        headers = {"Accept": "application/json"}
        if data.protocol == "claude":
            headers.update({"x-api-key": secret, "anthropic-version": "2023-06-01"})
        elif secret:
            headers["Authorization"] = f"Bearer {secret}"
        if not secret and data.protocol != "ollama" and httpx.URL(base_url).host not in {"localhost", "127.0.0.1", "::1"}:
            raise CloudError(422, "请在此电脑输入并保存 API Key", code="model_missing_api_key")
        path = "/api/tags" if data.protocol == "ollama" else "/models"
        try:
            async with asyncio.timeout(30), self.limit:
                response = await self.model_client.get(base_url + path, headers=headers, timeout=15)
                response.raise_for_status()
                models = discover_model_metadata(response.json(), base_url=base_url, protocol=data.protocol)
                if not models or len(models) > 1000:
                    raise ValueError
                if data.protocol == "ollama":
                    semaphore = asyncio.Semaphore(6)

                    async def enrich(model):
                        async with semaphore:
                            try:
                                result = await self.model_client.post(base_url + "/api/show", json={"model": model.model_id, "verbose": False}, timeout=5)
                                result.raise_for_status()
                                return ollama_show_metadata(model.model_id, result.json()) or model
                            except (httpx.HTTPError, ValueError, ModelGatewayError):
                                return model

                    models = list(await asyncio.gather(*(enrich(model) for model in models[:256]))) + models[256:]
                return [model.as_dict() for model in models]
        except httpx.HTTPStatusError as error:
            code = {401: "unauthorized", 403: "unauthorized", 429: "rate_limited", 404: "model_not_found"}.get(error.response.status_code, "provider_error")
            raise CloudError(502, MODEL_ERROR_MESSAGES[code], code=f"model_{code}") from None
        except (httpx.HTTPError, TimeoutError, ValueError, ModelGatewayError):
            raise CloudError(502, "本机无法读取模型列表，请检查地址、网络和接口协议", code="model_discovery_failed") from None

    async def cancel_probes(self):
        tasks = list(self.probes.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def start_probe(self, token: str, profile: str):
        catalog = self.authorized(token)
        selected, provider, _ = self.selection(token, profile)
        if profile in self.probes or len(self.probes) >= 2:
            raise CloudError(409, "已有模型能力探测正在运行，请稍后重试", code="probe_running")
        pending = {"status": "running", "error_code": None, "pass_count": 0, "sample_count": 0,
                   "results": None, "requirements": None, "probed_at": None}
        catalog.data["probes"][profile] = pending
        catalog.save()
        service = self

        class Client:
            async def complete(self, request):
                response = await service.complete(token, profile, request.model_dump(mode="json"))
                return ModelResponse.model_validate({key: value for key, value in response.items() if key in ModelResponse.model_fields})

        async def probe():
            try:
                async with asyncio.timeout(180):
                    snapshot = await run_probe(Client(), provider=provider["protocol"], model_name=selected["model_name"])
                pending.update(status="ok" if snapshot.passed else "failed", error_code=None if snapshot.passed else "probe_not_passed",
                               pass_count=snapshot.pass_count, sample_count=snapshot.sample_count, results=snapshot.results,
                               requirements=snapshot.requirements.model_dump(), probed_at=snapshot.probed_at.isoformat())
            except asyncio.CancelledError:
                pending.update(status="failed", error_code="probe_interrupted")
                raise
            except (CloudError, ValueError, TimeoutError):
                pending.update(status="failed", error_code="model_probe_failed")
            finally:
                try:
                    catalog.save()
                except sqlite3.Error:
                    # 通过查询接口报告持久化失败，不能留下永久“运行中”的后台任务。
                    pending.update(status="failed", error_code="probe_storage_failed")
                    catalog.data["probes"][profile] = pending
                finally:
                    self.probes.pop(profile, None)

        self.probes[profile] = asyncio.create_task(probe())

    async def close(self):
        try:
            await self.release_models()
        finally:
            self.secrets.clear()
            await self.model_client.aclose()
