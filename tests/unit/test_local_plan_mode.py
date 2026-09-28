"""规划模式的权限边界、真实用户交互与实施交接。"""
import asyncio
import uuid

import pytest
from test_local_executor import call, close, response, setup, until
from test_local_planning import idle_run, model_requests, plan_call, step
from test_local_recovery import control, create

from private_agent_core.planning import PlanUpdate
from private_agent_local.completion import LocalCompletionVerifier
from private_agent_local.planning import completion_blockers
from private_agent_local.runtime import TERMINAL, Runtime
from private_agent_local.store import Store
from private_agent_local.task_constraints import tool_allowed


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    values[4].update(recovery_contract_version="1.0", permission_mode="confirm", collaboration_mode="plan")
    try:
        yield values
    finally:
        await close(values[0], values[1])


def question():
    return call("request_user_input", {"questions": [{"id": "scope", "question": "希望覆盖哪些模块？",
        "options": [{"label": "当前模块", "description": "限制到当前模块"}, {"label": "整个项目", "description": "覆盖所有模块"}]}]})


def control_data(run, **fields):
    return {"request_id": uuid.uuid4().hex, "expected_state_version": run["state_version"],
            "checkpoint_id": run["checkpoint_id"], **fields}


@pytest.mark.asyncio
async def test_plan_finishes_pending_and_implementation_is_separate(api):
    api[2].responses = [response(plan_call(items=[step(status="pending")])), response(text="先阅读模块，再给出建议。")]
    run_id = await create(api, message="制定模块检查计划")
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed", final
    assert final["goal_outcome"] == "answered"
    assert final["plan"]["items"][0]["status"] == "pending"
    assert final["output"].startswith("实施计划（尚未执行）")
    assert final["run_outcome"]["unverified_items"]
    owner = api[0].state.desktop.runtime
    exposed = {tool["name"] for tool in model_requests(api)[0]["tools"]}
    assert "request_user_input" in exposed
    assert not exposed.intersection({"write_project_file", "exec_command", "run_project_command", "propose_project_patch"})
    data = control_data(final, expected_plan_version=final["plan"]["version"])
    stale = await api[1].post(f"/agent-runs/{run_id}/implement-plan", json={**data, "expected_plan_version": 9})
    assert stale.status_code == 409
    api[2].responses = [response(plan_call(1, [step()])), response(plan_call(2, [step(status="completed")])), response(text="已检查。")]
    accepted = await api[1].post(f"/agent-runs/{run_id}/implement-plan", json=data)
    assert accepted.status_code == 202, accepted.text
    repeated = await api[1].post(f"/agent-runs/{run_id}/implement-plan", json=data)
    assert repeated.json() == accepted.json()
    child = await until(api[1], accepted.json()["result_run_id"], TERMINAL)
    assert child["collaboration_mode"] == "default" and child["permission_mode"] == final["permission_mode"]
    assert child["resumed_from_run_id"] == run_id and child["logical_task_id"] == final["logical_task_id"]
    assert child["plan"]["version"] == 3 and child["status"] == "completed", child
    assert owner.store.run_state(run_id)["plan"] == final["plan"]


@pytest.mark.asyncio
async def test_plan_blocks_direct_write_command_and_execution_claims(api):
    owner, run = idle_run(api, message="修改 sample.py")
    for name in ("write_project_file", "apply_project_patch", "propose_project_patch", "run_project_command", "exec_command", "write_stdin"):
        result = await owner.tool(run, api[3], call(name, {}))
        assert result["error_code"] == "user_constraint", (name, result)
        assert not tool_allowed(name, run)
    assert not (api[3] / "sample.py").exists()
    verifier = LocalCompletionVerifier(owner, run, api[3])
    assert not (await verifier.verify("已完成", attempt=1)).passed
    await owner.tool(run, api[3], plan_call(items=[step(status="pending")]))
    assert not (await verifier.verify("计划已写好", attempt=1)).passed
    requirements = [item["requirement_id"] for item in run["completion_requirements"]]
    await owner.tool(run, api[3], plan_call(1, [step(status="pending", requirement_ids=requirements)]))
    assert (await verifier.verify("拟修改 sample.py 并验证结果", attempt=1)).passed
    assert verifier.last_outcome.goal_outcome == "answered"
    assert not verifier.last_outcome.verification_results


@pytest.mark.asyncio
async def test_question_waits_for_real_answer_and_replans(api):
    api[2].responses = [response(question())]
    run_id = await create(api, message="制定模块检查计划")
    waiting = await until(api[1], run_id, {"waiting_input"})
    owner = api[0].state.desktop.runtime
    assert owner.store.has_active_run()
    assert owner.store.runs(active_only=True)[0]["id"] == run_id
    assert owner.contexts[run_id].input_started is not None
    remaining = owner.contexts[run_id].remaining_seconds()
    await asyncio.sleep(0.06)
    assert owner.contexts[run_id].remaining_seconds() == pytest.approx(remaining, abs=0.015)
    data = control_data(waiting, input_id=waiting["pending_input"]["input_id"], answers={"scope": "仅查看，不修改文件"})
    invalid = await api[1].post(f"/agent-runs/{run_id}/answer", json={**data, "answers": {"wrong": "回答"}})
    assert invalid.status_code == 422
    api[2].responses = [response(plan_call(items=[step(status="pending")], goal=2)), response(text="只读检查计划。")]
    accepted = await api[1].post(f"/agent-runs/{run_id}/answer", json=data)
    assert accepted.status_code == 202, accepted.text
    repeated = await api[1].post(f"/agent-runs/{run_id}/answer", json=data)
    assert repeated.json() == accepted.json()
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed" and final["goal_version"] == 2, final
    assert not final.get("pending_input") and final["input_wait_seconds"] > 0
    assert owner.store.run_state(run_id)["completion_policy"]["writes_forbidden"]
    assert len([e for e in owner.store.events(run_id) if e["type"] == "input.resolved"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pause", "steer", "cancel"])
async def test_control_invalidates_waiting_question(api, kind):
    api[2].responses = [response(question())]
    run_id = await create(api, message="制定模块检查计划")
    waiting = await until(api[1], run_id, {"waiting_input"})
    data = control_data(waiting, input_id=waiting["pending_input"]["input_id"], answers={"scope": "当前模块"})
    await control(api, run_id, kind, **({"message": "改为检查目录结构"} if kind == "steer" else {}))
    await asyncio.sleep(0.05)
    current = (await api[1].get(f"/agent-runs/{run_id}")).json()
    assert not current.get("pending_input")
    assert (await api[1].post(f"/agent-runs/{run_id}/answer", json={**data, "expected_state_version": current["state_version"]})).status_code == 409
    assert run_id not in api[0].state.desktop.runtime.planning_interaction.pending


@pytest.mark.asyncio
async def test_failed_step_recovery_retains_history_and_does_not_forge_evidence(api):
    owner, run = idle_run(api, collaboration_mode="default", message="修改 sample.py")
    requirements = [item["requirement_id"] for item in run["completion_requirements"]]
    await owner.tool(run, api[3], plan_call(items=[step(requirement_ids=requirements)]))
    failed = step(status="failed", requirement_ids=requirements)
    await owner.tool(run, api[3], plan_call(1, [failed, step("repair", supersedes=["read"], requirement_ids=requirements)]))
    assert completion_blockers(run)[0] == "blocked"
    await owner.tool(run, api[3], plan_call(2, [failed, step("repair", status="completed", supersedes=["read"], requirement_ids=requirements)]))
    assert completion_blockers(run)[0] is None
    assert run["plan"]["items"][0]["status"] == "failed"
    assert not (await LocalCompletionVerifier(owner, run, api[3]).verify("已修复", attempt=1)).passed
    for bad in ([step(supersedes=["read"])], [failed, step("repair", supersedes=["read"])],
                [step(status="completed"), step("repair", supersedes=["read"], requirement_ids=requirements)]):
        with pytest.raises(ValueError):
            PlanUpdate.model_validate(plan_call(items=bad)["arguments"])


@pytest.mark.asyncio
async def test_restart_invalidates_pending_question_and_keeps_checkpoint(tmp_path):
    values = await setup(tmp_path)
    values[4].update(recovery_contract_version="1.0", collaboration_mode="plan")
    try:
        owner, run = idle_run(values)
        run.update(status="waiting_input", pending_input={"input_id": "interrupted-question", **question()["arguments"]})
        owner.event(run, "input.requested", pending_input=run["pending_input"])
        path, run_id = owner.store.path, run["id"]
    finally:
        await close(values[0], values[1])
    restarted = Store(path)
    try:
        saved = restarted.run(run_id)
        assert saved["status"] == "interrupted" and not saved.get("pending_input")
        runtime = Runtime(restarted, None, "fixture")
        checkpoint = runtime.recovery.load_checkpoint(saved)
        assert checkpoint["boundary"] == "input.invalidated"
        assert saved["collaboration_mode"] == "plan" and not saved["executions"]
    finally:
        restarted.db.close()


@pytest.mark.asyncio
async def test_answer_transaction_failure_does_not_resume_model(api, monkeypatch):
    api[2].responses = [response(question())]
    run_id = await create(api, message="制定模块检查计划")
    waiting = await until(api[1], run_id, {"waiting_input"})
    owner = api[0].state.desktop.runtime
    data = control_data(waiting, input_id=waiting["pending_input"]["input_id"], answers={"scope": "当前模块"})
    original = owner.event

    def fail_commit(run, event_type, **payload):
        if event_type == "input.resolved":
            raise OSError("注入回答提交故障")
        return original(run, event_type, **payload)

    monkeypatch.setattr(owner, "event", fail_commit)
    with pytest.raises(OSError):
        owner.planning_interaction.answer(run_id, data)
    assert owner.store.run_state(run_id)["pending_input"] == waiting["pending_input"]
    assert owner.live[run_id]["goal_version"] == 1
    assert not owner.planning_interaction.pending[run_id].done()
    assert not owner.recovery.controls(run_id)
    monkeypatch.setattr(owner, "event", original)
    result = owner.planning_interaction.answer(run_id, data)
    assert result["status"] == "applied"


@pytest.mark.asyncio
async def test_implement_confirmation_still_requires_write_approval(api):
    owner = api[0].state.desktop.runtime
    original = "规划后创建 new.txt"
    owner_run = owner.create({**api[4], "message": original}, launch=False)
    run = owner.store.run(owner_run["id"])
    ids = [item["requirement_id"] for item in run["completion_requirements"]]
    await owner.tool(run, api[3], plan_call(items=[step(status="pending", requirement_ids=ids)]))
    verifier = LocalCompletionVerifier(owner, run, api[3])
    assert (await verifier.verify("计划创建文件", attempt=1)).passed
    run["output"] = "计划创建文件"
    run["run_outcome"] = verifier.last_outcome.model_dump(mode="json")
    owner.finish(run, "completed")
    api[2].responses = [response(call("write_project_file", {"rel_path": "new.txt", "content": "new"}))]
    final = owner.store.run_state(run["id"])
    result = await api[1].post(f"/agent-runs/{run['id']}/implement-plan", json=control_data(final, expected_plan_version=1))
    assert result.status_code == 202, result.text
    child_id = result.json()["result_run_id"]
    await until(api[1], child_id, {"waiting_approval"})
    assert not (api[3] / "new.txt").exists()
    assert len((await api[1].get(f"/agent-runs/{child_id}/approvals")).json()) == 1


def test_recovery_chain_resolves_earlier_failures_without_rewriting_them():
    items = [step("first", "failed"), step("second", "failed", supersedes=["first"]),
             step("last", "completed", supersedes=["second"])]
    PlanUpdate.model_validate(plan_call(items=items)["arguments"])
    assert completion_blockers({"goal_version": 1, "plan": {"goal_version": 1, "items": items}}) == (None, [])
