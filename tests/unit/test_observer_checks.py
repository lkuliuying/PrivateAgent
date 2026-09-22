"""观察器配置、用户约束、真实完成证据与诊断边界的隔离回归。"""
import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_core.coding_contracts import Requirement
from private_agent_core.task_intent import interpret_task
from private_agent_local.completion import LocalCompletionVerifier
from private_agent_local.observer import selected_checks
from private_agent_local.runtime import TERMINAL
from private_agent_local.task_constraints import apply_steer, store_interpretation

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    try:
        yield values
    finally:
        await close(values[0], values[1])


def check(kind="artifact", scope="app.py", identifier="result"):
    return {"id": identifier, "kind": kind, "scope": scope}


async def configure(api, checks, *, enabled=True, expected_version=0):
    result = await api[1].put(f"/projects/{api[4]['project_id']}/observer-config", json={
        "expected_version": expected_version, "enabled": enabled, "checks": checks})
    assert result.status_code == 200, result.text
    return result.json()


def pending(api, message="修改 app.py", **overrides):
    owner = api[0].state.desktop.runtime
    value = owner.create({**api[4], "message": message, "permission_mode": "workspace", **overrides}, launch=False)
    return owner, owner.store.run(value["id"])


async def complete(api, responses, *, message="修改 app.py", **overrides):
    api[2].responses = responses
    created = await api[1].post("/agent-runs", json={**api[4], "message": message,
                                                       "permission_mode": "workspace", **overrides})
    assert created.status_code == 201, created.text
    return await until(api[1], created.json()["id"], TERMINAL)


def interpreted(message, checks, **overrides):
    run = {"id": str(uuid4()), "permission_mode": "workspace", "collaboration_mode": "default",
           "observer_config": {"version": 1, "enabled": True, "checks": checks}}
    store_interpretation(run, interpret_task(message))
    run.update(overrides)
    return run


async def test_local_report_does_not_disable_independent_project_checks(tmp_path):
    run = interpreted("只修改 A.py，解析模块先汇报不动工，然后运行测试", [check("test", "python -m pytest", "tests")])
    requirements, checks = selected_checks(run, tmp_path)
    assert len(requirements) == 1 and checks[0]["status"] == "pending"
    apply_steer(run, "不运行测试", "stop-tests")
    requirements, checks = selected_checks(run, tmp_path)
    assert not requirements and checks[0]["reason_code"] == "user_constraint"


async def test_config_defaults_versions_and_rejected_save_preserve_state(api):
    url = f"/projects/{api[4]['project_id']}/observer-config"
    initial = await api[1].get(url)
    assert initial.status_code == 200
    assert initial.json() == {"version": 0, "enabled": False, "checks": []}
    saved = await configure(api, [check("test", "python   -m pytest", "tests")])
    assert saved == {"version": 1, "enabled": True,
                     "checks": [check("test", "python -m pytest", "tests")]}
    stale = await api[1].put(url, json={"expected_version": 0, "enabled": False, "checks": []})
    assert stale.status_code == 422
    assert stale.json()["error_code"] == "observer_config_changed"
    assert (await api[1].get(url)).json() == saved
    disabled = await configure(api, [], enabled=False, expected_version=1)
    assert disabled == {"version": 2, "enabled": False, "checks": []}


@pytest.mark.parametrize("changes", [
    {"enabled": True, "checks": []},
    {"enabled": "true"},
    {"expected_version": True},
    {"expected_version": -1},
    {"extra": "unexpected"},
    {"checks": [check(identifier=f"check-{index}", scope=f"file-{index}.py") for index in range(9)]},
    {"checks": [check(), check(scope="other.py")]},
    {"checks": [check(), check(identifier="other")]},
    {"checks": [{**check(), "unknown": "unexpected"}]},
    {"checks": [check(identifier="bad identifier")]},
    {"checks": [check(kind="unknown")]},
    {"checks": [check(scope="")]},
    {"checks": [check(scope="x" * 1001)]},
    {"checks": [check(scope="../outside.txt")]},
    {"checks": [check(scope="C:\\outside.txt")]},
    {"checks": [check(scope="/outside.txt")]},
    {"checks": [check(scope=".env")]},
    {"checks": [check(scope="app.py\nsecret.txt")]},
    {"checks": [check("command", "python -c 'print(1)'")]},
    {"checks": [check("command", "python -m pytest; echo done")]},
    {"checks": [check("test", "python --version")]},
])
async def test_invalid_config_never_persists(api, changes):
    url = f"/projects/{api[4]['project_id']}/observer-config"
    data = {"expected_version": 0, "enabled": True, "checks": [check()], **changes}
    result = await api[1].put(url, json=data)
    assert result.status_code == 422, result.text
    assert (await api[1].get(url)).json() == {"version": 0, "enabled": False, "checks": []}


@pytest.mark.parametrize("duplicate", ["id", "scope"])
async def test_duplicate_config_error_does_not_echo_scope(api, duplicate):
    private_scope = "config-private-sentinel.py"
    checks = [check(scope=private_scope),
              check(scope="other.py" if duplicate == "id" else private_scope,
                    identifier="result" if duplicate == "id" else "another")]
    url = f"/projects/{api[4]['project_id']}/observer-config"
    result = await api[1].put(url, json={"expected_version": 0, "enabled": True, "checks": checks})
    assert result.status_code == 422, result.text
    assert result.json()["error_code"] == "observer_config_invalid"
    assert private_scope not in result.text
    assert (await api[1].get(url)).json() == {"version": 0, "enabled": False, "checks": []}


@pytest.mark.parametrize("message,overrides,reason", [
    ("解释 app.py", {}, "not_applicable"),
    ("只给 app.py 的补丁预览，不写入", {}, "user_constraint"),
    ("修改 app.py，但不修改任何文件", {}, "user_constraint"),
    ("修改 app.py", {"permission_mode": "readonly"}, "readonly"),
    ("修改 app.py", {"collaboration_mode": "plan"}, "plan_mode"),
])
async def test_inactive_tasks_do_not_acquire_project_requirements(tmp_path, message, overrides, reason):
    requirements, checks = selected_checks(interpreted(message, [check()], **overrides), tmp_path)
    assert requirements == []
    assert checks[0]["status"] == "skipped" and checks[0]["reason_code"] == reason


@pytest.mark.parametrize("kind,scope,blocked", [
    ("test", "python -m pytest", True), ("command", "python -m pytest", True),
    ("command", "npm run qa", True), ("command", "python verify.py", False),
])
async def test_test_ban_distinguishes_known_aliases_from_unknown_wrappers(tmp_path, kind, scope, blocked):
    (tmp_path / "package.json").write_text('{"scripts":{"qa":"vitest run"}}', encoding="utf-8")
    run = interpreted("修改 app.py，但不要运行测试", [check(kind, scope)])
    requirements, checks = selected_checks(run, tmp_path)
    assert bool(requirements) is not blocked
    assert checks[0]["reason_code"] == ("user_constraint" if blocked else "awaiting_evidence")


async def test_artifact_checks_cannot_expand_user_access_scope(tmp_path):
    run = interpreted("只允许访问 src/，修改 src/app.py", [check(scope="private/output.txt")])
    requirements, checks = selected_checks(run, tmp_path)
    assert requirements == []
    assert checks[0]["reason_code"] == "user_constraint"


async def test_steering_recalculates_effective_checks_without_rewriting_snapshot(tmp_path):
    run = interpreted("修改 app.py", [check("test", "python -m pytest")])
    run["goal"] = "修改 app.py"
    original = json.dumps(run["observer_config"], sort_keys=True)
    assert len(selected_checks(run, tmp_path)[0]) == 1
    apply_steer(run, "接下来不要运行任何命令", "stop-commands")
    requirements, checks = selected_checks(run, tmp_path)
    assert requirements == [] and checks[0]["reason_code"] == "user_constraint"
    assert json.dumps(run["observer_config"], sort_keys=True) == original


async def test_run_snapshot_survives_config_updates_and_linked_recovery(api):
    old = await configure(api, [check(scope="old.py")])
    owner, run = pending(api, recovery_contract_version="1.0")
    assert run["observer_config"] == old
    changed = await configure(api, [check(scope="new.py")], expected_version=1)
    assert owner.store.run(run["id"])["observer_config"] == old
    run["status"] = "cancelled"
    owner.store.save_run(run)
    resumed = owner.create({**api[4], "message": "继续", "permission_mode": "workspace",
                            "recovery_contract_version": "1.0"}, parent=run, launch=False)
    child = owner.store.run(resumed["id"])
    assert child["observer_config"] == old
    assert child["resumed_from_run_id"] == run["id"]
    child["observer_config"]["checks"][0]["scope"] = "child-only.py"
    assert run["observer_config"] == old
    child["status"] = "cancelled"
    owner.store.save_run(child)
    _, fresh = pending(api)
    assert fresh["observer_config"] == changed


@pytest.mark.parametrize("field,value", [("version", 99), ("enabled", False), ("checks", [check(scope="replaced.py")])])
async def test_checkpoint_rejects_changed_observer_snapshot(api, field, value):
    await configure(api, [check()])
    owner, run = pending(api, recovery_contract_version="1.0")
    checkpoint = owner.recovery.load_checkpoint(run)
    assert checkpoint["run_id"] == run["id"]
    run["observer_config"][field] = value
    owner.store.save_run(run)
    with pytest.raises(ValueError, match="检查点不一致"):
        owner.recovery.load_checkpoint(owner.store.run(run["id"]))


@pytest.mark.parametrize("message,overrides,reason", [
    ("修改 app.py", {"collaboration_mode": "plan", "recovery_contract_version": "1.0"}, "plan_mode"),
    ("修改 app.py", {"permission_mode": "readonly"}, "readonly"),
    ("解释 app.py", {}, "not_applicable"),
])
async def test_unverified_inapplicable_runs_report_checks_as_skipped(api, message, overrides, reason):
    await configure(api, [check()])
    owner, run = pending(api, message, **overrides)
    prior_sequence = run["last_event_sequence"]
    result = await api[1].get(f"/agent-runs/{run['id']}/observer")
    assert result.status_code == 200, result.text
    assert result.json()["checks"] == [{"id": "result", "kind": "artifact", "status": "skipped",
                                         "reason_code": reason, "evidence_ids": []}]
    assert owner.store.run_state(run["id"])["last_event_sequence"] == prior_sequence
    assert not api[2].calls


async def test_diagnostics_survive_workspace_revocation_without_mutating_run(api):
    await configure(api, [check(scope="scope-private-sentinel.py")])
    owner, run = pending(api)
    owner.store.update("workspace", api[4]["workspace_id"], status="archived")
    before = owner.store.run(run["id"])
    result = await api[1].get(f"/agent-runs/{run['id']}/observer")
    assert result.status_code == 200, result.text
    assert result.json()["checks"] == [{"id": "result", "kind": "artifact", "status": "unverified",
                                         "reason_code": "scope_unavailable", "evidence_ids": []}]
    assert "private-sentinel" not in result.text
    assert str(api[3]) not in result.text and api[3].as_posix() not in result.text
    assert owner.store.run(run["id"]) == before
    assert api[3].is_dir()
    assert not api[2].calls


async def test_existing_requirement_id_collision_preserves_both_verdicts(api):
    await configure(api, [check()])
    owner, run = pending(api)
    await owner.tool(run, api[3], call("write_project_file", {"rel_path": "app.py", "content": "fixed"}))
    # 模拟已有记录的外部验收 ID 与新配置名重叠，不能让产物通过覆盖用户失败。
    user_requirement = Requirement(requirement_id="observer-result", kind="artifact", scope="required.txt",
                                   description="用户要求的独立产物", origin="user", evidence_policy="disk")
    run["completion_requirements"].append(user_requirement.model_dump(mode="json"))
    owner.store.save_run(run)
    requirements, checks = selected_checks(run, api[3])
    assert len(requirements) == 1
    configured_id = requirements[0].requirement_id
    assert configured_id != user_requirement.requirement_id
    assert checks[0]["requirement_id"] == configured_id
    outcome = await LocalCompletionVerifier(owner, run, api[3]).load_outcome("产物已经准备好")
    verdicts = {item.requirement_id: item for item in outcome.verification_results}
    assert len(verdicts) == len(outcome.verification_results)
    assert verdicts[user_requirement.requirement_id].status == "failed"
    assert verdicts[configured_id].status == "passed"
    assert outcome.goal_outcome == "unmet"
    report = await api[1].get(f"/agent-runs/{run['id']}/observer")
    assert report.status_code == 200, report.text
    assert report.json()["checks"][0]["status"] == "passed"
    assert "requirement_id" not in report.json()["checks"][0]


async def test_real_file_evidence_satisfies_project_check(api, monkeypatch):
    await configure(api, [check()])
    command = AsyncMock()
    monkeypatch.setattr("private_agent_local.runtime.run_command", command)
    run = await complete(api, [response(call("write_project_file", {"rel_path": "app.py", "content": "fixed"})),
                               response(text="文件已修改")])
    assert run["status"] == "completed" and run["goal_outcome"] == "verified"
    report = (await api[1].get(f"/agent-runs/{run['id']}/observer")).json()
    assert report["checks"][0]["status"] == "passed"
    assert report["checks"][0]["evidence_ids"]
    assert (api[3] / "app.py").read_text(encoding="utf-8") == "fixed"
    command.assert_not_called()


async def test_missing_configured_evidence_retries_same_model_at_most_twice(api, monkeypatch):
    await configure(api, [check("test", "python -m pytest", "tests")])
    command = AsyncMock()
    monkeypatch.setattr("private_agent_local.runtime.run_command", command)
    run = await complete(api, [response(call("write_project_file", {"rel_path": "app.py", "content": "fixed"})),
                               *[response(text="全部测试通过") for _ in range(3)]])
    assert run["status"] == "failed" and run["goal_outcome"] == "unmet"
    assert run["verification_retries"] == 2
    requests = [json.loads(body) for path, body in api[2].calls if path == "/desktop/model/complete"]
    assert len(requests) == 4
    assert run["loop_budget"]["model_requests"] == 4
    assert run["tool_call_count"] == 1
    assert any("python -m pytest" in item.get("content", "")
               for item in requests[-1]["request"]["messages"] if item["role"] == "user")
    command.assert_not_called()


@pytest.mark.parametrize("message", ["修改 app.py，不要运行测试", "修改 app.py，不要运行任何命令"])
async def test_user_ban_skips_configured_tests_without_retry_or_false_success(api, monkeypatch, message):
    await configure(api, [check("test", "python -m pytest", "tests")])
    command = AsyncMock()
    monkeypatch.setattr("private_agent_local.runtime.run_command", command)
    run = await complete(api, [response(call("write_project_file", {"rel_path": "app.py", "content": "fixed"})),
                               response(text="修改和测试全部通过")], message=message)
    assert run["status"] == "completed" and run["goal_outcome"] == "unknown"
    assert not run.get("verification_retries")
    assert "功能正确性尚未验证" in run["output"]
    assert "测试全部通过" not in run["output"]
    report = (await api[1].get(f"/agent-runs/{run['id']}/observer")).json()
    assert report["checks"][0]["status"] == "skipped"
    assert report["checks"][0]["reason_code"] == "user_constraint"
    command.assert_not_called()


@pytest.mark.parametrize("change", ["disk", "terminal", "cwd"])
async def test_configured_command_requires_current_bound_evidence(api, monkeypatch, change):
    await configure(api, [check("test", "python -m pytest", "tests")])
    owner, run = pending(api)
    monkeypatch.setattr("private_agent_local.runtime.run_command", AsyncMock(return_value={
        "returncode": 0, "stdout": "1 passed", "stderr": "", "truncated": False}))
    await owner.tool(run, api[3], call("write_project_file", {"rel_path": "app.py", "content": "fixed"}))
    await owner.tool(run, api[3], call("run_project_command", {"command": "python -m pytest"}))
    verifier = LocalCompletionVerifier(owner, run, api[3])
    first = await verifier.verify("已修改并检查", attempt=1)
    assert first.passed
    if change == "disk":
        (api[3] / "unrelated.py").write_text("changed externally", encoding="utf-8")
    else:
        execution = next(item for item in run["executions"] if item.get("command"))
        if change == "terminal":
            execution["source_sequence"] = -1
        else:
            execution.update(tool_name="exec_command", cwd="another-package")
        owner.store.save_run(run)
    second = await verifier.verify("仍然通过", attempt=2)
    assert not second.passed
    result = next(item for item in verifier.last_outcome.verification_results if item.requirement_id == "observer-tests")
    assert result.status != "passed"
    if change == "disk":
        assert result.status == "failed" and "过期" in result.message


@pytest.mark.parametrize("kind,change", [("artifact", "workspace"), ("test", "workspace"), ("test", "steer")])
async def test_diagnostics_do_not_reuse_checks_after_workspace_or_constraint_changes(api, monkeypatch, kind, change):
    scope = "app.py" if kind == "artifact" else "python -m pytest"
    await configure(api, [check(kind, scope)])
    owner, run = pending(api)
    command = AsyncMock(return_value={"returncode": 0, "stdout": "1 passed", "stderr": "", "truncated": False})
    monkeypatch.setattr("private_agent_local.runtime.run_command", command)
    first_write = await owner.tool(run, api[3], call("write_project_file", {"rel_path": "app.py", "content": "fixed"}))
    assert first_write["status"] == "applied" and first_write.get("error") is None, first_write
    assert (api[3] / "app.py").read_text(encoding="utf-8") == "fixed"
    if kind == "test":
        await owner.tool(run, api[3], call("run_project_command", {"command": scope}))
    assert (await LocalCompletionVerifier(owner, run, api[3]).verify("已核对完成", attempt=1)).passed
    initial = (await api[1].get(f"/agent-runs/{run['id']}/observer")).json()
    assert initial["checks"][0]["status"] == "passed"
    assert initial["checks"][0]["evidence_ids"]
    if change == "workspace":
        prior_version = run["workspace_version"]
        snapshot = await owner.tool(run, api[3], call("read_code_file", {"rel_path": "app.py"}))
        assert "error" not in snapshot and snapshot.get("snapshot_id"), snapshot
        written = await owner.tool(run, api[3], call("write_project_file", {"rel_path": "app.py", "content": "changed again"}))
        assert written["status"] == "applied" and written.get("error") is None, written
        assert (api[3] / "app.py").read_text(encoding="utf-8") == "changed again"
        assert run["workspace_version"] == prior_version + 1
    else:
        apply_steer(run, "接下来不要运行测试", "observer-stop-tests")
        owner.store.save_run(run)
    before = owner.store.run(run["id"])
    result = await api[1].get(f"/agent-runs/{run['id']}/observer")
    assert result.status_code == 200, result.text
    selected = result.json()["checks"][0]
    assert selected["status"] == ("pending" if change == "workspace" else "skipped")
    assert selected["reason_code"] == ("evidence_stale" if change == "workspace" else "user_constraint")
    assert selected["evidence_ids"] == []
    assert owner.store.run(run["id"]) == before
    assert command.await_count == (1 if kind == "test" else 0)


async def test_diagnostics_are_bounded_and_never_return_free_text(api):
    await configure(api, [check(scope="scope-private-sentinel.py")])
    owner, run = pending(api, "修改 app.py；goal-private-sentinel")
    run.update(output="output-private-sentinel", error_code="code-private-sentinel",
               error_message="error-private-sentinel", pending_response={"text": "response-private-sentinel"})
    run["steps"] = [{"id": str(uuid4()), "ordinal": index, "kind": "tool", "status": "completed",
                     "name": "name-private-sentinel", "tool_call_id": "call-private-sentinel",
                     "arguments": {"password": "argument-private-sentinel"}, "output": "step-private-sentinel",
                     "plan_context": {"item_key": "plan-private-sentinel"}} for index in range(105)]
    run["steps"][-1]["id"] = "id-private-sentinel"
    owner.store.save_run(run)
    for index in range(105):
        owner.event(run, "tool.completed", step_id="id-private-sentinel", execution_id="execution-private-sentinel",
                    stdout="stdout-private-sentinel", stderr="stderr-private-sentinel",
                    arguments={"token": "event-private-sentinel"}, message="message-private-sentinel", index=index)
    report = await api[1].get(f"/agent-runs/{run['id']}/observer")
    assert report.status_code == 200, report.text
    data = report.json()
    assert "private-sentinel" not in report.text
    assert len(data["events"]) == len(data["steps"]) == 100
    assert data["counts"]["events"] == 105 and data["counts"]["steps"] == 105
    assert data["truncated"] is True
    assert data["error"] == {"category": "other", "code": "unknown_error"}
    assert data["events"][0]["sequence"] == 6
    assert all(item["step_id"] is None and item["execution_id"] is None for item in data["events"])
    assert all(item["name"] is None for item in data["steps"])


async def test_diagnostics_and_config_require_existing_local_records(api):
    missing = await api[1].get(f"/agent-runs/{uuid4()}/observer")
    assert missing.status_code == 404
    missing_config = await api[1].get("/projects/999999/observer-config")
    assert missing_config.status_code == 404
    unauthorized = await api[1].get(f"/projects/{api[4]['project_id']}/observer-config",
                                     headers={"Authorization": ""})
    assert unauthorized.status_code == 401


async def test_real_cancel_resume_preserves_observer_snapshot_and_retry_budget(api):
    await configure(api, [check(scope="missing.py")])
    api[2].responses = [response(call("write_project_file", {"rel_path": "app.py", "content": "fixed"})),
                        response(text="已完成修改")]
    created = await api[1].post("/agent-runs", json={**api[4], "message": "修改 app.py", "permission_mode": "workspace",
                                                    "recovery_contract_version": "1.0"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    owner = api[0].state.desktop.runtime
    for _ in range(300):
        state = owner.store.run_state(run_id)
        if state.get("verification_retries") == 1 and state.get("loop_budget", {}).get("model_requests", 0) >= 3:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("观察器反馈后未进入下一次模型请求")
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    cancelled = await api[1].post(f"/agent-runs/{run_id}/cancel", json={
        "request_id": "cancel-observer", "expected_state_version": report["state_version"]})
    assert cancelled.status_code in {200, 202}, cancelled.text
    await until(api[1], run_id, {"cancelled"})
    await configure(api, [], enabled=False, expected_version=1)
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    api[2].responses = [response(text="仍然没有产物"), response(text="产物仍未创建")]
    resumed = await api[1].post(f"/agent-runs/{run_id}/resume", json={
        "request_id": "resume-observer", "expected_state_version": report["state_version"],
        "checkpoint_id": report["checkpoint_id"]})
    assert resumed.status_code == 202, resumed.text
    final = await until(api[1], resumed.json()["result_run_id"], TERMINAL)
    assert final["verification_retries"] == 2
    assert final["goal_outcome"] == "unmet"
    child = owner.store.run(final["id"])
    assert child["observer_config"]["version"] == 1 and child["observer_config"]["enabled"]
    assert child["loop_budget"]["model_requests"] == 5
