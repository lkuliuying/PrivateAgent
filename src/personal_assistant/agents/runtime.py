"""A small, provider-neutral and bounded Agent execution runtime."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from .contracts import (
    AgentEvent,
    AgentEventType,
    AgentRunCheckpoint,
    AgentRunLimits,
    AgentRunResult,
    AgentRunStatus,
    AgentStep,
    AgentStepKind,
    AgentStepStatus,
    ModelMessage,
    ModelOutputFormat,
    ModelRequest,
    ModelResponse,
    ModelToolDefinition,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from .verification import OutputVerification, OutputVerifier


class ModelClient(Protocol):
    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> ModelResponse: ...


class ToolDispatcher(Protocol):
    async def execute(
        self,
        call: ToolCall,
        *,
        cancellation: CancellationToken,
    ) -> ToolResult: ...


class EventSink(Protocol):
    async def emit(self, event: AgentEvent) -> None: ...


ModelOutputSink = Callable[[str], Awaitable[None]]


class EventSinkError(RuntimeError):
    """Raised when a public run event cannot be durably delivered."""


class CancellationToken:
    """A cooperative token that also lets the runtime cancel pending awaitables."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise _RunCancelled


class _NullEventSink:
    async def emit(self, event: AgentEvent) -> None:
        del event


class _RunCancelled(Exception):
    pass


class _RunLimitExceeded(Exception):
    def __init__(self, limit: str) -> None:
        super().__init__(f"Agent 运行达到限制：{limit}")
        self.limit = limit


class _RunWaitingApproval(Exception):
    pass


class _RuntimeProtocolError(RuntimeError):
    pass


class _OutputValidationFailed(RuntimeError):
    def __init__(self, result: OutputVerification) -> None:
        super().__init__(result.message)
        self.result = result


@dataclass(frozen=True, slots=True)
class _CompletedModelTurn:
    response: ModelResponse
    deltas: tuple[str, ...] = ()


@dataclass(slots=True)
class _RunContext:
    run_id: str
    limits: AgentRunLimits
    sink: EventSink
    steps: list[AgentStep] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    tool_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    has_cost: bool = False
    last_sequence: int = 0

    @property
    def next_sequence(self) -> int:
        return self.last_sequence + 1

    async def emit(
        self,
        event_type: AgentEventType,
        *,
        step_id: str | None = None,
        payload: dict[str, object] | None = None,
        checkpoint: AgentRunCheckpoint | None = None,
    ) -> None:
        event = AgentEvent(
            run_id=self.run_id,
            sequence=self.next_sequence,
            type=event_type,
            step_id=step_id,
            payload=payload or {},
        )
        try:
            if checkpoint is not None:
                if checkpoint.run_id != self.run_id or (
                    checkpoint.event_sequence != event.sequence
                ):
                    raise ValueError(
                        "checkpoint must match the emitted run and sequence"
                    )
                emit_with_checkpoint = getattr(
                    self.sink,
                    "emit_with_checkpoint",
                    None,
                )
                if emit_with_checkpoint is not None:
                    await emit_with_checkpoint(event, checkpoint)
                else:
                    await self.sink.emit(event)
            else:
                await self.sink.emit(event)
        except Exception as exc:
            # A sink can commit an event and still lose the acknowledgement. Do
            # not consume the in-memory sequence or turn this into a synthetic
            # run.failed event; a retry can then safely use the same sequence.
            raise EventSinkError(
                f"Agent event persistence failed at sequence {event.sequence}"
            ) from exc
        self.events.append(event)
        self.last_sequence = event.sequence

    async def sync_sequence(self) -> None:
        """工具执行后校准内存事件序列到 DB 最新已提交事实。

        PatchSetService 等经独立 session 写入 durable 事件（patch_set.
        preview_created / applied 等，E3 §3）会推进 run.last_event_sequence；
        若 runtime 内存序列滞后，后续 TOOL_COMPLETED 等事件将与外部事件
        序列冲突（E0 严格序列契约）。sink 未提供 latest_sequence（内存
        sink）时跳过。
        """
        latest = getattr(self.sink, "latest_sequence", None)
        if latest is None:
            return
        try:
            db_last = await latest(self.run_id)
        except Exception:
            return
        if db_last is not None:
            self.last_sequence = max(self.last_sequence, db_last)

    def start_step(
        self,
        kind: AgentStepKind,
        *,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> AgentStep:
        if len(self.steps) >= self.limits.max_steps:
            raise _RunLimitExceeded("max_steps")
        step = AgentStep(
            id=str(uuid4()),
            ordinal=len(self.steps) + 1,
            kind=kind,
            status=AgentStepStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            tool_call_id=tool_call_id,
            name=name,
        )
        self.steps.append(step)
        return step

    def finish_step(
        self,
        step: AgentStep,
        status: AgentStepStatus,
        *,
        error: str | None = None,
    ) -> AgentStep:
        completed = step.model_copy(
            update={
                "status": status,
                "completed_at": (
                    None
                    if status == AgentStepStatus.WAITING_APPROVAL
                    else datetime.now(timezone.utc)
                ),
                "error": error,
            }
        )
        self.steps[step.ordinal - 1] = completed
        return completed

    def finish_running_step(
        self, status: AgentStepStatus, *, error: str | None = None
    ) -> None:
        for step in reversed(self.steps):
            if step.status == AgentStepStatus.RUNNING:
                self.finish_step(step, status, error=error)
                return

    def add_usage(self, usage: TokenUsage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cached_tokens += usage.cached_tokens
        if usage.cost_usd is not None:
            self.cost_usd += usage.cost_usd
            self.has_cost = True

    def usage(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cached_tokens=self.cached_tokens,
            cost_usd=self.cost_usd if self.has_cost else None,
        )


_T = TypeVar("_T")


async def _await_with_cancellation(
    awaitable: Awaitable[_T],
    cancellation: CancellationToken,
) -> _T:
    """Await an awaitable, racing a cancellation token.

    The awaitable is scheduled (ensure_future) immediately, before any
    cancellation check, so a token cancelled in the window between coroutine
    creation and this function's entry can never leave a bare coroutine
    unawaited (avoids "coroutine was never awaited" on GC).
    """
    operation = asyncio.ensure_future(awaitable)
    if cancellation.is_cancelled:
        operation.cancel()
        with suppress(asyncio.CancelledError):
            await operation
        raise _RunCancelled
    cancelled = asyncio.create_task(cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            {operation, cancelled},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled in done:
            operation.cancel()
            with suppress(asyncio.CancelledError):
                await operation
            raise _RunCancelled
        return await operation
    finally:
        cancelled.cancel()
        with suppress(asyncio.CancelledError):
            await cancelled
        if not operation.done():
            operation.cancel()
            with suppress(asyncio.CancelledError):
                await operation


class AgentRuntime:
    """Execute model/tool turns with deterministic termination conditions."""

    def __init__(
        self,
        model: ModelClient,
        tools: ToolDispatcher,
        *,
        event_sink: EventSink | None = None,
        model_output_sink: ModelOutputSink | None = None,
        output_verifier: OutputVerifier | None = None,
        max_verification_retries: int | None = None,
    ) -> None:
        effective_verification_retries = (
            1
            if output_verifier is not None and max_verification_retries is None
            else int(max_verification_retries or 0)
        )
        if output_verifier is None and effective_verification_retries:
            raise ValueError("verification retries require an output verifier")
        if not 0 <= effective_verification_retries <= 2:
            raise ValueError("max_verification_retries must be between 0 and 2")
        if output_verifier is not None:
            verifier_name = str(output_verifier.name)
            if not 1 <= len(verifier_name) <= 200:
                raise ValueError("output verifier name must contain 1..200 characters")
        output_schema = (
            output_verifier.output_schema if output_verifier is not None else None
        )
        self._model = model
        self._tools = tools
        self._event_sink = event_sink or _NullEventSink()
        self._model_output_sink = model_output_sink
        self._output_verifier = output_verifier
        self._model_output_format = (
            ModelOutputFormat(
                name="agent_output",
                description="The final validated Agent output.",
                json_schema=output_schema,
            )
            if output_schema is not None
            else None
        )
        self._max_verification_retries = effective_verification_retries

    async def run(
        self,
        messages: list[ModelMessage] | tuple[ModelMessage, ...],
        *,
        limits: AgentRunLimits | None = None,
        cancellation: CancellationToken | None = None,
        tool_definitions: list[ModelToolDefinition]
        | tuple[ModelToolDefinition, ...] = (),
        run_id: str | None = None,
        event_sink: EventSink | None = None,
        context_metadata: Mapping[str, Any] | None = None,
    ) -> AgentRunResult:
        if not messages:
            raise ValueError("Agent 运行至少需要一条消息")

        effective_limits = limits or AgentRunLimits()
        token = cancellation or CancellationToken()
        context = _RunContext(
            run_id=run_id or str(uuid4()),
            limits=effective_limits,
            sink=event_sink or self._event_sink,
        )
        await context.emit(
            AgentEventType.RUN_STARTED,
            payload={
                "max_steps": effective_limits.max_steps,
                "max_tool_calls": effective_limits.max_tool_calls,
                "max_wall_time_seconds": effective_limits.max_wall_time_seconds,
                "output_verifier": (
                    self._output_verifier.name if self._output_verifier else None
                ),
                "max_verification_retries": self._max_verification_retries,
            },
        )
        if context_metadata is not None:
            await context.emit(
                AgentEventType.CONTEXT_PREPARED,
                payload=dict(context_metadata),
            )

        try:
            async with asyncio.timeout(effective_limits.max_wall_time_seconds):
                output = await self._drive(
                    list(messages),
                    tuple(tool_definitions),
                    context,
                    token,
                )
        except _RunCancelled:
            context.finish_running_step(AgentStepStatus.CANCELLED, error="cancelled")
            error = "运行已取消"
            await context.emit(
                AgentEventType.RUN_CANCELLED,
                payload=self._terminal_payload(context, error=error),
            )
            return self._result(context, AgentRunStatus.CANCELLED, error=error)
        except _RunLimitExceeded as exc:
            await context.emit(
                AgentEventType.RUN_LIMIT_EXCEEDED,
                payload=self._terminal_payload(
                    context,
                    error=str(exc),
                    error_code=exc.limit,
                ),
            )
            return self._result(context, AgentRunStatus.LIMIT_EXCEEDED, error=str(exc))
        except _RunWaitingApproval:
            return self._result(context, AgentRunStatus.WAITING_APPROVAL)
        except TimeoutError:
            context.finish_running_step(AgentStepStatus.TIMED_OUT, error="timed_out")
            error = "运行超时"
            await context.emit(
                AgentEventType.RUN_TIMED_OUT,
                payload=self._terminal_payload(
                    context,
                    error=error,
                    error_code="wall_time",
                ),
            )
            return self._result(context, AgentRunStatus.TIMED_OUT, error=error)
        except EventSinkError:
            raise
        except _OutputValidationFailed as exc:
            error = exc.result.message
            await context.emit(
                AgentEventType.RUN_FAILED,
                payload=self._terminal_payload(
                    context,
                    error=error,
                    error_code="output_validation_failed",
                ),
            )
            return self._result(context, AgentRunStatus.FAILED, error=error)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            context.finish_running_step(AgentStepStatus.FAILED, error=error)
            await context.emit(
                AgentEventType.RUN_FAILED,
                payload=self._terminal_payload(
                    context,
                    error=error,
                    error_code=type(exc).__name__,
                ),
            )
            return self._result(context, AgentRunStatus.FAILED, error=error)

        await context.emit(
            AgentEventType.RUN_COMPLETED,
            payload=self._terminal_payload(context, output=output),
        )
        return self._result(context, AgentRunStatus.COMPLETED, output=output)

    async def resume(
        self,
        checkpoint: AgentRunCheckpoint,
        *,
        steps: list[AgentStep] | tuple[AgentStep, ...],
        approval_id: str,
        limits: AgentRunLimits,
        cancellation: CancellationToken | None = None,
        tool_definitions: list[ModelToolDefinition]
        | tuple[ModelToolDefinition, ...] = (),
        event_sink: EventSink | None = None,
    ) -> AgentRunResult:
        """Continue the exact pending tool sequence from a durable checkpoint."""

        if not approval_id:
            raise ValueError("approval_id is required to resume an Agent run")
        waiting = [
            step for step in steps if step.status == AgentStepStatus.WAITING_APPROVAL
        ]
        if len(waiting) != 1:
            raise ValueError("resume requires exactly one waiting approval step")
        first_call = checkpoint.pending_tool_calls[0]
        if (
            waiting[0].tool_call_id != first_call.id
            or waiting[0].name != first_call.name
        ):
            raise ValueError("checkpoint does not match the waiting tool step")

        token = cancellation or CancellationToken()
        usage = checkpoint.usage
        context = _RunContext(
            run_id=checkpoint.run_id,
            limits=limits,
            sink=event_sink or self._event_sink,
            steps=list(steps),
            tool_call_count=checkpoint.tool_call_count,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            cost_usd=usage.cost_usd or 0.0,
            has_cost=usage.cost_usd is not None,
            last_sequence=checkpoint.event_sequence,
        )

        try:
            async with asyncio.timeout(limits.max_wall_time_seconds):
                output = await self._resume_drive(
                    checkpoint,
                    approval_id=approval_id,
                    tool_definitions=tuple(tool_definitions),
                    context=context,
                    cancellation=token,
                )
        except _RunCancelled:
            context.finish_running_step(AgentStepStatus.CANCELLED, error="cancelled")
            error = "运行已取消"
            await context.emit(
                AgentEventType.RUN_CANCELLED,
                payload=self._terminal_payload(context, error=error),
            )
            return self._result(context, AgentRunStatus.CANCELLED, error=error)
        except _RunLimitExceeded as exc:
            await context.emit(
                AgentEventType.RUN_LIMIT_EXCEEDED,
                payload=self._terminal_payload(
                    context,
                    error=str(exc),
                    error_code=exc.limit,
                ),
            )
            return self._result(context, AgentRunStatus.LIMIT_EXCEEDED, error=str(exc))
        except _RunWaitingApproval:
            return self._result(context, AgentRunStatus.WAITING_APPROVAL)
        except TimeoutError:
            context.finish_running_step(AgentStepStatus.TIMED_OUT, error="timed_out")
            error = "运行超时"
            await context.emit(
                AgentEventType.RUN_TIMED_OUT,
                payload=self._terminal_payload(
                    context,
                    error=error,
                    error_code="wall_time",
                ),
            )
            return self._result(context, AgentRunStatus.TIMED_OUT, error=error)
        except EventSinkError:
            raise
        except _OutputValidationFailed as exc:
            error = exc.result.message
            await context.emit(
                AgentEventType.RUN_FAILED,
                payload=self._terminal_payload(
                    context,
                    error=error,
                    error_code="output_validation_failed",
                ),
            )
            return self._result(context, AgentRunStatus.FAILED, error=error)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            context.finish_running_step(AgentStepStatus.FAILED, error=error)
            await context.emit(
                AgentEventType.RUN_FAILED,
                payload=self._terminal_payload(
                    context,
                    error=error,
                    error_code=type(exc).__name__,
                ),
            )
            return self._result(context, AgentRunStatus.FAILED, error=error)

        await context.emit(
            AgentEventType.RUN_COMPLETED,
            payload=self._terminal_payload(context, output=output),
        )
        return self._result(context, AgentRunStatus.COMPLETED, output=output)

    async def _resume_drive(
        self,
        checkpoint: AgentRunCheckpoint,
        *,
        approval_id: str,
        tool_definitions: tuple[ModelToolDefinition, ...],
        context: _RunContext,
        cancellation: CancellationToken,
    ) -> str:
        conversation = list(checkpoint.conversation)
        pending_calls = checkpoint.pending_tool_calls
        allowed_tool_names = {tool.name for tool in tool_definitions}

        for call_index, call in enumerate(pending_calls):
            cancellation.raise_if_cancelled()
            if call_index == 0:
                tool_step = next(
                    step
                    for step in reversed(context.steps)
                    if step.status == AgentStepStatus.WAITING_APPROVAL
                )
            else:
                if context.tool_call_count + 1 > context.limits.max_tool_calls:
                    raise _RunLimitExceeded("max_tool_calls")
                context.tool_call_count += 1
                tool_step = context.start_step(
                    AgentStepKind.TOOL,
                    tool_call_id=call.id,
                    name=call.name,
                )
                await context.emit(
                    AgentEventType.TOOL_REQUESTED,
                    step_id=tool_step.id,
                    payload={
                        "ordinal": tool_step.ordinal,
                        "kind": tool_step.kind.value,
                        "tool_call_id": call.id,
                        "name": call.name,
                    },
                )
                await context.emit(
                    AgentEventType.TOOL_STARTED,
                    step_id=tool_step.id,
                    payload={"tool_call_id": call.id, "name": call.name},
                )

            if call.name not in allowed_tool_names:
                result = ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    success=False,
                    error=f"工具未向模型注册：{call.name}",
                )
            else:
                try:
                    result = await _await_with_cancellation(
                        self._tools.execute(call, cancellation=cancellation),
                        cancellation,
                    )
                except _RunCancelled:
                    raise
                except Exception as exc:
                    result = ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        success=False,
                        error=str(exc) or type(exc).__name__,
                    )

            # 工具执行期间外部 durable 事件（patch_set.* 等）可能已推进
            # run.last_event_sequence，校准内存序列避免后续事件冲突（E3 §3）。
            await context.sync_sequence()

            self._validate_tool_result(call, result)
            if result.error_code == "approval_required":
                if call_index == 0:
                    raise _RuntimeProtocolError(
                        "approved checkpoint returned to approval_required"
                    )
                context.finish_step(tool_step, AgentStepStatus.WAITING_APPROVAL)
                next_checkpoint = AgentRunCheckpoint(
                    run_id=context.run_id,
                    event_sequence=context.next_sequence,
                    conversation=tuple(conversation),
                    pending_tool_calls=tuple(pending_calls[call_index:]),
                    tool_call_count=context.tool_call_count,
                    usage=context.usage(),
                )
                await context.emit(
                    AgentEventType.TOOL_APPROVAL_REQUIRED,
                    step_id=tool_step.id,
                    payload={
                        "tool_call_id": call.id,
                        "name": call.name,
                        "approval_id": result.approval_id,
                        "tool_call_count": context.tool_call_count,
                    },
                    checkpoint=next_checkpoint,
                )
                raise _RunWaitingApproval

            if call_index == 0:
                running_step = tool_step.model_copy(
                    update={"status": AgentStepStatus.RUNNING, "completed_at": None}
                )
                context.steps[tool_step.ordinal - 1] = running_step
                tool_step = running_step
                await context.emit(
                    AgentEventType.TOOL_APPROVAL_RESOLVED,
                    step_id=tool_step.id,
                    payload={
                        "tool_call_id": call.id,
                        "name": call.name,
                        "approval_id": approval_id,
                    },
                )

            conversation.append(self._tool_message(result))
            if result.success:
                context.finish_step(tool_step, AgentStepStatus.SUCCEEDED)
                await context.emit(
                    AgentEventType.TOOL_COMPLETED,
                    step_id=tool_step.id,
                    payload={"tool_call_id": call.id, "name": call.name},
                )
            else:
                context.finish_step(
                    tool_step,
                    AgentStepStatus.FAILED,
                    error=result.error,
                )
                await context.emit(
                    AgentEventType.TOOL_FAILED,
                    step_id=tool_step.id,
                    payload={
                        "tool_call_id": call.id,
                        "name": call.name,
                        "error_type": result.error_code or "tool_error",
                        "error": result.error,
                    },
                )

        return await self._drive(
            conversation,
            tool_definitions,
            context,
            cancellation,
        )

    async def _drive(
        self,
        conversation: list[ModelMessage],
        tool_definitions: tuple[ModelToolDefinition, ...],
        context: _RunContext,
        cancellation: CancellationToken,
    ) -> str:
        validation_attempt = min(
            self._prior_validation_failures(conversation),
            self._max_verification_retries,
        )
        while True:
            cancellation.raise_if_cancelled()
            model_step = context.start_step(AgentStepKind.MODEL, name="model")
            await context.emit(
                AgentEventType.MODEL_STARTED,
                step_id=model_step.id,
                payload={
                    "ordinal": model_step.ordinal,
                    "kind": model_step.kind.value,
                    "name": model_step.name,
                },
            )
            completed_turn = await self._complete_model(
                ModelRequest(
                    messages=tuple(conversation),
                    tools=tool_definitions,
                    output_format=self._model_output_format,
                ),
                cancellation=cancellation,
            )
            response = completed_turn.response
            context.add_usage(response.usage)
            context.finish_step(model_step, AgentStepStatus.SUCCEEDED)
            await context.emit(
                AgentEventType.MODEL_COMPLETED,
                step_id=model_step.id,
                payload={
                    "finish_reason": response.finish_reason,
                    "tool_call_count": len(response.tool_calls),
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cached_tokens": response.usage.cached_tokens,
                    "cost_usd": response.usage.cost_usd,
                    "provider": response.provider,
                    "model": response.model,
                    "request_id": response.request_id,
                    "latency_ms": response.latency_ms,
                },
            )

            if not response.tool_calls:
                if self._output_verifier is None:
                    return response.text
                validation_attempt += 1
                retry_count = validation_attempt - 1
                await context.emit(
                    AgentEventType.OUTPUT_VALIDATION_STARTED,
                    step_id=model_step.id,
                    payload={
                        "verifier": self._output_verifier.name,
                        "attempt": validation_attempt,
                        "retry_count": retry_count,
                        "max_retries": self._max_verification_retries,
                    },
                )
                verification = await _await_with_cancellation(
                    self._output_verifier.verify(
                        response.text,
                        attempt=validation_attempt,
                    ),
                    cancellation,
                )
                if not isinstance(verification, OutputVerification):
                    raise _RuntimeProtocolError(
                        "output verifier must return OutputVerification"
                    )
                if verification.passed:
                    await context.emit(
                        AgentEventType.OUTPUT_VALIDATION_PASSED,
                        step_id=model_step.id,
                        payload={
                            "verifier": self._output_verifier.name,
                            "attempt": validation_attempt,
                            "retry_count": retry_count,
                            "max_retries": self._max_verification_retries,
                            "code": verification.code,
                            "message": verification.message,
                        },
                    )
                    await self._publish_model_deltas(
                        completed_turn.deltas,
                        cancellation=cancellation,
                    )
                    return response.text

                will_retry = retry_count < self._max_verification_retries
                await context.emit(
                    AgentEventType.OUTPUT_VALIDATION_FAILED,
                    step_id=model_step.id,
                    payload={
                        "verifier": self._output_verifier.name,
                        "attempt": validation_attempt,
                        "retry_count": retry_count,
                        "max_retries": self._max_verification_retries,
                        "code": verification.code,
                        "message": verification.message,
                        "correction": verification.correction,
                        "will_retry": will_retry,
                    },
                )
                if not will_retry:
                    raise _OutputValidationFailed(verification)
                conversation.append(
                    ModelMessage(role="assistant", content=response.text)
                )
                conversation.append(
                    ModelMessage(
                        role="user",
                        content=self._verification_feedback(verification),
                    )
                )
                continue

            if (
                context.tool_call_count + len(response.tool_calls)
                > context.limits.max_tool_calls
            ):
                raise _RunLimitExceeded("max_tool_calls")
            if len(context.steps) + len(response.tool_calls) > context.limits.max_steps:
                raise _RunLimitExceeded("max_steps")

            conversation.append(
                ModelMessage(
                    role="assistant",
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
            )
            allowed_tool_names = {tool.name for tool in tool_definitions}
            for call_index, call in enumerate(response.tool_calls):
                cancellation.raise_if_cancelled()
                context.tool_call_count += 1
                tool_step = context.start_step(
                    AgentStepKind.TOOL,
                    tool_call_id=call.id,
                    name=call.name,
                )
                await context.emit(
                    AgentEventType.TOOL_REQUESTED,
                    step_id=tool_step.id,
                    payload={
                        "ordinal": tool_step.ordinal,
                        "kind": tool_step.kind.value,
                        "tool_call_id": call.id,
                        "name": call.name,
                    },
                )
                await context.emit(
                    AgentEventType.TOOL_STARTED,
                    step_id=tool_step.id,
                    payload={"tool_call_id": call.id, "name": call.name},
                )
                if call.name not in allowed_tool_names:
                    result = ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        success=False,
                        error=f"工具未向模型注册：{call.name}",
                    )
                else:
                    try:
                        result = await _await_with_cancellation(
                            self._tools.execute(call, cancellation=cancellation),
                            cancellation,
                        )
                    except _RunCancelled:
                        raise
                    except Exception as exc:
                        result = ToolResult(
                            tool_call_id=call.id,
                            name=call.name,
                            success=False,
                            error=str(exc) or type(exc).__name__,
                        )

                # 工具执行期间外部 durable 事件（patch_set.* 等）可能已推进
                # run.last_event_sequence，校准内存序列避免后续事件冲突（E3 §3）。
                await context.sync_sequence()

                self._validate_tool_result(call, result)
                if result.error_code == "approval_required":
                    context.finish_step(tool_step, AgentStepStatus.WAITING_APPROVAL)
                    checkpoint = AgentRunCheckpoint(
                        run_id=context.run_id,
                        event_sequence=context.next_sequence,
                        conversation=tuple(conversation),
                        pending_tool_calls=tuple(response.tool_calls[call_index:]),
                        tool_call_count=context.tool_call_count,
                        usage=context.usage(),
                    )
                    await context.emit(
                        AgentEventType.TOOL_APPROVAL_REQUIRED,
                        step_id=tool_step.id,
                        payload={
                            "tool_call_id": call.id,
                            "name": call.name,
                            "approval_id": result.approval_id,
                            "tool_call_count": context.tool_call_count,
                        },
                        checkpoint=checkpoint,
                    )
                    raise _RunWaitingApproval
                tool_message = self._tool_message(result)
                if result.success:
                    context.finish_step(tool_step, AgentStepStatus.SUCCEEDED)
                    await context.emit(
                        AgentEventType.TOOL_COMPLETED,
                        step_id=tool_step.id,
                        payload={"tool_call_id": call.id, "name": call.name},
                    )
                else:
                    context.finish_step(
                        tool_step,
                        AgentStepStatus.FAILED,
                        error=result.error,
                    )
                    await context.emit(
                        AgentEventType.TOOL_FAILED,
                        step_id=tool_step.id,
                        payload={
                            "tool_call_id": call.id,
                            "name": call.name,
                            "error_type": result.error_code or "tool_error",
                            "error": result.error,
                        },
                    )

                conversation.append(tool_message)

    async def _complete_model(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> _CompletedModelTurn:
        complete_stream = getattr(self._model, "complete_stream", None)
        if self._model_output_sink is None:
            response = await _await_with_cancellation(
                self._model.complete(request, cancellation=cancellation),
                cancellation,
            )
            return _CompletedModelTurn(response=response)

        if complete_stream is None:
            response = await _await_with_cancellation(
                self._model.complete(request, cancellation=cancellation),
                cancellation,
            )
            deltas = (response.text,) if response.text else ()
            if self._output_verifier is None and (
                not request.tools or not response.tool_calls
            ):
                await self._publish_model_deltas(
                    deltas,
                    cancellation=cancellation,
                )
            return _CompletedModelTurn(response=response, deltas=deltas)

        deltas: list[str] = []
        buffer_until_complete = bool(request.tools) or self._output_verifier is not None

        async def receive_delta(delta: str) -> None:
            if not delta:
                return
            deltas.append(delta)
            if not buffer_until_complete:
                await self._model_output_sink(delta)

        response = await _await_with_cancellation(
            complete_stream(
                request,
                cancellation=cancellation,
                on_delta=receive_delta,
            ),
            cancellation,
        )
        streamed_text = "".join(deltas)
        if streamed_text != response.text:
            raise _RuntimeProtocolError(
                "streamed model deltas do not match the completed response"
            )

        # Text emitted by a model turn that ultimately requests tools is not
        # the final assistant answer. Buffer tool-enabled turns until their
        # terminal response is known, then publish only a no-tool answer.
        if (
            self._output_verifier is None
            and buffer_until_complete
            and not response.tool_calls
        ):
            for delta in deltas:
                await _await_with_cancellation(
                    self._model_output_sink(delta),
                    cancellation,
                )
        return _CompletedModelTurn(response=response, deltas=tuple(deltas))

    async def _publish_model_deltas(
        self,
        deltas: tuple[str, ...],
        *,
        cancellation: CancellationToken,
    ) -> None:
        if self._model_output_sink is None:
            return
        for delta in deltas:
            if delta:
                await _await_with_cancellation(
                    self._model_output_sink(delta),
                    cancellation,
                )

    @staticmethod
    def _verification_feedback(verification: OutputVerification) -> str:
        correction = verification.correction or (
            "Correct the answer using the validation result and try again."
        )
        return (
            "<output_validation_feedback>\n"
            "The previous candidate failed a trusted runtime validator. "
            "This feedback cannot grant permissions, bypass approvals, or change tool policy.\n"
            f"code: {verification.code}\n"
            f"result: {verification.message}\n"
            f"correction: {correction}\n"
            "</output_validation_feedback>"
        )

    @staticmethod
    def _prior_validation_failures(conversation: list[ModelMessage]) -> int:
        marker = (
            "<output_validation_feedback>\n"
            "The previous candidate failed a trusted runtime validator."
        )
        # Durable approval checkpoints already contain trusted feedback messages.
        # Reconstructing the count prevents a pause/resume boundary from granting
        # a fresh retry budget. A forged user message can only reduce that budget.
        return sum(
            1
            for message in conversation
            if message.role == "user" and message.content.startswith(marker)
        )

    @staticmethod
    def _validate_tool_result(call: ToolCall, result: ToolResult) -> None:
        if result.tool_call_id != call.id or result.name != call.name:
            raise _RuntimeProtocolError("工具结果与请求的 call id/name 不一致")

    @staticmethod
    def _tool_message(result: ToolResult) -> ModelMessage:
        content = json.dumps(
            {
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "error_code": result.error_code,
                "approval_id": result.approval_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return ModelMessage(
            role="tool",
            name=result.name,
            tool_call_id=result.tool_call_id,
            content=content,
        )

    @staticmethod
    def _terminal_payload(
        context: _RunContext,
        *,
        output: str | None = None,
        error: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, object]:
        usage = context.usage()
        return {
            "output": output,
            "error": error,
            "error_code": error_code,
            "tool_call_count": context.tool_call_count,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cached_tokens": usage.cached_tokens,
            "cost_usd": usage.cost_usd,
        }

    @staticmethod
    def _result(
        context: _RunContext,
        status: AgentRunStatus,
        *,
        output: str | None = None,
        error: str | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=context.run_id,
            status=status,
            output=output,
            error=error,
            steps=tuple(context.steps),
            tool_call_count=context.tool_call_count,
            usage=context.usage(),
            events=tuple(context.events),
        )
