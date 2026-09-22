"""本地编排使用真实存储与受控模型验证，计划勾选不能代替验收。"""
import asyncio
import json

import pytest
from test_local_executor import call, close, response, setup, until
from test_local_recovery import control, create

from private_agent_core.contracts import ModelMessage, ModelRequest
from private_agent_core.planning import PlanUpdate
from private_agent_local.completion import LocalCompletionVerifier
from private_agent_local.context_manager import LocalContext
from private_agent_local.planning import completion_blockers
from private_agent_local.runtime import TERMINAL, Runtime
from private_agent_local.store import Store


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    values[4].update(recovery_contract_version="1.0", permission_mode="readonly")
    try:
        yield values
    finally:
        await close(values[0], values[1])


def step(key="read", status="in_progress", **changes):
    return {"item_key": key, "title": key, "status": status, "detail": "",
            "requirement_ids": [], "evidence_calls": [], **changes}


def plan_call(version=0, items=None, *, goal=1, explanation="先检查现有实现"):
    return {**call("update_run_plan", {"expected_plan_version": version, "goal_version": goal,
                                     "items": items if items is not None else [step()], "explanation": explanation}),
            "id": f"plan-{goal}-{version}"}


def idle_run(api, **changes):
    owner = api[0].state.desktop.runtime
    run = owner.create({**api[4], **changes}, launch=False)
    return owner, owner.store.run(run["id"])


def model_requests(api):
    return [json.loads(content)["request"] for path, content in api[2].calls if path == "/desktop/model/complete"]


@pytest.mark.parametrize("items", [[], [step(), step()], [step(), step("test")], [step(status="invented")],
    [step(title=" ")], [step(evidence_calls=["same", "same"])], [step(requirement_ids=[""])],
    [step(str(i), "pending") for i in range(33)],
    [step(str(i), "pending", detail="字" * 1000) for i in range(6)]])
def test_plan_rejects_invalid_or_unbounded_state(items):
    with pytest.raises(ValueError):
        PlanUpdate.model_validate(plan_call(items=items)["arguments"])


@pytest.mark.asyncio
async def test_model_plan_read_update_and_snapshot_replay(api):
    (api[3] / "sample.py").write_text("value = 1\n", encoding="utf-8")
    api[2].responses = [response(plan_call()), response(call("read_code_file", {"rel_path": "sample.py"})),
                        response(plan_call(1, [step(status="completed", evidence_calls=["call-read_code_file"])])),
                        response(text="sample.py 中 value 的值为 1。")]
    run_id = await create(api, message="读取 sample.py 并解释")
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed", final
    assert final["plan"]["version"] == 2 and final["plan"]["items"][0]["status"] == "completed"
    evidence, = final["plan"]["items"][0]["evidence"]
    owner = api[0].state.desktop.runtime
    run = owner.store.run(run_id)
    source = next(event for event in run["events"] if event["sequence"] == evidence["sequence"])
    assert source["type"] == "tool.completed" and source["payload"]["execution_id"] == evidence["execution_id"]
    plans = [event["payload"] for event in run["events"] if event["type"] in {"plan.created", "plan.updated"}]
    assert plans[-1]["items"] == final["plan"]["items"]
    assert owner.recovery.load_checkpoint(run)["goal_version"] == 1
    context = owner.planner.context(run)
    assert context["decisions"][0]["content_ref"]
    assert "当前运行计划" in json.dumps(model_requests(api)[-1], ensure_ascii=False)


@pytest.mark.asyncio
async def test_conflicts_bad_references_and_illegal_transitions_preserve_plan(api):
    owner, run = idle_run(api)
    assert "plan" in await owner.tool(run, api[3], plan_call())
    before = json.loads(json.dumps(run["plan"]))
    for invalid, code in [
        (plan_call(0), "plan_version_conflict"),
        (plan_call(1, goal=2), "plan_goal_conflict"),
        (plan_call(1, [step("other")]), "plan_transition_invalid"),
        (plan_call(1, [step(evidence_calls=["invented"])]), "plan_evidence_invalid"),
        (plan_call(1, [step(requirement_ids=["invented"])]), "plan_requirement_invalid"),
    ]:
        result = await owner.tool(run, api[3], invalid)
        assert result["error_code"] == code
        assert run["plan"] == before == owner.store.run_state(run["id"])["plan"]
    await owner.tool(run, api[3], plan_call(1, [step(status="completed")]))
    assert (await owner.tool(run, api[3], plan_call(2)))["error_code"] == "plan_transition_invalid"
    assert (await owner.tool(run, api[3], plan_call(2, [step(status="completed", title="改写历史")])))["error_code"] == "plan_transition_invalid"


@pytest.mark.asyncio
async def test_plan_and_terminal_event_roll_back_together(api, monkeypatch):
    owner, run = idle_run(api)
    original = owner.complete_tool

    def fail_once(run, call, execution, *, failed):
        if not failed:
            raise OSError("注入工具完成事件写入失败")
        return original(run, call, execution, failed=failed)

    monkeypatch.setattr(owner, "complete_tool", fail_once)
    result = await owner.tool(run, api[3], plan_call())
    assert "error" in result
    assert run["plan"] is None and owner.store.run_state(run["id"])["plan"] is None
    assert not any(event["type"].startswith("plan.") for event in owner.store.events(run["id"]))
    owner.recovery.load_checkpoint(owner.store.run(run["id"]))


@pytest.mark.asyncio
async def test_plan_ticks_do_not_satisfy_missing_file_evidence(api):
    owner, run = idle_run(api, message="修改 sample.py")
    await owner.tool(run, api[3], plan_call())
    await owner.tool(run, api[3], plan_call(1, [step(status="completed")]))
    verifier = LocalCompletionVerifier(owner, run, api[3])
    result = await verifier.verify("已经修改完成", attempt=1)
    assert not result.passed
    assert verifier.last_outcome.goal_outcome != "verified"
    assert all(item.status != "passed" for item in verifier.last_outcome.verification_results)


@pytest.mark.asyncio
async def test_unfinished_plan_returns_feedback_before_final_answer(api):
    api[2].responses = [response(plan_call()), response(text="尝试直接交付"),
                        response(plan_call(1, [step(status="completed")])), response(text="检查说明已完成")]
    run_id = await create(api)
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed" and final["verification_retries"] == 1
    assert "计划仍有未完成步骤" in json.dumps(model_requests(api)[2], ensure_ascii=False)


@pytest.mark.asyncio
async def test_steering_invalidates_plan_and_old_model_cannot_update_it(api):
    api[2].responses = [response(plan_call())]
    run_id = await create(api)
    owner = api[0].state.desktop.runtime
    for _ in range(200):
        if (owner.store.run_state(run_id).get("loop_budget") or {}).get("model_requests", 0) >= 2:
            break
        await asyncio.sleep(0.01)
    await control(api, run_id, "pause")
    await until(api[1], run_id, {"paused"})
    await control(api, run_id, "steer", message="只解释，不要修改文件")
    api[2].responses = [response(plan_call(2, [step(status="completed")], goal=2)), response(text="只提供解释")]
    await control(api, run_id, "resume")
    final = await until(api[1], run_id, TERMINAL)
    assert final["goal_version"] == 2 and final["plan"]["version"] == 3
    assert not final["plan"]["needs_review"]
    updates = [event["payload"] for event in owner.store.events(run_id) if event["type"] == "plan.updated"]
    assert updates[0]["needs_review"] and updates[0]["plan_version"] == 2
    assert final["status"] == "completed", final


@pytest.mark.asyncio
async def test_resume_preserves_plan_and_rejects_tampering(api):
    owner, run = idle_run(api)
    (api[3] / "sample.py").write_text("value = 1\n", encoding="utf-8")
    await owner.tool(run, api[3], call("read_code_file", {"rel_path": "sample.py"}))
    evidence = ["call-read_code_file"]
    await owner.tool(run, api[3], plan_call(items=[step(evidence_calls=evidence)]))
    before = owner.store.run(run["id"])
    run["plan"] = {**run["plan"], "version": 900}
    with pytest.raises(ValueError, match="计划或进度"):
        owner.recovery.load_checkpoint(run)
    owner.finish(before, "cancelled", "cancelled", "用户取消")
    api[2].responses = [response(plan_call(1, [step(status="completed", evidence_calls=evidence)])), response(text="已继续原计划")]
    _, resumed = await control(api, run["id"], "resume")
    final = await until(api[1], resumed["result_run_id"], TERMINAL)
    assert final["plan"]["version"] == 2 and final["logical_task_id"] == run["id"]
    assert final["plan"]["items"][0]["evidence"][0]["run_id"] == run["id"]
    assert owner.store.run_state(run["id"])["plan"]["version"] == 1


@pytest.mark.asyncio
async def test_plan_cannot_reference_a_different_logical_task(api):
    owner, first = idle_run(api)
    (api[3] / "sample.py").write_text("value = 1\n", encoding="utf-8")
    await owner.tool(first, api[3], call("read_code_file", {"rel_path": "sample.py"}))
    owner.finish(first, "completed", None, None)
    _, second = idle_run(api)
    result = await owner.tool(second, api[3], plan_call(items=[step(evidence_calls=["call-read_code_file"])]))
    assert result["error_code"] == "plan_evidence_invalid" and second["plan"] is None


@pytest.mark.asyncio
async def test_compaction_keeps_goal_plan_pending_items_and_source_refs(api):
    api[2].responses = [response(plan_call(items=[step(), step("verify", "pending")])),
                        response(plan_call(1, [step(status="completed"), step("verify", "in_progress")], explanation="已有证据支持继续验证")),
                        response(plan_call(2, [step(status="completed"), step("verify", "completed")], explanation="完成检查，保留结果来源")),
                        response(text="结果说明")]
    run_id = await create(api)
    await until(api[1], run_id, TERMINAL)
    owner = api[0].state.desktop.runtime
    checkpoint = owner.store.context.begin(api[4]["session_id"], "plan-compact")
    compacted = owner.compact_idle(api[4]["session_id"], checkpoint)
    assert compacted["state"] == "completed", compacted
    state = compacted["summary"]["task_state_at_compaction"]
    assert state["plan"]["version"] == 3 and len(state["plan"]["items"]) == 2
    assert all(item["content_ref"] for item in state["decisions"])
    assert owner.store.context.messages(api[4]["session_id"])[0].content == api[4]["message"]


@pytest.mark.asyncio
async def test_old_protocol_and_simple_tasks_do_not_require_plan(api):
    api[2].responses = [response(text="简短回答")]
    run_id = await create(api, recovery_contract_version=None)
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed" and final["plan"] is None
    assert "update_run_plan" not in [tool["name"] for tool in model_requests(api)[0]["tools"]]


@pytest.mark.parametrize("status,expected", [("pending", "unmet"), ("in_progress", "unmet"),
    ("blocked", "blocked"), ("failed", "blocked"), ("completed", None), ("cancelled", None)])
def test_plan_status_is_not_verification(status, expected):
    run = {"goal_version": 1, "plan": {"goal_version": 1, "items": [step(status=status)]}}
    assert completion_blockers(run)[0] == expected
    run["goal_version"] = 2
    assert completion_blockers(run)[0] == "unmet"


@pytest.mark.asyncio
async def test_restart_retains_plan_checkpoint(tmp_path):
    values = await setup(tmp_path)
    values[4].update(recovery_contract_version="1.0", permission_mode="readonly")
    try:
        owner, run = idle_run(values)
        await owner.tool(run, values[3], plan_call())
        path, run_id = owner.store.path, run["id"]
    finally:
        await close(values[0], values[1])
    restarted = Store(path)
    try:
        saved = restarted.run(run_id)
        runtime = Runtime(restarted, None, "fixture")
        assert saved["plan"]["version"] == 1
        assert runtime.recovery.load_checkpoint(saved)["orchestration_digest"]
    finally:
        restarted.db.close()


@pytest.mark.asyncio
async def test_long_task_compacts_twice_then_writes_and_finishes_plan(api):
    owner = api[0].state.desktop.runtime
    api[2].profiles[0]["context_tokens"] = 48000
    for index in range(24):
        (api[3] / f"input-{index}.txt").write_text(f"input {index}\n" + "x" * 3000, encoding="utf-8")
    api[2].responses = [response(plan_call(items=[step(), step("write", "pending"), step("check", "pending")]))]
    api[2].responses += [response({**call("read_code_file", {"rel_path": f"input-{i}.txt"}), "id": f"read-{i}"}) for i in range(24)]
    api[2].responses += [
        response(plan_call(1, [step(status="completed"), step("write"), step("check", "pending")], explanation="读取完成，创建约定文件")),
        response(call("write_project_file", {"rel_path": "done.txt", "content": "verified data"})),
        response(plan_call(2, [step(status="completed"), step("write", "completed"), step("check")], explanation="写入完成，回读核对")),
        response(call("read_code_file", {"rel_path": "done.txt"})),
        response(plan_call(3, [step(status="completed"), step("write", "completed"), step("check", "completed")], explanation="已回读并保留验证来源")),
        response(text="文件创建并回读完成"),
    ]
    for result in api[2].responses:
        result["usage"] = {"input_tokens": 0, "output_tokens": 2}
    run_id = await create(api, message="检查项目后创建 done.txt；禁止联网", permission_mode="workspace")
    await asyncio.wait_for(owner.tasks[run_id], 30)
    run = owner.store.run(run_id)
    assert run["status"] == "completed", (run["error_code"], run["error_message"])
    assert (api[3] / "done.txt").read_text() == "verified data"
    assert all(item["status"] == "completed" for item in run["plan"]["items"])
    assert sum(event["type"] == "context.compaction_completed" for event in run["events"]) >= 2
    last_request = json.dumps(model_requests(api)[-1], ensure_ascii=False)
    assert "禁止联网" in last_request and "当前运行计划" in last_request
    checkpoint = owner.store.context.checkpoint(api[4]["session_id"])
    assert checkpoint["summary"]["task_state_at_compaction"]["plan"]["items"]


@pytest.mark.asyncio
async def test_late_model_plan_after_steering_is_discarded(api, monkeypatch):
    owner = api[0].state.desktop.runtime
    entered = asyncio.Event()
    calls = 0

    async def complete(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return response(plan_call())
        if calls == 2:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return response(plan_call(1, [step(status="completed")], explanation="过期响应不得落盘"))
        if calls == 3:
            return response(plan_call(2, [step(status="cancelled"), step("explain")], goal=2))
        if calls == 4:
            return response(plan_call(3, [step(status="cancelled"), step("explain", "completed")], goal=2))
        return response(text="已按新要求解释")

    monkeypatch.setattr(owner.cloud, "complete", complete)
    run_id = await create(api)
    await asyncio.wait_for(entered.wait(), 5)
    await control(api, run_id, "steer", message="只解释，不写文件")
    final = await until(api[1], run_id, TERMINAL)
    assert final["status"] == "completed" and final["plan"]["version"] == 4
    assert "过期响应不得落盘" not in json.dumps(owner.store.run(run_id), ensure_ascii=False)
    assert any(event["type"] == "model.response_discarded" for event in owner.store.events(run_id))


@pytest.mark.asyncio
async def test_compaction_steering_race_preserves_history_and_uses_new_plan(api, monkeypatch):
    from test_local_compaction import seed

    owner, run = idle_run(api)
    await owner.tool(run, api[3], plan_call())
    history = owner.store.context
    seed(owner.store, run["session_id"])
    original_items = history.items(run["session_id"])
    context = LocalContext(owner, run, api[3])
    original_event = owner.event
    controls = []
    owner.live[run["id"]] = run

    def event(current, event_type, **payload):
        result = original_event(current, event_type, **payload)
        if event_type == "context.compaction_started" and not controls:
            controls.append(asyncio.create_task(owner.controls.request(run["id"], "steer", {
                "request_id": "during-compaction", "expected_state_version": run["state_version"],
                "message": "追加限制：不运行任何命令，只解释",
            })))
        return result

    monkeypatch.setattr(owner, "event", event)
    request = ModelRequest(messages=(ModelMessage(role="system", content="测试编排边界"),))
    try:
        with pytest.raises(asyncio.CancelledError):
            await context.prepare(request)
        await asyncio.gather(*controls)
        assert history.items(run["session_id"]) == original_items
        assert not any(item["type"] == "context.compaction_completed" for item in run["events"])
        await owner.controls.boundary(run, model=True)
        prepared = await context.prepare(request)
        checkpoint = history.checkpoint(run["session_id"])
        state = checkpoint["summary"]["task_state_at_compaction"]
        assert state["goal_version"] == 2 and state["plan"]["needs_review"]
        assert "不运行任何命令" in prepared.model_dump_json()
        assert run["plan"]["version"] == 2
    finally:
        owner.live.pop(run["id"], None)
