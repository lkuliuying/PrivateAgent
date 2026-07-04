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
        return ChatOllama(
            model=self.llm_model,
            base_url=self.base_url,
            temperature=self.temperature,
            num_ctx=self.context_length,
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
        return OllamaEmbeddings(model=self.embed_model, base_url=self.base_url)

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
