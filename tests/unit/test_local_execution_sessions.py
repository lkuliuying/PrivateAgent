"""S4 持续执行：真实宿主、临时 SQLite、输入竞态与进程树回收。"""
import asyncio
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_local import execution_diagnostics, files
from private_agent_local.entry import parent_alive
from private_agent_local.execution_tools import ExecArgs
from private_agent_local.runtime import Runtime
from private_agent_local.store import Store

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("stderr, restricted, platform, expected", [
    ("Failed to find real location of C:\\Python\\python.EXE\r\n", True, "nt", True),
    ("Failed to find real location of C:\\ProgramSoftware\\Environment\\python\\python.EXE\n", True, "nt", True),
    ("Failed to find real location of C:\\Program Files\\Python\\python.EXE\n", True, "nt", True),
    ("Failed to find real location of C:/Python/python3.13.exe\n", True, "nt", True),
    ("Failed to find real location of C:\\Python\\python.exe\nTraceback: actual error", True, "nt", True),
    ("Failed to find real location of C:\\Python\\python.exe\n", False, "nt", False),
    ("Failed to find real location of /usr/bin/python.exe\n", True, "posix", False),
    ("Failed to find real location of C:\\Other\\node.exe", True, "nt", False),
    ("prefix Failed to find real location of C:\\Python\\python.exe", True, "nt", False),
    ("Failed to find real location of C:\\Python\\py", True, "nt", False),
    ("", True, "nt", False),
])
async def test_runtime_diagnostic_is_bounded_to_known_windows_sandbox_warning(monkeypatch, stderr, restricted, platform, expected):
    monkeypatch.setattr(execution_diagnostics, "os", SimpleNamespace(name=platform))
    warnings = execution_diagnostics.runtime_warnings(stderr, restricted=restricted)
    assert bool(warnings) is expected
    if expected:
        assert len(warnings) == 1 and warnings[0]["code"] == "python_path_resolution_warning"
        assert "仅根据 stderr 警告文本匹配" in warnings[0]["message"]
        assert "本次执行的根因尚未核实" in warnings[0]["message"]
        assert "可能原因之一" in warnings[0]["message"]
        assert "不能直接套用其他环境的定位结论" in warnings[0]["message"]
        assert "不能据此保证其他用途正常" in warnings[0]["message"]
        assert "C:" not in warnings[0]["message"]


class Identity:
    async def identity(self, token):
        return {"id": 1}


@pytest.fixture
async def session(tmp_path):
    root = tmp_path / "中文 项目"
    root.mkdir()
    store = Store(tmp_path / "state.sqlite3")
    project = store.create("project", {"status": "active", "authorized": True})
    workspace = store.create("workspace", {"project_id": project["id"], "root_path": str(root), "status": "active"})
    item = store.create("session", {"project_id": project["id"], "workspace_id": workspace["id"]})
    run = {"id": str(uuid.uuid4()), "project_id": project["id"], "workspace_id": workspace["id"], "session_id": item["id"],
           "permission_mode": "workspace", "execution_contract_version": "1.0", "status": "running", "events": [], "executions": [], "approvals": [],
           "last_event_sequence": 0, "root_identity": files.file_identity(root), "tool_call_count": 0, "output": None}
    store.save_run(run)
    owner = Runtime(store, Identity(), "fixture")
    try:
        yield owner, run, root
    finally:
        await owner.close()


async def start(session, code, **options):
    owner, run, root = session
    tool_name = options.pop("tool_name", "exec_command")
    execution = {"id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()), "tool_call_id": str(uuid.uuid4()),
                 "arguments_sha256": "a" * 64, "status": "running", "tool_name": tool_name}
    run["executions"].append(execution)
    owner.store.save_run(run)
    args = ExecArgs(argv=[sys.executable, "-c", code], **{"execution_mode": "trusted_project", "network_policy": "approved", **options})
    return await owner.execution_sessions.start(run, execution, root, root, args.argv, args)


async def finished(session, execution_id):
    manager = session[0].execution_sessions
    for _ in range(200):
        result = await manager.read(execution_id, session[1]["session_id"])
        if result["status"] not in {"starting", "running"}:
            return result
        await asyncio.sleep(0.025)
    pytest.fail("真实执行没有结束")


async def test_scoped_test_process_persists_violation_before_terminal_result(session):
    from private_agent_core.task_intent import interpret_task
    from private_agent_local.task_constraints import (
        TaskConstraintError,
        guard_paths,
        store_interpretation,
    )

    owner, run, root = session
    store_interpretation(run, interpret_task("只修改 A.py，然后运行测试"))
    (root / "test_scope.py").write_text(
        "from pathlib import Path\ndef test_effect():\n    Path('B.py').write_text('unexpected')\n", encoding="utf-8")
    execution = {"id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()), "tool_call_id": str(uuid.uuid4()),
                 "arguments_sha256": "a" * 64, "status": "running", "tool_name": "exec_command"}
    run["executions"].append(execution)
    owner.store.save_run(run)
    args = ExecArgs(argv=[sys.executable, "-m", "pytest", "--noconftest", "-p", "no:cacheprovider", "test_scope.py"],
                    execution_mode="trusted_project", network_policy="approved", yield_time_ms=0)
    result = await owner.execution_sessions.start(run, execution, root, root, args.argv, args)
    final = await finished(session, result["execution_id"])
    assert final["exit_code"] == 0 and "B.py" in final["error"]
    persisted = owner.store.run(run["id"])
    assert persisted["command_scope_issue"]["paths"] == ["B.py"]
    assert persisted["executions"][0]["scope_check"]["status"] == "violated"
    assert persisted["executions"][0]["error_code"] == "user_constraint"
    with pytest.raises(TaskConstraintError, match="B.py"):
        guard_paths(persisted, root, ["A.py"], write=True)
    assert (root / "B.py").read_text() == "unexpected"


@pytest.mark.parametrize("options, expected", [
    ({"execution_mode": "restricted", "network_policy": "approved"}, 'network_policy="none"'),
    ({"execution_mode": "restricted", "tty": True}, "tty=false"),
    ({"execution_mode": "trusted_project", "network_policy": "none"}, "用户明确审批"),
])
async def test_invalid_execution_combinations_are_rejected_before_approval_or_launch(session, options, expected):
    owner, run, root = session
    result = await owner.tool(run, root, call("exec_command", {"argv": ["python", "-m", "pytest", "-q"], **options}))
    assert result["error_code"] == "invalid_execution_options" and expected in result["error"]
    assert run["executions"][-1]["status"] == "failed"
    assert not run["approvals"] and not owner.execution_sessions.slots
    assert not any(event["type"] == "tool.started" for event in run["events"])


async def test_no_network_blocks_advanced_mode_before_approval(session):
    owner, run, root = session
    run["completion_policy"] = {"network_forbidden": True}
    result = await owner.tool(run, root, call("request_execution", {
        "argv": ["python", "-m", "pytest", "-q"],
        "execution_mode": "trusted_project", "network_policy": "approved",
    }))
    assert result["error_code"] == "user_constraint"
    assert not run["approvals"] and not owner.execution_sessions.slots


async def test_advanced_execution_terminal_event_keeps_original_tool_name(session):
    result = await start(session, "print('ok')", tool_name="request_execution", yield_time_ms=0)
    final = await finished(session, result["execution_id"])
    assert final["status"] == "exited" and final["exit_code"] == 0
    run = session[0].store.run(session[1]["id"])
    execution = run["executions"][0]
    event = next(item for item in run["events"] if item["sequence"] == execution["source_sequence"])
    assert event["payload"]["name"] == "request_execution"
    assert event["payload"]["tool_call_id"] == execution["tool_call_id"]


async def test_yield_is_not_timeout_and_small_unicode_output_arrives(session):
    result = await start(session, "import time; print('中文🙂',flush=True); time.sleep(1); print('尾部')", yield_time_ms=300, timeout_ms=600_000)
    assert result["status"] == "running" and result["timeout_ms"] == 600_000
    assert "中文🙂" in "".join(chunk["data"] for chunk in result["chunks"])
    final = await finished(session, result["execution_id"])
    assert final["exit_code"] == 0 and final["stopped"]
    assert "尾部" in "".join(chunk["data"] for chunk in final["chunks"])
    assert not session[0].execution_sessions.slots


async def test_restricted_session_enforces_workspace_and_releases_lease(session):
    result = await start(session, "from pathlib import Path; Path('inside.txt').write_text('ok');\ntry: Path('../outside.txt').write_text('bad')\nexcept PermissionError: print('DENIED')",
                         execution_mode="restricted", network_policy="none", yield_time_ms=1000)
    final = await finished(session, result["execution_id"])
    assert final["status"] == "exited" and final["exit_code"] == 0 and final["stopped"]
    assert "DENIED" in "".join(chunk["data"] for chunk in final["chunks"])
    assert (session[2] / "inside.txt").read_text() == "ok" and not (session[2].parent / "outside.txt").exists()
    assert not list((session[0].store.path.parent / "sandbox-leases").glob("*.json"))


@pytest.mark.parametrize("exit_code", [0, 1])
async def test_python_path_diagnostic_preserves_stderr_exit_and_replay(session, exit_code):
    warning = "Failed to find real location of C:\\Python\\python.exe\n"
    raw = (warning + "other warning\n").encode()
    code = f"import os,sys; os.write(2, {raw!r}); sys.exit({exit_code})"
    result = await start(session, code, execution_mode="restricted", network_policy="none", yield_time_ms=1000)
    final = await finished(session, result["execution_id"])
    owner, run, _ = session
    replay = await owner.execution_sessions.read(result["execution_id"], run["session_id"])
    execution = owner.store.run(run["id"])["executions"][0]
    assert replay["runtime_warnings"] == final["runtime_warnings"] == execution["output"]["runtime_warnings"]
    assert final["runtime_warnings"][0]["code"] == "python_path_resolution_warning"
    assert "本次执行的根因尚未核实" in final["runtime_warnings"][0]["message"]
    assert "可能原因之一" in final["runtime_warnings"][0]["message"]
    assert warning in execution["output"]["stderr"] and "other warning" in execution["output"]["stderr"]
    assert final["exit_code"] == execution["output"]["returncode"] == exit_code
    assert execution["execution_result"]["validation_outcome"] == ("failed" if exit_code else "unknown")


async def test_delayed_failure_updates_original_tool_and_s1_evidence(session):
    result = await start(session, "import time,sys; time.sleep(.3); sys.exit(1)", yield_time_ms=0)
    final = await finished(session, result["execution_id"])
    run = session[0].store.run(session[1]["id"])
    execution = run["executions"][0]
    assert execution["status"] == "failed" and final["exit_code"] == 1
    assert final["execution_result"]["validation_outcome"] == "failed"
    event = next(event for event in run["events"] if event["sequence"] == execution["source_sequence"])
    assert event["type"] == "tool.failed" and event["payload"]["execution_id"] == result["execution_id"]


async def test_stdin_eof_state_versions_and_foreign_session(session):
    result = await start(session, "import sys; print('READY',flush=True); print(sys.stdin.read())", stdin=True)
    manager, sid, eid = session[0].execution_sessions, session[1]["session_id"], result["execution_id"]
    with pytest.raises(ValueError, match="会话"):
        await manager.read(eid, sid + 100)
    with pytest.raises(ValueError, match="状态"):
        await manager.write(eid, sid, "oops", False, 1)
    await manager.write(eid, sid, "交互🙂\n", True, result["state_version"])
    with pytest.raises(ValueError):
        await manager.write(eid, sid, "duplicate", False, result["state_version"])
    final = await finished(session, eid)
    assert "交互🙂" in "".join(chunk["data"] for chunk in final["chunks"])
    assert final["status"] == "exited"


async def test_service_survives_second_command_and_close_kills_descendants(session):
    owner, run, root = session
    code = "import http.server,os; from pathlib import Path; Path('server.pid').write_text(str(os.getpid())); s=http.server.HTTPServer(('127.0.0.1',0),http.server.SimpleHTTPRequestHandler); Path('port').write_text(str(s.server_port)); print('READY',flush=True); s.serve_forever()"
    server = await start(session, code, retention="session", yield_time_ms=500)
    response = await start(session, "import urllib.request; from pathlib import Path; print(urllib.request.urlopen('http://127.0.0.1:'+Path('port').read_text()).status)", yield_time_ms=500)
    final = await finished(session, response["execution_id"])
    assert "200" in "".join(chunk["data"] for chunk in final["chunks"])
    pid = int((root / "server.pid").read_text())
    assert parent_alive(pid)
    result = await owner.execution_sessions.cancel(server["execution_id"], run["session_id"])
    assert result["stopped"] and result["status"] == "cancelled"
    for _ in range(100):
        if not parent_alive(pid):
            break
        await asyncio.sleep(0.01)
    assert not parent_alive(pid)
    assert (await owner.execution_sessions.cancel(server["execution_id"], run["session_id"])) == result


async def test_output_ring_gaps_and_split_utf8_are_explicit(session):
    code = "import os,time; data='中🙂'.encode(); [(os.write(1, bytes([x])),time.sleep(.003)) for x in data]; os.write(2,b'z'*1500000)"
    result = await start(session, code, yield_time_ms=100)
    final = await finished(session, result["execution_id"])
    assert final["status"] == "exited" and final["dropped_bytes"] > 0 and final["gap"]
    db = session[0].store.db
    assert db.execute("SELECT SUM(size) FROM execution_chunks").fetchone()[0] <= 1024 * 1024
    assert db.execute("SELECT COUNT(*) FROM execution_chunks").fetchone()[0] <= 512
    with pytest.raises(ValueError, match="游标"):
        await session[0].execution_sessions.read(final["execution_id"], session[1]["session_id"], after=final["last_output_sequence"] + 1)


async def test_slots_timeout_and_project_switch_are_bounded(session):
    a = await start(session, "import time; time.sleep(60)", yield_time_ms=0, timeout_ms=1000)
    b = await start(session, "import time; time.sleep(60)", yield_time_ms=0)
    with pytest.raises(ValueError, match="上限"):
        await start(session, "print('must not run')", yield_time_ms=0)
    final = await finished(session, a["execution_id"])
    assert final["status"] == "timed_out" and final["stopped"]
    await session[0].activate_project(None)
    result = session[0].store.execution_sessions.get(b["execution_id"], session[1]["session_id"])
    assert result["status"] == "cancelled" and result["stopped"]


async def test_restricted_request_and_old_host_fail_closed(session, monkeypatch):
    capabilities = await session[0].execution_sessions.capabilities()
    assert capabilities["contract"]["execution"] is True
    assert capabilities["contract"]["pty"] is False
    assert capabilities["network_isolation"] is True
    from private_agent_core.execution.contracts import ExecHealth
    from private_agent_core.execution.exec_host_client import ExecHostClient
    original = ExecHostClient.start

    async def old_start(client):
        health = await original(client)
        return ExecHealth(protocol_version=health.protocol_version, sandbox_available=False)

    monkeypatch.setattr(ExecHostClient, "start", old_start)
    with pytest.raises(ValueError, match="升级"):
        await start(session, "raise SystemExit('must not run')")
    assert not session[0].execution_sessions.slots


async def test_run_events_have_one_durable_sequence_and_output_is_not_rewritten(session):
    started_at = time.time_ns() / 1_000_000
    result = await start(session, "import time; [(print(i,flush=True),time.sleep(.02)) for i in range(15)]", yield_time_ms=0)
    final = await finished(session, result["execution_id"])
    events = session[0].store.events(session[1]["id"])
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert any(event["type"] == "execution.output" for event in events)
    assert all("data" not in event["payload"] for event in events if event["type"] == "execution.output")
    timings = [event["payload"] for event in events if event["type"] == "execution.output"]
    assert all(started_at <= item["received_at_unix_ms"] <= time.time_ns() / 1_000_000 for item in timings)
    sequences = {chunk["host_sequence"] for chunk in final["chunks"]}
    assert all(item["first_host_sequence"] in sequences for item in timings)
    assert final["status"] == "exited"


async def test_real_api_explicit_approval_cwd_stdin_and_logout(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    directory = root / "中文 空格"
    directory.mkdir()
    (directory / "echo.py").write_text("import os,sys; from pathlib import Path; Path('pid').write_text(str(os.getpid())); print('READY',flush=True); print(sys.stdin.read())", encoding="utf-8")
    try:
        server.responses = [response(call("exec_command", {"argv": ["python", "echo.py"], "cwd": "中文 空格", "stdin": True,
                                    "retention": "session", "execution_mode": "trusted_project", "network_policy": "approved"}))]
        run_id = (await client.post("/agent-runs", json={**body, "permission_mode": "workspace", "execution_contract_version": "1.0"})).json()["id"]
        await until(client, run_id, {"waiting_approval"})
        assert not (directory / "pid").exists()
        approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
        assert approval["required_capabilities"] == ["command.execute"] and approval["risk_level"] == "high"
        preview = (await client.get(f"/agent-runs/{run_id}/approvals/{approval['id']}/preview")).json()
        assert "没有文件或网络沙箱" in preview["reason"]
        await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")
        for _ in range(300):
            records = (await client.get(f"/sessions/{body['session_id']}/executions")).json()["items"]
            if records and records[0]["status"] == "running" and (directory / "pid").exists():
                break
            await asyncio.sleep(.01)
        assert records and records[0]["status"] == "running"
        eid = records[0]["execution_id"]
        assert (await client.get(f"/sessions/{body['session_id']+99}/executions/{eid}")).status_code == 422
        page = (await client.get(f"/sessions/{body['session_id']}/executions/{eid}?wait_ms=1000")).json()
        assert "READY" in "".join(chunk["data"] for chunk in page["chunks"])
        pid = int((directory / "pid").read_text())
        await app.state.desktop.clear()
        for _ in range(100):
            if not parent_alive(pid):
                break
            await asyncio.sleep(.01)
        assert not parent_alive(pid)
    finally:
        await close(app, client)


async def test_script_change_during_approval_prevents_start(tmp_path):
    app, client, server, root, body = await setup(tmp_path)
    path = root / "task.py"
    path.write_text("print('safe')", encoding="utf-8")
    try:
        server.responses = [response(call("exec_command", {"argv": ["python", "task.py"], "execution_mode": "trusted_project", "network_policy": "approved"}))]
        run_id = (await client.post("/agent-runs", json={**body, "execution_contract_version": "1.0"})).json()["id"]
        await until(client, run_id, {"waiting_approval"})
        approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
        path.write_text("from pathlib import Path; Path('unexpected').touch()", encoding="utf-8")
        await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")
        for _ in range(100):
            executions = (await client.get(f"/agent-runs/{run_id}/executions")).json()
            if executions[0]["status"] == "failed":
                break
            await asyncio.sleep(.01)
        assert executions[0]["status"] == "failed"
        assert "审批后变化" in executions[0]["error_message"]
        assert not (root / "unexpected").exists()
        assert not (await client.get(f"/sessions/{body['session_id']}/executions")).json()["items"]
    finally:
        await close(app, client)


async def test_concurrent_cancellation_and_disk_failure_still_reap_process(session, monkeypatch):
    result = await start(session, "import os,time; from pathlib import Path; Path('pid').write_text(str(os.getpid())); print('first',flush=True); time.sleep(60)", yield_time_ms=500)
    manager, sid, eid = session[0].execution_sessions, session[1]["session_id"], result["execution_id"]
    pid = int((session[2] / "pid").read_text())
    results = await asyncio.gather(manager.cancel(eid, sid), manager.cancel(eid, sid))
    assert all(item["stopped"] for item in results)
    assert not parent_alive(pid)
    def fail_output(*args):
        raise OSError("fixture disk full")
    monkeypatch.setattr(manager.store, "append", fail_output)
    result = await start(session, "import os,time; from pathlib import Path; Path('other.pid').write_text(str(os.getpid())); print('first',flush=True); time.sleep(60)", yield_time_ms=500)
    final = await finished(session, result["execution_id"])
    assert final["status"] == "unknown" and final["stopped"]
    assert not parent_alive(int((session[2] / "other.pid").read_text()))


async def test_cmd_quoting_spaces_and_metacharacters(session, tmp_path, monkeypatch):
    import os
    from pathlib import Path
    runner = tmp_path / "tool path"
    runner.mkdir()
    script = runner / "echo-fixture.cmd"
    script.write_text('@echo off\r\necho [%~1]\r\n', encoding="ascii")
    monkeypatch.setenv("PATH", str(runner) + os.pathsep + os.environ["PATH"])
    command, env = files.prepare_process(["echo-fixture", "two words"])
    assert Path(command[0]).name.casefold() == "cmd.exe"
    for value in ('%PATH%', '&whoami', 'a"b', '!variable!'):
        with pytest.raises(ValueError, match="shell"):
            files.prepare_process(["echo-fixture", value])
    from private_agent_local.executor import run_command
    result = await run_command(session[2], ["echo-fixture", "two words"])
    assert result["returncode"] == 0 and "[two words]" in result["stdout"]


async def test_expired_grant_reaps_real_parent_and_child(session):
    owner, run, root = session
    grant = owner.store.grant(run["session_id"], run["project_id"], (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat())
    run.update(permission_mode="full_access", full_access_grant_id=grant["id"])
    code = "import subprocess,sys,os,time; from pathlib import Path; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); Path('tree').write_text(str(os.getpid())+','+str(child.pid)); print('READY',flush=True); time.sleep(60)"
    result = await start(session, code, retention="session", yield_time_ms=500)
    pids = [int(value) for value in (root / "tree").read_text().split(",")]
    assert all(parent_alive(pid) for pid in pids)
    final = await finished(session, result["execution_id"])
    assert final["status"] == "unknown" and final["stopped"]
    assert all(not parent_alive(pid) for pid in pids)


async def test_output_quota_and_restart_never_replay(session, monkeypatch):
    monkeypatch.setattr("private_agent_local.execution_store.ACCOUNT_BYTES", 1024)
    result = await start(session, "print('x'*20000)", yield_time_ms=0)
    final = await finished(session, result["execution_id"])
    assert final["output_quota_exceeded"] and final["dropped_bytes"] > 0 and final["gap"]
    store = session[0].store.execution_sessions
    assert store.db.execute("SELECT COALESCE(SUM(size),0) FROM execution_chunks").fetchone()[0] <= 1024
    record = {**store.get(final["execution_id"], session[1]["session_id"]), "status": "running", "stopped": False}
    store.save(record)
    store.recover()
    assert store.get(record["execution_id"], record["session_id"])["status"] == "unknown"
    assert not session[0].execution_sessions.slots


@pytest.mark.parametrize("fault", ["previous_execution", "duplicate_sequence", "missing_sequence"])
async def test_stale_host_output_cannot_cross_execution_identity(session, monkeypatch, fault):
    from private_agent_local.execution_sessions import ExecHostClient

    previous = await start(session, "print('OLD-OUTPUT',flush=True)", yield_time_ms=0)
    previous = await finished(session, previous["execution_id"])
    manager, run, root = session[0].execution_sessions, session[1], session[2]
    saved = manager.store.get(previous["execution_id"], run["session_id"])
    next_event = ExecHostClient.next_event
    injected = False

    async def corrupt_output(client, **options):
        nonlocal injected
        event = await next_event(client, **options)
        if event and event.data and "CURRENT-MARKER" in event.data:
            injected = True
            if fault == "previous_execution":
                return event.model_copy(update={"execution_id": previous["execution_id"], "data": "OLD-LATE-OUTPUT"})
            return event.model_copy(update={"sequence": event.sequence + (1 if fault == "missing_sequence" else -1)})
        return event

    monkeypatch.setattr(ExecHostClient, "next_event", corrupt_output)
    code = "import os,time; from pathlib import Path; Path('pid').write_text(str(os.getpid())); print('CURRENT-MARKER',flush=True); time.sleep(60)"
    current = await start(session, code, yield_time_ms=0)
    final = await finished(session, current["execution_id"])
    assert injected and final["host_instance_id"] != previous["host_instance_id"]
    assert final["status"] == "unknown" and final["stopped"]
    assert not final["chunks"]
    assert not parent_alive(int((root / "pid").read_text()))
    assert manager.store.get(previous["execution_id"], run["session_id"]) == saved
    assert not manager.slots


async def test_old_host_rejected_before_run_creation_but_readonly_remains(tmp_path, monkeypatch):
    app, client, server, root, body = await setup(tmp_path)
    async def unsupported():
        return {"contract": {"execution": False}}
    monkeypatch.setattr(app.state.desktop.runtime.execution_sessions, "capabilities", unsupported)
    try:
        result = await client.post("/agent-runs", json={**body, "execution_contract_version": "1.0"})
        assert result.status_code == 422
        assert not app.state.desktop.runtime.store.runs()
        server.responses = [response(text="只读仍可用")]
        result = await client.post("/agent-runs", json={**body, "execution_contract_version": "1.0", "permission_mode": "readonly"})
        assert result.status_code == 201
        final = await until(client, result.json()["id"], {"completed", "failed"})
        assert final["status"] == "completed"
    finally:
        await close(app, client)
