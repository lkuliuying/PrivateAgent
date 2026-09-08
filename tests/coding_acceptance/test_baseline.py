"""S0 缺陷基线；预期失败只覆盖已复现的产品缺口，不覆盖环境错误。"""
import json
import os
from pathlib import Path

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_local import files
from private_agent_local.runtime import TERMINAL
from private_agent_local.store import Store


def record(case_id: str, **facts):
    directory = Path(os.environ["CODING_VALIDATION_DIR"]) / "observations"
    directory.mkdir(exist_ok=True)
    (directory / f"{case_id}.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    try:
        yield values
    finally:
        await close(values[0], values[1])


async def test_s0_t01_false_completion(api):
    app, client, server, root, body = api
    target = root / "source.txt"
    target.write_text("before", encoding="utf-8")
    server.responses = [response(text="已修改 source.txt 并通过测试") for _ in range(3)]
    run_id = (await client.post("/agent-runs", json={**body, "message": "修改 source.txt 并测试"})).json()["id"]
    run = await until(client, run_id, TERMINAL)
    record("S0-T01", status=run["status"], goal_outcome=run.get("goal_outcome"),
           tool_call_count=run["tool_call_count"], disk_changed=target.read_text() != "before")
    assert run.get("goal_outcome") == "unmet"


async def test_s0_t02_failed_test(api, monkeypatch):
    app, client, server, root, body = api

    async def fail_command(*args, **kwargs):
        return {"returncode": 1, "stdout": "1 failed", "stderr": "", "truncated": False}

    monkeypatch.setattr("private_agent_local.runtime.run_command", fail_command)
    server.responses = [response(call("run_project_command", {"command": "python -m pytest"})), *[response(text="已完成") for _ in range(3)]]
    run_id = (await client.post("/agent-runs", json={**body, "permission_mode": "workspace"})).json()["id"]
    run = await until(client, run_id, TERMINAL)
    execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
    request = json.loads(server.calls[-1][1])
    record("S0-T02", status=run["status"], execution=execution,
           model_request=request)
    assert run.get("goal_outcome") == "unmet"


async def test_s0_t03_large_file_tail(api):
    app, client, server, root, body = api
    content = "x" * (files.MAX_OUTPUT + 100) + "TAIL_NEEDLE"
    (root / "large.txt").write_text(content, encoding="utf-8")
    server.responses = [response(call("read_code_file", {"rel_path": "large.txt"})), response(text="已读取")]
    run_id = (await client.post("/agent-runs", json=body)).json()["id"]
    await until(client, run_id, TERMINAL)
    execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
    output = execution["output"]
    record("S0-T03", truncated=output["truncated"], visible_characters=len(output["content"]), tail_visible="TAIL_NEEDLE" in output["content"])
    assert output["truncated"] and len(output["content"]) == files.MAX_OUTPUT
    assert "TAIL_NEEDLE" not in output["content"]


async def test_s0_t04_model_round_limit_and_store_cost(api):
    app, client, server, root, body = api
    server.responses = [response({"id": f"round-{i}", "name": "list_project_directory", "arguments": {}}) for i in range(25)]
    statements = []
    store = app.state.desktop.runtime.store
    store.db.set_trace_callback(statements.append)
    try:
        run_id = (await client.post("/agent-runs", json={**body, "context_limits": {"max_model_requests": 24}})).json()["id"]
        run = await until(client, run_id, TERMINAL)
    finally:
        store.db.set_trace_callback(None)
    persisted = store.run(run_id)
    calls = sum(path == "/desktop/model/complete" for path, _ in server.calls)
    record("S0-T04", model_requests=calls, status=run["status"], error_code=run["error_code"],
           event_count=len(persisted["events"]),
           run_row_writes=sum(s.startswith("INSERT INTO runs") for s in statements),
           execution_row_reads=sum(s.startswith("SELECT data FROM executions") for s in statements),
           blob_count=len(list(store.blobs.glob("*"))) if store.blobs.exists() else 0)
    assert calls == 24 and run["status"] == "limit_exceeded" and run["error_code"] == "max_model_requests"
    assert [event["sequence"] for event in persisted["events"]] == list(range(1, len(persisted["events"]) + 1))


async def test_s0_t05_desktop_passes_s4_timeout(api, monkeypatch):
    app, client, server, root, body = api
    observed = []

    async def timeout_command(*args, **kwargs):
        observed.append(kwargs["timeout"])
        raise TimeoutError

    monkeypatch.setattr("private_agent_local.runtime.run_command", timeout_command)
    server.responses = [response(call("run_project_command", {"command": "python -m pytest"})), response(text="停止")]
    run_id = (await client.post("/agent-runs", json={**body, "permission_mode": "workspace"})).json()["id"]
    await until(client, run_id, TERMINAL)
    execution = (await client.get(f"/agent-runs/{run_id}/executions")).json()[0]
    record("S0-T05", configured_timeout=observed, execution_status=execution["status"], real_120_second_command=False)
    assert observed == [600] and execution["status"] == "failed"


async def test_s0_t06_cancel_approval_then_restart(api, tmp_path):
    app, client, server, root, body = api
    target = root / "cancel.txt"
    target.write_text("before", encoding="utf-8")
    server.responses = [response(call("read_code_file", {"rel_path": "cancel.txt"})),
                        response(call("write_project_file", {"rel_path": "cancel.txt", "content": "after"}))]
    run_id = (await client.post("/agent-runs", json=body)).json()["id"]
    await until(client, run_id, {"waiting_approval"})
    approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
    await client.post(f"/agent-runs/{run_id}/cancel")
    run = await until(client, run_id, TERMINAL)
    late = await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")
    path = tmp_path / "restart.sqlite3"
    store = Store(path)
    store.save_run({"id": "interrupted", "status": "waiting_approval", "approvals": [{"status": "pending"}],
                    "executions": [{"status": "running"}]})
    store.db.close()
    restarted = Store(path)
    try:
        recovered = restarted.run("interrupted")
        record("S0-T06", cancelled_status=run["status"], late_approval_status=late.status_code,
               recovered_status=recovered["status"], operation_status=recovered["executions"][0]["status"], disk_changed=target.read_text() != "before")
        assert recovered["status"] == "failed" and recovered["executions"][0]["status"] == "unknown"
    finally:
        restarted.db.close()
    assert run["status"] == "cancelled" and late.status_code == 422 and target.read_text() == "before"


async def test_s0_t07_preserves_user_change_after_preview(api):
    app, client, server, root, body = api
    target = root / "dirty.txt"
    target.write_text("user change", encoding="utf-8")
    server.responses = [response(call("read_code_file", {"rel_path": "dirty.txt"})),
                        response(call("write_project_file", {"rel_path": "dirty.txt", "content": "model change"})), response(text="停止")]
    run_id = (await client.post("/agent-runs", json=body)).json()["id"]
    await until(client, run_id, {"waiting_approval"})
    target.write_text("new user change", encoding="utf-8")
    approval = (await client.get(f"/agent-runs/{run_id}/approvals")).json()[0]
    await client.post(f"/agent-runs/{run_id}/approvals/{approval['id']}/approve")
    await until(client, run_id, TERMINAL)
    record("S0-T07", preserved=target.read_text() == "new user change", protection_window="preview-to-write")
    assert target.read_text() == "new user change"


async def test_s0_t08_current_capability_surface(api):
    app, client, server, root, body = api
    health = (await client.get("/health")).json()
    caps = (await client.get("/capabilities")).json()
    record("S0-T08", health=health, capabilities=caps,
           note="旧客户端失败关闭由 localExecutor.spec.ts 验证；当前没有新的必需能力协商")
    assert health["protocol"] == 1 and health["mode"] == "desktop-local"
    assert caps["coding_worktree_enabled"] is False
