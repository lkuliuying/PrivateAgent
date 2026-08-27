"""只读工具 bounded 并发调度器（专项计划 §9.4/AD-T07/CT-4）。

并发资格（全部满足才可并行）：

    parallel_safe && side_effect_class == none && idempotent
      && approval_mode == auto（is_parallel_eligible()）

规则：
- 一轮内所有调用都合格才允许并发；只要出现任何不合格（副作用/需审批）
  调用，整轮退化为按提交顺序串行——副作用工具并发数恒为 1；
- bounded task group：并发上限 max_concurrency，任一任务取消时收敛全部
  子任务；
- 结果按原 tool call 顺序返回，完成顺序不影响 replay。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence


@dataclass(frozen=True, slots=True)
class ScheduledCall:
    """一个待调度调用及其 AD-T07 并发资格结论。"""

    call_id: str
    parallel_eligible: bool


class ParallelScheduleError(ValueError):
    """调度输入非法。"""


def plan_schedule(
    calls: Sequence[ScheduledCall], *, max_concurrency: int = 4
) -> tuple[bool, int]:
    """判定本轮调度形态。

    返回 ``(parallel, concurrency)``：
    - 任一调用不合格 → (False, 1)（整轮串行）；
    - 全部合格 → (True, min(max_concurrency, len(calls)))，至少 1。
    """
    if not calls:
        raise ParallelScheduleError("调度入参不能为空")
    if max_concurrency < 1:
        raise ParallelScheduleError("max_concurrency 必须 >= 1")
    eligible = all(item.parallel_eligible for item in calls)
    if not eligible:
        return (False, 1)
    return (True, max(1, min(max_concurrency, len(calls))))


async def run_scheduled(
    calls: Sequence[ScheduledCall],
    execute_one: Callable[[ScheduledCall], Awaitable[Any]],
    *,
    max_concurrency: int = 4,
) -> list[Any]:
    """执行一轮调用并按原顺序返回结果。

    - 串行模式：逐个 await，任何异常直接上抛（由调用方转换为工具失败）；
    - 并行模式：asyncio.TaskGroup + 有界信号量；任一任务取消/失败时，
      TaskGroup 收敛其余子任务后统一上抛首个异常。
    """
    parallel, concurrency = plan_schedule(calls, max_concurrency=max_concurrency)
    if not parallel:
        return [await execute_one(item) for item in calls]

    semaphore = asyncio.Semaphore(concurrency)
    results: list[Any] = [None] * len(calls)

    async def _run(index: int, item: ScheduledCall) -> None:
        async with semaphore:
            results[index] = await execute_one(item)

    async with asyncio.TaskGroup() as task_group:
        for index, item in enumerate(calls):
            task_group.create_task(_run(index, item))
    return results
