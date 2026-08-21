"""Native tool-call adapters for Ollama, OpenAI Chat Completions and Claude."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

import httpx

from personal_assistant.agents.contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
)
from personal_assistant.agents.runtime import CancellationToken

from .contracts import ModelCapabilities, ModelGatewayError
from .sse import iter_sse_events
from .url_policy import validate_remote_base_url


def _tool_definitions_openai(
    request: ModelRequest, *, strict: bool
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in request.tools:
        function: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }
        if strict:
            function["strict"] = True
        tools.append({"type": "function", "function": function})
    return tools


def _openai_response_format(request: ModelRequest) -> dict[str, Any] | None:
    output = request.output_format
    if output is None:
        return None
    json_schema: dict[str, Any] = {
        "name": output.name,
        "schema": output.json_schema,
        "strict": output.strict,
    }
    if output.description is not None:
        json_schema["description"] = output.description
    return {
        "type": "json_schema",
        "json_schema": json_schema,
    }


def _parse_arguments(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("模型工具参数必须是 JSON object")


def _openai_messages(messages: tuple[ModelMessage, ...]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant" and message.tool_calls:
            converted.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
        elif message.role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
        else:
            converted.append({"role": message.role, "content": message.content})
    return converted


class _HttpAdapter:
    _MAX_SSE_LINE_CHARS = 1_048_576
    _MAX_SSE_EVENT_CHARS = 2_097_152

    def __init__(self, client: httpx.AsyncClient | None) -> None:
        self._client = client

    async def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        if self._client is not None:
            response = await self._client.post(url, headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(
                timeout=60.0, follow_redirects=False
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response

    async def _stream_lines(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> AsyncIterator[str]:
        if self._client is not None:
            async with self._client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    yield line
            return

        async with (
            httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client,
            client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                yield line

    async def _stream_sse(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> AsyncIterator[tuple[str | None, str]]:
        async for event in iter_sse_events(
            self._stream_lines(
                url,
                headers=headers,
                payload=payload,
            ),
            max_line_chars=self._MAX_SSE_LINE_CHARS,
            max_event_chars=self._MAX_SSE_EVENT_CHARS,
        ):
            yield event


class OpenAIChatAdapter(_HttpAdapter):
    provider_name = "openai_compatible"
    _MAX_STREAM_OUTPUT_CHARS = 8_388_608
    _MAX_STREAM_TOOL_ARGUMENT_CHARS = 1_048_576
    _MAX_STREAM_TOOL_CALLS = 128

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        strict_tools: bool = True,
        require_api_key: bool = True,
        allow_http: bool = False,
        allow_private_network: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client)
        self.base_url = validate_remote_base_url(
            base_url or "https://api.openai.com/v1",
            allow_http=allow_http,
            allow_private_network=allow_private_network,
        )
        self.api_key = api_key
        self.model_name = model
        self.temperature = temperature
        self.strict_tools = strict_tools
        self.require_api_key = require_api_key
        self.capabilities = ModelCapabilities(
            streaming=True,
            native_tool_calls=True,
            structured_output=True,
            usage_reporting=True,
            cancellation=True,
        )

    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> ModelResponse:
        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        if self.require_api_key and not self.api_key:
            raise ModelGatewayError(
                "OpenAI-compatible provider 未配置 API key",
                code="missing_api_key",
                provider=self.provider_name,
            )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": _openai_messages(request.messages),
            "temperature": self.temperature,
            "stream": False,
        }
        # v0.7.0 验收修复（P0-1）：OpenAI 系请求体透传 reasoning_effort
        if request.reasoning_effort:
            payload["reasoning_effort"] = request.reasoning_effort
        if request.tools:
            payload["tools"] = _tool_definitions_openai(
                request,
                strict=self.strict_tools,
            )
            payload["tool_choice"] = "auto"
        response_format = _openai_response_format(request)
        if response_format is not None:
            payload["response_format"] = response_format
        response = await self._post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            payload=payload,
        )
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
        calls = tuple(
            ToolCall(
                id=str(item["id"]),
                name=str(item["function"]["name"]),
                arguments=_parse_arguments(item["function"].get("arguments", "{}")),
            )
            for item in (message.get("tool_calls") or [])
        )
        usage = data.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        return ModelResponse(
            text=str(message.get("content") or ""),
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=TokenUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                cached_tokens=int(prompt_details.get("cached_tokens") or 0),
            ),
            provider=self.provider_name,
            model=str(data.get("model") or self.model_name),
            request_id=str(data.get("id")) if data.get("id") else None,
        )

    async def complete_stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        """Consume OpenAI Chat Completions SSE text and tool-call deltas."""

        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        if self.require_api_key and not self.api_key:
            raise ModelGatewayError(
                "OpenAI-compatible provider 未配置 API key",
                code="missing_api_key",
                provider=self.provider_name,
            )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": _openai_messages(request.messages),
            "temperature": self.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # v0.7.0 验收修复（P0-1）：OpenAI 系请求体透传 reasoning_effort
        if request.reasoning_effort:
            payload["reasoning_effort"] = request.reasoning_effort
        if request.tools:
            payload["tools"] = _tool_definitions_openai(
                request,
                strict=self.strict_tools,
            )
            payload["tool_choice"] = "auto"
        response_format = _openai_response_format(request)
        if response_format is not None:
            payload["response_format"] = response_format

        text_parts: list[str] = []
        text_length = 0
        raw_calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        finish_reason: str | None = None
        request_id: str | None = None
        response_model = self.model_name
        terminal = False

        async for _event_name, raw_data in self._stream_sse(
            f"{self.base_url}/chat/completions",
            headers=headers,
            payload=payload,
        ):
            if cancellation.is_cancelled:
                raise asyncio.CancelledError
            if raw_data == "[DONE]":
                terminal = True
                break
            data = json.loads(raw_data)
            if not isinstance(data, dict):
                raise TypeError("OpenAI stream event must be a JSON object")
            if data.get("error"):
                raise ModelGatewayError(
                    "OpenAI-compatible provider returned a stream error",
                    code="provider_rejected_request",
                    provider=self.provider_name,
                )
            if data.get("id"):
                request_id = str(data["id"])
            if data.get("model"):
                response_model = str(data["model"])
            if data.get("usage") is not None:
                if not isinstance(data["usage"], dict):
                    raise TypeError("OpenAI stream usage must be an object")
                usage = data["usage"]
            choices = data.get("choices") or []
            if not isinstance(choices, list):
                raise TypeError("OpenAI stream choices must be a list")
            for choice in choices:
                if not isinstance(choice, dict):
                    raise TypeError("OpenAI stream choice must be an object")
                if int(choice.get("index") or 0) != 0:
                    continue
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice["finish_reason"])
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    raise TypeError("OpenAI stream delta must be an object")
                content = delta.get("content")
                if content is not None and not isinstance(content, str):
                    raise TypeError("OpenAI stream text delta must be a string")
                if content:
                    text_length += len(content)
                    if text_length > self._MAX_STREAM_OUTPUT_CHARS:
                        raise ValueError(
                            "OpenAI stream output exceeds the configured limit"
                        )
                    text_parts.append(content)
                    await on_delta(content)
                tool_deltas = delta.get("tool_calls") or []
                if not isinstance(tool_deltas, list):
                    raise TypeError("OpenAI stream tool_calls must be a list")
                for item in tool_deltas:
                    if not isinstance(item, dict):
                        raise TypeError("OpenAI stream tool call must be an object")
                    index = int(item.get("index") or 0)
                    if index < 0 or index >= self._MAX_STREAM_TOOL_CALLS:
                        raise ValueError("OpenAI stream tool call index is invalid")
                    call = raw_calls.setdefault(
                        index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if item.get("id"):
                        streamed_id = str(item["id"])
                        if not call["id"]:
                            call["id"] = streamed_id
                        elif call["id"] != streamed_id:
                            call["id"] += streamed_id
                    function = item.get("function") or {}
                    if not isinstance(function, dict):
                        raise TypeError("OpenAI stream tool function must be an object")
                    if function.get("name"):
                        streamed_name = str(function["name"])
                        if not call["name"]:
                            call["name"] = streamed_name
                        elif call["name"] != streamed_name:
                            call["name"] += streamed_name
                    arguments = function.get("arguments")
                    if arguments is not None and not isinstance(arguments, str):
                        raise TypeError(
                            "OpenAI stream tool arguments delta must be a string"
                        )
                    if arguments:
                        call["arguments"] += arguments
                        if (
                            len(call["arguments"])
                            > self._MAX_STREAM_TOOL_ARGUMENT_CHARS
                        ):
                            raise ValueError(
                                "OpenAI stream tool arguments exceed the configured limit"
                            )

        if not terminal:
            raise ValueError("OpenAI stream ended without a [DONE] event")
        calls = tuple(
            ToolCall(
                id=call["id"] or f"openai-{index}-{uuid4().hex}",
                name=call["name"],
                arguments=_parse_arguments(call["arguments"] or "{}"),
            )
            for index, call in sorted(raw_calls.items())
        )
        prompt_details = usage.get("prompt_tokens_details") or {}
        if not isinstance(prompt_details, dict):
            raise TypeError("OpenAI stream prompt token details must be an object")
        return ModelResponse(
            text="".join(text_parts),
            tool_calls=calls,
            finish_reason=finish_reason,
            usage=TokenUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                cached_tokens=int(prompt_details.get("cached_tokens") or 0),
            ),
            provider=self.provider_name,
            model=response_model,
            request_id=request_id,
        )


def _ollama_messages(messages: tuple[ModelMessage, ...]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "assistant" and message.tool_calls:
            item["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in message.tool_calls
            ]
        elif message.role == "tool":
            item.pop("tool_call_id", None)
            item["tool_name"] = message.name
        converted.append(item)
    return converted


class OllamaChatAdapter(_HttpAdapter):
    provider_name = "ollama"

    _MAX_STREAM_LINE_CHARS = 1_048_576
    _MAX_STREAM_OUTPUT_CHARS = 8_388_608

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        context_length: int = 8_192,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client)
        parsed = httpx.URL(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.host:
            raise ValueError("Ollama base_url 必须是有效的 HTTP(S) URL")
        self.base_url = str(parsed).rstrip("/")
        self.model_name = model
        self.temperature = temperature
        self.context_length = context_length
        self.capabilities = ModelCapabilities(
            streaming=True,
            native_tool_calls=True,
            structured_output=True,
            usage_reporting=True,
            cancellation=True,
            max_context_tokens=context_length,
        )

    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> ModelResponse:
        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": _ollama_messages(request.messages),
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_length,
            },
        }
        if request.tools:
            payload["tools"] = _tool_definitions_openai(request, strict=False)
        if request.output_format is not None:
            payload["format"] = request.output_format.json_schema
        response = await self._post(
            f"{self.base_url}/api/chat",
            headers={"Content-Type": "application/json"},
            payload=payload,
        )
        data = response.json()
        message = data["message"]
        calls: list[ToolCall] = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item["function"]
            calls.append(
                ToolCall(
                    id=str(item.get("id") or f"ollama-{index}-{uuid4().hex}"),
                    name=str(function["name"]),
                    arguments=_parse_arguments(function.get("arguments", {})),
                )
            )
        return ModelResponse(
            text=str(message.get("content") or ""),
            tool_calls=tuple(calls),
            finish_reason=data.get("done_reason"),
            usage=TokenUsage(
                input_tokens=int(data.get("prompt_eval_count") or 0),
                output_tokens=int(data.get("eval_count") or 0),
            ),
            provider=self.provider_name,
            model=str(data.get("model") or self.model_name),
        )

    async def complete_stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        """Consume Ollama's NDJSON stream while retaining a complete response."""

        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": _ollama_messages(request.messages),
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_length,
            },
        }
        if request.tools:
            payload["tools"] = _tool_definitions_openai(request, strict=False)
        if request.output_format is not None:
            payload["format"] = request.output_format.json_schema

        text_parts: list[str] = []
        text_length = 0
        raw_calls: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None
        async for line in self._stream_lines(
            f"{self.base_url}/api/chat",
            headers={"Content-Type": "application/json"},
            payload=payload,
        ):
            if cancellation.is_cancelled:
                raise asyncio.CancelledError
            if not line:
                continue
            if len(line) > self._MAX_STREAM_LINE_CHARS:
                raise ValueError("Ollama stream frame exceeds the configured limit")
            data = json.loads(line)
            if not isinstance(data, dict):
                raise TypeError("Ollama stream frame must be a JSON object")
            if data.get("error"):
                raise ModelGatewayError(
                    "Ollama provider returned an error",
                    code="provider_rejected_request",
                    provider=self.provider_name,
                )
            message = data.get("message") or {}
            if not isinstance(message, dict):
                raise TypeError("Ollama stream message must be a JSON object")
            delta = str(message.get("content") or "")
            if delta:
                text_length += len(delta)
                if text_length > self._MAX_STREAM_OUTPUT_CHARS:
                    raise ValueError(
                        "Ollama stream output exceeds the configured limit"
                    )
                text_parts.append(delta)
                await on_delta(delta)
            chunk_calls = message.get("tool_calls") or []
            if not isinstance(chunk_calls, list):
                raise TypeError("Ollama stream tool_calls must be a list")
            raw_calls.extend(chunk_calls)
            final = data

        if final is None or final.get("done") is not True:
            raise ValueError("Ollama stream ended without a terminal frame")

        calls: list[ToolCall] = []
        for index, item in enumerate(raw_calls):
            function = item["function"]
            calls.append(
                ToolCall(
                    id=str(item.get("id") or f"ollama-{index}-{uuid4().hex}"),
                    name=str(function["name"]),
                    arguments=_parse_arguments(function.get("arguments", {})),
                )
            )
        return ModelResponse(
            text="".join(text_parts),
            tool_calls=tuple(calls),
            finish_reason=final.get("done_reason"),
            usage=TokenUsage(
                input_tokens=int(final.get("prompt_eval_count") or 0),
                output_tokens=int(final.get("eval_count") or 0),
            ),
            provider=self.provider_name,
            model=str(final.get("model") or self.model_name),
        )


def _tool_result_is_error(content: str) -> bool:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and data.get("success") is False


def _claude_messages(
    messages: tuple[ModelMessage, ...],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "system":
            system_parts.append(message.content)
            index += 1
            continue
        if message.role == "tool":
            blocks: list[dict[str, Any]] = []
            while index < len(messages) and messages[index].role == "tool":
                tool_message = messages[index]
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_message.tool_call_id,
                        "content": tool_message.content,
                        "is_error": _tool_result_is_error(tool_message.content),
                    }
                )
                index += 1
            converted.append({"role": "user", "content": blocks})
            continue
        if message.role == "assistant" and message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            content.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
                for call in message.tool_calls
            )
            converted.append({"role": "assistant", "content": content})
        else:
            converted.append({"role": message.role, "content": message.content})
        index += 1
    return "\n\n".join(system_parts) or None, converted


class ClaudeMessagesAdapter(_HttpAdapter):
    provider_name = "claude"
    _MAX_STREAM_OUTPUT_CHARS = 8_388_608
    _MAX_STREAM_TOOL_ARGUMENT_CHARS = 1_048_576
    _MAX_STREAM_BLOCKS = 128

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com/v1",
        temperature: float = 0.7,
        max_output_tokens: int = 4_096,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client)
        self.base_url = validate_remote_base_url(base_url)
        self.api_key = api_key
        self.model_name = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.capabilities = ModelCapabilities(
            streaming=True,
            native_tool_calls=True,
            structured_output=True,
            usage_reporting=True,
            cancellation=True,
        )

    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> ModelResponse:
        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        if not self.api_key:
            raise ModelGatewayError(
                "Claude provider 未配置 API key",
                code="missing_api_key",
                provider=self.provider_name,
            )
        system, messages = _claude_messages(request.messages)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_output_tokens,
            "temperature": self.temperature,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = {"type": "auto"}
        if request.output_format is not None:
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": request.output_format.json_schema,
                }
            }
        response = await self._post(
            f"{self.base_url}/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
        )
        data = response.json()
        blocks = data.get("content") or []
        text = "".join(
            str(block.get("text") or "")
            for block in blocks
            if block.get("type") == "text"
        )
        calls = tuple(
            ToolCall(
                id=str(block["id"]),
                name=str(block["name"]),
                arguments=_parse_arguments(block.get("input", {})),
            )
            for block in blocks
            if block.get("type") == "tool_use"
        )
        usage = data.get("usage") or {}
        return ModelResponse(
            text=text,
            tool_calls=calls,
            finish_reason=data.get("stop_reason"),
            usage=TokenUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cached_tokens=int(usage.get("cache_read_input_tokens") or 0),
            ),
            provider=self.provider_name,
            model=str(data.get("model") or self.model_name),
            request_id=response.headers.get("request-id") or data.get("id"),
        )

    async def complete_stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        """Consume Anthropic Messages SSE without exposing thinking deltas."""

        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        if not self.api_key:
            raise ModelGatewayError(
                "Claude provider 未配置 API key",
                code="missing_api_key",
                provider=self.provider_name,
            )
        system, messages = _claude_messages(request.messages)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = {"type": "auto"}
        if request.output_format is not None:
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": request.output_format.json_schema,
                }
            }

        text_parts: list[str] = []
        text_length = 0
        blocks: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        finish_reason: str | None = None
        request_id: str | None = None
        response_model = self.model_name
        started = False
        terminal = False

        async for event_name, raw_data in self._stream_sse(
            f"{self.base_url}/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
        ):
            if cancellation.is_cancelled:
                raise asyncio.CancelledError
            data = json.loads(raw_data)
            if not isinstance(data, dict):
                raise TypeError("Claude stream event must be a JSON object")
            data_type = data.get("type")
            if not isinstance(data_type, str):
                raise TypeError("Claude stream event type must be a string")
            if event_name and event_name != data_type:
                raise ValueError("Claude SSE event name does not match its data type")
            if data_type == "error":
                error = data.get("error") or {}
                error_type = error.get("type") if isinstance(error, dict) else None
                code = {
                    "overloaded_error": "provider_unavailable",
                    "rate_limit_error": "rate_limited",
                    "authentication_error": "unauthorized",
                    "not_found_error": "model_not_found",
                }.get(str(error_type), "provider_rejected_request")
                raise ModelGatewayError(
                    "Claude provider returned a stream error",
                    code=code,
                    provider=self.provider_name,
                )
            if data_type == "message_start":
                if started:
                    raise ValueError("Claude stream contains duplicate message_start")
                message = data.get("message") or {}
                if not isinstance(message, dict):
                    raise TypeError("Claude message_start message must be an object")
                started = True
                if message.get("id"):
                    request_id = str(message["id"])
                if message.get("model"):
                    response_model = str(message["model"])
                start_usage = message.get("usage") or {}
                if not isinstance(start_usage, dict):
                    raise TypeError("Claude message_start usage must be an object")
                usage.update(start_usage)
                continue
            if data_type == "content_block_start":
                index = int(data.get("index") or 0)
                if index < 0 or index >= self._MAX_STREAM_BLOCKS or index in blocks:
                    raise ValueError("Claude content block index is invalid")
                content_block = data.get("content_block") or {}
                if not isinstance(content_block, dict):
                    raise TypeError("Claude content block must be an object")
                block_type = content_block.get("type")
                if not isinstance(block_type, str):
                    raise TypeError("Claude content block type must be a string")
                blocks[index] = {
                    "type": block_type,
                    "id": str(content_block.get("id") or ""),
                    "name": str(content_block.get("name") or ""),
                    "input": content_block.get("input") or {},
                    "partial_json": "",
                    "stopped": False,
                }
                initial_text = content_block.get("text")
                if block_type == "text" and initial_text:
                    if not isinstance(initial_text, str):
                        raise TypeError("Claude initial text must be a string")
                    text_length += len(initial_text)
                    if text_length > self._MAX_STREAM_OUTPUT_CHARS:
                        raise ValueError(
                            "Claude stream output exceeds the configured limit"
                        )
                    text_parts.append(initial_text)
                    await on_delta(initial_text)
                continue
            if data_type == "content_block_delta":
                index = int(data.get("index") or 0)
                block = blocks.get(index)
                if block is None or block["stopped"]:
                    raise ValueError("Claude delta refers to an inactive content block")
                delta = data.get("delta") or {}
                if not isinstance(delta, dict):
                    raise TypeError("Claude content delta must be an object")
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    text = delta.get("text")
                    if not isinstance(text, str):
                        raise TypeError("Claude text delta must be a string")
                    if text:
                        text_length += len(text)
                        if text_length > self._MAX_STREAM_OUTPUT_CHARS:
                            raise ValueError(
                                "Claude stream output exceeds the configured limit"
                            )
                        text_parts.append(text)
                        await on_delta(text)
                elif delta_type == "input_json_delta":
                    if block["type"] != "tool_use":
                        raise ValueError(
                            "Claude input JSON delta belongs to a non-tool block"
                        )
                    partial = delta.get("partial_json")
                    if not isinstance(partial, str):
                        raise TypeError("Claude tool input delta must be a string")
                    block["partial_json"] += partial
                    if (
                        len(block["partial_json"])
                        > self._MAX_STREAM_TOOL_ARGUMENT_CHARS
                    ):
                        raise ValueError(
                            "Claude stream tool input exceeds the configured limit"
                        )
                # Thinking/signature and future delta types are deliberately not exposed.
                continue
            if data_type == "content_block_stop":
                index = int(data.get("index") or 0)
                block = blocks.get(index)
                if block is None or block["stopped"]:
                    raise ValueError("Claude stop refers to an inactive content block")
                block["stopped"] = True
                continue
            if data_type == "message_delta":
                delta = data.get("delta") or {}
                if not isinstance(delta, dict):
                    raise TypeError("Claude message delta must be an object")
                if delta.get("stop_reason") is not None:
                    finish_reason = str(delta["stop_reason"])
                delta_usage = data.get("usage") or {}
                if not isinstance(delta_usage, dict):
                    raise TypeError("Claude message delta usage must be an object")
                usage.update(delta_usage)
                continue
            if data_type == "message_stop":
                terminal = True
                break
            # ping and future event types are ignored per Anthropic's versioning policy.

        if not started or not terminal:
            raise ValueError("Claude stream ended without a complete message lifecycle")
        if any(not block["stopped"] for block in blocks.values()):
            raise ValueError("Claude stream ended with an open content block")
        calls: list[ToolCall] = []
        for index, block in sorted(blocks.items()):
            if block["type"] != "tool_use":
                continue
            partial_json = block["partial_json"]
            arguments = (
                _parse_arguments(partial_json)
                if partial_json
                else _parse_arguments(block["input"])
            )
            calls.append(
                ToolCall(
                    id=block["id"] or f"claude-{index}-{uuid4().hex}",
                    name=block["name"],
                    arguments=arguments,
                )
            )
        return ModelResponse(
            text="".join(text_parts),
            tool_calls=tuple(calls),
            finish_reason=finish_reason,
            usage=TokenUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cached_tokens=int(usage.get("cache_read_input_tokens") or 0),
            ),
            provider=self.provider_name,
            model=response_model,
            request_id=request_id,
        )
