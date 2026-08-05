from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from personal_assistant.agents import (
    AgentRunStatus,
    AgentRuntime,
    CancellationToken,
    ModelMessage,
    ModelOutputFormat,
    ModelRequest,
    ModelResponse,
    ModelToolDefinition,
    ToolCall,
    ToolResult,
)
from personal_assistant.core.provider import ProviderRouter
from personal_assistant.llm import (
    ClaudeMessagesAdapter,
    ModelCapabilities,
    ModelGateway,
    ModelGatewayError,
    OllamaChatAdapter,
    OpenAIChatAdapter,
    RetryPolicy,
)
from personal_assistant.llm.url_policy import (
    UnsafeModelEndpointError,
    validate_remote_base_url,
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def structured_output() -> ModelOutputFormat:
    return ModelOutputFormat(
        name="answer",
        description="Return a structured answer.",
        json_schema=OUTPUT_SCHEMA,
    )


def weather_tool() -> ModelToolDefinition:
    return ModelToolDefinition(
        name="weather",
        description="Return the weather for a city.",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    )


@pytest.mark.asyncio
async def test_openai_adapter_sends_and_parses_native_tool_calls():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "chatcmpl-1",
                "model": "example-model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "weather",
                                        "arguments": '{"city":"Shanghai"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 4,
                    "prompt_tokens_details": {"cached_tokens": 5},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIChatAdapter(
            base_url="https://api.openai.com/v1",
            api_key="secret",
            model="example-model",
            client=client,
        )
        response = await ModelGateway(
            adapter,
            retry_policy=RetryPolicy(max_attempts=1),
        ).complete(
            ModelRequest(
                messages=(ModelMessage(role="user", content="weather?"),),
                tools=(weather_tool(),),
                output_format=structured_output(),
            ),
            cancellation=CancellationToken(),
        )

    assert captured["tools"][0]["function"]["strict"] is True
    assert captured["tool_choice"] == "auto"
    assert captured["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "answer",
            "description": "Return a structured answer.",
            "schema": OUTPUT_SCHEMA,
            "strict": True,
        },
    }
    assert response.tool_calls == (
        ToolCall(id="call-1", name="weather", arguments={"city": "Shanghai"}),
    )
    assert response.usage.input_tokens == 15
    assert response.usage.cached_tokens == 5
    assert response.provider == "openai_compatible"
    assert response.request_id == "chatcmpl-1"
    assert response.latency_ms is not None


@pytest.mark.asyncio
async def test_openai_adapter_streams_sse_text_tools_and_usage():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        frames = [
            {
                "id": "chatcmpl-stream-1",
                "model": "example-stream-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "Checking "},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-stream-1",
                "model": "example-stream-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": "now.",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-stream-1",
                                    "type": "function",
                                    "function": {
                                        "name": "weather",
                                        "arguments": '{"city":"Shang',
                                    },
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-stream-1",
                "model": "example-stream-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": 'hai"}'},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
            {
                "id": "chatcmpl-stream-1",
                "model": "example-stream-model",
                "choices": [],
                "usage": {
                    "prompt_tokens": 18,
                    "completion_tokens": 9,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            },
        ]
        body = "".join(
            f"data: {json.dumps(frame, separators=(',', ':'))}\n\n"
            for frame in frames
        )
        body += "data: [DONE]\n\n"
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    deltas: list[str] = []

    async def record_delta(delta: str) -> None:
        deltas.append(delta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ModelGateway(
            OpenAIChatAdapter(
                base_url="https://api.openai.com/v1",
                api_key="secret",
                model="example-model",
                client=client,
            ),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        response = await gateway.complete_stream(
            ModelRequest(
                messages=(ModelMessage(role="user", content="weather?"),),
                tools=(weather_tool(),),
                output_format=structured_output(),
            ),
            cancellation=CancellationToken(),
            on_delta=record_delta,
        )

    assert captured["stream"] is True
    assert captured["stream_options"] == {"include_usage": True}
    assert captured["response_format"]["json_schema"]["schema"] == OUTPUT_SCHEMA
    assert gateway.capabilities.streaming is True
    assert deltas == ["Checking ", "now."]
    assert response.text == "Checking now."
    assert response.tool_calls == (
        ToolCall(
            id="call-stream-1",
            name="weather",
            arguments={"city": "Shanghai"},
        ),
    )
    assert response.finish_reason == "tool_calls"
    assert response.usage.input_tokens == 18
    assert response.usage.output_tokens == 9
    assert response.usage.cached_tokens == 4
    assert response.request_id == "chatcmpl-stream-1"


@pytest.mark.asyncio
async def test_openai_stream_fails_closed_without_done_after_a_delta():
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            request=request,
            content=(
                'data: {"choices":[{"index":0,"delta":{"content":"partial"}}]}'
                "\n\n"
            ),
        )

    deltas: list[str] = []

    async def record_delta(delta: str) -> None:
        deltas.append(delta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelGatewayError) as exc_info:
            await ModelGateway(
                OpenAIChatAdapter(
                    base_url="https://api.openai.com/v1",
                    api_key="secret",
                    model="example-model",
                    client=client,
                ),
                retry_policy=RetryPolicy(
                    max_attempts=3,
                    initial_backoff_seconds=0,
                    max_backoff_seconds=0,
                ),
            ).complete_stream(
                ModelRequest(messages=(ModelMessage(role="user", content="hi"),)),
                cancellation=CancellationToken(),
                on_delta=record_delta,
            )

    assert exc_info.value.code == "invalid_response"
    assert deltas == ["partial"]
    assert requests == 1


@pytest.mark.asyncio
async def test_claude_adapter_coalesces_tool_results_and_parses_tool_use_blocks():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            headers={"request-id": "req-claude-1"},
            json={
                "id": "msg-1",
                "model": "claude-test",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "I need another lookup."},
                    {
                        "type": "tool_use",
                        "id": "call-3",
                        "name": "weather",
                        "input": {"city": "Beijing"},
                    },
                ],
                "usage": {
                    "input_tokens": 21,
                    "output_tokens": 7,
                    "cache_read_input_tokens": 6,
                },
            },
        )

    prior_calls = (
        ToolCall(id="call-1", name="weather", arguments={"city": "Shanghai"}),
        ToolCall(id="call-2", name="weather", arguments={"city": "London"}),
    )
    messages = (
        ModelMessage(role="system", content="Be concise."),
        ModelMessage(role="user", content="Compare weather."),
        ModelMessage(role="assistant", tool_calls=prior_calls),
        ModelMessage(
            role="tool",
            name="weather",
            tool_call_id="call-1",
            content='{"success":true,"output":{"temp":20},"error":null}',
        ),
        ModelMessage(
            role="tool",
            name="weather",
            tool_call_id="call-2",
            content='{"success":false,"output":null,"error":"offline"}',
        ),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ClaudeMessagesAdapter(
            api_key="secret",
            model="claude-test",
            client=client,
        )
        response = await adapter.complete(
            ModelRequest(
                messages=messages,
                tools=(weather_tool(),),
                output_format=structured_output(),
            ),
            cancellation=CancellationToken(),
        )

    assert captured["system"] == "Be concise."
    assert captured["output_config"] == {
        "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    }
    assert captured["messages"][-1]["role"] == "user"
    result_blocks = captured["messages"][-1]["content"]
    assert [block["tool_use_id"] for block in result_blocks] == ["call-1", "call-2"]
    assert [block["is_error"] for block in result_blocks] == [False, True]
    assert response.text == "I need another lookup."
    assert response.tool_calls[0].arguments == {"city": "Beijing"}
    assert response.request_id == "req-claude-1"
    assert response.usage.cached_tokens == 6


@pytest.mark.asyncio
async def test_claude_adapter_streams_sse_text_tools_and_cumulative_usage():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-stream-1",
                    "model": "claude-stream-test",
                    "content": [],
                    "usage": {
                        "input_tokens": 24,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 5,
                    },
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "thinking",
                    "thinking": "",
                    "signature": "",
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "private"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Checking "},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "weather."},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-stream-1",
                    "name": "weather",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"city":"Bei',
                },
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": 'jing"}'},
            },
            {"type": "content_block_stop", "index": 2},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 12},
            },
            {"type": "future_event", "value": "ignored"},
            {"type": "message_stop"},
        ]
        body = "".join(
            f"event: {event['type']}\n"
            f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
            for event in events
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    deltas: list[str] = []

    async def record_delta(delta: str) -> None:
        deltas.append(delta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ModelGateway(
            ClaudeMessagesAdapter(
                api_key="secret",
                model="claude-test",
                client=client,
            ),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        response = await gateway.complete_stream(
            ModelRequest(
                messages=(ModelMessage(role="user", content="weather?"),),
                tools=(weather_tool(),),
                output_format=structured_output(),
            ),
            cancellation=CancellationToken(),
            on_delta=record_delta,
        )

    assert captured["stream"] is True
    assert captured["output_config"]["format"]["schema"] == OUTPUT_SCHEMA
    assert gateway.capabilities.streaming is True
    assert deltas == ["Checking ", "weather."]
    assert "private" not in response.text
    assert response.text == "Checking weather."
    assert response.tool_calls == (
        ToolCall(
            id="toolu-stream-1",
            name="weather",
            arguments={"city": "Beijing"},
        ),
    )
    assert response.finish_reason == "tool_use"
    assert response.usage.input_tokens == 24
    assert response.usage.output_tokens == 12
    assert response.usage.cached_tokens == 5
    assert response.request_id == "msg-stream-1"


@pytest.mark.asyncio
async def test_claude_stream_classifies_in_band_overload_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = (
            "event: error\n"
            'data: {"type":"error","error":'
            '{"type":"overloaded_error","message":"busy"}}\n\n'
        )
        return httpx.Response(200, request=request, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelGatewayError) as exc_info:
            await ModelGateway(
                ClaudeMessagesAdapter(
                    api_key="secret",
                    model="claude-test",
                    client=client,
                ),
                retry_policy=RetryPolicy(max_attempts=1),
            ).complete_stream(
                ModelRequest(messages=(ModelMessage(role="user", content="hi"),)),
                cancellation=CancellationToken(),
                on_delta=lambda _delta: asyncio.sleep(0),
            )

    assert exc_info.value.code == "provider_unavailable"


@pytest.mark.asyncio
async def test_ollama_adapter_uses_tool_name_for_tool_results():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "qwen-test",
                "done": True,
                "done_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "weather",
                                "arguments": {"city": "Shanghai"},
                            }
                        }
                    ],
                },
                "prompt_eval_count": 11,
                "eval_count": 3,
            },
        )

    messages = (
        ModelMessage(role="user", content="weather?"),
        ModelMessage(
            role="tool",
            name="weather",
            tool_call_id="prior-call",
            content='{"success":true}',
        ),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await OllamaChatAdapter(
            base_url="http://127.0.0.1:11434",
            model="qwen-test",
            client=client,
        ).complete(
            ModelRequest(
                messages=messages,
                tools=(weather_tool(),),
                output_format=structured_output(),
            ),
            cancellation=CancellationToken(),
        )

    assert captured["messages"][-1] == {
        "role": "tool",
        "content": '{"success":true}',
        "tool_name": "weather",
    }
    assert captured["tools"][0]["function"]["name"] == "weather"
    assert captured["format"] == OUTPUT_SCHEMA
    assert response.tool_calls[0].name == "weather"
    assert response.tool_calls[0].id.startswith("ollama-0-")
    assert response.usage.input_tokens == 11


@pytest.mark.asyncio
async def test_ollama_adapter_streams_ndjson_and_returns_the_complete_response():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        frames = [
            {
                "model": "qwen-test",
                "done": False,
                "message": {"role": "assistant", "content": "hello "},
            },
            {
                "model": "qwen-test",
                "done": False,
                "message": {"role": "assistant", "content": "world"},
            },
            {
                "model": "qwen-test",
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": ""},
                "prompt_eval_count": 12,
                "eval_count": 2,
            },
        ]
        body = "".join(f"{json.dumps(frame)}\n" for frame in frames)
        return httpx.Response(200, request=request, content=body)

    deltas: list[str] = []

    async def record_delta(delta: str) -> None:
        deltas.append(delta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ModelGateway(
            OllamaChatAdapter(
                base_url="http://127.0.0.1:11434",
                model="qwen-test",
                client=client,
            ),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        response = await gateway.complete_stream(
            ModelRequest(
                messages=(ModelMessage(role="user", content="hello"),),
                output_format=structured_output(),
            ),
            cancellation=CancellationToken(),
            on_delta=record_delta,
        )

    assert captured["stream"] is True
    assert captured["format"] == OUTPUT_SCHEMA
    assert gateway.capabilities.streaming is True
    assert deltas == ["hello ", "world"]
    assert response.text == "hello world"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 2
    assert response.provider == "ollama"
    assert response.latency_ms is not None


@pytest.mark.asyncio
async def test_streaming_gateway_retries_only_before_publishing_a_delta():
    class FlakyStreamingAdapter:
        provider_name = "flaky-stream"
        model_name = "test"
        capabilities = ModelCapabilities(True, False, False, False, True)

        def __init__(self, *, fail_after_delta: bool) -> None:
            self.calls = 0
            self.fail_after_delta = fail_after_delta

        async def complete(self, request, *, cancellation):
            raise AssertionError(f"unexpected fallback: {request}; {cancellation}")

        async def complete_stream(self, request, *, cancellation, on_delta):
            del request, cancellation
            self.calls += 1
            if self.calls == 1 and not self.fail_after_delta:
                raise httpx.ConnectError("offline before output")
            await on_delta("partial" if self.fail_after_delta else "recovered")
            if self.fail_after_delta:
                raise httpx.ConnectError("offline after output")
            return ModelResponse(text="recovered")

    retryable = FlakyStreamingAdapter(fail_after_delta=False)
    recovered: list[str] = []

    async def record_recovered(delta: str) -> None:
        recovered.append(delta)

    response = await ModelGateway(
        retryable,
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
        ),
    ).complete_stream(
        ModelRequest(messages=(ModelMessage(role="user", content="hello"),)),
        cancellation=CancellationToken(),
        on_delta=record_recovered,
    )
    assert response.text == "recovered"
    assert retryable.calls == 2
    assert recovered == ["recovered"]

    non_retryable = FlakyStreamingAdapter(fail_after_delta=True)
    partial: list[str] = []

    async def record_partial(delta: str) -> None:
        partial.append(delta)

    with pytest.raises(ModelGatewayError, match="network_error"):
        await ModelGateway(
            non_retryable,
            retry_policy=RetryPolicy(
                max_attempts=2,
                initial_backoff_seconds=0,
                max_backoff_seconds=0,
            ),
        ).complete_stream(
            ModelRequest(messages=(ModelMessage(role="user", content="hello"),)),
            cancellation=CancellationToken(),
            on_delta=record_partial,
        )
    assert non_retryable.calls == 1
    assert partial == ["partial"]


@pytest.mark.asyncio
async def test_runtime_discards_streamed_tool_turn_text_and_publishes_final_deltas():
    class StreamingToolModel:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request, *, cancellation):
            raise AssertionError(f"unexpected fallback: {request}; {cancellation}")

        async def complete_stream(self, request, *, cancellation, on_delta):
            del request, cancellation
            self.calls += 1
            if self.calls == 1:
                await on_delta("draft before tool")
                return ModelResponse(
                    text="draft before tool",
                    tool_calls=(
                        ToolCall(
                            id="call-stream",
                            name="weather",
                            arguments={"city": "Shanghai"},
                        ),
                    ),
                )
            await on_delta("final ")
            await on_delta("answer")
            return ModelResponse(text="final answer")

    class WeatherDispatcher:
        async def execute(self, call, *, cancellation):
            del cancellation
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                success=True,
                output={"condition": "clear"},
            )

    published: list[str] = []

    async def publish(delta: str) -> None:
        published.append(delta)

    result = await AgentRuntime(
        StreamingToolModel(),
        WeatherDispatcher(),
        model_output_sink=publish,
    ).run(
        [ModelMessage(role="user", content="How is Shanghai?")],
        tool_definitions=[weather_tool()],
    )

    assert result.status == AgentRunStatus.COMPLETED
    assert result.output == "final answer"
    assert published == ["final ", "answer"]


@pytest.mark.asyncio
async def test_runtime_cancels_an_active_model_stream():
    started = asyncio.Event()

    class BlockingStreamingModel:
        async def complete(self, request, *, cancellation):
            raise AssertionError(f"unexpected fallback: {request}; {cancellation}")

        async def complete_stream(self, request, *, cancellation, on_delta):
            del request, cancellation
            await on_delta("partial")
            started.set()
            await asyncio.sleep(60)
            raise AssertionError("cancelled stream resumed")

    class NoTools:
        async def execute(self, call, *, cancellation):
            raise AssertionError(f"unexpected tool: {call}; {cancellation}")

    cancellation = CancellationToken()
    published: list[str] = []

    async def publish(delta: str) -> None:
        published.append(delta)

    task = asyncio.create_task(
        AgentRuntime(
            BlockingStreamingModel(),
            NoTools(),
            model_output_sink=publish,
        ).run(
            [ModelMessage(role="user", content="hello")],
            cancellation=cancellation,
        )
    )
    await started.wait()
    cancellation.cancel()
    result = await task

    assert result.status == AgentRunStatus.CANCELLED
    assert published == ["partial"]


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://localhost/v1",
        "https://127.0.0.1/v1",
        "https://169.254.169.254/latest",
        "https://10.0.0.5/v1",
        "https://user:pass@example.com/v1",
    ],
)
def test_remote_url_policy_rejects_unsafe_defaults(url: str):
    with pytest.raises(UnsafeModelEndpointError):
        validate_remote_base_url(url)


def test_remote_url_policy_allows_explicit_private_development_endpoint():
    result = validate_remote_base_url(
        "http://127.0.0.1:9000/v1",
        allow_http=True,
        allow_private_network=True,
    )

    assert result == "http://127.0.0.1:9000/v1"


@pytest.mark.asyncio
async def test_gateway_retries_only_normalized_transient_errors():
    class FlakyAdapter:
        provider_name = "flaky"
        model_name = "test"
        capabilities = ModelCapabilities(False, True, False, False, True)

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request, *, cancellation):
            del request, cancellation
            self.calls += 1
            if self.calls < 3:
                raise httpx.ConnectError("offline")
            return ModelResponse(text="recovered")

    adapter = FlakyAdapter()
    response = await ModelGateway(
        adapter,
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
        ),
    ).complete(
        ModelRequest(messages=(ModelMessage(role="user", content="hello"),)),
        cancellation=CancellationToken(),
    )

    assert response.text == "recovered"
    assert adapter.calls == 3
    assert response.provider == "flaky"


def test_model_output_format_rejects_unsafe_or_incompatible_schemas():
    with pytest.raises(ValueError, match="root type must be object"):
        ModelOutputFormat(json_schema={"type": "array"})

    with pytest.raises(ValueError, match="forbids remote references"):
        ModelOutputFormat(
            json_schema={
                "type": "object",
                "properties": {
                    "answer": {"$ref": "https://example.com/answer.schema.json"}
                },
            }
        )


@pytest.mark.asyncio
async def test_gateway_rejects_unsupported_structured_output_without_calling_adapter():
    class UnstructuredAdapter:
        provider_name = "unstructured"
        model_name = "test"
        capabilities = ModelCapabilities(False, False, False, False, True)

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request, *, cancellation):
            del request, cancellation
            self.calls += 1
            return ModelResponse(text="unexpected")

    adapter = UnstructuredAdapter()
    gateway = ModelGateway(adapter, retry_policy=RetryPolicy(max_attempts=1))
    request = ModelRequest(
        messages=(ModelMessage(role="user", content="hello"),),
        output_format=structured_output(),
    )

    with pytest.raises(ModelGatewayError) as complete_error:
        await gateway.complete(request, cancellation=CancellationToken())
    with pytest.raises(ModelGatewayError) as stream_error:
        await gateway.complete_stream(
            request,
            cancellation=CancellationToken(),
            on_delta=lambda _delta: asyncio.sleep(0),
        )

    assert complete_error.value.code == "unsupported_capability"
    assert stream_error.value.code == "unsupported_capability"
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_gateway_does_not_retry_invalid_provider_payloads():
    class InvalidAdapter:
        provider_name = "invalid"
        model_name = "test"
        capabilities = ModelCapabilities(False, True, False, False, True)

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request, *, cancellation):
            del request, cancellation
            self.calls += 1
            raise ValueError("bad payload")

    adapter = InvalidAdapter()
    with pytest.raises(ModelGatewayError) as exc_info:
        await ModelGateway(
            adapter,
            retry_policy=RetryPolicy(
                max_attempts=3,
                initial_backoff_seconds=0,
                max_backoff_seconds=0,
            ),
        ).complete(
            ModelRequest(messages=(ModelMessage(role="user", content="hello"),)),
            cancellation=CancellationToken(),
        )

    assert exc_info.value.code == "invalid_response"
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_openai_gateway_drives_the_bounded_runtime_tool_loop():
    payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": '{"city":"Shanghai"}',
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "Shanghai is clear."}
            finish_reason = "stop"
        return httpx.Response(
            200,
            request=request,
            json={
                "id": f"chatcmpl-{len(payloads)}",
                "model": "example-model",
                "choices": [{"finish_reason": finish_reason, "message": message}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )

    class WeatherDispatcher:
        async def execute(self, call, *, cancellation):
            del cancellation
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                success=True,
                output={"condition": "clear"},
            )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ModelGateway(
            OpenAIChatAdapter(
                base_url="https://api.openai.com/v1",
                api_key="secret",
                model="example-model",
                client=client,
            ),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        result = await AgentRuntime(gateway, WeatherDispatcher()).run(
            [ModelMessage(role="user", content="How is Shanghai?")],
            tool_definitions=[weather_tool()],
        )

    assert result.status == AgentRunStatus.COMPLETED
    assert result.output == "Shanghai is clear."
    assert len(payloads) == 2
    assert payloads[1]["messages"][-2]["tool_calls"][0]["id"] == "call-1"
    assert payloads[1]["messages"][-1]["tool_call_id"] == "call-1"


def test_legacy_provider_router_exposes_typed_gateway_without_switching_chat_path():
    local = ProviderRouter({}).model_gateway()
    remote = ProviderRouter(
        {
            "provider_type": "openai",
            "remote_provider_enabled": "true",
            "openai_api_key": "secret",
            "openai_base_url": "https://api.openai.com/v1",
        }
    ).model_gateway()

    assert local.adapter.provider_name == "ollama"
    assert remote.adapter.provider_name == "openai_compatible"
    assert remote.capabilities.native_tool_calls is True
