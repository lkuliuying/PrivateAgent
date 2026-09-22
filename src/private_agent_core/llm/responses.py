"""Responses 原生文本、工具与推理续接；公开增量和不透明状态严格分离。"""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import aclosing

from private_agent_core.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderState,
    ToolCall,
)

from .adapters import OpenAIChatAdapter, _parse_arguments, _reported_usage
from .contracts import ModelGatewayError, ModelTextDelta

MAX_OUTPUT_BYTES = 1_500_000


def _encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _string(value, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        raise ValueError(f"Responses 的 {field} 无效")
    return value


def _output(items: object) -> tuple[str, tuple[ToolCall, ...], str | None]:
    """仅解释公开文本与函数调用，推理条目原样留给供应商。"""
    if not isinstance(items, list) or not 1 <= len(items) <= 128:
        raise ValueError("Responses 输出条目数量无效")
    if len(_encode(items).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("Responses 输出超过大小限制")
    text, final_text, calls, phase, ids = [], [], [], None, set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Responses 输出条目必须为对象")
        identifier = _string(item.get("id"), "output.id")
        if identifier in ids:
            raise ValueError("Responses 输出条目标识重复")
        ids.add(identifier)
        kind = item.get("type")
        if kind == "reasoning":
            if item.get("status") not in {None, "completed"}:
                raise ValueError("Responses 推理条目未完整结束")
            _string(item.get("encrypted_content"), "reasoning.encrypted_content")
        elif kind == "message":
            if item.get("role") != "assistant" or item.get("status") not in {None, "completed"}:
                raise ValueError("Responses 助手消息未完整结束")
            item_phase = item.get("phase")
            if item_phase not in {None, "commentary", "final_answer"}:
                raise ValueError("Responses 消息阶段无效")
            if item_phase is not None:
                phase = "final_answer" if phase == "final_answer" else item_phase
            content = item.get("content")
            if not isinstance(content, list):
                raise ValueError("Responses 消息内容无效")
            for part in content:
                if not isinstance(part, dict):
                    raise ValueError("Responses 消息内容块无效")
                if part.get("type") == "output_text":
                    value = _string(part.get("text"), "output_text.text", empty=True)
                elif part.get("type") == "refusal":
                    value = _string(part.get("refusal"), "refusal.refusal")
                else:
                    raise ValueError("当前 Responses 适配器不支持此输出内容块")
                text.append(value)
                if item_phase == "final_answer":
                    final_text.append(value)
        elif kind == "function_call":
            if item.get("status") not in {None, "completed"}:
                raise ValueError("Responses 函数调用未完整结束")
            calls.append(ToolCall(id=_string(item.get("call_id"), "function_call.call_id"),
                                  name=_string(item.get("name"), "function_call.name"),
                                  arguments=_parse_arguments(_string(item.get("arguments"), "function_call.arguments"))))
        else:
            # 没有注册的托管工具不具备本机权限和执行证据，不能视为已成功执行。
            raise ValueError("当前 Responses 适配器不支持此输出类型")
    if not text and not calls:
        raise ValueError("Responses 没有公开正文或工具调用")
    return "".join(final_text if phase == "final_answer" else text), tuple(calls), phase


class OpenAIResponsesAdapter(OpenAIChatAdapter):
    provider_name = "openai_responses"

    def _route(self) -> str:
        # 不保存密钥；更换端点、模型或凭据后不会发送旧路由的不透明状态。
        return hashlib.sha256(_encode([self.base_url, self.model_name, self.api_key]).encode()).hexdigest()

    def _input(self, request: ModelRequest) -> list[dict]:
        result = []
        for message in request.messages:
            state = message.provider_state
            if state is not None and state.route == self._route():
                items = json.loads(state.output_json)
                text, calls, phase = _output(items)
                if (text, calls, phase) != (message.content, message.tool_calls, message.phase):
                    raise ValueError("Responses 续接状态与公开消息不一致")
                result.extend(items)
                continue
            if message.role == "tool":
                result.append({"type": "function_call_output", "call_id": message.tool_call_id, "output": message.content})
                continue
            if message.content:
                item = {"role": message.role, "content": message.content}
                if message.phase is not None:
                    item["phase"] = message.phase
                result.append(item)
            for call in message.tool_calls:
                result.append({"type": "function_call", "call_id": call.id, "name": call.name,
                               "arguments": _encode(call.arguments)})
        return result

    def _payload(self, request: ModelRequest, *, streaming: bool) -> dict:
        if self.require_api_key and not self.api_key:
            raise ModelGatewayError("Responses 未配置 API Key", code="missing_api_key", provider=self.provider_name)
        payload = {"model": self.model_name, "input": self._input(request), "stream": streaming,
                   "store": False, "include": ["reasoning.encrypted_content"]}
        if request.reasoning_effort:
            payload["reasoning"] = {"effort": request.reasoning_effort}
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.tools:
            payload["tools"] = [{"type": "function", "name": tool.name, "description": tool.description,
                                 "parameters": tool.input_schema, "strict": self.strict_tools} for tool in request.tools]
            payload["tool_choice"] = "auto"
        if request.output_format is not None:
            output = request.output_format
            payload["text"] = {"format": {"type": "json_schema", "name": output.name,
                                           "schema": output.json_schema, "strict": output.strict}}
            if output.description is not None:
                payload["text"]["format"]["description"] = output.description
        return payload

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}

    def _response(self, data: object) -> ModelResponse:
        if not isinstance(data, dict):
            raise ValueError("Responses 响应必须为对象")
        if data.get("status") != "completed" or data.get("error") is not None:
            raise ModelGatewayError("模型响应未完整结束，未执行其工具请求", code="incomplete_response", provider=self.provider_name)
        text, calls, phase = _output(data.get("output"))
        usage = data.get("usage") or {}
        if not isinstance(usage, dict) or not isinstance(usage.get("input_tokens_details") or {}, dict):
            raise ValueError("Responses 用量格式无效")
        response = ModelResponse(text=text, tool_calls=calls, phase=phase, finish_reason="completed",
            usage=_reported_usage(input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                                  cached_tokens=(usage.get("input_tokens_details") or {}).get("cached_tokens")),
            model=_string(data.get("model"), "model"), provider=self.provider_name,
            request_id=_string(data.get("id"), "id"),
            provider_state=ProviderState(route=self._route(), output_json=_encode(data["output"])))
        response.require_complete()
        return response

    async def complete(self, request, *, cancellation):
        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        response = await self._post(f"{self.base_url}/responses", headers=self._headers(), payload=self._payload(request, streaming=False))
        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        return self._response(response.json())

    async def complete_stream(self, request, *, cancellation, on_delta):
        return await self._complete_stream(request, cancellation=cancellation, on_delta=on_delta)

    async def complete_stream_messages(self, request, *, cancellation, on_delta, on_message_delta):
        return await self._complete_stream(request, cancellation=cancellation, on_delta=on_delta,
                                           on_message_delta=on_message_delta)

    async def _complete_stream(self, request, *, cancellation, on_delta, on_message_delta=None):
        if cancellation.is_cancelled:
            raise asyncio.CancelledError
        payload = self._payload(request, streaming=True)
        parts, emitted, final_items, size, count, response_id = [], [], set(), 0, 0, None
        messages, message_parts = {}, {}
        async with aclosing(self._stream_sse(f"{self.base_url}/responses", headers=self._headers(), payload=payload)) as events:
            async for event_name, raw in events:
                if cancellation.is_cancelled:
                    raise asyncio.CancelledError
                count += 1
                if count > 20000:
                    raise ValueError("Responses 流事件数量超过限制")
                event = json.loads(raw)
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    raise ValueError("Responses 流事件格式无效")
                kind = event["type"]
                if event_name is not None and event_name != kind:
                    raise ValueError("Responses 流事件类型不一致")
                if kind == "response.created":
                    if not isinstance(event.get("response"), dict):
                        raise ValueError("Responses 流响应元数据无效")
                    identifier = _string(event["response"].get("id"), "response.id")
                    if response_id is not None:
                        raise ValueError("Responses 流重复开始")
                    response_id = identifier
                elif kind == "response.output_item.added":
                    item = event.get("item")
                    if not isinstance(item, dict):
                        raise ValueError("Responses 流输出条目无效")
                    if item.get("type") == "message":
                        identifier = _string(item.get("id"), "output.id")
                        phase = item.get("phase")
                        ModelTextDelta(identifier, phase, "")
                        if item.get("role") != "assistant" or identifier in messages or len(messages) >= 128:
                            raise ValueError("Responses 流消息身份无效")
                        messages[identifier] = phase
                        if phase == "final_answer":
                            final_items.add(identifier)
                elif kind in {"response.output_text.delta", "response.refusal.delta"}:
                    delta = _string(event.get("delta"), "delta", empty=True)
                    size += len(delta.encode("utf-8"))
                    if size > MAX_OUTPUT_BYTES:
                        raise ValueError("Responses 公开增量超过限制")
                    parts.append(delta)
                    identifier = event.get("item_id")
                    if on_message_delta is not None:
                        if identifier not in messages:
                            raise ValueError("Responses 公开增量缺少已登记消息")
                        message_parts.setdefault(identifier, []).append(delta)
                        if delta:
                            await on_message_delta(ModelTextDelta(identifier, messages[identifier], delta))
                    # 旧文本回调只包含最终选中的正文；过程说明通过独立消息回调公开。
                    if delta and event.get("item_id") in final_items:
                        emitted.append(delta)
                        await on_delta(delta)
                elif kind == "response.completed":
                    result = self._response(event.get("response"))
                    if response_id is not None and result.request_id != response_id:
                        raise ValueError("Responses 流响应标识不一致")
                    public_text = "".join(part.get("text", part.get("refusal", ""))
                        for item in event["response"]["output"] if item["type"] == "message" for part in item["content"])
                    if parts and "".join(parts) != public_text:
                        raise ValueError("Responses 流正文与最终响应不一致")
                    if emitted and "".join(emitted) != result.text:
                        raise ValueError("Responses 流最终答案与完整响应不一致")
                    if on_message_delta is not None:
                        completed_messages = {item["id"]: item for item in event["response"]["output"] if item["type"] == "message"}
                        if any(identifier not in completed_messages for identifier in messages):
                            raise ValueError("Responses 公开消息未出现在完整响应中")
                        for identifier, item in completed_messages.items():
                            text = "".join(part.get("text", part.get("refusal", "")) for part in item["content"])
                            if identifier in messages and messages[identifier] != item.get("phase"):
                                raise ValueError("Responses 公开消息阶段前后不一致")
                            if identifier in message_parts:
                                if "".join(message_parts[identifier]) != text:
                                    raise ValueError("Responses 公开消息增量与完整响应不一致")
                            elif text:
                                await on_message_delta(ModelTextDelta(identifier, item.get("phase"), text))
                    if not emitted and result.text:
                        await on_delta(result.text)
                    return result
                elif kind in {"response.failed", "response.incomplete", "error"}:
                    raise ModelGatewayError("模型响应未完整结束，未执行其工具请求", code="incomplete_response", provider=self.provider_name)
                # 工具参数和推理增量不进入公开正文，只有完整终态中的工具才交给执行器。
        raise ValueError("Responses stream ended without response.completed")
