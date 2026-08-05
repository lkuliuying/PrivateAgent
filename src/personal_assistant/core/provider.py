"""Provider 抽象：封装 LLM 与 Embedding。

第一阶段只实现 Ollama（经 langchain-ollama 集成）。
后续可在此抽象下扩展 OpenAI / Claude 兼容实现，而不改动上层 chat / rag 编排。
"""
from __future__ import annotations

import importlib
import json
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..config import settings
from ..llm.sse import iter_sse_events
from ..logging_setup import get_logger

logger = get_logger(__name__)


class ProviderError(RuntimeError):
    """Provider 调用失败。error_code 为第七阶段 M6 失败分类。"""

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


# 第七阶段 M6 失败分类（对齐 docs/phase7-requirements.md §5.6）
PROVIDER_ERROR_CODES = (
    "missing_api_key",
    "unauthorized",
    "network_error",
    "timeout",
    "rate_limited",
    "model_not_found",
    "provider_error",
)


def classify_error(
    exc: Exception, *, provider_type: str = "", api_key: str = ""
) -> str:
    """把异常映射到 M6 失败分类。已带 error_code 的 ProviderError 直接沿用。"""
    if isinstance(exc, ProviderError) and exc.error_code:
        return exc.error_code
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "network_error"
    if isinstance(exc, httpx.HTTPStatusError):
        resp = getattr(exc, "response", None)
        sc = getattr(resp, "status_code", 0) or 0
        if sc in (401, 403):
            return "unauthorized"
        if sc == 429:
            return "rate_limited"
        if sc == 404:
            return "model_not_found"
        if 500 <= sc < 600:
            return "provider_error"
    msg = str(exc).lower()
    if not api_key and ("key" in msg or "unauthorized" in msg):
        return "missing_api_key"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "unauthorized" in msg or " 401" in msg or " 403" in msg:
        return "unauthorized"
    if "rate" in msg and "limit" in msg:
        return "rate_limited"
    if "not found" in msg or " 404" in msg or "model" in msg and "not" in msg:
        return "model_not_found"
    if "connection" in msg or "network" in msg or "connect" in msg or "refused" in msg:
        return "network_error"
    return "provider_error"


@lru_cache(maxsize=1)
def _load_ollama_components() -> tuple[type[Any], type[Any]]:
    """按需加载 Ollama 客户端，避免可选网络依赖阻断后端启动。

    ``langchain_ollama`` 导入时会初始化 ``ollama`` 客户端。若系统设置了
    SOCKS 代理但未安装 ``socksio``，顶层导入会让整个 FastAPI 应用在尚未
    使用模型前就启动失败。惰性加载将故障隔离到真正的 Ollama 调用，并保留
    ProviderError 的统一错误分类。
    """
    try:
        module = importlib.import_module("langchain_ollama")
        return module.ChatOllama, module.OllamaEmbeddings
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(
            f"Ollama 客户端加载失败: {exc}",
            error_code=classify_error(exc, provider_type="ollama"),
        ) from exc


def _ollama_error(action: str, exc: Exception) -> ProviderError:
    return ProviderError(
        f"Ollama {action} 失败: {exc}",
        error_code=classify_error(exc, provider_type="ollama"),
    )


def _to_lc_messages(messages: list[dict[str, str]]) -> list[Any]:
    """把 [{"role","content"}] 转为 LangChain 消息对象。"""
    out: list[Any] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


async def _iter_remote_sse(
    client: httpx.AsyncClient | None,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> AsyncIterator[tuple[str | None, str]]:
    async def consume(active_client: httpx.AsyncClient) -> AsyncIterator[tuple[str | None, str]]:
        async with active_client.stream(
            "POST",
            url,
            headers=headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for event in iter_sse_events(response.aiter_lines()):
                yield event

    if client is not None:
        async for event in consume(client):
            yield event
        return
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as active_client:
        async for event in consume(active_client):
            yield event


class OllamaProvider:
    """Ollama LLM + Embedding 封装。

    LLM 流式输出为 async generator，供 SSE 路由逐 token 消费。
    """

    def __init__(
        self,
        base_url: str | None = None,
        llm_model: str | None = None,
        embed_model: str | None = None,
        temperature: float | None = None,
        context_length: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.llm_model = llm_model or settings.llm_model
        self.embed_model = embed_model or settings.embed_model
        self.temperature = (
            temperature if temperature is not None else settings.llm_temperature
        )
        self.context_length = context_length or settings.llm_context_length
        self._embedding_client: Any | None = None

    # ---------------- LLM ----------------
    def _chat_llm(self) -> Any:
        # client_kwargs.timeout 限制每次 HTTP 读写，避免 Ollama 连接但卡住时
        # ainvoke/astream 无限挂起（ollama 客户端默认 timeout=None）。
        chat_ollama, _ = _load_ollama_components()
        return chat_ollama(
            model=self.llm_model,
            base_url=self.base_url,
            temperature=self.temperature,
            num_ctx=self.context_length,
            client_kwargs={"timeout": httpx.Timeout(60.0)},
        )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """非流式对话。"""
        try:
            llm = self._chat_llm()
            resp = await llm.ainvoke(_to_lc_messages(messages))
            content = resp.content
            return content if isinstance(content, str) else str(content)
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _ollama_error("chat", e) from e

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """流式对话，逐 token 产出字符串片段。"""
        try:
            llm = self._chat_llm()
            async for chunk in llm.astream(_to_lc_messages(messages)):
                content = chunk.content
                if isinstance(content, str) and content:
                    yield content
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _ollama_error("流式对话", e) from e

    # ---------------- Embedding ----------------
    def _embedder(self) -> Any:
        if self._embedding_client is None:
            _, ollama_embeddings = _load_ollama_components()
            self._embedding_client = ollama_embeddings(
                model=self.embed_model,
                base_url=self.base_url,
                client_kwargs={"timeout": httpx.Timeout(60.0)},
            )
        return self._embedding_client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return await self._embedder().aembed_documents(texts)
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _ollama_error("embedding", e) from e

    async def embed_one(self, text: str) -> list[float]:
        try:
            return await self._embedder().aembed_query(text)
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _ollama_error("embedding", e) from e

    # ---------------- 健康 ----------------
    async def health(self) -> dict[str, Any]:
        """检查 Ollama 服务连通性与模型可用性。

        超时 3s（第八阶段 M6 热点优化）：Ollama 离线/慢响应时不再阻塞诊断快照与
        /health 轮询 5s；3s 内无响应即视为不可用，足够本地探测。
        """
        result: dict[str, Any] = {"ok": False, "base_url": self.base_url}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                if r.status_code != 200:
                    result["error"] = f"Ollama /api/tags 返回 {r.status_code}"
                    return result
                data = r.json()
                models = {m.get("name", "") for m in data.get("models", [])}
                result["models"] = sorted(models)
                result["llm_model_available"] = self._model_available(models, self.llm_model)
                result["embed_model_available"] = self._model_available(
                    models, self.embed_model
                )
                result["ok"] = True
        except Exception as e:  # noqa: BLE001
            result["error"] = f"无法连接 Ollama: {e}"
        return result

    @staticmethod
    def _model_available(available: set[str], wanted: str) -> bool:
        if not wanted:
            return False
        if wanted in available:
            return True
        # 兼容 :latest 等后缀差异
        wanted_base = wanted.split(":")[0]
        return any(m.split(":")[0] == wanted_base for m in available)


class OpenAICompatibleProvider:
    """OpenAI-compatible chat provider using raw HTTP.

    Embeddings intentionally fall back to Ollama elsewhere unless a later phase
    adds an OpenAI embedding model selector.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise ProviderError(
                "OpenAI-compatible Provider 未配置 API key",
                error_code="missing_api_key",
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
                return str(data["choices"][0]["message"]["content"])
        except Exception as e:  # noqa: BLE001
            code = classify_error(e, provider_type="openai", api_key=self.api_key)
            raise ProviderError(
                f"OpenAI-compatible chat 失败: {e}", error_code=code
            ) from e

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not self.api_key:
            raise ProviderError(
                "OpenAI-compatible Provider 未配置 API key",
                error_code="missing_api_key",
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        terminal = False
        output_chars = 0
        try:
            async for _event_name, raw_data in _iter_remote_sse(
                self._client,
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                payload=payload,
            ):
                if raw_data == "[DONE]":
                    terminal = True
                    break
                data = json.loads(raw_data)
                if not isinstance(data, dict):
                    raise TypeError("OpenAI stream event must be a JSON object")
                if data.get("error"):
                    raise ProviderError(
                        "OpenAI-compatible Provider 返回流式错误",
                        error_code="provider_error",
                    )
                choices = data.get("choices") or []
                if not isinstance(choices, list):
                    raise TypeError("OpenAI stream choices must be a list")
                for choice in choices:
                    if not isinstance(choice, dict):
                        raise TypeError("OpenAI stream choice must be an object")
                    if int(choice.get("index") or 0) != 0:
                        continue
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        raise TypeError("OpenAI stream delta must be an object")
                    content = delta.get("content")
                    if content is not None and not isinstance(content, str):
                        raise TypeError("OpenAI stream text delta must be a string")
                    if content:
                        output_chars += len(content)
                        if output_chars > 8_388_608:
                            raise ValueError(
                                "OpenAI stream output exceeds the configured limit"
                            )
                        yield content
            if not terminal:
                raise ValueError("OpenAI stream ended without a [DONE] event")
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            code = classify_error(e, provider_type="openai", api_key=self.api_key)
            raise ProviderError(
                f"OpenAI-compatible 流式对话失败: {e}", error_code=code
            ) from e

    async def health(self) -> dict[str, Any]:
        result = {
            "ok": False,
            "base_url": self.base_url,
            "model": self.model,
            "privacy_scope": "chat messages and selected context",
        }
        if not self.api_key:
            result["error"] = "未配置 API key"
            return result
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
                result["ok"] = r.status_code < 500
                result["status_code"] = r.status_code
        except Exception as e:  # noqa: BLE001
            result["error"] = f"无法连接 OpenAI-compatible Provider: {e}"
        return result


class ClaudeProvider:
    """Anthropic Claude messages provider using raw HTTP."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.base_url = "https://api.anthropic.com/v1"
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    @staticmethod
    def _convert_messages(messages: list[dict[str, str]]) -> tuple[str | None, list[dict]]:
        system_parts: list[str] = []
        out: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                out.append({"role": "assistant", "content": content})
            else:
                out.append({"role": "user", "content": content})
        return ("\n\n".join(system_parts) or None), out

    async def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise ProviderError(
                "Claude Provider 未配置 API key", error_code="missing_api_key"
            )
        system, converted = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": converted,
            "max_tokens": 4096,
            "temperature": self.temperature,
        }
        if system:
            payload["system"] = system
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self.base_url}/messages", headers=self._headers(), json=payload
                )
                r.raise_for_status()
                data = r.json()
                parts = data.get("content") or []
                return "".join(
                    str(p.get("text", "")) for p in parts if p.get("type") == "text"
                )
        except Exception as e:  # noqa: BLE001
            code = classify_error(e, provider_type="claude", api_key=self.api_key)
            raise ProviderError(f"Claude chat 失败: {e}", error_code=code) from e

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not self.api_key:
            raise ProviderError(
                "Claude Provider 未配置 API key", error_code="missing_api_key"
            )
        system, converted = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": converted,
            "max_tokens": 4096,
            "temperature": self.temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system
        started = False
        terminal = False
        output_chars = 0
        try:
            async for event_name, raw_data in _iter_remote_sse(
                self._client,
                f"{self.base_url}/messages",
                headers=self._headers(),
                payload=payload,
            ):
                data = json.loads(raw_data)
                if not isinstance(data, dict):
                    raise TypeError("Claude stream event must be a JSON object")
                data_type = data.get("type")
                if not isinstance(data_type, str):
                    raise TypeError("Claude stream event type must be a string")
                if event_name and event_name != data_type:
                    raise ValueError(
                        "Claude SSE event name does not match its data type"
                    )
                if data_type == "error":
                    error = data.get("error") or {}
                    error_type = error.get("type") if isinstance(error, dict) else None
                    code = {
                        "rate_limit_error": "rate_limited",
                        "authentication_error": "unauthorized",
                        "not_found_error": "model_not_found",
                    }.get(str(error_type), "provider_error")
                    raise ProviderError(
                        "Claude Provider 返回流式错误", error_code=code
                    )
                if data_type == "message_start":
                    if started:
                        raise ValueError(
                            "Claude stream contains duplicate message_start"
                        )
                    started = True
                elif data_type == "content_block_delta":
                    delta = data.get("delta") or {}
                    if not isinstance(delta, dict):
                        raise TypeError("Claude content delta must be an object")
                    if delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if not isinstance(text, str):
                            raise TypeError("Claude text delta must be a string")
                        if text:
                            output_chars += len(text)
                            if output_chars > 8_388_608:
                                raise ValueError(
                                    "Claude stream output exceeds the configured limit"
                                )
                            yield text
                    # Thinking/signature/tool input deltas are not user-visible text.
                elif data_type == "message_stop":
                    terminal = True
                    break
                # ping, block lifecycle and future event types do not contain visible text.
            if not started or not terminal:
                raise ValueError(
                    "Claude stream ended without a complete message lifecycle"
                )
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            code = classify_error(e, provider_type="claude", api_key=self.api_key)
            raise ProviderError(f"Claude 流式对话失败: {e}", error_code=code) from e

    async def health(self) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "model": self.model, "error": "未配置 API key"}
        return {
            "ok": True,
            "model": self.model,
            "privacy_scope": "chat messages and selected context",
            "note": "Claude Provider 使用真实调用时会在聊天接口验证。",
        }


class ProviderRouter:
    """Resolve configured LLM provider while keeping Ollama as the safe default."""

    def __init__(self, settings: dict[str, str]) -> None:
        self.settings = settings

    def privacy_scope(self) -> dict[str, Any]:
        provider_type = self.settings.get("provider_type", "ollama")
        remote_enabled = (
            self.settings.get("remote_provider_enabled", "false").lower() == "true"
        )
        return {
            "provider_type": provider_type,
            "remote_provider_enabled": remote_enabled,
            "sends": (
                []
                if provider_type == "ollama" or not remote_enabled
                else ["system prompt", "recent chat messages", "selected RAG/memory context"]
            ),
        }

    def chat_provider(self) -> Any:
        provider_type = self.settings.get("provider_type", "ollama")
        remote_enabled = (
            self.settings.get("remote_provider_enabled", "false").lower() == "true"
        )
        temperature = float(self.settings.get("llm_temperature", settings.llm_temperature))
        if provider_type == "openai" and remote_enabled:
            return OpenAICompatibleProvider(
                base_url=self.settings.get("openai_base_url") or "https://api.openai.com/v1",
                api_key=self.settings.get("openai_api_key") or "",
                model=self.settings.get("openai_model") or "gpt-4o-mini",
                temperature=temperature,
            )
        if provider_type == "claude" and remote_enabled:
            return ClaudeProvider(
                api_key=self.settings.get("claude_api_key") or "",
                model=self.settings.get("claude_model") or "claude-3-5-sonnet-latest",
                temperature=temperature,
            )
        return OllamaProvider(
            llm_model=self.settings.get("llm_model") or settings.llm_model,
            temperature=temperature,
            context_length=int(
                self.settings.get("llm_context_length", settings.llm_context_length)
            ),
        )

    def model_gateway(self) -> Any:
        """Build the typed Agent Runtime gateway without changing legacy callers.

        The existing ``chat_provider`` remains the compatibility path until the
        chat API is moved behind AgentRuntime.
        """
        from ..llm import (
            ClaudeMessagesAdapter,
            ModelGateway,
            OllamaChatAdapter,
            OpenAIChatAdapter,
        )

        provider_type = self.settings.get("provider_type", "ollama")
        remote_enabled = (
            self.settings.get("remote_provider_enabled", "false").lower() == "true"
        )
        temperature = float(
            self.settings.get("llm_temperature", settings.llm_temperature)
        )
        if provider_type == "openai" and remote_enabled:
            return ModelGateway(
                OpenAIChatAdapter(
                    base_url=self.settings.get("openai_base_url")
                    or "https://api.openai.com/v1",
                    api_key=self.settings.get("openai_api_key") or "",
                    model=self.settings.get("openai_model") or "gpt-4o-mini",
                    temperature=temperature,
                )
            )
        if provider_type == "claude" and remote_enabled:
            return ModelGateway(
                ClaudeMessagesAdapter(
                    api_key=self.settings.get("claude_api_key") or "",
                    model=self.settings.get("claude_model")
                    or "claude-3-5-sonnet-latest",
                    temperature=temperature,
                )
            )
        return ModelGateway(
            OllamaChatAdapter(
                base_url=settings.ollama_base_url,
                model=self.settings.get("llm_model") or settings.llm_model,
                temperature=temperature,
                context_length=int(
                    self.settings.get(
                        "llm_context_length",
                        settings.llm_context_length,
                    )
                ),
            )
        )

    def embedding_provider(self) -> OllamaProvider:
        return OllamaProvider(embed_model=self.settings.get("embed_model") or settings.embed_model)

    def fallback_provider(self) -> OllamaProvider:
        """远程 Provider 失败时回退到的本地 Ollama Provider（M6 降级）。"""
        return OllamaProvider(
            llm_model=self.settings.get("llm_model") or settings.llm_model,
            temperature=float(
                self.settings.get("llm_temperature", settings.llm_temperature)
            ),
            context_length=int(
                self.settings.get("llm_context_length", settings.llm_context_length)
            ),
        )
