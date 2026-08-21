"""Process-local lifecycle coordinator for feature-gated Agent runs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

import personal_assistant.core.db as dbmod
from personal_assistant.config import settings as cfg
from personal_assistant.logging_setup import get_logger

from .contracts import (
    AgentRunLimits,
    ModelMessage,
    ModelToolDefinition,
    ToolCall,
    ToolResult,
)
from .repository import AgentRunRepository, PersistentAgentRunner, SqlAgentRunEventSink
from .runtime import AgentRuntime, CancellationToken, ModelClient, ToolDispatcher
from .verification import (
    CompositeOutputVerifier,
    NonEmptyOutputVerifier,
    OutputVerifier,
)

logger = get_logger(__name__)

ToolDispatcherFactory = Callable[[AsyncSession, str], Awaitable[ToolDispatcher]]
ApprovalToolDispatcherFactory = Callable[
    [AsyncSession, str, str, str], Awaitable[ToolDispatcher]
]
OutputVerifierFactory = Callable[[AsyncSession, str], OutputVerifier]


def _output_verification_policy(
    workflow_verifier: OutputVerifier | None = None,
) -> tuple[OutputVerifier | None, int]:
    """Return the process-fixed verifier policy used by start and resume paths."""

    if not cfg.agent_output_verification_enabled:
        return None, 0
    verifiers: list[OutputVerifier] = [NonEmptyOutputVerifier()]
    if workflow_verifier is not None:
        verifiers.append(workflow_verifier)
    verifier: OutputVerifier = (
        verifiers[0]
        if len(verifiers) == 1
        else CompositeOutputVerifier(verifiers)
    )
    return verifier, cfg.agent_output_verification_max_retries


class _NoToolDispatcher:
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
            error="No tools are enabled for this AgentRun API slice",
        )


class AgentRunCoordinator:
    """Own cancellation tokens and background tasks for this API process."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._output_queues: dict[str, asyncio.Queue[str]] = {}

    def start(
        self,
        *,
        run_id: str,
        model: ModelClient,
        messages: tuple[ModelMessage, ...],
        limits: AgentRunLimits,
        tool_definitions: tuple[ModelToolDefinition, ...] = (),
        tool_dispatcher_factory: ToolDispatcherFactory | None = None,
        output_verifier_factory: OutputVerifierFactory | None = None,
        context_metadata: Mapping[str, Any] | None = None,
        stream_output: bool = False,
        # v0.7.0 验收修复（P0-1）：run 绑定的 reasoning_effort 透传到 runtime
        reasoning_effort: str | None = None,
    ) -> asyncio.Queue[str] | None:
        if run_id in self._tasks:
            raise RuntimeError(f"Agent run is already active: {run_id}")
        output_queue = asyncio.Queue[str](maxsize=256) if stream_output else None
        if output_queue is not None:
            self._output_queues[run_id] = output_queue
        cancellation = CancellationToken()
        task = asyncio.create_task(
            self._execute(
                run_id=run_id,
                model=model,
                messages=messages,
                limits=limits,
                cancellation=cancellation,
                tool_definitions=tool_definitions,
                tool_dispatcher_factory=tool_dispatcher_factory,
                output_verifier_factory=output_verifier_factory,
                context_metadata=context_metadata,
                output_queue=output_queue,
                reasoning_effort=reasoning_effort,
            ),
            name=f"agent-run:{run_id}",
        )
        self._tokens[run_id] = cancellation
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._forget(run_id))
        return output_queue

    def cancel(self, run_id: str) -> bool:
        token = self._tokens.get(run_id)
        if token is None:
            return False
        token.cancel()
        return True

    def resume(
        self,
        *,
        run_id: str,
        approval_id: str,
        approval_token: str,
        model: ModelClient,
        tool_definitions: tuple[ModelToolDefinition, ...],
        tool_dispatcher_factory: ApprovalToolDispatcherFactory,
        output_verifier_factory: OutputVerifierFactory | None = None,
        # v0.7.0 验收修复（P0-1）：resume 沿用 run 绑定的 reasoning_effort
        reasoning_effort: str | None = None,
    ) -> None:
        """Resume one durable approval checkpoint without exposing its raw token."""

        if run_id in self._tasks:
            raise RuntimeError(f"Agent run is already active: {run_id}")
        cancellation = CancellationToken()
        task = asyncio.create_task(
            self._resume_execute(
                run_id=run_id,
                approval_id=approval_id,
                approval_token=approval_token,
                model=model,
                cancellation=cancellation,
                tool_definitions=tool_definitions,
                tool_dispatcher_factory=tool_dispatcher_factory,
                output_verifier_factory=output_verifier_factory,
                output_queue=self._output_queues.get(run_id),
                reasoning_effort=reasoning_effort,
            ),
            name=f"agent-run-resume:{run_id}",
        )
        self._tokens[run_id] = cancellation
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._forget(run_id))

    def is_active(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def output_queue(self, run_id: str) -> asyncio.Queue[str] | None:
        """Return the process-local output queue for the single chat subscriber."""

        return self._output_queues.get(run_id)

    def release_output_queue(
        self,
        run_id: str,
        queue: asyncio.Queue[str] | None,
    ) -> None:
        if queue is not None and self._output_queues.get(run_id) is queue:
            self._output_queues.pop(run_id, None)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        if not tasks:
            self._output_queues.clear()
            return
        for token in self._tokens.values():
            token.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0,
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self._output_queues.clear()

    async def _execute(
        self,
        *,
        run_id: str,
        model: ModelClient,
        messages: tuple[ModelMessage, ...],
        limits: AgentRunLimits,
        cancellation: CancellationToken,
        tool_definitions: tuple[ModelToolDefinition, ...],
        tool_dispatcher_factory: ToolDispatcherFactory | None,
        output_verifier_factory: OutputVerifierFactory | None,
        context_metadata: Mapping[str, Any] | None,
        output_queue: asyncio.Queue[str] | None,
        reasoning_effort: str | None = None,
    ) -> None:
        try:
            async with dbmod.async_session_factory() as db:
                repository = AgentRunRepository(db)
                tools = (
                    await tool_dispatcher_factory(db, run_id)
                    if tool_dispatcher_factory is not None
                    else _NoToolDispatcher()
                )

                async def publish_output(delta: str) -> None:
                    if output_queue is not None:
                        await output_queue.put(delta)

                workflow_verifier = (
                    output_verifier_factory(db, run_id)
                    if output_verifier_factory is not None
                    else None
                )
                output_verifier, max_verification_retries = (
                    _output_verification_policy(workflow_verifier)
                )
                runtime = AgentRuntime(
                    model,
                    tools,
                    model_output_sink=(
                        publish_output if output_queue is not None else None
                    ),
                    output_verifier=output_verifier,
                    max_verification_retries=max_verification_retries,
                    reasoning_effort=reasoning_effort,
                )
                result = await runtime.run(
                    messages,
                    limits=limits,
                    cancellation=cancellation,
                    tool_definitions=tool_definitions,
                    run_id=run_id,
                    event_sink=SqlAgentRunEventSink(repository),
                    context_metadata=context_metadata,
                )
                # E3：run 进入终态时重建 Artifact 投影并生成 final_report
                # （独立 session 读 durable facts；flag 关闭时 no-op）
                await _project_terminal_artifacts(run_id, result.status.value)
        except Exception as exc:  # noqa: BLE001
            # Event persistence failures intentionally leave the last committed
            # state for reconciliation. Never log provider or database payloads.
            logger.error(
                "agent run background execution stopped",
                run_id=run_id,
                error_type=type(exc).__name__,
            )

    async def _resume_execute(
        self,
        *,
        run_id: str,
        approval_id: str,
        approval_token: str,
        model: ModelClient,
        cancellation: CancellationToken,
        tool_definitions: tuple[ModelToolDefinition, ...],
        tool_dispatcher_factory: ApprovalToolDispatcherFactory,
        output_verifier_factory: OutputVerifierFactory | None,
        output_queue: asyncio.Queue[str] | None,
        reasoning_effort: str | None = None,
    ) -> None:
        try:
            async with dbmod.async_session_factory() as db:
                repository = AgentRunRepository(db)
                tools = await tool_dispatcher_factory(
                    db,
                    run_id,
                    approval_id,
                    approval_token,
                )

                async def publish_output(delta: str) -> None:
                    if output_queue is not None:
                        await output_queue.put(delta)

                workflow_verifier = (
                    output_verifier_factory(db, run_id)
                    if output_verifier_factory is not None
                    else None
                )
                output_verifier, max_verification_retries = (
                    _output_verification_policy(workflow_verifier)
                )
                result = await PersistentAgentRunner(
                    AgentRuntime(
                        model,
                        tools,
                        model_output_sink=(
                            publish_output if output_queue is not None else None
                        ),
                        output_verifier=output_verifier,
                        max_verification_retries=max_verification_retries,
                        reasoning_effort=reasoning_effort,
                    ),
                    repository,
                ).resume(
                    run_id=run_id,
                    approval_id=approval_id,
                    cancellation=cancellation,
                    tool_definitions=tool_definitions,
                )
                # E3：审批恢复后 run 进入终态时同样重建 Artifact 投影
                await _project_terminal_artifacts(run_id, result.status.value)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "agent run approval resume stopped",
                run_id=run_id,
                error_type=type(exc).__name__,
            )

    def _forget(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._tokens.pop(run_id, None)


async def _project_terminal_artifacts(run_id: str, status: str) -> None:
    """E3：run 终态时重建 Artifact 投影（独立 session；失败不影响主流程）。

    投影只读 durable facts（executions / coding_patch_sets），幂等去重；
    ``PA_CODING_ARTIFACTS_ENABLED`` 关闭时整体 no-op。
    """
    from ..config import settings as cfg

    if not cfg.coding_artifacts_enabled:
        return
    from ..core.artifact_projection import ArtifactProjectionService

    try:
        async with dbmod.async_session_factory() as session:
            await ArtifactProjectionService(session).rebuild_terminal(
                run_id=run_id, status=status
            )
    except Exception:  # noqa: BLE001 - 投影失败不影响 run 事实
        logger.error(
            "terminal artifact projection stopped",
            run_id=run_id,
            exc_info=True,
        )
