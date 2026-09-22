"""独立复核使用合成响应和临时工作区，验证预算、引用及控制边界。"""
import asyncio
import copy
import json
import sqlite3
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from private_agent_core.coding_contracts import (
    Requirement,
    RunOutcome,
    VerificationResult,
)
from private_agent_core.context import ContextLimits, configuration_version
from private_agent_local.context_manager import LocalContext
from private_agent_local.model_errors import CloudError
from private_agent_local.recovery import model_capability_version
from private_agent_local.reflection_review import (
    review_completion,
    review_request,
    validate_review,
)


def decision(*, revise=False, **finding):
    return {"decision": "revise" if revise else "pass", "findings": [{
        "title": "边界遗漏", "detail": "候选说明未处理已要求的空输入。", "correction": "核对空输入并补齐处理。",
        "source_ids": ["candidate"], "requirement_ids": ["change"], **finding}] if revise else []}


class Model:
    def __init__(self, profile):
        self.profile = profile
        self.calls = []
        self.entered = asyncio.Event()
        self.profile_entered = asyncio.Event()
        self.release = None
        self.profile_release = None
        self.on_response = None
        self.failure = None
        self.response = {"text": json.dumps(decision()), "tool_calls": [], "model_profile_id": "model",
                         "usage": {"input_tokens": 100, "output_tokens": 20, "cached_tokens": 30, "cost_usd": 0.01}}

    async def complete(self, token, profile, request):
        self.calls.append(request)
        self.entered.set()
        if self.release:
            await self.release.wait()
        if self.failure:
            raise self.failure
        if self.on_response:
            self.on_response()
        return self.response

    async def profiles(self, token):
        self.profile_entered.set()
        if self.profile_release:
            await self.profile_release.wait()
        return [self.profile]


@pytest.fixture
def review(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text("result = 1\n", encoding="utf-8")
    profile = {"id": "model", "provider": "test", "model_name": "model", "context_tokens": 100000,
               "enabled": True, "supports_structured_output": True}
    run = {"id": "run", "session_id": 1, "logical_task_id": "logical", "goal": "修改 app.py",
           "goal_version": 1, "generation": 0, "workspace_version": 1, "model_profile_id": "model",
           "tool_call_count": 3, "completion_policy": {}, "input_tokens": 5, "output_tokens": 2,
           "cached_tokens": 0, "model_config_version": configuration_version(profile),
           "model_capability_version": model_capability_version(profile)}
    history = [{"item_id": "source-1", "role": "tool", "message": {"content": "app.py 修改已核对。"}}]
    saved, events = [], []
    @contextmanager
    def transaction(*, run):
        before = dict(run)
        try:
            yield
        except BaseException:
            run.clear()
            run.update(before)
            raise

    store = SimpleNamespace(context=SimpleNamespace(items=lambda session: history),
                            save_run=lambda value: saved.append(copy.deepcopy(value)), transaction=transaction)

    async def boundary(value):
        if value.get("cancel_requested_at"):
            raise asyncio.CancelledError

    def event(value, kind, **facts):
        events.append({"type": kind, "payload": facts})
        store.save_run(value)

    owner = SimpleNamespace(store=store, cloud=Model(profile), token="fixture", _profiles=[profile],
        memories=SimpleNamespace(secrets=lambda: ["fixture-sensitive-string"]), contexts={}, event=event,
        controls=SimpleNamespace(boundary=boundary, model_tasks={}))
    context = LocalContext(owner, run, root)
    owner.contexts[run["id"]] = context
    outcome = RunOutcome(run_id="run", goal_outcome="verified",
        requirements=[Requirement(requirement_id="change", description="修改 app.py", kind="file_changed", scope="app.py")],
        verification_results=[VerificationResult(requirement_id="change", status="passed", evidence_ids=["evidence-1"])],
        evidence_ids=["evidence-1"])
    return SimpleNamespace(owner=owner, run=run, root=root, context=context, outcome=outcome,
                           history=history, profile=profile, events=events, saved=saved)


async def check(fixture):
    return await review_completion(fixture.owner, fixture.run, fixture.root, "修改已完成并核对。", fixture.outcome)


@pytest.mark.parametrize("payload", [
    {"decision": "pass", "findings": decision(revise=True)["findings"]},
    {"decision": "revise", "findings": []},
    decision(revise=True, source_ids=["invented"]),
    decision(revise=True, requirement_ids=["invented"]),
    decision(revise=True, detail="fixture-sensitive-string"),
    decision(revise=True, correction="password=fixture-value"),
    decision(revise=True, title="\x00invalid"),
    {**decision(), "execute": "anything"},
    decision(revise=True, source_ids=[]),
])
def test_review_rejects_invalid_decisions_references_and_secrets(payload):
    with pytest.raises(ValueError):
        validate_review(json.dumps(payload), {"candidate"}, {"change"}, secrets=["fixture-sensitive-string"])


def test_review_output_and_required_input_are_bounded(review):
    with pytest.raises(ValueError):
        validate_review(" " * 16001, set(), set())
    with pytest.raises(ValueError):
        review_request(review.run, "x" * 24001, review.outcome, [], review.profile)
    with pytest.raises(ValueError):
        review_request(review.run, "完成", review.outcome, [], {**review.profile, "context_tokens": 100})


def test_review_request_filters_sources_and_keeps_exact_reference_sets(review):
    review.history.extend({"item_id": f"source-{index}", "role": "assistant", "message": {"content": "finding " * 200}}
                          for index in range(2, 20))
    review.history.append({"item_id": "secret", "role": "tool", "message": {"content": "fixture-sensitive-string"}})
    request, source_ids, requirement_ids = review_request(review.run, "候选", review.outcome, review.history,
        review.profile, secrets=["fixture-sensitive-string"])
    payload = json.loads(request.messages[1].content)
    assert len(payload["sources"]) == 12 and "secret" not in source_ids
    assert all(len(item["excerpt"]) < 1050 for item in payload["sources"])
    assert source_ids == {"candidate", *(item["id"] for item in payload["sources"])}
    assert requirement_ids == {"change"} and request.tools == ()
    assert request.output_format is not None
    request, _, _ = review_request(review.run, "候选", review.outcome, [], {**review.profile, "supports_structured_output": False})
    assert request.output_format is None


@pytest.mark.asyncio
async def test_pass_is_independent_and_accounts_without_changing_main_candidate_or_outcome(review):
    review.run["pending_response"] = {"text": "主回复"}
    before = review.outcome.model_dump()
    old_state = {"attempts": 0}
    cache_usage = {"input_tokens": 0, "cached_tokens": 0}
    review.run["cache_usage"] = cache_usage
    review.run["reflection_review"] = old_state
    result = await check(review)
    assert result.passed and result.code == "reflection_review_passed"
    assert review.run["pending_response"] == {"text": "主回复"} and review.outcome.model_dump() == before
    assert old_state == {"attempts": 0} and review.run["reflection_review"]["attempts"] == 1
    assert review.context.rounds == 1 and review.context.tokens == 120 and review.context.cost == 0.01
    assert (review.run["input_tokens"], review.run["output_tokens"], review.run["cached_tokens"]) == (105, 22, 30)
    assert review.run["cache_usage"] == {"input_tokens": 100, "cached_tokens": 30}
    assert cache_usage == {"input_tokens": 0, "cached_tokens": 0}
    assert "context_usage" not in review.run and review.context.prepared_request is None
    assert review.owner.cloud.calls[0]["tools"] == [] and not review.owner.controls.model_tasks


@pytest.mark.asyncio
async def test_revise_feedback_has_bound_sources_and_retry_budget_does_not_reset(review):
    review.owner.cloud.response["text"] = json.dumps(decision(revise=True), ensure_ascii=False)
    result = await check(review)
    assert not result.passed and result.retryable and result.code == "reflection_review_required"
    assert "空输入" in result.correction
    review.owner.cloud.response["text"] = json.dumps(decision())
    assert (await check(review)).passed
    assert review.run["reflection_review"]["findings"] == []
    third = await check(review)
    assert not third.passed and not third.retryable
    assert len(review.owner.cloud.calls) == 2 and review.run["reflection_review"]["attempts"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["request", "cost", "tokens", "time", "machine"])
async def test_budget_and_machine_preconditions_prevent_model_requests(review, case):
    if case == "request":
        review.context.limits = ContextLimits(max_model_requests=1)
    elif case == "cost":
        review.context.limits = ContextLimits(max_cost_usd=0.1)
        review.context.cost_known = False
    elif case == "tokens":
        review.context.limits = ContextLimits(max_total_tokens=100)
        review.context.tokens = 100
    elif case == "time":
        review.context.prior_active_seconds = 3600
    else:
        review.outcome = RunOutcome(run_id="run", goal_outcome="unknown")
    result = await check(review)
    assert not result.passed and not result.retryable and not review.owner.cloud.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["goal", "disk", "rule", "requirements", "policy", "generation"])
async def test_changes_during_review_invalidate_result_and_keep_usage(review, change):
    def mutate():
        if change == "disk":
            (review.root / "app.py").write_text("result = 2\n", encoding="utf-8")
        elif change == "rule":
            (review.root / "AGENTS.md").write_text("新增项目规则", encoding="utf-8")
        elif change == "requirements":
            review.run["completion_requirements"] = [{"requirement_id": "new"}]
        elif change == "policy":
            review.run["completion_policy"] = {"tests_forbidden": True}
        elif change == "generation":
            review.run["generation"] += 1
        else:
            review.run["goal"] = "新的目标"
    review.owner.cloud.on_response = mutate
    result = await check(review)
    assert result.code == "steering_superseded" and result.retryable
    assert review.context.tokens == 120 and review.run["reflection_review"]["status"] == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("model_name", "replacement"), ("supports_structured_output", False)])
async def test_model_configuration_changes_are_nonretryable(review, field, value):
    review.owner.cloud.on_response = lambda: review.profile.update({field: value})
    result = await check(review)
    assert result.code == "reflection_review_unavailable" and not result.retryable
    assert review.run["reflection_review"]["reason"] == "model_configuration_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["route", "tool", "truncated", "invalid_json", "secret"])
async def test_invalid_model_response_fails_closed_without_exposing_body(review, case):
    if case == "route":
        review.owner.cloud.response["model_profile_id"] = "wrong"
    elif case == "tool":
        review.owner.cloud.response["tool_calls"] = [{"id": "call", "name": "write_project_file", "arguments": {}}]
    elif case == "truncated":
        review.owner.cloud.response["finish_reason"] = "length"
    elif case == "secret":
        review.owner.cloud.response["text"] = json.dumps(decision(revise=True, detail="fixture-sensitive-string"))
    else:
        review.owner.cloud.response["text"] = "private-invalid-response"
    result = await check(review)
    assert not result.passed and not result.retryable and review.context.tokens == 120
    assert "fixture-sensitive-string" not in json.dumps(review.saved)
    assert "private-invalid-response" not in json.dumps(review.saved)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [CloudError(502, "private-error", code="model_request_failed"), TimeoutError(), ValueError("private-error")])
async def test_failed_request_marks_usage_unknown_without_secret_error(review, error):
    review.owner.cloud.failure = error
    result = await check(review)
    assert not result.passed and not result.retryable
    assert not review.context.tokens_known and not review.context.cost_known
    assert review.run["cost_usd"] is None and review.run["usage_complete"] is False
    assert "private-error" not in json.dumps(review.saved) and not review.owner.controls.model_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("storage failure"), sqlite3.OperationalError("storage failure")])
async def test_storage_errors_propagate(review, error):
    review.owner.cloud.failure = error
    with pytest.raises(type(error)):
        await check(review)
    assert review.run["usage_complete"] is False


@pytest.mark.asyncio
async def test_missing_provider_usage_stays_unknown(review):
    review.owner.cloud.response["usage"] = {}
    result = await check(review)
    assert result.passed
    assert not review.context.tokens_known and not review.context.cost_known
    assert review.run["cost_usd"] is None and review.run["usage_complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["tokens", "cost", "time", "unknown_usage"])
async def test_review_cannot_pass_after_exhausting_its_own_budget(review, case):
    if case == "tokens":
        review.context.limits = ContextLimits(max_total_tokens=100)
    elif case == "cost":
        review.context.limits = ContextLimits(max_cost_usd=0.005)
    elif case == "time":
        review.owner.cloud.on_response = lambda: setattr(review.context, "prior_active_seconds", 3600)
    else:
        review.context.limits = ContextLimits(max_total_tokens=1000)
        review.owner.cloud.response["usage"] = {}
    result = await check(review)
    assert not result.passed and not result.retryable and len(review.owner.cloud.calls) == 1


@pytest.mark.asyncio
async def test_record_storage_failure_rolls_back_review_state(review):
    state = {"attempts": 2, "status": "passed"}
    review.run["reflection_review"] = state

    def fail_event(*args, **kwargs):
        raise sqlite3.OperationalError("event unavailable")

    review.owner.event = fail_event
    with pytest.raises(sqlite3.OperationalError):
        await check(review)
    assert review.run["reflection_review"] is state


@pytest.mark.asyncio
async def test_external_cancel_propagates_and_cleans_registered_task(review):
    review.owner.cloud.release = asyncio.Event()
    task = asyncio.create_task(check(review))
    await review.owner.cloud.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not review.owner.controls.model_tasks and review.run["usage_complete"] is False
    assert review.run["reflection_review"]["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["model", "profiles"])
async def test_steering_cancels_all_async_review_stages_and_discards_conclusion(review, stage):
    if stage == "model":
        review.owner.cloud.release = asyncio.Event()
        entered = review.owner.cloud.entered
    else:
        review.owner.cloud.profile_release = asyncio.Event()
        entered = review.owner.cloud.profile_entered
    task = asyncio.create_task(check(review))
    await entered.wait()
    review.run["generation"] += 1
    review.owner.controls.model_tasks[review.run["id"]].cancel()
    result = await task
    assert result.code == "steering_superseded" and not review.owner.controls.model_tasks
    assert review.run.get("usage_complete") is (stage == "profiles")


@pytest.mark.asyncio
async def test_profiles_refresh_is_covered_by_same_timeout(review, monkeypatch):
    monkeypatch.setattr("private_agent_local.reflection_review.REVIEW_TIMEOUT", 0.03)
    review.owner.cloud.profile_release = asyncio.Event()
    result = await asyncio.wait_for(check(review), 1)
    assert not result.passed and not result.retryable and not review.owner.controls.model_tasks
    assert review.context.tokens == 120 and review.run["usage_complete"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("has_response_generation", [True, False])
async def test_generation_change_during_initial_scan_never_spends_review_budget(review, monkeypatch, has_response_generation):
    from private_agent_local.completion import workspace_state

    entered, release = threading.Event(), threading.Event()
    if has_response_generation:
        review.run["response_generation"] = 0

    def scan(root):
        entered.set()
        assert release.wait(timeout=2), "测试必须释放磁盘扫描线程"
        return workspace_state(root)

    monkeypatch.setattr("private_agent_local.completion.workspace_state", scan)
    task = asyncio.create_task(check(review))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        review.run["generation"] += 1
        release.set()
        result = await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert result.code == "steering_superseded" and result.retryable
    assert not review.owner.cloud.calls and review.context.rounds == 0
    assert review.run["reflection_review"].get("attempts", 0) == 0
    assert not review.owner.controls.model_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary_number", [1, 2])
async def test_control_boundary_change_cannot_review_old_candidate(review, boundary_number):
    calls = 0
    original = review.owner.controls.boundary
    review.run["response_generation"] = 0

    async def boundary(run):
        nonlocal calls
        calls += 1
        await original(run)
        if calls == boundary_number:
            run["generation"] += 1

    review.owner.controls.boundary = boundary
    result = await check(review)
    assert result.code == "steering_superseded" and not review.owner.cloud.calls
    assert review.context.rounds == 0 and review.run["reflection_review"].get("attempts", 0) == 0


@pytest.mark.asyncio
async def test_already_superseded_response_is_rejected_before_scanning(review, monkeypatch):
    review.run.update(generation=1, response_generation=0)

    def forbidden_scan(root):
        pytest.fail("旧模型候选不能进入磁盘扫描或复核请求")

    monkeypatch.setattr("private_agent_local.completion.workspace_state", forbidden_scan)
    result = await check(review)
    assert result.code == "steering_superseded" and not review.owner.cloud.calls
    assert review.context.rounds == 0 and review.run["reflection_review"].get("attempts", 0) == 0
