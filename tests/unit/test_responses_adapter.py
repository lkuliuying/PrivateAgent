"""原生 Responses 的多轮状态、阶段、流终态与取消边界。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from private_agent_core.contracts import (
    AgentRunStatus,
    ModelMessage,
    ModelOutputFormat,
    ModelRequest,
)
from private_agent_core.llm.adapters import _openai_messages
from private_agent_core.llm.contracts import (
    ModelGatewayError,
    ModelTextDelta,
    RetryPolicy,
)
from private_agent_core.llm.gateway import ModelGateway
from private_agent_core.llm.responses import OpenAIResponsesAdapter
from private_agent_core.runtime import AgentRuntime, CancellationToken

OPAQUE = "fixture-encrypted-reasoning-state"
REQUEST = ModelRequest(messages=(ModelMessage(role="user", content="检查当前文件"),))


def adapter(client=None, **overrides):
    return OpenAIResponsesAdapter(**{"base_url": "https://provider.example.test/v1", "api_key": "fixture",
                                    "model": "fixture-model", "client": client, **overrides})


def reasoning(identifier="rs_1"):
    return {"type": "reasoning", "id": identifier, "summary": [], "encrypted_content": OPAQUE}


def message(text="完成", phase="final_answer", identifier="msg_1"):
    return {"type": "message", "id": identifier, "role": "assistant", "status": "completed", "phase": phase,
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def function(identifier="call_1", name="read", arguments="{}"):
    return {"type": "function_call", "id": "fc_" + identifier, "call_id": identifier,
            "name": name, "arguments": arguments, "status": "completed"}


def response(*items, **overrides):
    return {"id": "resp_1", "model": "fixture-model", "status": "completed", "error": None,
            "output": list(items), "usage": {"input_tokens": 123, "output_tokens": 8,
            "input_tokens_details": {"cached_tokens": 50}}, **overrides}


def sse(*events):
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events).encode()


@pytest.mark.asyncio
async def test_native_state_and_phase_roundtrip_over_actual_requests():
    received = []
    first = response(reasoning(), message("先检查文件", "commentary"), function())

    def upstream(request):
        assert request.url.path == "/v1/responses"
        received.append(json.loads(request.content))
        return httpx.Response(200, json=first if len(received) == 1 else response(message()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        model = adapter(client)
        result = await model.complete(REQUEST.model_copy(update={"reasoning_effort": "high", "max_output_tokens": 2048}), cancellation=CancellationToken())
        restored = ModelMessage.model_validate_json(result.as_message().model_dump_json())
        tool = ModelMessage(role="tool", name="read", tool_call_id="call_1", content='{"success":true}')
        await model.complete(ModelRequest(messages=(*REQUEST.messages, restored, tool)), cancellation=CancellationToken())
    assert received[0]["store"] is False
    assert received[0]["include"] == ["reasoning.encrypted_content"]
    assert received[0]["reasoning"] == {"effort": "high"}
    assert received[0]["max_output_tokens"] == 2048
    assert "temperature" not in received[0] and "previous_response_id" not in received[0]
    assert received[1]["input"][1:-1] == first["output"]
    assert received[1]["input"][-1] == {"type": "function_call_output", "call_id": "call_1", "output": tool.content}
    assert result.usage.cached_tokens == 50
    assert OPAQUE not in repr(result) and OPAQUE not in result.text


@pytest.mark.parametrize("change", [{"api_key": "other"}, {"model": "other"}, {"base_url": "https://other.example.test/v1"}])
def test_native_state_never_crosses_model_endpoint_or_credential(change):
    first = adapter()._response(response(reasoning(), message("检查", "commentary"), function()))
    request = ModelRequest(messages=(*REQUEST.messages, first.as_message()))
    payload = adapter(**change)._payload(request, streaming=False)
    assert OPAQUE not in json.dumps(payload)
    assert payload["input"][1]["phase"] == "commentary"
    assert payload["input"][2]["call_id"] == "call_1"
    assert OPAQUE not in json.dumps(_openai_messages(request.messages))


def test_tampered_native_state_fails_before_request():
    first = adapter()._response(response(reasoning(), message()))
    changed = first.as_message().model_copy(update={"content": "篡改后的正文"})
    with pytest.raises(ValueError, match="不一致"):
        adapter()._payload(ModelRequest(messages=(changed,)), streaming=False)


def test_structured_output_uses_responses_text_format():
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    request = REQUEST.model_copy(update={"output_format": ModelOutputFormat(name="result", json_schema=schema)})
    assert adapter()._payload(request, streaming=False)["text"]["format"] == {
        "type": "json_schema", "name": "result", "schema": schema, "strict": True}


@pytest.mark.parametrize("broken", [
    response(function(), status="incomplete"),
    response(function(), status="failed"),
    response(function(arguments="[1]")),
    response(function(arguments="{")),
    response(function(), function()),
    response({"type": "reasoning", "id": "rs", "summary": []}, function()),
    response({**reasoning(), "status": "in_progress"}, function()),
    response({"type": "web_search_call", "id": "web_1"}, message()),
    response(message(), function()),
    response(message(), error={"message": "fixture-upstream-sensitive-error"}),
])
def test_invalid_or_incomplete_output_cannot_be_a_tool_decision(broken):
    with pytest.raises((ValueError, ModelGatewayError)):
        adapter()._response(broken)


@pytest.mark.parametrize("events", [
    [{"type": "response.created", "response": []}],
    [{"type": "response.created", "response": {"id": "another"}}, {"type": "response.completed", "response": response(message())}],
    [{"type": "response.output_text.delta", "delta": "不同正文"}, {"type": "response.completed", "response": response(message())}],
    [{"type": "response.output_item.added", "item": []}],
])
@pytest.mark.asyncio
async def test_malformed_or_inconsistent_stream_is_rejected(events):
    async def receive(_):
        pass

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse(*events)))) as client:
        with pytest.raises(ValueError):
            await adapter(client).complete_stream(REQUEST, cancellation=CancellationToken(), on_delta=receive)


@pytest.mark.asyncio
async def test_stream_final_answer_excludes_commentary_and_reasoning():
    commentary, final = message("正在检查", "commentary", "msg_progress"), message("检查完成")
    events = [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.output_item.added", "item": commentary},
        {"type": "response.output_text.delta", "item_id": "msg_progress", "delta": "正在检查"},
        {"type": "response.reasoning_text.delta", "delta": "fixture-private-reasoning"},
        {"type": "response.output_item.added", "item": final},
        {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "检查完成"},
        {"type": "response.completed", "response": response(reasoning(), commentary, final)},
    ]
    deltas = []

    async def receive(delta):
        deltas.append(delta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse(*events)))) as client:
        result = await adapter(client).complete_stream(REQUEST, cancellation=CancellationToken(), on_delta=receive)
    assert deltas == ["检查完成"] and result.text == "检查完成" and result.phase == "final_answer"
    assert json.loads(result.provider_state.output_json) == [reasoning(), commentary, final]


@pytest.mark.asyncio
async def test_message_stream_publishes_commentary_before_terminal_and_preserves_legacy_text():
    gate = asyncio.Event()
    commentary, final = message("正在检查", "commentary", "msg_progress"), message("检查完成")

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse({"type": "response.output_item.added", "item": commentary},
                      {"type": "response.output_text.delta", "item_id": "msg_progress", "delta": "正在检查"},
                      {"type": "response.reasoning_text.delta", "delta": "不应公开的推理"})
            await gate.wait()
            yield sse({"type": "response.output_item.added", "item": final},
                      {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "检查完成"},
                      {"type": "response.completed", "response": response(reasoning(), commentary, final)})

    legacy, messages = [], []

    async def receive(delta):
        legacy.append(delta)

    async def receive_message(delta):
        messages.append(delta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream()))) as client:
        task = asyncio.create_task(adapter(client).complete_stream_messages(REQUEST, cancellation=CancellationToken(),
            on_delta=receive, on_message_delta=receive_message))
        try:
            for _ in range(100):
                if messages:
                    break
                await asyncio.sleep(.005)
            assert messages == [ModelTextDelta("msg_progress", "commentary", "正在检查")]
            assert not task.done() and legacy == []
            gate.set()
            result = await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert messages == [ModelTextDelta("msg_progress", "commentary", "正在检查"),
                        ModelTextDelta("msg_1", "final_answer", "检查完成")]
    assert "".join(legacy) == result.text == "检查完成"
    assert json.loads(result.provider_state.output_json) == [reasoning(), commentary, final]


@pytest.mark.parametrize("invalid", ["unknown_message", "changed_phase", "changed_message_text", "duplicate_message"])
@pytest.mark.asyncio
async def test_message_stream_rejects_inconsistent_message_identity(invalid):
    first = message("内容", "commentary")
    completed = response(first)
    events = [{"type": "response.output_item.added", "item": first}]
    if invalid == "duplicate_message":
        events.append(events[0])
    events.append({"type": "response.output_text.delta", "item_id": "unknown" if invalid == "unknown_message" else "msg_1", "delta": "内容"})
    if invalid == "changed_phase":
        completed = response(message("内容"))
    elif invalid == "changed_message_text":
        completed = response(message("", "commentary"), message("内容", "commentary", "msg_2"))
    events.append({"type": "response.completed", "response": completed})

    async def receive(_):
        pass

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse(*events)))) as client:
        with pytest.raises(ValueError):
            await adapter(client).complete_stream_messages(REQUEST, cancellation=CancellationToken(),
                on_delta=receive, on_message_delta=receive)


@pytest.mark.parametrize("ending", [None, "response.incomplete", "response.failed", "error"])
@pytest.mark.asyncio
async def test_stream_requires_complete_terminal_response(ending):
    events = [{"type": "response.output_item.done", "item": function()}]
    if ending:
        events.append({"type": ending, "response": response(function(), status="incomplete")})
    deltas = []

    async def receive(delta):
        deltas.append(delta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse(*events)))) as client:
        with pytest.raises((ValueError, ModelGatewayError)):
            await adapter(client).complete_stream(REQUEST, cancellation=CancellationToken(), on_delta=receive)
    assert deltas == []


@pytest.mark.asyncio
async def test_cancellation_closes_http_stream_without_retry():
    token, deltas, calls = CancellationToken(), [], []

    class Stream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield sse({"type": "response.output_item.added", "item": message()},
                      {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "完成"})
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = Stream()

    async def receive(delta):
        deltas.append(delta)
        token.cancel()

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        gateway = ModelGateway(adapter(client), retry_policy=RetryPolicy(max_attempts=1))
        runtime = AgentRuntime(gateway, None, model_output_sink=receive)
        result = await asyncio.wait_for(runtime.run(REQUEST.messages, cancellation=token), timeout=2)
    assert result.status == AgentRunStatus.CANCELLED
    assert stream.closed and len(calls) == 1 and deltas == ["完成"]
