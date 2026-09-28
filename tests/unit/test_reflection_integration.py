"""真实本机存储、工具和合成模型下的纠错与独立复核集成回归。"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from test_local_executor import call, close, response, setup, until

from private_agent_core.contracts import ToolCall
from private_agent_core.runtime import CancellationToken
from private_agent_core.verification import OutputVerification
from private_agent_local import reflection
from private_agent_local.completion import LocalCompletionVerifier
from private_agent_local.core_adapter import LocalRunAdapter
from private_agent_local.runtime import TERMINAL

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def api(tmp_path):
    values = await setup(tmp_path)
    values[4]["recovery_contract_version"] = "1.0"
    try:
        yield values
    finally:
        await close(values[0], values[1])


def failed_reads(count=2, path="missing.py"):
    return [response({**call("read_code_file", {"rel_path": path}), "id": f"missing-{index}"})
            for index in range(count)]


def write_file(content="value = 1\n"):
    return response(call("write_project_file", {"rel_path": "app.py", "content": content}))


def review_response(decision="pass"):
    findings = [] if decision == "pass" else [{
        "title": "候选交付与需求不一致", "detail": "候选说明保留了错误常量。",
        "correction": "将 app.py 的 value 改为 2 后重新核对。",
        "source_ids": ["candidate"], "requirement_ids": [],
    }]
    return response(text=json.dumps({"decision": decision, "findings": findings}, ensure_ascii=False))


def model_requests(api):
    return [json.loads(data) for path, data in api[2].calls if path == "/desktop/model/complete"]


async def run_responses(api, responses, *, message="创建 app.py", **overrides):
    api[2].responses = list(responses)
    created = await api[1].post("/agent-runs", json={**api[4], "message": message,
        "permission_mode": "workspace", **overrides})
    assert created.status_code == 201, created.text
    return await until(api[1], created.json()["id"], TERMINAL)


async def pending_failures(api, count=2, **overrides):
    owner = api[0].state.desktop.runtime
    created = owner.create({**api[4], "message": "创建 app.py", "permission_mode": "workspace", **overrides}, launch=False)
    run = owner.store.run(created["id"])
    adapter = LocalRunAdapter(owner, run, api[3])
    for index in range(count):
        tool = ToolCall(id=f"missing-{index}", name="read_code_file", arguments={"rel_path": "missing.py"})
        result = await adapter.execute(tool, cancellation=CancellationToken())
        assert not result.success
        await adapter.finalize_result(tool, result)
    return owner, run, adapter


@pytest.mark.parametrize("failures,write,modern", [
    (0, False, True), (0, True, True), (1, True, True), (2, False, True), (2, True, False),
])
async def test_review_does_not_add_requests_without_eligible_repeated_failure(api, monkeypatch, failures, write, modern):
    review = AsyncMock(side_effect=AssertionError("未满足条件时不应调用独立复核"))
    monkeypatch.setattr("private_agent_local.reflection_review.review_completion", review)
    responses = [*failed_reads(failures), *([write_file()] if write else []), response(text="已完成当前任务说明")]
    run = await run_responses(api, responses, message="创建 app.py" if write else "解释项目职责",
                              recovery_contract_version="1.0" if modern else None)
    assert run["status"] == "completed"
    assert run["goal_outcome"] == ("verified" if write else "answered")
    assert len(model_requests(api)) == len(responses)
    assert run["loop_budget"]["model_requests"] == len(responses)
    review.assert_not_awaited()
    stored = api[0].state.desktop.runtime.store.run(run["id"])
    if not modern:
        assert "reflection_state" not in stored


async def test_two_failed_tools_latch_review_after_successful_write(api, monkeypatch):
    reviewed = []

    async def review(owner, run, root, candidate, outcome):
        assert outcome.goal_outcome == "verified"
        assert reflection.requires_review(run)
        assert run["reflection_state"]["correctable_failures"] == 2
        assert (root / "app.py").read_text(encoding="utf-8") == "value = 1\n"
        assert any(item.status == "passed" and item.evidence_ids for item in outcome.verification_results)
        reviewed.append(candidate)
        return OutputVerification(passed=True, code="reflection_review_passed", message="复核通过", retryable=False)

    monkeypatch.setattr("private_agent_local.reflection_review.review_completion", review)
    run = await run_responses(api, [*failed_reads(), write_file(), response(text="已创建文件")])
    assert run["status"] == "completed" and run["goal_outcome"] == "verified"
    assert reviewed == ["已创建文件"]
    stored = api[0].state.desktop.runtime.store.run(run["id"])
    assert stored["loop_budget"]["failure_count"] == 0
    assert stored["reflection_state"]["review_required"]
    assert "reflection_state" not in run and "reflection_review" not in run
    failed = [item for item in stored["executions"] if item["status"] == "failed"]
    assert len(failed) == 2
    feedback = [json.loads(item["content"]).get("output", {}).get("correction")
                for item in model_requests(api)[2]["request"]["messages"] if item["role"] == "tool"]
    assert any(item and item["retry_policy"] == "change_required" for item in feedback)


async def test_real_reviewer_revises_then_passes_with_shared_usage_and_fresh_evidence(api):
    run = await run_responses(api, [
        *failed_reads(), write_file(), response(text="文件已创建，value 当前为 1。"), review_response("revise"),
        response(call("read_code_file", {"rel_path": "app.py"})), write_file("value = 2\n"),
        response(text="已将 value 改为 2 并核对落盘。"), review_response(),
    ])
    assert run["status"] == "completed" and run["goal_outcome"] == "verified"
    assert (api[3] / "app.py").read_text(encoding="utf-8") == "value = 2\n"
    owner = api[0].state.desktop.runtime
    stored = owner.store.run(run["id"])
    assert stored["reflection_review"]["attempts"] == 2
    assert stored["reflection_review"]["status"] == "passed"
    assert run["verification_retries"] == 1
    requests = model_requests(api)
    assert len(requests) == run["loop_budget"]["model_requests"] == 9
    assert run["input_tokens"] == 27 and run["output_tokens"] == 18
    assert run["loop_budget"]["known_tokens"] == 45
    reviews = [item for item in requests if item["request"]["tools"] == []]
    assert len(reviews) == 2
    assert {item["model_profile_id"] for item in requests} == {"test-profile"}
    assert all(len(item["request"]["messages"]) == 2 for item in reviews)
    assert any("value 改为 2" in item["content"]
               for item in requests[5]["request"]["messages"] if item["role"] == "user")
    events = owner.store.events(run["id"])
    types = [item["type"] for item in events]
    assert types.index("reflection.review_revise") < types.index("reflection.review_passed") < types.index("run.completed")
    assert types.count("run.completed") == 1


async def test_unavailable_review_never_delivers_verified(api, monkeypatch):
    review = AsyncMock(return_value=OutputVerification(passed=False, code="reflection_review_unavailable",
        message="独立质量复核未完成，结果尚未确认", retryable=False))
    monkeypatch.setattr("private_agent_local.reflection_review.review_completion", review)
    run = await run_responses(api, [*failed_reads(), write_file(), response(text="全部验证通过")])
    assert run["goal_outcome"] == "unknown"
    assert run["verification_state"] == "failed"
    assert "独立质量复核未完成" in "；".join(run["run_outcome"]["unverified_items"])
    assert run["status"] == "completed" and run["output"].startswith("任务结果：未确认")
    assert "全部验证通过" not in run["output"]
    assert len(model_requests(api)) == 4
    review.assert_awaited_once()


async def test_review_pass_cannot_reuse_machine_evidence_after_external_file_change(api, monkeypatch):
    owner, run, _ = await pending_failures(api)
    written = await owner.tool(run, api[3], call("write_project_file", {"rel_path": "app.py", "content": "value = 1\n"}))
    assert written["status"] == "applied"
    reviewed = []

    async def review(_owner, current, root, candidate, outcome):
        assert current["id"] == run["id"] and outcome.goal_outcome == "verified"
        assert any(item.status == "passed" and item.evidence_ids for item in outcome.verification_results)
        (root / "app.py").write_text("value = 999\n", encoding="utf-8")
        reviewed.append(candidate)
        return OutputVerification(passed=True, code="reflection_review_passed", message="复核通过", retryable=False)

    monkeypatch.setattr("private_agent_local.reflection_review.review_completion", review)
    verifier = LocalCompletionVerifier(owner, run, api[3])
    result = await verifier.verify("已创建 app.py，value 为 1", attempt=1)
    assert reviewed == ["已创建 app.py，value 为 1"]
    assert not result.passed and result.retryable
    assert verifier.last_outcome.goal_outcome == "unmet"
    assert any(item.status == "failed" for item in verifier.last_outcome.verification_results)
    assert owner.store.run(run["id"])["verification_state"] == "failed"


@pytest.mark.parametrize("blocker,expected", [("manual", "unknown"), ("plan", "blocked")])
async def test_review_cannot_override_manual_or_blocked_machine_outcome(api, monkeypatch, blocker, expected):
    review = AsyncMock(side_effect=AssertionError("机器检查未通过时不应调用独立复核"))
    monkeypatch.setattr("private_agent_local.reflection_review.review_completion", review)
    owner, run, _ = await pending_failures(api)
    written = await owner.tool(run, api[3], call("write_project_file", {"rel_path": "app.py", "content": "value = 1\n"}))
    assert written["status"] == "applied"
    if blocker == "manual":
        from private_agent_core.coding_contracts import Requirement
        from private_agent_core.task_intent import interpret_task
        from private_agent_local.task_constraints import store_interpretation

        store_interpretation(run, interpret_task("创建 app.py", [
            Requirement(requirement_id="manual", kind="manual", description="人工核对业务结果")]))
    else:
        run["plan"] = {"goal_version": 1, "needs_review": False,
                       "items": [{"item_key": "blocked", "status": "blocked", "title": "等待外部条件"}]}
    owner.store.save_run(run)
    verifier = LocalCompletionVerifier(owner, run, api[3])
    result = await verifier.verify("文件创建并已全部验收", attempt=1)
    assert reflection.requires_review(run)
    assert not result.passed and not result.retryable
    assert verifier.last_outcome.goal_outcome == expected
    review.assert_not_awaited()


async def test_linked_resume_preserves_correction_and_review_budget_without_aliasing(api):
    owner, run, adapter = await pending_failures(api)
    adapter.context.rounds = 7
    run["reflection_review"] = {"attempts": 1, "status": "revise"}
    run["status"] = "cancelled"
    owner.event(run, "run.cancelled")
    parent = owner.store.run(run["id"])
    child_view = owner.create({**api[4], "message": "继续", "permission_mode": "workspace"}, parent=parent, launch=False)
    child = owner.store.run(child_view["id"])
    assert child["reflection_state"] == parent["reflection_state"]
    assert child["reflection_review"] == parent["reflection_review"]
    assert child["loop_budget"]["model_requests"] == 7
    child_adapter = LocalRunAdapter(owner, child, api[3])
    assert child_adapter.context.rounds == 7 and child_adapter.context.failure_count == 2
    owner.recovery.load_checkpoint(child)
    assert "reflection_state" not in child_view and "reflection_review" not in child_view
    child["reflection_state"]["entries"][0]["status"] = "resolved"
    child["reflection_review"]["attempts"] = 2
    assert parent["reflection_state"]["entries"][0]["status"] == "open"
    assert parent["reflection_review"]["attempts"] == 1


@pytest.mark.parametrize("field", ["reflection_state", "reflection_review"])
async def test_checkpoint_rejects_tampered_correction_or_review_attempts(api, field):
    owner, run, _ = await pending_failures(api)
    run["reflection_review"] = {"attempts": 1, "status": "revise"}
    owner.event(run, "reflection.review_revise")
    owner.recovery.load_checkpoint(run)
    if field == "reflection_state":
        run[field]["review_required"] = False
    else:
        run[field]["attempts"] = 0
    owner.store.save_run(run)
    with pytest.raises(ValueError, match="检查点不一致"):
        owner.recovery.load_checkpoint(owner.store.run(run["id"]))


async def test_correction_state_and_checkpoint_rollback_if_event_commit_fails(api, monkeypatch):
    owner, run, adapter = await pending_failures(api, count=1)
    tool = ToolCall(id="failed-second", name="read_code_file", arguments={"rel_path": "missing.py"})
    result = await adapter.execute(tool, cancellation=CancellationToken())
    before = deepcopy(owner.store.run(run["id"]))
    checkpoints = owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints").fetchone()[0]
    original = owner.store.emit

    def fail(current, kind, payload, **kwargs):
        value = original(current, kind, payload, **kwargs)
        if kind == "reflection.observed":
            raise OSError("注入纠错事件提交失败")
        return value

    with monkeypatch.context() as patch:
        patch.setattr(owner.store, "emit", fail)
        with pytest.raises(OSError, match="纠错事件提交失败"):
            await adapter.finalize_result(tool, result)
    assert owner.store.run(run["id"]) == before
    assert run["reflection_state"] == before["reflection_state"]
    assert owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints").fetchone()[0] == checkpoints
    owner.recovery.load_checkpoint(owner.store.run(run["id"]))


async def test_observer_classifies_reflection_events_without_exposing_free_text(api):
    owner, run, adapter = await pending_failures(api)
    adapter.context.failure_count = 0
    adapter.context.failure_key = None
    owner.event(run, "reflection.review_revise", findings=[{
        "title": "private-finding-sentinel", "detail": "private-review-detail",
        "correction": "private-correction-sentinel", "source_ids": ["private-source-sentinel"],
    }], binding="private-binding-sentinel")
    report = await api[1].get(f"/agent-runs/{run['id']}/observer")
    assert report.status_code == 200, report.text
    assert report.json()["progress"]["failure_repeats"] == 2
    events = [item for item in report.json()["events"] if item["type"].startswith("reflection.")]
    assert {item["type"] for item in events} == {"reflection.observed", "reflection.review_revise"}
    assert {item["category"] for item in events} == {"verification"}
    assert all(set(item) == {"sequence", "type", "step_id", "execution_id", "category"} for item in events)
    assert "private-" not in report.text
    assert "correction" not in report.text and "reflection_state" not in report.text
    assert "missing.py" not in report.text


async def test_steer_checkpoint_immediately_resets_old_failures_without_waiting_for_next_request(api):
    owner, run, adapter = await pending_failures(api)
    adapter.context.rounds = 7
    run["reflection_review"] = {"attempts": 1, "status": "revise"}
    owner.event(run, "reflection.review_revise")
    owner.live[run["id"]] = run
    try:
        await owner.controls.request(run["id"], "steer", {"request_id": "new-boundary-goal",
            "expected_state_version": run["state_version"], "message": "停止修改文件，只解释当前信息"})
        await owner.controls.boundary(run)
        stored = owner.store.run(run["id"])
        assert stored["goal_version"] == 2
        assert stored["reflection_state"]["entries"] == []
        assert not stored["reflection_state"]["review_required"]
        assert stored["reflection_review"]["attempts"] == 1
        assert stored["loop_budget"]["model_requests"] == 7
        assert stored["loop_budget"]["failure_count"] == 0
        assert stored["loop_budget"]["failure_key"] is None
        assert adapter.context.failure_count == 0 and adapter.context.failure_key is None
        checkpoint = owner.recovery.load_checkpoint(stored)
        assert checkpoint["budget"]["failure_count"] == 0
    finally:
        owner.live.pop(run["id"], None)


async def test_steer_during_evidence_check_cannot_record_old_failure_in_new_goal(api, monkeypatch):
    owner, run, _ = await pending_failures(api)
    verifier = LocalCompletionVerifier(owner, run, api[3])
    original = verifier.load_outcome
    owner.live[run["id"]] = run

    async def steer_after_evidence(candidate):
        outcome = await original(candidate)
        assert outcome.goal_outcome == "unmet"
        await owner.controls.request(run["id"], "steer", {"request_id": "during-evidence",
            "expected_state_version": run["state_version"], "message": "停止修改文件，只解释当前信息"})
        await owner.controls.boundary(run)
        return outcome

    monkeypatch.setattr(verifier, "load_outcome", steer_after_evidence)
    review = AsyncMock(side_effect=AssertionError("旧目标的完成证据不能触发新目标复核"))
    monkeypatch.setattr("private_agent_local.reflection_review.review_completion", review)
    try:
        result = await verifier.verify("已创建 app.py", attempt=1)
        assert not result.passed and result.code == "steering_superseded"
        stored = owner.store.run(run["id"])
        assert stored["goal_version"] == 2
        assert stored["reflection_state"]["entries"] == []
        assert stored["reflection_state"]["correctable_failures"] == 0
        review.assert_not_awaited()
    finally:
        owner.live.pop(run["id"], None)


async def ask_plan_question(owner, run):
    task = asyncio.create_task(owner.planning_interaction.ask(run, {"questions": [{
        "id": "scope", "question": "希望检查哪些内容？", "options": [
            {"label": "当前模块", "description": "只检查当前模块"},
            {"label": "整个项目", "description": "检查整个项目"},
        ],
    }]}))
    for _ in range(100):
        if run.get("pending_input"):
            return task
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    pytest.fail("未进入规划澄清等待状态")


async def test_planning_answer_clears_failures_and_checkpoint_but_preserves_review_budget(api):
    owner, run, adapter = await pending_failures(api, collaboration_mode="plan")
    adapter.context.rounds = 7
    run["reflection_review"] = {"attempts": 1, "status": "revise"}
    owner.event(run, "reflection.review_revise")
    owner.live[run["id"]] = run
    question = await ask_plan_question(owner, run)
    try:
        answered = owner.planning_interaction.answer(run["id"], {"request_id": "answer-new-goal",
            "expected_state_version": run["state_version"], "input_id": run["pending_input"]["input_id"],
            "answers": {"scope": "只检查当前模块，不修改文件"}})
        assert answered["status"] == "applied"
        stored = owner.store.run(run["id"])
        assert stored["goal_version"] == 2
        assert stored["reflection_state"]["entries"] == []
        assert not stored["reflection_state"]["review_required"]
        assert stored["reflection_review"]["attempts"] == 1
        assert stored["loop_budget"]["model_requests"] == 7
        assert stored["loop_budget"]["failure_count"] == 0
        assert adapter.context.failure_count == 0
        assert owner.recovery.load_checkpoint(stored)["budget"]["failure_count"] == 0
        assert (await question)["goal_version"] == 2
    finally:
        question.cancel()
        await asyncio.gather(question, return_exceptions=True)
        owner.live.pop(run["id"], None)


@pytest.mark.parametrize("kind", ["steer", "answer"])
async def test_new_goal_event_failure_rolls_back_live_and_persisted_correction_budget(api, monkeypatch, kind):
    owner, run, adapter = await pending_failures(api, collaboration_mode="plan" if kind == "answer" else "default")
    adapter.context.rounds = 7
    run["reflection_review"] = {"attempts": 1, "status": "revise"}
    owner.event(run, "reflection.review_revise")
    owner.live[run["id"]] = run
    question = await ask_plan_question(owner, run) if kind == "answer" else None
    data = {"request_id": "failed-new-goal", "expected_state_version": run["state_version"]}
    if kind == "steer":
        await owner.controls.request(run["id"], "steer", {**data, "message": "停止写入，只解释"})
    else:
        data.update(input_id=run["pending_input"]["input_id"], answers={"scope": "停止写入，只解释"})
    before = deepcopy(owner.store.run(run["id"]))
    live_before = deepcopy(run)
    failure_before = adapter.context.failure_key
    count = owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints").fetchone()[0]
    messages = (await api[1].get(f"/sessions/{run['session_id']}/messages")).json()
    original = owner.event

    def fail(current, event_type, **payload):
        result = original(current, event_type, **payload)
        if event_type == ("steer.applied" if kind == "steer" else "input.resolved"):
            raise OSError("注入新目标事件提交故障")
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner, "event", fail)
            with pytest.raises(OSError, match="新目标事件提交故障"):
                if kind == "steer":
                    await owner.controls.boundary(run)
                else:
                    owner.planning_interaction.answer(run["id"], data)
        assert owner.store.run(run["id"]) == before
        assert run == live_before
        assert adapter.context.failure_count == 2 and adapter.context.failure_key == failure_before
        assert adapter.context.rounds == 7
        assert owner.store.db.execute("SELECT COUNT(*) FROM run_checkpoints").fetchone()[0] == count
        assert (await api[1].get(f"/sessions/{run['session_id']}/messages")).json() == messages
        if kind == "answer":
            assert not owner.planning_interaction.pending[run["id"]].done()
            assert not owner.recovery.controls(run["id"])
        else:
            assert owner.recovery.controls(run["id"])[0]["status"] == "received"
        owner.recovery.load_checkpoint(owner.store.run(run["id"]))
    finally:
        if question:
            question.cancel()
            await asyncio.gather(question, return_exceptions=True)
        owner.live.pop(run["id"], None)


async def test_steer_resets_previous_goal_failures_but_preserves_spent_review_budget(api):
    api[2].responses = [*failed_reads(), write_file(), response(text="文件 value 为 1。"), review_response("revise"),
                        *failed_reads(path="other-missing.py")]
    created = await api[1].post("/agent-runs", json={**api[4], "message": "创建 app.py", "permission_mode": "workspace"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    owner = api[0].state.desktop.runtime
    for _ in range(300):
        stored = owner.store.run(run_id)
        if stored.get("reflection_state", {}).get("correctable_failures") == 4 and stored["loop_budget"]["model_requests"] == 8:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("未到达复核纠正后的第二组失败边界")
    assert stored["reflection_review"]["attempts"] == 1
    assert owner.contexts[run_id].failure_count == 2
    report = (await api[1].get(f"/agent-runs/{run_id}/recovery")).json()
    result = await api[1].post(f"/agent-runs/{run_id}/steer", json={"request_id": "new-goal",
        "expected_state_version": report["state_version"], "message": "停止修改文件，接下来只解释已经获得的信息"})
    assert result.status_code == 202, result.text
    for _ in range(300):
        stored = owner.store.run(run_id)
        if stored.get("goal_version") == 2 and stored["loop_budget"]["model_requests"] == 9:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("追加约束未进入新模型请求")
    assert stored["reflection_state"]["entries"] == []
    assert stored["reflection_state"]["correctable_failures"] == 0
    assert not stored["reflection_state"]["review_required"]
    assert stored["reflection_review"]["attempts"] == 1
    assert stored["loop_budget"]["failure_count"] == 0
    assert owner.contexts[run_id].failure_count == 0
    assert stored["verification_retries"] == 1
    await owner.cancel(run_id)
