"""Provider 抽象：封装 LLM 与 Embedding。

第一阶段只实现 Ollama（经 langchain-ollama 集成）。
后续可在此抽象下扩展 OpenAI / Claude 兼容实现，而不改动上层 chat / rag 编排。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama, OllamaEmbeddings

from ..config import settings
from ..logging_setup import get_logger

logger = get_logger(__name__)


class ProviderError(RuntimeError):
    """Provider 调用失败。"""


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

    # ---------------- LLM ----------------
    def _chat_llm(self) -> ChatOllama:
        # client_kwargs.timeout 限制每次 HTTP 读写，避免 Ollama 连接但卡住时
        # ainvoke/astream 无限挂起（ollama 客户端默认 timeout=None）。
        return ChatOllama(
            model=self.llm_model,
            base_url=self.base_url,
            temperature=self.temperature,
            num_ctx=self.context_length,
            client_kwargs={"timeout": httpx.Timeout(60.0)},
        )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """非流式对话。"""
        llm = self._chat_llm()
        try:
            resp = await llm.ainvoke(_to_lc_messages(messages))
            content = resp.content
            return content if isinstance(content, str) else str(content)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"Ollama chat 失败: {e}") from e

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """流式对话，逐 token 产出字符串片段。"""
        llm = self._chat_llm()
        try:
            async for chunk in llm.astream(_to_lc_messages(messages)):
                content = chunk.content
                if isinstance(content, str) and content:
                    yield content
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"Ollama 流式对话失败: {e}") from e

    # ---------------- Embedding ----------------
    def _embedder(self) -> OllamaEmbeddings:
        return OllamaEmbeddings(
            model=self.embed_model,
            base_url=self.base_url,
            client_kwargs={"timeout": httpx.Timeout(60.0)},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return await self._embedder().aembed_documents(texts)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"Ollama embedding 失败: {e}") from e

    async def embed_one(self, text: str) -> list[float]:
        try:
            return await self._embedder().aembed_query(text)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"Ollama embedding 失败: {e}") from e

    # ---------------- 健康 ----------------
    async def health(self) -> dict[str, Any]:
        """检查 Ollama 服务连通性与模型可用性。"""
        result: dict[str, Any] = {"ok": False, "base_url": self.base_url}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
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
    ) -> None:
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(self, messages: list[dict[str, str]]) -> str:
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
            raise ProviderError(f"OpenAI-compatible chat 失败: {e}") from e

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield await self.chat(messages)

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
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.base_url = "https://api.anthropic.com/v1"

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
            raise ProviderError(f"Claude chat 失败: {e}") from e

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield await self.chat(messages)

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

    def embedding_provider(self) -> OllamaProvider:
        return OllamaProvider(embed_model=self.settings.get("embed_model") or settings.embed_model)
