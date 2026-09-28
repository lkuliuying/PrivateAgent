"""受限内联命令经过真实工具入口时的参数、任务限制和系统沙箱边界。"""
import asyncio
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_execution_autonomy import capture_start
from test_execution_autonomy import session as session
from test_local_executor import call

from private_agent_local import policy

pytestmark = pytest.mark.asyncio
windows_sandbox = pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows AppContainer 原生边界")


@pytest.mark.parametrize("argv", [
    ["python", "-c", "print('中文;引号\\\\路径')\nprint(2)"],
    ["python3", "-B", "-c", "print(1)"],
    ["python", "-cprint(1)"],
    ["python", "-Icprint(1)"],
    ["node", "-e", "console.log('中文');\nconsole.log('a\\\\b')"],
    ["node", "--eval=console.log('ok')"],
    ["node", "-p", "1 + 1"],
    ["node", "--print", "1 + 1"],
    ["node", "-pe", "1 + 1"],
    ["python", "-c", "print(1)", "--eval"],
])
async def test_restricted_policy_preserves_supported_inline_argv(argv):
    plan = policy.execution_plan(argv, "workspace")
    assert plan.argv == tuple(argv)
    assert plan.display_argv == tuple(argv)
    assert plan.automatic
    assert plan.inline_code


@pytest.mark.parametrize("argv", [
    ["python", "-mcompileall", "-q", "."],
    ["python", "-Imcompileall", "-q", "."],
    ["python", "-IWignore", "task.py"],
    ["node", "--conditions=development", "task.js", "--print-summary"],
])
async def test_ordinary_module_and_script_arguments_keep_existing_meaning(argv):
    for plan in (policy.execution_plan(argv, "workspace"), policy.command_plan(shlex.join(argv), "workspace")):
        assert plan.argv == tuple(argv)
        assert not plan.inline_code


@pytest.mark.parametrize("argv", [
    ["python", "-c", "print(1)"],
    ["python", "-cprint(1)"],
    ["python", "-Icprint(1)"],
    ["python", "-I", "-c", "print(1)"],
    ["python", "-Wignore::UserWarning:fixtureW", "-cprint(1)"],
    ["node", "-e", "console.log(1)"],
    ["node", "-econsole.log(1)"],
    ["node", "--eval=console.log(1)"],
    ["node", "-p", "1 + 1"],
    ["node", "--print=1 + 1"],
    ["node", "-pe", "1 + 1"],
    ["node", "--conditions", "development", "--eval=console.log(1)"],
])
async def test_legacy_and_trusted_entries_reject_all_inline_forms(argv):
    with pytest.raises(ValueError):
        policy.command_plan(shlex.join(argv), "full_access")
    with pytest.raises(ValueError):
        policy.execution_plan(argv, "full_access", execution_mode="trusted_project")


@pytest.mark.parametrize("argv", [
    ["python", "-c"],
    ["node", "--eval"],
    ["node", "-p"],
    ["node", "--eval="],
    ["node", "-econsole.log(1)"],
    ["node", "-p1"],
    ["node", "-pe1"],
    ["node", "--print=1"],
    ["node", "-ep", "1"],
    ["python", "-c", "  \n"],
    ["python", "-c", "print('" + "a" * 2000 + "')"],
    ["python", "-c", "print(1)", "arg\x00"],
    ["python", "-c", "print(1)", "x;echo"],
    ["python", "-c", "print(1)", "../outside.txt"],
    ["python", "-c", "print(1)", ".env"],
    ["node", "-e", "console.log(1)", "C:/outside.txt"],
    ["python", "-c", "print(1)\x00"],
    ["cmd", "/c", "echo unrestricted"],
    ["powershell", "-Command", "Write-Output unrestricted"],
    ["bun", "-e", "console.log(1)"],
    ["node", "--require", "bootstrap.js", "--eval=console.log(1)"],
    ["node", "--conditions", "development", "--eval=console.log(1)"],
])
async def test_inline_policy_keeps_argument_and_program_boundaries(argv):
    with pytest.raises(ValueError):
        policy.execution_plan(argv, "workspace")


async def test_inline_policy_preserves_permission_and_explicit_approval():
    argv = ["python", "-c", "print('ok')"]
    with pytest.raises(ValueError):
        policy.execution_plan(argv, "readonly")
    assert not policy.execution_plan(argv, "confirm").automatic
    assert not policy.execution_plan(argv, "workspace", require_approval=True).automatic
    assert policy.execution_plan(argv, "full_access").automatic


@pytest.mark.parametrize("prefix", [[], ["--conditions", "development"]])
@pytest.mark.parametrize("option", ["--import", "--loader", "--experimental-loader"])
@pytest.mark.parametrize("attached", [False, True])
async def test_inline_data_preloads_cannot_bypass_declared_entry_points(prefix, option, attached):
    payload = "data:text/javascript,console.log(1)"
    argv = ["node", *prefix, *([option + "=" + payload] if attached else [option, payload])]
    with pytest.raises(ValueError):
        policy.execution_plan(argv, "workspace")
    with pytest.raises(ValueError):
        policy.execution_plan(argv, "full_access", execution_mode="trusted_project")
    with pytest.raises(ValueError):
        policy.command_plan(shlex.join(argv), "full_access")


@pytest.mark.parametrize("limits", [
    {"commands_forbidden": True},
    {"preview_only": True},
    {"writes_forbidden": True},
    {"write_scopes": [["task.py"]]},
    {"access_scopes": [["task.py"]]},
    {"forbidden_write_paths": ["task.py"]},
])
async def test_inline_code_never_bypasses_task_constraints(session, monkeypatch, limits):
    owner, run, root = session
    run["completion_policy"] = limits
    start, approve = AsyncMock(), AsyncMock()
    monkeypatch.setattr(owner.execution_sessions, "start", start)
    monkeypatch.setattr(owner, "approve", approve)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "-c", "print('ok')"]}))
    assert result["error_code"] == "user_constraint"
    start.assert_not_awaited()
    approve.assert_not_awaited()


async def test_no_test_restriction_allows_unclassified_inline_code_at_existing_permission(session, monkeypatch):
    owner, run, root = session
    run["completion_policy"] = {"tests_forbidden": True}
    started = capture_start(monkeypatch, owner)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "-c", "print('ok')"]}))
    assert not result.get("error")
    started.assert_awaited_once()
    options = started.call_args.args[5]
    assert options.execution_mode == "restricted" and options.network_policy == "none"
    assert not run["approvals"]


async def test_inline_denial_in_confirm_mode_never_starts(session, monkeypatch):
    owner, run, root = session
    run["permission_mode"] = "confirm"
    start, approve = AsyncMock(), AsyncMock(return_value=False)
    monkeypatch.setattr(owner.execution_sessions, "start", start)
    monkeypatch.setattr(owner, "approve", approve)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "-c", "print('ok')"]}))
    assert result.get("error")
    approve.assert_awaited_once()
    start.assert_not_awaited()


async def test_inline_payload_is_not_opened_as_a_host_file_during_version_binding(session, monkeypatch):
    owner, run, root = session
    outside = root.parent / "inline-payload.txt"
    outside.write_text("fixture", encoding="utf-8")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != outside, "内联正文不能被摘要逻辑当成本机路径读取"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    start = capture_start(monkeypatch, owner)
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "-c", str(outside)]}))
    assert not result.get("error"), result
    start.assert_awaited_once()
    assert start.call_args.args[4] == ["python", "-c", str(outside)]
    assert run["executions"][-1]["authorization_sha256"]


async def execute_inline(session, monkeypatch, code=None, *, argv=None):
    owner, run, root = session
    argv = argv if argv is not None else ["python", "-c", code]
    # 只使用测试所需的现有解释器，避免全局工具目录中的无关包耗尽沙箱扫描预算。
    if argv[0] == "node":
        runtime = root.parent / "node-runtime"
        runtime.mkdir()
        shutil.copy2(shutil.which("node"), runtime / "node.exe")
    else:
        runtime = Path(sys._base_executable).parent
    monkeypatch.setenv("PATH", str(runtime) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(owner, "approve", AsyncMock(side_effect=AssertionError("普通受限命令不应重复审批")))
    result = await owner.tool(run, root, call("exec_command", {
        "argv": argv, "yield_time_ms": 1000, "timeout_ms": 15_000,
    }))
    assert not result.get("error"), result
    # 推进游标才能在已收到部分输出后继续等待，避免忙轮询抢占沙箱回收。
    async with asyncio.timeout(30):
        while result["status"] in {"starting", "running"}:
            result = await owner.execution_sessions.read(
                result["execution_id"], run["session_id"], after=result["next_cursor"], wait_ms=1000,
            )
    assert result["status"] == "exited" and result["exit_code"] == 0 and result["stopped"], result
    execution = next(item for item in owner.store.run(run["id"])["executions"] if item["id"] == result["execution_id"])
    assert execution["status"] == "completed", execution
    assert result["execution_mode"] == "restricted" and result["network_policy"] == "none"
    assert result["argv"] == execution["output"]["args"] == argv
    assert not result["gap"] and not result["dropped_bytes"] and not execution["output"]["truncated"]
    assert not owner.execution_sessions.slots
    assert not list((owner.store.path.parent / "sandbox-leases").glob("*.json"))
    assert not list((owner.store.path.parent / "sandbox-leases").glob("*.pending"))
    return execution


@windows_sandbox
async def test_real_inline_payload_preserves_text_and_file_change_evidence(session, monkeypatch):
    _, _, root = session
    value = "中文 '单引号' \"双引号\";\\路径\n第二行"
    code = (
        "import json\nfrom pathlib import Path\n"
        f"value={value!r}\n"
        "Path('inline-result.txt').write_text(value, encoding='utf-8'); print(json.dumps(value, ensure_ascii=False))"
    )
    execution = await execute_inline(session, monkeypatch, code)
    assert (root / "inline-result.txt").read_text(encoding="utf-8") == value
    assert json.loads(execution["output"]["stdout"]) == value
    assert execution["output"]["args"] == ["python", "-c", code]
    assert execution["workspace_changed"] and execution["workspace_digest"]


@windows_sandbox
@pytest.mark.parametrize("prefix", [["python", "-Ic"], ["python", "-B", "-c"]])
async def test_real_python_inline_prefix_preserves_code_and_trailing_arguments(session, monkeypatch, prefix):
    trailing = ["含空格 参数", "单'双\"引号"]
    code = "import json,sys; sys.stdout.reconfigure(encoding='utf-8'); print(json.dumps(sys.argv[1:],ensure_ascii=False))"
    argv = [*prefix, code, *trailing] if prefix[-1] == "-c" else [*prefix[:-1], prefix[-1] + code, *trailing]
    execution = await execute_inline(session, monkeypatch, argv=argv)
    assert json.loads(execution["output"]["stdout"]) == trailing


@windows_sandbox
@pytest.mark.skipif(shutil.which("node") is None, reason="本机未安装 Node，不能验证真实 Node 内联命令")
@pytest.mark.parametrize("option,attached,printed", [
    ("-e", False, False),
    ("--eval", False, False),
    ("--eval=", True, False),
    ("-p", False, True),
    ("--print", False, True),
    ("-pe", False, True),
])
async def test_real_node_inline_forms_preserve_payload_and_arguments(session, monkeypatch, option, attached, printed):
    value, trailing = "中文;单双'\"引号\\路径\n第二行", ["尾部 空格", "单'双\"引号"]
    expression = f"JSON.stringify([{json.dumps(value, ensure_ascii=False)},process.argv.slice(1)])"
    code = expression if printed else f"console.log({expression})"
    argv = ["node", option + code, *trailing] if attached else ["node", option, code, *trailing]
    execution = await execute_inline(session, monkeypatch, argv=argv)
    assert json.loads(execution["output"]["stdout"]) == [value, trailing]


@windows_sandbox
async def test_real_inline_code_cannot_read_or_write_outside_project(session, monkeypatch):
    _, _, root = session
    outside = root.parent / "outside-fixture.txt"
    outside.write_text("ISOLATED_SENTINEL", encoding="utf-8")
    code = (
        "from pathlib import Path\n"
        "Path('inside-control.txt').write_text('allowed')\n"
        "for action in ('read', 'write'):\n"
        " try:\n"
        "  path=Path('../outside-fixture.txt')\n"
        "  value=path.read_text() if action=='read' else path.write_text('unexpected')\n"
        " except PermissionError:\n"
        "  print(action + '_DENIED')\n"
        " else:\n"
        "  raise AssertionError(action + '_ESCAPED')\n"
    )
    execution = await execute_inline(session, monkeypatch, code)
    assert (root / "inside-control.txt").read_text() == "allowed"
    assert outside.read_text(encoding="utf-8") == "ISOLATED_SENTINEL"
    assert "read_DENIED" in execution["output"]["stdout"]
    assert "write_DENIED" in execution["output"]["stdout"]
    assert "ISOLATED_SENTINEL" not in execution["output"]["stdout"]


@windows_sandbox
async def test_real_inline_child_inherits_appcontainer_without_capabilities(session, monkeypatch):
    probe = (
        "import ctypes as c; from ctypes import wintypes as w; "
        "k=c.WinDLL('kernel32'); a=c.WinDLL('advapi32'); k.GetCurrentProcess.restype=w.HANDLE; "
        "a.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]; "
        "a.GetTokenInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]; "
        "t=w.HANDLE(); assert a.OpenProcessToken(k.GetCurrentProcess(),8,c.byref(t)); "
        "flag=w.DWORD(); n=w.DWORD(); assert a.GetTokenInformation(t,29,c.byref(flag),4,c.byref(n)); "
        "assert flag.value==1; print('APPCONTAINER',flag.value); "
        "caps=c.create_string_buffer(4096); assert a.GetTokenInformation(t,30,caps,4096,c.byref(n)); "
        "assert w.DWORD.from_buffer(caps).value==0; print('CAPABILITIES',w.DWORD.from_buffer(caps).value); "
        "k.CloseHandle.argtypes=[w.HANDLE]; assert k.CloseHandle(t)"
    )
    code = f"import subprocess,sys\nprobe={probe!r}\nexec(probe)\nsubprocess.run([sys.executable,'-c',probe],check=True)"
    execution = await execute_inline(session, monkeypatch, code)
    assert execution["output"]["stdout"].count("APPCONTAINER 1") == 2
    assert execution["output"]["stdout"].count("CAPABILITIES 0") == 2


@windows_sandbox
async def test_real_inline_network_denial_has_live_loopback_controls(session, monkeypatch):
    accepted = []

    async def echo(reader, writer):
        try:
            data = await reader.read(1)
            accepted.append(data)
            writer.write(data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def control(port):
        async with asyncio.timeout(5):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                writer.write(b"c")
                await writer.drain()
                assert await reader.readexactly(1) == b"c"
            finally:
                writer.close()
                await writer.wait_closed()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        await control(port)
        code = (
            "import socket\nprint('PROBE_STARTED')\n"
            "try:\n"
            f" connection=socket.create_connection(('127.0.0.1',{port}),timeout=2)\n"
            "except (PermissionError, TimeoutError) as error:\n"
            " print('NETWORK_BLOCKED',type(error).__name__)\n"
            "else:\n"
            " connection.sendall(b'x'); connection.close(); raise AssertionError('NETWORK_ESCAPED')\n"
        )
        execution = await execute_inline(session, monkeypatch, code)
        await control(port)
        assert "PROBE_STARTED" in execution["output"]["stdout"]
        assert "NETWORK_BLOCKED" in execution["output"]["stdout"]
        assert accepted == [b"c", b"c"]
    finally:
        server.close()
        await server.wait_closed()
