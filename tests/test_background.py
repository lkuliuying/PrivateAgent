"""受控后台任务生命周期测试。"""
from __future__ import annotations

import asyncio

import pytest

from personal_assistant.core.background import BackgroundTaskSupervisor


@pytest.mark.asyncio
async def test_supervisor_drains_completed_tasks():
    supervisor = BackgroundTaskSupervisor()
    completed: list[str] = []

    async def work() -> None:
        await asyncio.sleep(0)
        completed.append("done")

    supervisor.spawn(work, name="unit-work")
    await supervisor.drain(timeout=1.0)

    assert completed == ["done"]
    assert supervisor.stats() == {
        "queued": 0,
        "running": 0,
        "failed": 0,
        "deduplicated": 0,
        "recent_failures": [],
    }


@pytest.mark.asyncio
async def test_supervisor_records_failures_without_leaking_task_exception():
    supervisor = BackgroundTaskSupervisor()

    async def fail() -> None:
        raise RuntimeError("expected failure")

    supervisor.spawn(fail, name="unit-failure")
    await supervisor.drain(timeout=1.0)

    stats = supervisor.stats()
    assert stats["running"] == 0
    assert stats["failed"] == 1
    assert stats["recent_failures"] == [
        {"name": "unit-failure", "error": "expected failure"}
    ]


@pytest.mark.asyncio
async def test_supervisor_only_cancels_its_own_tasks_on_timeout():
    supervisor = BackgroundTaskSupervisor()
    unrelated = asyncio.create_task(asyncio.sleep(0.2), name="unrelated")

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    managed = supervisor.spawn(wait_forever, name="managed")
    await supervisor.drain(timeout=0.01)

    assert managed.cancelled()
    assert not unrelated.cancelled()
    unrelated.cancel()
    await asyncio.gather(unrelated, return_exceptions=True)


@pytest.mark.asyncio
async def test_supervisor_enforces_concurrency_limit():
    supervisor = BackgroundTaskSupervisor(max_concurrency=2)
    release = asyncio.Event()
    at_capacity = asyncio.Event()
    running = 0
    peak_running = 0
    completed: list[int] = []

    async def work(index: int) -> None:
        nonlocal running, peak_running
        running += 1
        peak_running = max(peak_running, running)
        if running == 2:
            at_capacity.set()
        try:
            await release.wait()
            completed.append(index)
        finally:
            running -= 1

    for index in range(6):
        supervisor.spawn(
            lambda index=index: work(index),
            name=f"limited-{index}",
            key=f"limited:{index}",
        )

    await asyncio.wait_for(at_capacity.wait(), timeout=1.0)
    await asyncio.sleep(0)
    assert supervisor.stats()["running"] == 2
    assert supervisor.stats()["queued"] == 4

    release.set()
    await supervisor.drain(timeout=1.0)

    assert peak_running == 2
    assert sorted(completed) == list(range(6))


@pytest.mark.asyncio
async def test_supervisor_deduplicates_active_resource_key():
    supervisor = BackgroundTaskSupervisor()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def work() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "done"

    first_submission = supervisor.submit(work, name="first", key="document:42")
    duplicate_submission = supervisor.submit(
        work,
        name="duplicate",
        key="document:42",
    )
    first = first_submission.task
    duplicate = duplicate_submission.task

    assert first_submission.created is True
    assert duplicate_submission.created is False
    assert duplicate is first
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert calls == 1
    assert supervisor.stats()["deduplicated"] == 1

    release.set()
    await supervisor.drain(timeout=1.0)
    replacement_submission = supervisor.submit(
        work,
        name="replacement",
        key="document:42",
    )
    replacement = replacement_submission.task
    await supervisor.drain(timeout=1.0)

    assert replacement_submission.created is True
    assert replacement is not first
    assert calls == 2


@pytest.mark.asyncio
async def test_cancel_all_bounds_cleanup_and_preserves_unrelated_task():
    supervisor = BackgroundTaskSupervisor()
    started = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_blocked = asyncio.Event()
    unrelated = asyncio.create_task(asyncio.sleep(1.0), name="unrelated-cleanup")

    async def work() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            await cleanup_blocked.wait()
            raise

    managed = supervisor.spawn(work, name="managed-cleanup")
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await supervisor.cancel_all(cleanup_timeout=0.01)

    assert cleanup_started.is_set()
    assert managed.cancelled()
    assert not unrelated.cancelled()
    unrelated.cancel()
    await asyncio.gather(unrelated, return_exceptions=True)
