"""S5：真实 SQLite、磁盘、Git 和受控模型下的恢复及竞态验证。"""
import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_local.runtime import TERMINAL, Runtime
from private_agent_local.store import SCHEMA_VERSION, Store
from private_agent_local.workspaces import FileLock, workspace_key

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    subprocess.run(["git", "init"], cwd=values[3], check=True, capture_output=True)
    values[4]["recovery_contract_version"] = "1.0"
    try:
        yield values
    finally:
        await close(values[0], values[1])


async def create(api, **kwargs):
    result = await api[1].post("/agent-runs", json={**api[4], **kwargs})
    assert result.status_code == 201, result.text
    return result.json()["id"]


async def control(api, run_id, kind, **kwargs):
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    data = {"request_id": kind + "-request", "expected_state_version": report["state_version"], **kwargs}
    if kind == "resume":
        data["checkpoint_id"] = report["checkpoint_id"]
    result = await api[1].post(f"/agent-runs/{run_id}/{kind}", json=data)
    assert result.status_code in {200, 202}, result.text
    return data, result.json()


async def waiting_model(api, run_id):
    for _ in range(300):
        state = api[0].state.desktop.runtime.store.run_state(run_id)
        if state.get("loop_budget", {}).get("model_requests", 0):
            return state
        await asyncio.sleep(0.01)
    pytest.fail("模型请求未启动")


async def test_pause_resume_same_run_and_idempotent_steer(api):
    run_id = await create(api)
    await waiting_model(api, run_id)
    data, accepted = await control(api, run_id, "pause")
    paused = await until(api[1], run_id, {"paused"})
    assert paused["active_in_process"] is True
    duplicate = await api[1].post(f"/agent-runs/{run_id}/pause", json=data)
    assert duplicate.json()["status"] == "applied"
    data, _ = await control(api, run_id, "steer", message="只解释，不要运行测试，不写入文件")
    duplicate = await api[1].post(f"/agent-runs/{run_id}/steer", json=data)
    assert duplicate.status_code == 202
    messages = (await api[1].get(f"/sessions/{api[4]['session_id']}/messages")).json()
    assert sum(item["content"] == data["message"] for item in messages) == 1
    api[2].responses = [response(text="根据新约束解释")]
    _, result = await control(api, run_id, "resume")
    assert result["result_run_id"] == run_id
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed"
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    assert sum(item["kind"] == "steer" and item["status"] == "applied" for item in report["controls"]) == 1
    assert report["budget"]["model_requests"] == 2


async def test_version_conflict_and_request_id_reuse(api):
    run_id = await create(api)
    await waiting_model(api, run_id)
    result = await api[1].post(f"/agent-runs/{run_id}/pause", json={"request_id": "stale", "expected_state_version": 0})
    assert result.status_code == 409 and result.json()["state_version"] > 0
    data, _ = await control(api, run_id, "pause")
    result = await api[1].post(f"/agent-runs/{run_id}/steer", json={**data, "message": "另一个请求"})
    assert result.status_code == 409


async def test_approval_pause_cancel_race_never_writes(api):
    api[2].responses = [response(call("write_project_file", {"rel_path": "new.txt", "content": "unsafe"}))]
    run_id = await create(api)
    await until(api[1], run_id, {"waiting_approval"})
    approval = (await api[1].get(f"/agent-runs/{run_id}/approvals")).json()[0]
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    assert (await api[1].post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")).status_code == 422
    await control(api, run_id, "cancel")
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "cancelled" and not (api[3] / "new.txt").exists()


async def test_late_model_response_is_discarded(api, monkeypatch):
    owner = api[0].state.desktop.runtime
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def late(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                return response(call("write_project_file", {"rel_path": "late.txt", "content": "late"}))
        return response(text="只解释")

    monkeypatch.setattr(owner.cloud, "complete", late)
    run_id = await create(api, permission_mode="workspace")
    await entered.wait()
    await control(api, run_id, "steer", message="只解释，不要写入文件")
    await until(api[1], run_id, TERMINAL)
    assert calls == 2 and not (api[3] / "late.txt").exists()
    assert any(e["type"] == "model.response_discarded" for e in owner.store.events(run_id))


async def test_steer_invalidates_command_approval_and_does_not_replay(api, monkeypatch):
    from unittest.mock import AsyncMock

    execute = AsyncMock()
    monkeypatch.setattr("private_agent_local.runtime.run_command", execute)
    api[2].responses = [response(call("run_project_command", {"command": "python -m pytest"})),
                        response(text="根据新限制，未执行命令")]
    run_id = await create(api, message="运行测试")
    await until(api[1], run_id, {"waiting_approval"})
    approval = (await api[1].get(f"/agent-runs/{run_id}/approvals")).json()[0]
    await control(api, run_id, "steer", message="不运行任何命令")
    final = await until(api[1], run_id, TERMINAL)
    assert (await api[1].post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")).status_code == 422
    execute.assert_not_called()
    current = api[0].state.desktop.runtime.store.run(run_id)
    assert current["completion_policy"]["commands_forbidden"]
    assert final["goal_outcome"] != "verified"
    assert len(current["task_interpretation"]["sources"]) == 2


async def test_tightened_test_restriction_survives_pause_and_linked_resume(api, monkeypatch):
    from unittest.mock import AsyncMock

    (api[3] / "package.json").write_text(json.dumps({"scripts": {"qa": "pytest"}}), encoding="utf-8")
    execute = AsyncMock()
    monkeypatch.setattr("private_agent_local.runtime.run_command", execute)
    run_id = await create(api, message="读取项目")
    await waiting_model(api, run_id)
    await control(api, run_id, "steer", message="不运行测试")
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    await control(api, run_id, "cancel")
    before = api[0].state.desktop.runtime.store.run(run_id)
    api[2].responses = [response(call("run_project_command", {"command": "npm run qa"})),
                        response(text="保持原限制，未运行测试")]
    _, resumed = await control(api, run_id, "resume")
    child = resumed["result_run_id"]
    final = await until(api[1], child, TERMINAL)
    current = api[0].state.desktop.runtime.store.run(child)
    assert current["completion_policy"]["tests_forbidden"]
    assert not current["completion_policy"]["commands_forbidden"]
    assert current["goal_version"] >= 2 and final["goal_outcome"] != "verified"
    assert api[0].state.desktop.runtime.store.run(run_id) == before
    execute.assert_not_called()


async def test_legacy_restore_reparses_applied_steer_sources(api):
    from private_agent_local.task_constraints import restore_interpretation

    run_id = await create(api, message="读取项目")
    await waiting_model(api, run_id)
    await control(api, run_id, "steer", message="不要运行测试")
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    owner = api[0].state.desktop.runtime
    restored = owner.store.run(run_id)
    version = restored["goal_version"]
    restored.pop("task_interpretation")
    restored["completion_policy"] = {"preview_only": False, "answer_only": True, "commands_forbidden": False}
    restore_interpretation(owner, restored)
    assert restored["completion_policy"]["tests_forbidden"]
    assert restored["goal_version"] == version
    assert any(source["text"] == "不要运行测试" for source in restored["task_interpretation"]["sources"])


async def test_verified_legacy_sources_remove_stale_global_prohibition(api):
    from private_agent_local.task_constraints import restore_interpretation

    run_id = await create(api, message="修复 A.py，另一个模块只分析")
    await waiting_model(api, run_id)
    await control(api, run_id, "steer", message="不要运行测试")
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    owner = api[0].state.desktop.runtime
    restored = owner.store.run(run_id)
    restored["task_interpretation"]["schema_version"] = "1.1"
    restored["task_interpretation"]["policy"].update(writes_forbidden=True, commands_forbidden=True)
    restored["completion_policy"].update(writes_forbidden=True, commands_forbidden=True)
    previous_goal = restored["goal"]
    restore_interpretation(owner, restored)
    assert restored["task_interpretation"]["schema_version"] == "1.2"
    assert not restored["completion_policy"]["writes_forbidden"] and not restored["completion_policy"]["commands_forbidden"]
    assert restored["completion_policy"]["tests_forbidden"]
    assert restored["goal"] == previous_goal and restored["goal_version"] == 2
    assert any(item["kind"] == "file_changed" and item["scope"] == "A.py" for item in restored["completion_requirements"])


async def test_unverifiable_legacy_sources_keep_cached_limits(api):
    from private_agent_local.task_constraints import restore_interpretation

    run_id = await create(api, message="读取项目")
    await waiting_model(api, run_id)
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    owner = api[0].state.desktop.runtime
    restored = owner.store.run(run_id)
    restored["task_interpretation"]["schema_version"] = "1.1"
    restored["goal_version"] = 2
    restored["completion_policy"]["writes_forbidden"] = True
    restore_interpretation(owner, restored)
    assert restored["task_interpretation"]["schema_version"] == "1.1"
    assert restored["completion_policy"]["writes_forbidden"]
    assert any("原始来源不完整" in item for item in restored["completion_policy"]["unperformed"])


@pytest.mark.parametrize("initial,steer,tool,args", [
    ("不运行命令", "现在可以运行命令，请执行 python -m pytest", "run_project_command", {"command": "python -m pytest"}),
    ("不要修改文件", "现在可以修改文件，请创建 app.py", "write_project_file", {"rel_path": "app.py", "content": "value = 1\n"}),
])
async def test_explicit_steer_restores_visible_tools_in_same_model_loop(api, monkeypatch, initial, steer, tool, args):
    from unittest.mock import AsyncMock

    execute = AsyncMock(return_value={"returncode": 0, "stdout": "1 passed", "stderr": "", "truncated": False})
    monkeypatch.setattr("private_agent_local.runtime.run_command", execute)
    run_id = await create(api, message=initial, permission_mode="workspace")
    await waiting_model(api, run_id)
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    await control(api, run_id, "steer", message=steer)
    api[2].responses = [response(call(tool, args)), response(text="已按最新要求完成")]
    _, resumed = await control(api, run_id, "resume")
    assert resumed["result_run_id"] == run_id
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed" and final["goal_outcome"] == "verified"
    requests = [json.loads(data)["request"] for path, data in api[2].calls if path == "/desktop/model/complete"]
    assert len(requests) == 3
    assert tool not in {item["name"] for item in requests[0]["tools"]}
    assert tool in {item["name"] for item in requests[1]["tools"]}
    assert any(item["role"] == "user" and item["content"] == steer for item in requests[1]["messages"])
    first_system = [item for item in requests[0]["messages"] if item["role"] == "system"]
    assert first_system == [item for item in requests[1]["messages"] if item["role"] == "system"]
    hint = next(item["content"] for item in requests[1]["messages"] if item["content"].startswith("程序提取的任务状态"))
    state = json.loads(hint.split("：", 1)[1])
    assert state["goal_version"] == 2 and state["policy_releases"]
    assert not state["restrictions"]["commands_forbidden"] and not state["restrictions"]["writes_forbidden"]
    if tool == "run_project_command":
        execute.assert_awaited_once()
    else:
        assert (api[3] / "app.py").read_text() == "value = 1\n"
        execute.assert_not_called()


async def test_released_policy_survives_cancel_and_linked_resume(api):
    run_id = await create(api, message="不要运行测试，不要联网")
    await waiting_model(api, run_id)
    data, _ = await control(api, run_id, "steer", message="现在可以运行测试")
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    assert (await api[1].post(f"/agent-runs/{run_id}/steer", json=data)).status_code == 202
    await control(api, run_id, "cancel")
    owner = api[0].state.desktop.runtime
    parent = owner.store.run(run_id)
    assert not parent["completion_policy"]["tests_forbidden"]
    assert len(parent["task_interpretation"]["policy_releases"]) == 1
    api[2].responses = [response(text="继续依据最新用户要求分析项目")]
    _, resumed = await control(api, run_id, "resume")
    child_id = resumed["result_run_id"]
    final = await until(api[1], child_id, TERMINAL)
    child = owner.store.run(child_id)
    assert final["status"] == "completed" and child_id != run_id
    assert not child["completion_policy"]["tests_forbidden"] and child["completion_policy"]["network_forbidden"]
    assert child["task_interpretation"]["policy_releases"] == parent["task_interpretation"]["policy_releases"]
    assert child["task_interpretation"]["sources"] == parent["task_interpretation"]["sources"]
    assert owner.store.run(run_id) == parent


async def test_cancel_resume_creates_link_and_keeps_budget_and_old_events(api):
    run_id = await create(api)
    await waiting_model(api, run_id)
    await control(api, run_id, "cancel")
    owner = api[0].state.desktop.runtime
    previous = owner.store.run(run_id)
    api[2].responses = [response(text="继续解释")]
    data, result = await control(api, run_id, "resume")
    child = result["result_run_id"]
    assert child != run_id
    assert (await api[1].post(f"/agent-runs/{run_id}/resume", json=data)).json()["result_run_id"] == child
    final = await until(api[1], child, TERMINAL)
    assert final["resumed_from_run_id"] == run_id and final["logical_task_id"] == run_id
    assert final["loop_budget"]["model_requests"] >= 2
    assert owner.store.run(run_id) == previous


async def test_budget_exhaustion_blocks_resume(api):
    run_id = await create(api, context_limits={"max_model_requests": 1})
    await waiting_model(api, run_id)
    await control(api, run_id, "cancel")
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    assert report["can_resume"] is False and any("预算" in item for item in report["blockers"])


async def test_same_workspace_serializes_and_distinct_workspace_runs(api):
    first = await create(api)
    await waiting_model(api, first)
    session = (await api[1].post("/sessions", json={"project_id": api[4]["project_id"], "workspace_id": api[4]["workspace_id"], "title": "second"})).json()
    second = await create(api, session_id=session["id"])
    await until(api[1], second, {"queued"})
    root = api[3].parent / "other"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    project = (await api[1].post("/projects", json={"name": "other", "root_path": str(root)})).json()
    workspace = (await api[1].get(f"/projects/{project['id']}/workspaces")).json()[0]
    session = (await api[1].post("/sessions", json={"project_id": project["id"], "workspace_id": workspace["id"], "title": "third"})).json()
    third = await create(api, session_id=session["id"], project_id=project["id"], workspace_id=workspace["id"])
    await waiting_model(api, third)
    await control(api, first, "cancel")
    await waiting_model(api, second)
    assert (await api[1].get(f"/agent-runs/{third}")).json()["status"] == "running"


async def test_restart_checkpoint_unknown_commands_and_expired_approvals(tmp_path):
    values = await setup(tmp_path)
    owner = values[0].state.desktop.runtime
    run_id = await create((values[0], values[1], values[2], values[3], {**values[4], "recovery_contract_version": "1.0"}))
    await waiting_model(values, run_id)
    await owner.cancel(run_id)
    saved = owner.store.run(run_id)
    saved.update(status="waiting_approval", active_in_process=True)
    saved["approvals"] = [{"id": "old-approval", "status": "pending"}]
    saved["executions"] = [{"id": "unknown-command", "operation_id": "op", "status": "running", "command": "python -m pytest"}]
    owner.store.save_run(saved)
    path = owner.store.path
    await close(values[0], values[1])
    restarted = Store(path)
    try:
        run = restarted.run(run_id)
        assert run["status"] == "interrupted" and run["approvals"][0]["status"] == "cancelled"
        runtime = Runtime(restarted, None, "fixture")
        report = runtime.recovery.inspect(run)
        assert not report["can_resume"] and any("命令" in item for item in report["blockers"])
        assert run["executions"][0]["execution_result"]["outcome"] == "unknown"
    finally:
        restarted.db.close()


async def test_checkpoint_tampering_and_owner_lock(api):
    run_id = await create(api)
    await waiting_model(api, run_id)
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    owner = api[0].state.desktop.runtime
    with pytest.raises(ValueError, match="持有"):
        Store(owner.store.path)
    checkpoint_id = owner.store.run_state(run_id)["checkpoint_id"]
    with owner.store.transaction():
        owner.store.db.execute("UPDATE run_checkpoints SET sha256='tampered' WHERE id=?", (checkpoint_id,))
    report = owner.recovery.inspect(owner.store.run(run_id))
    assert any("摘要" in item for item in report["blockers"])


async def test_checkpoint_and_event_rollback_together(api, monkeypatch):
    run_id = await create(api)
    await waiting_model(api, run_id)
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    owner = api[0].state.desktop.runtime
    before = owner.store.run(run_id)
    count = owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints").fetchone()[0]
    original = owner.store._save_run

    def fail(run, **kwargs):
        original(run, **kwargs)
        raise OSError("注入事务提交前失败")

    with monkeypatch.context() as patch:
        patch.setattr(owner.store, "_save_run", fail)
        with pytest.raises(OSError):
            owner.event(dict(before), "fixture.failed")
    assert owner.store.run(run_id) == before
    assert owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints").fetchone()[0] == count


async def test_control_transaction_failure_preserves_live_state_and_messages(api, monkeypatch):
    run_id = await create(api)
    await waiting_model(api, run_id)
    owner = api[0].state.desktop.runtime
    before = json.loads(json.dumps(owner.live[run_id]))
    original = owner.recovery.save_control

    def fail(*args):
        original(*args)
        raise OSError("注入控制回执保存失败")

    with monkeypatch.context() as patch:
        patch.setattr(owner.recovery, "save_control", fail)
        with pytest.raises(OSError):
            await owner.controls.request(run_id, "steer", {"request_id": "failed-control", "expected_state_version": before["state_version"], "message": "只解释"})
    assert owner.live[run_id] == before
    assert owner.store.run(run_id)["state_version"] == before["state_version"]
    assert not owner.recovery.controls(run_id)
    messages = (await api[1].get(f"/sessions/{api[4]['session_id']}/messages")).json()
    assert all(message["content"] != "只解释" for message in messages)


async def test_failed_resume_transaction_never_launches_orphan_run(api, monkeypatch):
    run_id = await create(api)
    await waiting_model(api, run_id)
    await control(api, run_id, "cancel")
    owner = api[0].state.desktop.runtime
    before = owner.store.run(run_id)

    def fail(*_):
        raise OSError("注入恢复回执保存失败")

    with monkeypatch.context() as patch:
        patch.setattr(owner.recovery, "save_control", fail)
        with pytest.raises(OSError):
            await owner.controls.request(run_id, "resume", {"request_id": "failed-resume", "expected_state_version": before["state_version"], "checkpoint_id": before["checkpoint_id"]})
    assert len(owner.store.runs()) == 1
    assert not owner.tasks and not owner.live
    assert owner.store.get("session", before["session_id"])["last_run_id"] == run_id
    assert owner.store.run(run_id) == before
    assert not any(record["kind"] == "resume" for record in owner.recovery.controls(run_id))


async def test_pause_during_real_host_start_prevents_command_dispatch(api, monkeypatch):
    from private_agent_core.execution.exec_host_client import ExecHostClient

    owner = api[0].state.desktop.runtime
    starting = asyncio.Event()
    original_start = ExecHostClient.start
    original_dispatch = ExecHostClient.start_execution
    dispatched = []

    async def start(client):
        health = await original_start(client)
        if owner.execution_sessions.slots:
            starting.set()
            await asyncio.Event().wait()
        return health

    async def dispatch(client, params):
        dispatched.append(params)
        return await original_dispatch(client, params)

    monkeypatch.setattr(ExecHostClient, "start", start)
    monkeypatch.setattr(ExecHostClient, "start_execution", dispatch)
    (api[3] / "startup.py").write_text("print('fixture')", encoding="utf-8")
    api[2].responses = [response(call("exec_command", {"argv": ["python", "startup.py"], "execution_mode": "trusted_project", "network_policy": "approved"}))]
    run_id = await create(api, permission_mode="workspace", execution_contract_version="1.0")
    await until(api[1], run_id, {"waiting_approval"})
    approval = (await api[1].get(f"/agent-runs/{run_id}/approvals")).json()[0]
    assert (await api[1].post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")).status_code == 200
    await asyncio.wait_for(starting.wait(), 5)
    await asyncio.wait_for(control(api, run_id, "pause"), 5)
    await until(api[1], run_id, {"paused"})
    assert not dispatched and not owner.execution_sessions.slots
    assert all(record["stopped"] for record in owner.store.execution_sessions.list(api[4]["session_id"]))


async def test_resume_preserves_consumed_verification_retries(api):
    api[2].responses = [response(text="尚未修改文件")]
    run_id = await create(api, message="修改 target.txt", permission_mode="workspace")
    owner = api[0].state.desktop.runtime
    for _ in range(300):
        if owner.store.run_state(run_id).get("loop_budget", {}).get("model_requests", 0) >= 2:
            break
        await asyncio.sleep(0.01)
    await control(api, run_id, "cancel")
    assert owner.store.run(run_id)["verification_retries"] == 1
    api[2].responses = [response(text="文件仍未修改"), response(text="仍未完成要求")]
    _, continued = await control(api, run_id, "resume")
    final = await until(api[1], continued["result_run_id"], TERMINAL)
    assert final["verification_retries"] == 2
    assert final["loop_budget"]["model_requests"] == 4
    assert final["run_outcome"]["goal_outcome"] == "unmet"


async def test_revoked_grant_requires_explicit_new_grant_to_continue(api):
    endpoint = f"/sessions/{api[4]['session_id']}/full-access-grant"
    old_grant = (await api[1].post(endpoint, json={})).json()
    run_id = await create(api, permission_mode="full_access")
    await waiting_model(api, run_id)
    await api[1].delete(f"/full-access-grants/{old_grant['grant_id']}")
    owner = api[0].state.desktop.runtime
    before = owner.store.run(run_id)
    data = {"request_id": "after-revoke", "expected_state_version": before["state_version"], "checkpoint_id": before["checkpoint_id"]}
    rejected = await api[1].post(f"/agent-runs/{run_id}/resume", json=data)
    assert rejected.status_code == 422 and "授权" in rejected.text
    new_grant = (await api[1].post(endpoint, json={})).json()
    assert new_grant["grant_id"] != old_grant["grant_id"]
    api[2].responses = [response(text="继续检查")]
    result = await api[1].post(f"/agent-runs/{run_id}/resume", json=data)
    assert result.status_code == 202, result.text
    final = await until(api[1], result.json()["result_run_id"], TERMINAL)
    assert final["full_access_grant_id"] == new_grant["grant_id"]
    assert owner.store.run(run_id)["full_access_grant_id"] == old_grant["grant_id"]


async def test_resume_blocks_changed_model_capability_and_checkpoint_format(api):
    from private_agent_local import files
    from private_agent_local.store import encode

    run_id = await create(api)
    await waiting_model(api, run_id)
    await control(api, run_id, "cancel")
    owner = api[0].state.desktop.runtime
    before = owner.store.run(run_id)
    data = {"request_id": "changed-capability", "expected_state_version": before["state_version"], "checkpoint_id": before["checkpoint_id"]}
    api[2].profiles[0]["supports_streaming"] = True
    result = await api[1].post(f"/agent-runs/{run_id}/resume", json=data)
    assert result.status_code == 422 and "能力" in result.text
    api[2].profiles[0].pop("supports_streaming")
    checkpoint = owner.recovery.load_checkpoint(before)
    checkpoint["format_version"] = "future"
    with owner.store.transaction():
        owner.store.db.execute("UPDATE run_checkpoints SET sha256=?,data=? WHERE id=?", (files.digest(encode(checkpoint).encode()), owner.store._pack(checkpoint), before["checkpoint_id"]))
    assert any("格式不兼容" in message for message in owner.recovery.inspect(before)["blockers"])


async def test_recovery_and_review_never_cross_accounts(api):
    run_id = await create(api)
    await waiting_model(api, run_id)
    assert (await api[1].get(f"/agent-runs/{run_id}/recovery", headers={"Authorization": "Bearer account-b"})).status_code == 401
    await api[0].state.desktop.activate("account-b", api[0].state.desktop.cloud.origin, 2)
    for suffix in ("recovery", "review", "events"):
        result = await api[1].get(f"/agent-runs/{run_id}/{suffix}", headers={"Authorization": "Bearer account-b"})
        assert result.status_code == 404


async def test_steer_after_first_file_stops_second_write_and_keeps_facts(api):
    from recovery_process import Model

    root = api[3]
    for name in ("a.txt", "b.txt"):
        (root / name).write_text("before", encoding="utf-8")
    api[2].profiles[0]["context_tokens"] = 128000
    owner = api[0].state.desktop.runtime
    model = Model(False)
    owner.cloud.complete = model.complete
    identity = owner.cloud.identity
    received = []

    async def with_control(token):
        result = await identity(token)
        if (root / "a.txt").read_text() == "after" and not received:
            run = next(iter(owner.live.values()))
            received.append(await owner.controls.request(run["id"], "steer", {"request_id": "after-first-file", "expected_state_version": run["state_version"], "message": "停止写文件，只解释"}))
        return result

    owner.cloud.identity = with_control
    run_id = await create(api, message="修改 a.txt 和 b.txt", permission_mode="workspace")
    final = await until(api[1], run_id, TERMINAL)
    assert received and (root / "a.txt").read_text() == "after"
    assert (root / "b.txt").read_text() == "before"
    patch = next(item for item in owner.patches.list(run_id) if item["status"] == "partially_applied")
    facts = owner.patches.facts(run_id, patch["patch_set_id"], root)
    assert facts[0]["verified"] and facts[1]["journal_status"] == "not_started"
    assert owner.recovery.controls(run_id)[0]["status"] == "applied"
    assert final["run_outcome"]["goal_outcome"] != "verified"


async def test_worktree_real_git_dirty_cleanup_and_request_identity(api):
    root = api[3]
    for args in (["init"], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "fixture"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    owner = api[0].state.desktop.runtime
    (root / "user.txt").write_text("user dirty", encoding="utf-8")
    worktree = owner.workspaces.create_worktree(api[4]["project_id"], "HEAD", "create-one")
    from pathlib import Path
    target = Path(worktree["root_path"])
    assert (target / ".git").is_file() and not (target / "user.txt").exists()
    assert owner.workspaces.create_worktree(api[4]["project_id"], "HEAD", "create-one")["id"] == worktree["id"]
    with pytest.raises(ValueError):
        owner.workspaces.create_worktree(api[4]["project_id"], "missing-ref", "bad")
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="保留"):
        owner.workspaces.remove_worktree(api[4]["project_id"], worktree["id"])
    (target / "keep.txt").unlink()
    assert owner.workspaces.remove_worktree(api[4]["project_id"], worktree["id"])["status"] == "archived"
    assert not target.exists() and (root / "user.txt").read_text() == "user dirty"


async def test_review_distinguishes_user_edit_and_protected_rollback(api):
    (api[3] / "existing.txt").write_text("before", encoding="utf-8")
    api[2].responses = [response(call("read_code_file", {"rel_path": "existing.txt"})),
        response(call("write_project_file", {"rel_path": "existing.txt", "content": "agent"})), response(text="修改已核对")]
    run_id = await create(api, permission_mode="workspace", message="修改 existing.txt")
    await until(api[1], run_id, TERMINAL)
    (api[3] / "existing.txt").write_text("user after", encoding="utf-8")
    report = (await api[1].get(f"/agent-runs/{run_id}/review")).json()
    assert report["task_changes"] and report["external_or_unattributed"][0]["rel_path"] == "existing.txt"
    patch_id = report["task_changes"][0]["patch_set_id"]
    preview = await api[1].post(f"/agent-runs/{run_id}/patches/{patch_id}/rollback-preview", json={"operation_id": "rollback-review"})
    assert preview.json()["status"] == "conflicted"
    assert (api[3] / "existing.txt").read_text() == "user after"


async def test_v6_migration_backup_and_future_version_rejection(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    for table in ("run_checkpoints", "run_control_requests", "workspace_leases"):
        store.db.execute(f"DROP TABLE {table}")
    store.db.execute("DELETE FROM schema_migrations")
    store.db.execute("PRAGMA user_version=6")
    store.db.commit()
    store.db.close()
    current = Store(path)
    assert current.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    backup = json.loads(current.db.execute("SELECT evidence FROM schema_migrations").fetchone()[0])["backup"]
    with sqlite3.connect(tmp_path / backup["filename"]) as old:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 6
    current.db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    current.db.close()
    with pytest.raises(ValueError, match="降级"):
        Store(path)


async def test_workspace_alias_and_abandoned_lease_never_expire(api):
    owner = api[0].state.desktop.runtime
    key = workspace_key(api[3])
    assert key == workspace_key(api[3] / ".")
    lock = FileLock(owner.workspaces.directory / (key + ".lock"))
    lock.write({"account": "other-owner", "run_id": "unknown", "updated_at": "2000-01-01"})
    lock.close()
    run_id = await create(api)
    queued = await until(api[1], run_id, {"queued"})
    assert "另一账号" in queued["queue_reason"]
    assert not owner.controls.model_tasks


async def test_failed_host_cleanup_keeps_lease_without_tool_result(api):
    run_id = await create(api)
    await waiting_model(api, run_id)
    owner = api[0].state.desktop.runtime
    owner.store.execution_sessions.save({"execution_id": "unconfirmed-host", "run_id": run_id,
        "session_id": api[4]["session_id"], "workspace_id": api[4]["workspace_id"], "status": "unknown", "stopped": False})
    _, cancelled = await control(api, run_id, "cancel")
    assert cancelled["cleanup_complete"] is False
    run = owner.store.run(run_id)
    assert not owner.recovery.inspect(run)["can_resume"]
    acquired, reason = owner.workspaces._take({**run, "id": "next-run"}, api[3])
    assert not acquired and "未核实副作用" in reason


async def test_resume_applies_received_but_interrupted_steer_without_duplicate_message(api):
    run_id = await create(api, permission_mode="workspace")
    await waiting_model(api, run_id)
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    await control(api, run_id, "steer", message="停止写文件，只解释")
    await control(api, run_id, "cancel")
    owner = api[0].state.desktop.runtime
    before = owner.store.run(run_id)
    old_controls = owner.recovery.controls(run_id)
    assert next(record for record in old_controls if record["kind"] == "steer")["status"] == "interrupted"
    api[2].responses = [response(call("write_project_file", {"rel_path": "forbidden.txt", "content": "旧工具不可执行"})), response(text="只解释当前结果")]
    _, resumed = await control(api, run_id, "resume")
    final = await until(api[1], resumed["result_run_id"], TERMINAL)
    assert not (api[3] / "forbidden.txt").exists()
    assert final["goal_version"] == before["goal_version"] + 1
    assert owner.store.run(run_id) == before
    carried = owner.recovery.controls(final["id"])[0]
    assert carried["status"] == "applied" and carried["source_run_id"] == run_id
    messages = (await api[1].get(f"/sessions/{api[4]['session_id']}/messages")).json()
    assert sum(message["content"] == "停止写文件，只解释" for message in messages) == 1


@pytest.mark.parametrize("boundary", ["model.requested", "model.response_confirmed", "tool.requested", "tool.approval_required", "patch.intent", "patch.disk", "patch.record", "tool.result_recorded"])
async def test_real_process_exit_preserves_checkpoint_and_partial_patch(tmp_path, boundary):
    helper = Path(__file__).parents[1] / "coding_acceptance" / "recovery_process.py"
    result = subprocess.run([sys.executable, "-B", str(helper), str(tmp_path), boundary], capture_output=True, timeout=25)
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    root = tmp_path / "project"
    before = {name: (root / name).read_text() for name in ("a.txt", "b.txt")}
    store = Store(tmp_path / "state.sqlite3")
    try:
        owner = Runtime(store, None, "fixture")
        run = store.runs()[0]
        report = owner.recovery.inspect(run)
        assert run["status"] == "interrupted"
        assert store.events(run["id"])[-1]["type"] == "run.interrupted"
        assert before == {name: (root / name).read_text() for name in before}
        assert store.db.execute("SELECT COUNT(*) FROM run_checkpoints").fetchone()[0] > 0
        assert report["can_resume"] is (boundary not in {"patch.intent", "patch.disk"}), report
        if boundary in {"patch.disk", "patch.record"}:
            assert before == {"a.txt": "after", "b.txt": "before"}
        if boundary == "tool.approval_required":
            assert report["expired_approvals"]
        if report["can_resume"]:
            acquired, reason = owner.workspaces._take(run, root)
            assert acquired, reason
            owner.workspaces.release(run)
    finally:
        store.db.close()


async def test_real_host_start_then_service_exit_marks_unknown_without_replay(tmp_path):
    helper = Path(__file__).parents[1] / "coding_acceptance" / "recovery_process.py"
    result = subprocess.run([sys.executable, "-B", str(helper), str(tmp_path), "execution.started"], capture_output=True, timeout=25)
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    store = Store(tmp_path / "state.sqlite3")
    try:
        owner = Runtime(store, None, "fixture")
        run = store.runs()[0]
        report = owner.recovery.inspect(run)
        assert not report["can_resume"]
        assert report["executions"][0]["status"] == "unknown"
        assert report["executions"][0]["host_instance_id"]
        acquired, _ = owner.workspaces._take(run, tmp_path / "project")
        assert not acquired
        starts = tmp_path / "project" / "starts.txt"
        await asyncio.sleep(0.3)
        assert not starts.exists() or starts.read_text().splitlines() == ["started"]
    finally:
        store.db.close()


async def test_resume_reuses_prior_file_evidence_and_checks_model_version(api):
    api[2].responses = [response(call("write_project_file", {"rel_path": "done.txt", "content": "done"}))]
    run_id = await create(api, permission_mode="workspace", message="创建 done.txt")
    for _ in range(200):
        if api[0].state.desktop.runtime.store.run_state(run_id).get("loop_budget", {}).get("model_requests", 0) >= 2:
            break
        await asyncio.sleep(0.01)
    await control(api, run_id, "cancel")
    owner = api[0].state.desktop.runtime
    previous = owner.store.run(run_id)
    api[2].profiles[0]["context_tokens"] += 1
    report = owner.recovery.inspect(previous)
    result = await api[1].post(f"/agent-runs/{run_id}/resume", json={"request_id": "changed", "expected_state_version": report["state_version"], "checkpoint_id": report["checkpoint_id"]})
    assert result.status_code == 422 and "模型" in result.text
    api[2].profiles[0]["context_tokens"] -= 1
    api[2].responses = [response(text="已核对前次文件结果")]
    _, resumed = await control(api, run_id, "resume")
    final = await until(api[1], resumed["result_run_id"], TERMINAL)
    assert final["goal_outcome"] == "verified", final
    assert final["run_outcome"]["evidence_refs"][0]["run_id"] == final["id"]
    assert any(event["type"] == "evidence.revalidated" and event["payload"]["source_run_id"] == run_id for event in owner.store.events(final["id"]))
    assert owner.store.run(run_id) == previous


async def test_same_git_worktree_subdirectory_has_same_lease(api):
    subprocess.run(["git", "init"], cwd=api[3], check=True, capture_output=True)
    sub = api[3] / "sub"
    sub.mkdir()
    assert workspace_key(api[3]) == workspace_key(sub)
