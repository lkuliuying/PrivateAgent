"""S4 持续执行：真实宿主、临时 SQLite、输入竞态与进程树回收。"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_local import files
from private_agent_local.entry import parent_alive
from private_agent_local.execution_tools import ExecArgs
from private_agent_local.runtime import Runtime
from private_agent_local.store import Store

pytestmark = pytest.mark.asyncio


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
           "permission_mode": "workspace", "status": "running", "events": [], "executions": [], "approvals": [],
           "last_event_sequence": 0, "root_identity": files.file_identity(root), "tool_call_count": 0, "output": None}
    store.save_run(run)
    owner = Runtime(store, Identity(), "fixture")
    try:
        yield owner, run, root
    finally:
        await owner.close()


async def start(session, code, **options):
    owner, run, root = session
    execution = {"id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()), "tool_call_id": str(uuid.uuid4()),
                 "arguments_sha256": "a" * 64, "status": "running", "tool_name": "exec_command"}
    run["executions"].append(execution)
    owner.store.save_run(run)
    args = ExecArgs(argv=[sys.executable, "-c", code], execution_mode="trusted_project", network_policy="approved", **options)
    return await owner.execution_sessions.start(run, execution, root, root, args.argv, args)


async def finished(session, execution_id):
    manager = session[0].execution_sessions
    for _ in range(200):
        result = await manager.read(execution_id, session[1]["session_id"])
        if result["status"] not in {"starting", "running"}:
            return result
        await asyncio.sleep(0.025)
    pytest.fail("真实执行没有结束")


async def test_yield_is_not_timeout_and_small_unicode_output_arrives(session):
    result = await start(session, "import time; print('中文🙂',flush=True); time.sleep(1); print('尾部')", yield_time_ms=300, timeout_ms=600_000)
    assert result["status"] == "running" and result["timeout_ms"] == 600_000
    assert "中文🙂" in "".join(chunk["data"] for chunk in result["chunks"])
    final = await finished(session, result["execution_id"])
    assert final["exit_code"] == 0 and final["stopped"]
    assert "尾部" in "".join(chunk["data"] for chunk in final["chunks"])
    assert not session[0].execution_sessions.slots


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
    assert capabilities["network_isolation"] is False
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
    result = await start(session, "import time; [(print(i,flush=True),time.sleep(.02)) for i in range(15)]", yield_time_ms=0)
    final = await finished(session, result["execution_id"])
    events = session[0].store.events(session[1]["id"])
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert any(event["type"] == "execution.output" for event in events)
    assert all("data" not in event["payload"] for event in events if event["type"] == "execution.output")
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
