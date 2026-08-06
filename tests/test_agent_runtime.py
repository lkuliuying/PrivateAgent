from __future__ import annotations

import asyncio
from collections import deque

import pytest

from personal_assistant.agents import (
    AgentEventType,
    AgentRunLimits,
    AgentRunStatus,
    AgentRuntime,
    AgentStepStatus,
    CancellationToken,
    EventSinkError,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolDefinition,
    TokenUsage,
    ToolCall,
    ToolResult,
)


class ScriptedModel:
    def __init__(self, *responses: ModelResponse, delay: float = 0) -> None:
        self.responses = deque(responses)
        self.requests: list[ModelRequest] = []
        self.delay = delay
        self.was_cancelled = False

    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> ModelResponse:
        del cancellation
        self.requests.append(request)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return self.responses.popleft()
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise


class RecordingTools:
    def __init__(self, *, fail: bool = False, delay: float = 0) -> None:
        self.calls: list[ToolCall] = []
        self.fail = fail
        self.delay = delay
        self.was_cancelled = False

    async def execute(
        self,
        call: ToolCall,
        *,
        cancellation: CancellationToken,
    ) -> ToolResult:
        del cancellation
        self.calls.append(call)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise
        if self.fail:
            raise RuntimeError("tool exploded")
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            success=True,
            output={"echo": call.arguments},
        )


def user_message(content: str = "hello") -> ModelMessage:
    return ModelMessage(role="user", content=content)


def model_tool(name: str) -> ModelToolDefinition:
    return ModelToolDefinition(
        name=name,
        description=f"Test tool {name}",
        input_schema={"type": "object", "properties": {}},
    )


@pytest.mark.asyncio
async def test_completes_without_tools_and_aggregates_usage():
    model = ScriptedModel(
        ModelResponse(
            text="done",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=7, output_tokens=3, cost_usd=0.02),
        )
    )
    runtime = AgentRuntime(model, RecordingTools())

    result = await runtime.run([user_message()], run_id="run-direct")

    assert result.status == AgentRunStatus.COMPLETED
    assert result.output == "done"
    assert result.tool_call_count == 0
    assert result.usage == TokenUsage(input_tokens=7, output_tokens=3, cost_usd=0.02)
    assert [event.type for event in result.events] == [
        AgentEventType.RUN_STARTED,
        AgentEventType.MODEL_STARTED,
        AgentEventType.MODEL_COMPLETED,
        AgentEventType.RUN_COMPLETED,
    ]
    assert [event.sequence for event in result.events] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_executes_multiple_native_tool_calls_then_returns_to_model():
    first = ModelResponse(
        text="I will inspect both inputs.",
        tool_calls=(
            ToolCall(id="call-1", name="read", arguments={"path": "a.txt"}),
            ToolCall(id="call-2", name="read", arguments={"path": "b.txt"}),
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=4),
    )
    second = ModelResponse(
        text="both files inspected",
        usage=TokenUsage(input_tokens=20, output_tokens=5),
    )
    model = ScriptedModel(first, second)
    tools = RecordingTools()

    result = await AgentRuntime(model, tools).run(
        [user_message()],
        tool_definitions=[model_tool("read")],
    )

    assert result.status == AgentRunStatus.COMPLETED
    assert result.output == "both files inspected"
    assert [call.id for call in tools.calls] == ["call-1", "call-2"]
    assert result.tool_call_count == 2
    assert len(result.steps) == 4
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 9
    follow_up = model.requests[1].messages
    assert follow_up[-2].role == "tool" and follow_up[-2].tool_call_id == "call-1"
    assert follow_up[-1].role == "tool" and follow_up[-1].tool_call_id == "call-2"


@pytest.mark.asyncio
async def test_tool_failure_is_returned_to_the_model_for_recovery():
    model = ScriptedModel(
        ModelResponse(tool_calls=(ToolCall(id="call-1", name="fragile"),)),
        ModelResponse(text="I recovered from the tool failure."),
    )

    result = await AgentRuntime(model, RecordingTools(fail=True)).run(
        [user_message()],
        tool_definitions=[model_tool("fragile")],
    )

    assert result.status == AgentRunStatus.COMPLETED
    assert result.output == "I recovered from the tool failure."
    assert result.steps[1].status == AgentStepStatus.FAILED
    assert "tool exploded" in model.requests[1].messages[-1].content
    assert AgentEventType.TOOL_FAILED in [event.type for event in result.events]


@pytest.mark.asyncio
async def test_approval_required_pauses_run_without_returning_failure_to_model():
    class ApprovalTools:
        async def execute(
            self,
            call: ToolCall,
            *,
            cancellation: CancellationToken,
        ) -> ToolResult:
            del cancellation
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                success=False,
                error="工具需要用户审批",
                error_code="approval_required",
                approval_id="approval-1",
            )

    model = ScriptedModel(
        ModelResponse(
            tool_calls=(
                ToolCall(
                    id="call-1",
                    name="read_file",
                    arguments={"path": "C:/notes/a.md"},
                ),
            )
        )
    )

    result = await AgentRuntime(model, ApprovalTools()).run(
        [user_message()],
        tool_definitions=[model_tool("read_file")],
        run_id="run-waiting-approval",
    )

    assert result.status == AgentRunStatus.WAITING_APPROVAL
    assert result.output is None
    assert result.error is None
    assert result.tool_call_count == 1
    assert result.steps[-1].status == AgentStepStatus.WAITING_APPROVAL
    assert result.steps[-1].completed_at is None
    assert len(model.requests) == 1
    assert result.events[-1].type == AgentEventType.TOOL_APPROVAL_REQUIRED
    assert result.events[-1].payload == {
        "tool_call_id": "call-1",
        "name": "read_file",
        "approval_id": "approval-1",
        "tool_call_count": 1,
    }


@pytest.mark.asyncio
async def test_cancellation_stops_a_non_cooperative_model_awaitable():
    model = ScriptedModel(ModelResponse(text="too late"), delay=30)
    token = CancellationToken()
    task = asyncio.create_task(
        AgentRuntime(model, RecordingTools()).run(
            [user_message()],
            cancellation=token,
        )
    )
    await asyncio.sleep(0.01)

    token.cancel()
    result = await asyncio.wait_for(task, timeout=1)

    assert result.status == AgentRunStatus.CANCELLED
    assert result.steps[0].status == AgentStepStatus.CANCELLED
    assert result.events[-1].type == AgentEventType.RUN_CANCELLED
    assert model.was_cancelled is True


@pytest.mark.asyncio
async def test_wall_time_cancels_an_active_tool():
    model = ScriptedModel(
        ModelResponse(tool_calls=(ToolCall(id="call-1", name="slow"),))
    )
    tools = RecordingTools(delay=30)

    result = await AgentRuntime(model, tools).run(
        [user_message()],
        limits=AgentRunLimits(max_wall_time_seconds=0.03),
        tool_definitions=[model_tool("slow")],
    )

    assert result.status == AgentRunStatus.TIMED_OUT
    assert result.steps[-1].status == AgentStepStatus.TIMED_OUT
    assert result.events[-1].type == AgentEventType.RUN_TIMED_OUT
    assert tools.was_cancelled is True


@pytest.mark.asyncio
async def test_rejects_a_tool_batch_before_partial_execution_when_limit_is_too_low():
    model = ScriptedModel(
        ModelResponse(
            tool_calls=(
                ToolCall(id="call-1", name="read"),
                ToolCall(id="call-2", name="read"),
            )
        )
    )
    tools = RecordingTools()

    result = await AgentRuntime(model, tools).run(
        [user_message()],
        limits=AgentRunLimits(max_tool_calls=1),
        tool_definitions=[model_tool("read")],
    )

    assert result.status == AgentRunStatus.LIMIT_EXCEEDED
    assert result.tool_call_count == 0
    assert tools.calls == []
    assert result.events[-1].payload["error_code"] == "max_tool_calls"
    assert result.events[-1].payload["tool_call_count"] == 0


@pytest.mark.asyncio
async def test_step_budget_stops_before_an_incomplete_tool_batch():
    model = ScriptedModel(
        ModelResponse(tool_calls=(ToolCall(id="call-1", name="read"),))
    )
    tools = RecordingTools()

    result = await AgentRuntime(model, tools).run(
        [user_message()],
        limits=AgentRunLimits(max_steps=1),
        tool_definitions=[model_tool("read")],
    )

    assert result.status == AgentRunStatus.LIMIT_EXCEEDED
    assert tools.calls == []
    assert len(result.steps) == 1
    assert result.events[-1].payload["error_code"] == "max_steps"
    assert result.events[-1].payload["tool_call_count"] == 0


@pytest.mark.asyncio
async def test_mismatched_tool_result_fails_the_run():
    class WrongTool:
        async def execute(
            self,
            call: ToolCall,
            *,
            cancellation: CancellationToken,
        ) -> ToolResult:
            del call, cancellation
            return ToolResult(
                tool_call_id="wrong-id",
                name="wrong-name",
                success=True,
                output={},
            )

    model = ScriptedModel(
        ModelResponse(tool_calls=(ToolCall(id="call-1", name="read"),))
    )

    result = await AgentRuntime(model, WrongTool()).run(
        [user_message()],
        tool_definitions=[model_tool("read")],
    )

    assert result.status == AgentRunStatus.FAILED
    assert result.steps[-1].status == AgentStepStatus.FAILED
    assert result.events[-1].type == AgentEventType.RUN_FAILED


@pytest.mark.asyncio
async def test_non_json_tool_output_fails_before_the_tool_step_is_marked_succeeded():
    class NonJsonTool:
        async def execute(
            self,
            call: ToolCall,
            *,
            cancellation: CancellationToken,
        ) -> ToolResult:
            del cancellation
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                success=True,
                output={"not_json": {1, 2, 3}},
            )

    model = ScriptedModel(
        ModelResponse(tool_calls=(ToolCall(id="call-1", name="read"),))
    )

    result = await AgentRuntime(model, NonJsonTool()).run(
        [user_message()],
        tool_definitions=[model_tool("read")],
    )

    assert result.status == AgentRunStatus.FAILED
    assert result.steps[-1].status == AgentStepStatus.FAILED
    assert "JSON serializable" in (result.error or "")


@pytest.mark.asyncio
async def test_unregistered_tool_is_not_dispatched_and_can_be_recovered_by_model():
    model = ScriptedModel(
        ModelResponse(tool_calls=(ToolCall(id="call-1", name="not_registered"),)),
        ModelResponse(text="The requested tool is unavailable."),
    )
    tools = RecordingTools()

    result = await AgentRuntime(model, tools).run(
        [user_message()],
        tool_definitions=[model_tool("read")],
    )

    assert result.status == AgentRunStatus.COMPLETED
    assert tools.calls == []
    assert result.steps[1].status == AgentStepStatus.FAILED
    assert "not_registered" in model.requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_event_sink_failure_is_not_hidden_as_a_synthetic_run_failure():
    class FailingSink:
        def __init__(self) -> None:
            self.sequences: list[int] = []

        async def emit(self, event) -> None:
            self.sequences.append(event.sequence)
            if event.sequence == 2:
                raise RuntimeError("database acknowledgement lost")

    sink = FailingSink()
    runtime = AgentRuntime(
        ScriptedModel(ModelResponse(text="unreachable")),
        RecordingTools(),
        event_sink=sink,
    )

    with pytest.raises(EventSinkError, match="sequence 2"):
        await runtime.run([user_message()])

    assert sink.sequences == [1, 2]
