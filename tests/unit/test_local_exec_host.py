"""本机命令通过真实 Rust 宿主执行的边界与资源清理。"""
import asyncio
import os
import sys

import pytest

from private_agent_local import policy
from private_agent_local.entry import parent_alive
from private_agent_local.executor import host_path, run_command


@pytest.mark.asyncio
async def test_missing_exec_host_never_falls_back_to_python_executor(tmp_path):
    with pytest.raises(ValueError, match="缺少可信执行宿主"):
        await run_command(tmp_path, [sys.executable, "-c", "open('unexpected', 'w').write('bad')"], executable=tmp_path / "missing.exe")
    assert not (tmp_path / "unexpected").exists()


@pytest.mark.asyncio
async def test_real_host_returns_complete_output_and_kills_background_descendants(tmp_path):
    assert host_path().is_file(), "先构建 Rust 执行器，不把未执行验收标记为通过"
    code = (
        "import subprocess,sys; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "Path('child.pid').write_text(str(child.pid)); print('done')"
    )
    result = await run_command(tmp_path, [sys.executable, "-c", code])
    assert result["returncode"] == 0
    assert result["stdout"].strip() == "done"
    assert len(result["execution_host_sha256"]) == 64
    assert result["sandbox_available"] is False
    child = int((tmp_path / "child.pid").read_text())
    for _ in range(100):
        if not parent_alive(child):
            break
        await asyncio.sleep(0.01)
    assert not parent_alive(child)


@pytest.mark.asyncio
async def test_real_host_timeout_and_cancel_stop_process(tmp_path):
    code = "import os,time; from pathlib import Path; Path('parent.pid').write_text(str(os.getpid())); time.sleep(60)"
    with pytest.raises(TimeoutError):
        await run_command(tmp_path, [sys.executable, "-c", code], timeout=1)
    assert not parent_alive(int((tmp_path / "parent.pid").read_text()))
    task = asyncio.create_task(run_command(tmp_path, [sys.executable, "-c", code]))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not parent_alive(int((tmp_path / "parent.pid").read_text()))


@pytest.mark.asyncio
async def test_real_host_drains_output_before_returning_exit_and_bounds_bytes(tmp_path):
    for _ in range(3):
        result = await run_command(tmp_path, [sys.executable, "-c", "import sys; sys.stdout.write('x'*25000+'TAIL'); sys.stderr.write('END')"])
        assert result["stdout"].endswith("TAIL") and len(result["stdout"]) == 25004
        assert result["stderr"] == "END" and not result["truncated"]
    result = await run_command(tmp_path, [sys.executable, "-c", "print('x'*100000)"])
    assert result["truncated"] and len(result["stdout"]) == 32000


@pytest.mark.skipif(os.name != "nt", reason="受控 PowerShell 只在 Windows 客户端提供")
@pytest.mark.asyncio
async def test_real_host_runs_registered_powershell_inside_project(tmp_path):
    (tmp_path / "visible.txt").write_text("ok", encoding="utf-8")
    plan = policy.powershell_plan(
        tmp_path,
        "Get-ChildItem",
        ["-LiteralPath", ".", "-Name"],
        "full_access",
    )

    result = await run_command(tmp_path, list(plan.argv))

    assert result["returncode"] == 0
    assert "visible.txt" in result["stdout"]
    assert result["stderr"] == ""
