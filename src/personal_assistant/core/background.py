"""受控后台任务生命周期。

路由提交的导入、OCR、扫描任务必须在这里登记，避免裸 ``create_task`` 的异常
无人读取，也让测试和应用关停只等待自己创建的任务，而不是误伤事件循环中的
pytest、HTTP 客户端或运行时任务。
"""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from ..logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TaskSubmission:
    """Structured result that distinguishes new work from active-key deduplication."""

    task: asyncio.Task[Any]
    created: bool


class BackgroundTaskSupervisor:
    def __init__(
        self, *, max_concurrency: int = 4, failure_history: int = 20
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency 必须大于 0")
        self._max_concurrency = max_concurrency
        self._tasks: set[asyncio.Task[Any]] = set()
        self._tasks_by_key: dict[str, asyncio.Task[Any]] = {}
        self._task_keys: dict[asyncio.Task[Any], str] = {}
        self._failures: deque[dict[str, str]] = deque(maxlen=failure_history)
        self._failure_count = 0
        self._deduplicated = 0
        self._running = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._semaphore: asyncio.Semaphore | None = None

    def spawn(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        name: str,
        key: str | None = None,
        limited: bool = True,
    ) -> asyncio.Task[Any]:
        """Backward-compatible task-only API; prefer submit when dedupe matters."""
        return self.submit(
            factory,
            name=name,
            key=key,
            limited=limited,
        ).task

    def submit(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        name: str,
        key: str | None = None,
        limited: bool = True,
    ) -> TaskSubmission:
        """Register lazy work and report whether this call actually created it."""
        resource_key = key or name
        existing = self._tasks_by_key.get(resource_key)
        if existing is not None and not existing.done():
            self._deduplicated += 1
            return TaskSubmission(task=existing, created=False)

        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            if self._tasks:
                raise RuntimeError("后台任务不能跨事件循环迁移")
            self._loop = loop
            self._semaphore = asyncio.Semaphore(self._max_concurrency)

        async def run() -> Any:
            if not limited:
                self._running += 1
                try:
                    return await factory()
                finally:
                    self._running -= 1

            assert self._semaphore is not None
            async with self._semaphore:
                self._running += 1
                try:
                    return await factory()
                finally:
                    self._running -= 1

        task = asyncio.create_task(run(), name=name)
        self._tasks.add(task)
        self._tasks_by_key[resource_key] = task
        self._task_keys[task] = resource_key
        task.add_done_callback(self._on_done)
        return TaskSubmission(task=task, created=True)

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        resource_key = self._task_keys.pop(task, None)
        if resource_key and self._tasks_by_key.get(resource_key) is task:
            self._tasks_by_key.pop(resource_key, None)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is None:
            return
        name = task.get_name()
        self._failure_count += 1
        self._failures.append({"name": name, "error": str(error)})
        logger.error("后台任务失败", task=name, error=str(error))

    async def drain(self, *, timeout: float = 10.0) -> None:
        """等待当前受控任务完成；超时后只取消本 supervisor 管理的任务。"""
        deadline = monotonic() + timeout
        while self._tasks:
            remaining = deadline - monotonic()
            if remaining <= 0:
                await self.cancel_all()
                return
            snapshot = tuple(self._tasks)
            _, pending = await asyncio.wait(snapshot, timeout=remaining)
            if pending and monotonic() >= deadline:
                await self.cancel_all()
                return

    async def cancel_all(self, *, cleanup_timeout: float = 5.0) -> None:
        """Cancel managed tasks while bounding their cancellation cleanup window.

        Workers may catch ``CancelledError`` to persist a retryable terminal state.
        They receive one grace window for that write; a second cancellation prevents a
        stuck database/network cleanup from blocking application shutdown forever.
        """
        if cleanup_timeout < 0:
            raise ValueError("cleanup_timeout must be non-negative")
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if not tasks:
            return

        _, pending = await asyncio.wait(tasks, timeout=cleanup_timeout)
        if not pending:
            return

        logger.warning(
            "background task cancellation cleanup timed out",
            pending=len(pending),
            cleanup_timeout=cleanup_timeout,
        )
        for task in pending:
            task.cancel()
        # A short second grace lets the repeated CancelledError unwind cleanup code,
        # while asyncio.wait guarantees even a cancellation-suppressing task cannot
        # make shutdown wait without a bound.
        _, stubborn = await asyncio.wait(pending, timeout=0.25)
        if stubborn:
            logger.error(
                "background tasks ignored repeated cancellation",
                tasks=sorted(task.get_name() for task in stubborn),
            )

    def stats(self) -> dict[str, Any]:
        return {
            "queued": max(0, len(self._tasks) - self._running),
            "running": self._running,
            "failed": self._failure_count,
            "deduplicated": self._deduplicated,
            "recent_failures": list(self._failures),
        }


background_tasks = BackgroundTaskSupervisor()
