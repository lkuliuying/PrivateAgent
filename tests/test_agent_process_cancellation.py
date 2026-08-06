"""R3 故障门禁：子进程/线程取消清理与 owner 监控。

覆盖：
- ``_execute_command`` / ``_run_git`` 在 CancelledError 时杀掉子进程并重抛；
- ``ProjectService.search_content`` 的 stop_event 协作退让（grep to_thread）；
- tool_adapter 把取消绑定到 grep stop_event；
- SSE 断线（流关闭）触发 run 取消（见 test_chat_agent_runtime_compat.py 补充）。
- owner 监控 verify 失败 → coordinator.shutdown（main_api.monitor_agent_runtime_owner）。
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import threading

import pytest

from personal_assistant.core.code_tools import _execute_command, _run_git
from personal_assistant.core.models import Project, ProjectFile
from personal_assistant.core.projects import ProjectService


def _tasklist_has_pid(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return f"\"{pid}\"" in out.stdout
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.asyncio
async def test_execute_command_kills_subprocess_on_cancellation(tmp_path):
    pidfile = tmp_path / "child.pid"
    script = (
        f"import os,time;open({str(pidfile)!r},'w').write(str(os.getpid()));"
        "time.sleep(60)"
    )
    task = asyncio.create_task(
        _execute_command([sys.executable, "-c", script], str(tmp_path))
    )
    # 等待子进程写入 PID 后取消
    deadline = asyncio.get_event_loop().time() + 10
    while not pidfile.exists() and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
    assert pidfile.exists(), "子进程未在超时前写入 PID"
    child_pid = int(pidfile.read_text().strip())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.5)
    assert _tasklist_has_pid(child_pid) is False, "取消后子进程仍然存活"


@pytest.mark.asyncio
async def test_run_git_kills_subprocess_on_cancellation(monkeypatch):
    """用可取消的假子进程验证 _run_git 的 CancelledError 清理路径。"""

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.killed = False

        async def communicate(self) -> tuple[bytes, bytes]:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            return b"", b""

        def kill(self) -> None:
            self.killed = True
            self.returncode = 137

        async def wait(self) -> int:
            self.returncode = 137
            return 137

    fake = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):  # noqa: ARG001
        return fake

    monkeypatch.setattr(
        "personal_assistant.core.code_tools.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    task = asyncio.create_task(_run_git("C:\\work", ["status"]))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.killed is True, "git 子进程在取消时必须被 kill"


@pytest.mark.asyncio
async def test_grep_stop_event_short_circuits_scan(db, tmp_path):
    project = Project(name=f"cancel-proj-{tmp_path.name}", root_path=str(tmp_path))
    db.add(project)
    await db.flush()
    files = []
    for i in range(20):
        rel = f"file-{i}.txt"
        (tmp_path / rel).write_text(f"needle in file {i}\n", encoding="utf-8")
        files.append(
            ProjectFile(
                project_id=project.id,
                rel_path=rel,
                language="txt",
                size_bytes=20,
                is_binary=False,
            )
        )
    db.add_all(files)
    await db.commit()

    stop = threading.Event()
    stop.set()  # 预先置位：扫描应在第一处检查点立即退出
    result = await ProjectService(db).search_content(project.id, "needle", stop_event=stop)
    assert result == {"results": [], "count": 0, "truncated": False}

    stop = threading.Event()
    result = await ProjectService(db).search_content(project.id, "needle", stop_event=stop)
    assert result["count"] == 20


@pytest.mark.asyncio
async def test_tool_adapter_binds_grep_stop_event_to_cancellation(db, monkeypatch):
    from personal_assistant.agents import CancellationToken
    from personal_assistant.core.tool_adapter import build_read_only_tool_registry

    captured: dict = {}

    async def fake_search_content(self, project_id, pattern, stop_event=None):  # noqa: ARG001
        captured["stop_event"] = stop_event
        return {"results": [], "count": 0, "truncated": False}

    monkeypatch.setattr(ProjectService, "search_content", fake_search_content)
    registry = build_read_only_tool_registry(db)
    spec = registry.get("grep_code")
    assert spec is not None

    token = CancellationToken()
    await spec.executor({"project_id": 1, "pattern": "x"}, token)
    event = captured["stop_event"]
    assert isinstance(event, threading.Event)
    # 正常/取消路径都会置位（finally 语义：扫描线程应停止）；取消路径断言如下
    token.cancel()
    await asyncio.sleep(0.05)
    assert event.is_set() is True, "取消后 grep stop_event 必须置位"
    with pytest.raises(RuntimeError, match="已取消"):
        await spec.executor({"project_id": 1, "pattern": "x"}, token)


@pytest.mark.asyncio
async def test_owner_monitor_shuts_down_coordinator_when_lock_lost(monkeypatch):
    from personal_assistant.main_api import monitor_agent_runtime_owner

    class FakeGuard:
        def __init__(self) -> None:
            self.verify_calls = 0

        async def verify(self) -> bool:
            self.verify_calls += 1
            return False

    class FakeCoordinator:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        async def shutdown(self) -> None:
            self.shutdown_calls += 1

    guard = FakeGuard()
    coordinator = FakeCoordinator()
    await monitor_agent_runtime_owner(guard, coordinator, interval=0.01)
    assert guard.verify_calls >= 1
    assert coordinator.shutdown_calls == 1
    # verify 失败后监控退出，不再继续轮询
    calls = guard.verify_calls
    await asyncio.sleep(0.05)
    assert guard.verify_calls == calls


@pytest.mark.asyncio
async def test_owner_monitor_keeps_polling_while_lock_held(monkeypatch):
    from personal_assistant.main_api import monitor_agent_runtime_owner

    class FakeGuard:
        def __init__(self) -> None:
            self.verify_calls = 0

        async def verify(self) -> bool:
            self.verify_calls += 1
            return True

    class FakeCoordinator:
        shutdown_calls = 0

        async def shutdown(self) -> None:
            FakeCoordinator.shutdown_calls += 1

    guard = FakeGuard()
    coordinator = FakeCoordinator()
    monitor = asyncio.create_task(
        monitor_agent_runtime_owner(guard, coordinator, interval=0.01)
    )
    await asyncio.sleep(0.06)
    monitor.cancel()
    with pytest.raises(asyncio.CancelledError):
        await monitor
    assert guard.verify_calls >= 3
    assert FakeCoordinator.shutdown_calls == 0
