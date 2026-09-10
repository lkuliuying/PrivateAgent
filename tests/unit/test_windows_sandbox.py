"""真实沙箱身份、权限清理、进程崩溃和不支持路径的正反对照。"""
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from private_agent_core.execution.contracts import ExecStartParams
from private_agent_core.execution.exec_host_client import (
    ExecHostClient,
    ExecutorUnavailable,
)
from private_agent_local import files
from private_agent_local.executor import host_path, run_command
from private_agent_local.policy import powershell_plan
from private_agent_local.windows_sandbox import (
    SandboxLease,
    WindowsSecurity,
    runtime_roots,
)
from private_agent_local.workspaces import FileLock

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows AppContainer 原生边界")]


@pytest.mark.parametrize("extension", [".cmd", ".bat", ".exe"])
async def test_python_runtime_grants_follow_the_actual_entrypoint(tmp_path, monkeypatch, extension):
    runtime, base = tmp_path / "tool-copy", tmp_path / "unrelated-interpreter"
    runtime.mkdir()
    base.mkdir()
    command = runtime / ("python" + extension)
    command.write_bytes(b"synthetic-runtime-entry")
    monkeypatch.setattr(sys, "base_prefix", str(base))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    roots = runtime_roots([str(command)], {"PATH": str(runtime), "SYSTEMROOT": os.environ["SYSTEMROOT"]})
    assert set(roots) == ({runtime, base} if extension == ".exe" else {runtime})


async def test_journal_write_failure_releases_ownership_lock(tmp_path, monkeypatch):
    root, state = tmp_path / "project", tmp_path / "leases"
    root.mkdir()
    def failed_save(self):
        raise OSError("fixture journal failure")
    monkeypatch.setattr(SandboxLease, "_save", failed_save)
    _, env = files.prepare_process([os.environ["COMSPEC"]])
    with pytest.raises(OSError, match="fixture journal failure"):
        await SandboxLease.prepare(root, [os.environ["COMSPEC"]], env, directory=state)
    assert not list(state.glob("*.json"))
    locks = list(state.glob("*.lock"))
    assert len(locks) == 1
    FileLock(locks[0]).close()


async def test_missing_sandbox_identity_and_invalid_policy_never_execute(tmp_path):
    command, env = files.prepare_process([sys.executable, "-c", "from pathlib import Path; Path('bad').write_text('bad')"])
    client = ExecHostClient([str(host_path())], cwd=str(tmp_path), env=env)
    try:
        await client.start()
        for network in ("none", "allowlist"):
            with pytest.raises(ExecutorUnavailable):
                await client.start_execution(ExecStartParams(execution_id=str(uuid.uuid4()), argv=command,
                    cwd=str(tmp_path), env_diff=env, sandbox_policy_hash="deny-missing-identity", network_policy=network))
        assert not (tmp_path / "bad").exists()
    finally:
        await client.close()


async def test_real_token_and_child_inherit_appcontainer_and_no_capabilities(tmp_path):
    code = (
        "import ctypes as c,subprocess,sys; from ctypes import wintypes as w; "
        "k=c.WinDLL('kernel32'); a=c.WinDLL('advapi32'); k.GetCurrentProcess.restype=w.HANDLE; "
        "a.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]; "
        "a.GetTokenInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]; "
        "t=w.HANDLE(); assert a.OpenProcessToken(k.GetCurrentProcess(),8,c.byref(t)); "
        "flag=w.DWORD(); n=w.DWORD(); assert a.GetTokenInformation(t,29,c.byref(flag),4,c.byref(n)); "
        "print('APPCONTAINER',flag.value); assert flag.value==1; "
        "caps=c.create_string_buffer(4096); assert a.GetTokenInformation(t,30,caps,4096,c.byref(n)); "
        "print('CAPABILITIES',w.DWORD.from_buffer(caps).value); assert w.DWORD.from_buffer(caps).value==0; "
        "k.CloseHandle.argtypes=[w.HANDLE]; k.CloseHandle(t)"
    )
    child = "import subprocess,sys; subprocess.run([sys.executable,'-c'," + repr(code) + "],check=True)"
    result = await run_command(tmp_path, [sys.executable, "-c", code + "; " + child])
    assert result["returncode"] == 0, result["stderr"]
    assert result["stdout"].count("APPCONTAINER 1") == 2
    assert result["stdout"].count("CAPABILITIES 0") == 2


async def test_restricted_argv_preserves_quotes_unicode_and_trailing_slashes(tmp_path):
    arguments = ['中文 空格', 'a"b', 'C:\\path with spaces\\', 'back\\\\"quote']
    result = await run_command(tmp_path, [sys.executable, "-c", "import sys,json; print(json.dumps(sys.argv[1:]))", *arguments])
    assert result["returncode"] == 0, result["stderr"]
    assert json.loads(result["stdout"]) == arguments


async def test_read_write_boundaries_runtime_readonly_and_cleanup(tmp_path):
    root, runtime = tmp_path / "project", tmp_path / "runtime"
    root.mkdir()
    runtime.mkdir()
    fixture = runtime / "sandbox-fixture.cmd"
    fixture.write_text("@echo off\r\necho TOOL_STARTED\r\necho inside>inside.txt\r\necho escape>..\\outside.txt\r\necho change>\"%~dp0immutable.txt\"\r\ntype ..\\private.txt\r\n", encoding="ascii")
    (runtime / "immutable.txt").write_text("original")
    (tmp_path / "private.txt").write_text("PRIVATE_SENTINEL")
    state = tmp_path / "leases"
    result = await run_command(root, [str(fixture)], sandbox_directory=state)
    assert "TOOL_STARTED" in result["stdout"] and "PRIVATE_SENTINEL" not in result["stdout"]
    assert (root / "inside.txt").is_file() and not (tmp_path / "outside.txt").exists()
    assert (runtime / "immutable.txt").read_text() == "original"
    assert not list(state.glob("*.json"))


async def test_registered_powershell_stays_in_authorized_workspace(tmp_path):
    root = tmp_path / "中文 项目"
    root.mkdir()
    (root / "inside.txt").write_text("ok")
    (tmp_path / "outside.txt").write_text("PRIVATE_SENTINEL")
    plan = powershell_plan(root, "Get-ChildItem", ["-LiteralPath", ".", "-Name"], "workspace")
    result = await run_command(root, list(plan.argv))
    assert result["returncode"] == 0, result["stderr"]
    assert "inside.txt" in result["stdout"] and "outside.txt" not in result["stdout"]


async def test_distinct_sandbox_identity_does_not_grant_other_workspace(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    other = second / "owned.txt"
    other.write_text("original")
    _, env = files.prepare_process([sys.executable])
    a = await SandboxLease.prepare(first, [sys.executable], env, directory=tmp_path / "leases")
    b = await SandboxLease.prepare(second, [sys.executable], env, directory=tmp_path / "leases")
    try:
        assert a.name != b.name
        code = f"from pathlib import Path; print('STARTED');\ntry: Path({str(other)!r}).write_text('bad')\nexcept PermissionError: print('DENIED')"
        client = ExecHostClient([str(host_path())], env=env)
        try:
            await client.start()
            a.bind(client.pid)
            await client.start_execution(ExecStartParams(execution_id=str(uuid.uuid4()), argv=[sys.executable, "-c", code],
                cwd=str(first), env_diff=a.environment, sandbox_policy_hash="separate-workspaces", appcontainer=True, appcontainer_profile=a.name))
            output = ""
            while True:
                event = await client.next_event(timeout=10)
                assert event is not None
                output += event.data or ""
                if event.notification.value == "execution/exited":
                    assert event.exit_code == 0
                    break
            assert "STARTED" in output and "DENIED" in output and other.read_text() == "original"
        finally:
            await client.close()
    finally:
        await asyncio.to_thread(a.close)
        await asyncio.to_thread(b.close)


async def test_junction_rejected_without_grant_or_write(tmp_path):
    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    junction = root / "alias"
    process = await asyncio.create_subprocess_exec("cmd", "/d", "/c", "mklink", "/J", str(junction), str(outside),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    output, error = await process.communicate()
    assert process.returncode == 0, (output, error)
    _, env = files.prepare_process([sys.executable])
    with pytest.raises(ValueError, match="联接"):
        await SandboxLease.prepare(root, [sys.executable], env, directory=tmp_path / "leases")
    assert list(outside.iterdir()) == []


async def test_workspace_hardlink_rejected_before_acl_grant(tmp_path):
    root, state = tmp_path / "project", tmp_path / "leases"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original")
    os.link(outside, root / "inside.txt")
    with pytest.raises(ValueError, match="硬链接"):
        await run_command(root, [sys.executable, "-c", "from pathlib import Path; Path('inside.txt').write_text('bad')"],
            sandbox_directory=state)
    assert outside.read_text() == "original"
    assert not list(state.glob("*.json")) and not list(state.glob("*.lock"))


async def test_crash_journal_is_reconciled_without_pid_only_takeover(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    state = tmp_path / "leases"
    source = Path(__file__).resolve().parents[2] / "src"
    code = (f"import sys,os; sys.path.insert(0,{str(source)!r}); from private_agent_local import files; "
            "from private_agent_local.windows_sandbox import SandboxLease; from pathlib import Path; "
            f"SandboxLease(Path({str(root)!r}), [sys.executable], files.prepare_process([sys.executable])[1], directory=Path({str(state)!r})); print(os.getpid(),flush=True); os._exit(23)")
    _, env = files.prepare_process([sys.executable])
    child = await asyncio.create_subprocess_exec(sys.executable, "-B", "-c", code, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    output, error = await child.communicate()
    assert child.returncode == 23, error
    records = list(state.glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    # 虚拟环境启动器可转交另一个进程，核对实际创建租约的进程身份。
    assert record["owner"]["pid"] == int(output.strip()) and record["owner"]["created"] > 0
    assert WindowsSecurity().identity(record["owner"]["pid"]) is None
    await asyncio.to_thread(SandboxLease.recover, state)
    assert not list(state.glob("*.json"))
    assert WindowsSecurity().identity(os.getpid()) is not None
