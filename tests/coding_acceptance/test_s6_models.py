"""阶段 C：真实路径替身、预算边界、错误分类和过程指标。"""
import copy
import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
from coding_acceptance_budget import ExperimentBudget
from coding_acceptance_catalog import load_catalog
from coding_acceptance_evidence import aggregate
from coding_acceptance_metrics import (
    ResourceSampler,
    duration,
    process_metrics,
    without,
)
from coding_acceptance_models import (
    ProductSession,
    model_identity_fingerprint,
    product_config,
)
from coding_acceptance_schema import budget, load_external
from coding_acceptance_transport import Fixture
from test_local_executor import call, close, response, setup, until

from private_agent_core.context import ContextLimits
from private_agent_local.runtime import TERMINAL


def budgets():
    return {"max_model_requests": 4, "max_tool_calls": 4, "max_active_seconds": 30, "max_attempt_tokens": 1000,
            "max_total_tokens": 2000, "cost_usd": None, "total_cost_usd": None,
            "max_total_model_requests": 8, "max_total_tool_calls": 8, "max_total_active_seconds": 60}


def config():
    return {"schema_version": 1, "connection_mode": "product_proxy", "endpoint": "https://test.example.invalid",
            "profile_id": "s6-profile", "model": "s6-fixture", "model_version": None, "context_tokens": 131072,
            "parameters": {"reasoning_effort": None, "max_output_tokens": 2048, "auto_compact": True}, "budget": budgets()}


@pytest.mark.parametrize("change", [
    lambda c: c.update(api_key="synthetic-secret"), lambda c: c.update(schema_version=True),
    lambda c: c.update(endpoint="https://user:synthetic-secret@test.invalid"),
    lambda c: c.update(endpoint="https://test.invalid/?token=synthetic-secret"),
    lambda c: c.update(context_tokens=True), lambda c: c["parameters"].update(temperature=1),
    lambda c: c["budget"].update(max_total_model_requests=1), lambda c: c["budget"].update(cost_usd=float("nan")),
    lambda c: c.update(endpoint=[]), lambda c: c.update(endpoint="https://test.invalid/\n"),
    lambda c: c["parameters"].update(reasoning_effort=[]),
])
def test_product_config_is_strict_and_never_accepts_credentials(change):
    data = config()
    change(data)
    with pytest.raises(ValueError):
        product_config(data)


def test_product_session_never_requests_a_platform_token(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("不得请求平台凭据"))
    session = ProductSession(config())
    assert session.model_name == config()["model"]
    assert not hasattr(session, "token")


def test_model_identity_ignores_only_catalog_record_times():
    before = {"profile": {"id": "model-a", "created_at": "old", "updated_at": "old"},
              "provider": {"endpoint": "https://models.example.test"}, "parameters": {"temperature": 0.7}}
    after = copy.deepcopy(before)
    after["profile"].update(created_at="new", updated_at="new")
    assert model_identity_fingerprint(before) == model_identity_fingerprint(after)
    for key, value in (("profile", {"id": "model-b"}), ("provider", {"endpoint": "https://other.example.test"}),
                       ("parameters", {"temperature": 0.1})):
        assert model_identity_fingerprint(before) != model_identity_fingerprint({**after, key: value})


def test_connection_mode_is_frozen_without_reinterpreting_legacy_rows():
    plan = {"attempt_id": "one", "model": "fixture", "task_id": "PY01", "family": "python", "category": "feature",
            "split": "development", "mode": "quality", "coding_goal": True}
    assert aggregate([{**plan, "started": False}], [plan])["integrity_passed"]
    modern = {**plan, "connection_mode": "fixture"}
    result = aggregate([{**modern, "connection_mode": "product_proxy", "started": True}], [modern])
    assert result["runner_errors"] == ["attempt_identity_mismatch:one"]


def test_v1_preserved_v2_explicit_cost_and_total_budget(tmp_path):
    old = load_catalog()["budget"]
    budget(old)
    with pytest.raises(ValueError):
        budget({**old, "cost_usd": 1})
    budget(budgets(), 2)
    data = json.loads((Path(__file__).parent / "external_public/catalog.json").read_text(encoding="utf-8"))
    assessment = Path(__file__).parent / "external_public/assessment.json"
    (tmp_path / "assessment.json").write_bytes(assessment.read_bytes())
    data["schema_version"] = 2
    data["budget"] = budgets()
    for task in data["tasks"]:
        task["budget"] = budgets()
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_external(path)["schema_version"] == 2


@pytest.mark.parametrize("dimension", ["model_requests", "tool_calls", "active_seconds", "tokens", "cost_usd"])
def test_total_budget_boundary_and_unknown_cannot_restart(dimension):
    limits = {**budgets(), "cost_usd": 1, "total_cost_usd": 2}
    ledger = ExperimentBudget(limits, 2)
    row = {"attempt_id": "one", "started": True, "model_requests": 1, "tool_calls": 1,
           "active_seconds": 1, "tokens": 1, "cost_usd": 0.1}
    row[dimension] = ledger.limit[dimension]
    ledger.settle(row)
    with pytest.raises(ValueError, match="exhausted"):
        ledger.allocate(limits)
    with pytest.raises(ValueError, match="重复"):
        ledger.settle(row)
    unknown = ExperimentBudget(limits, 2)
    unknown.settle({**row, dimension: None})
    assert unknown.snapshot()["usage"][dimension] is None
    with pytest.raises(ValueError, match="unknown"):
        unknown.allocate(limits)


def test_remaining_is_allocated_instead_of_reserving_full_attempt():
    ledger = ExperimentBudget(budgets(), 2)
    ledger.settle({"attempt_id": "one", "started": True, "model_requests": 7, "tool_calls": 7, "active_seconds": 59,
                   "tokens": 1999, "cost_usd": None})
    result = ledger.allocate(budgets())
    assert [result[k] for k in ("max_model_requests", "max_tool_calls", "max_active_seconds", "max_attempt_tokens")] == [1, 1, 1, 1]
    assert ledger.snapshot()["usage"]["cost_usd"] is None


def test_fixture_unknown_simulated_usage_preserves_calibration_and_resource_budgets():
    ledger = ExperimentBudget(budgets(), 2, enforce_model_usage=False)
    row = {"attempt_id": "paused", "started": True, "model_requests": 1, "tool_calls": 1,
           "active_seconds": 1, "tokens": None, "cost_usd": None}
    ledger.settle(row)
    assert ledger.allocate(budgets())["max_attempt_tokens"] == 1000
    assert ledger.snapshot()["usage"]["tokens"] is None
    assert ledger.snapshot()["token_enforcement"] == "fixture_simulation_not_enforced"
    ledger.settle({**row, "attempt_id": "later", "model_requests": 7})
    with pytest.raises(ValueError, match="total_model_requests_exhausted"):
        ledger.allocate(budgets())


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,limits,error", [
    ({"input_tokens": 3, "output_tokens": 2}, {"max_total_tokens": 5}, "max_total_tokens"),
    ({}, {"max_total_tokens": 20}, "token_usage_unknown"),
    ({"input_tokens": 3, "output_tokens": 2}, {"max_cost_usd": 0.1}, "cost_usage_unknown"),
    ({"input_tokens": 3, "output_tokens": 2, "cost_usd": 0.1}, {"max_cost_usd": 0.1}, "max_cost_usd"),
])
async def test_runtime_stops_before_next_model_request(tmp_path, usage, limits, error):
    app, client, server, root, body = await setup(tmp_path)
    (root / "read.txt").write_text("sample")
    server.responses = [{**response(call("read_code_file", {"rel_path": "read.txt"})), "usage": usage}, response(text="不应请求")]
    try:
        created = (await client.post("/agent-runs", json={**body, "context_limits": limits})).json()
        final = await until(client, created["id"], TERMINAL)
        assert final["error_code"] == error
        assert len(server.responses) == 1
        assert final["loop_budget"]["model_requests"] == 1
        assert final["status"] == ("limit_exceeded" if error.startswith("max_") else "failed")
        if not usage:
            assert final["loop_budget"]["tokens"] is None and final["usage_complete"] is False
    finally:
        await close(app, client)










def event(kind, stamp, **payload):
    return {"type": kind, "payload": {"timing": {"clock_id": "one-process", "monotonic_seconds": stamp}, **payload}}


def test_metrics_intervals_use_union_and_subtract_approval():
    events = [event("model.requested", 0, attempt_id="a"), event("model.output.finished", 4, attempt_id="a"),
              event("tool.requested", 3, tool_call_id="t"), event("tool.approval_required", 4, approval_id="p"),
              event("tool.approval_resolved", 6, approval_id="p"), event("tool.invocation_finished", 8, tool_call_id="t"),
              {"type": "tool.completed", "payload": {"tool_call_id": "t"}}]
    metrics = process_metrics(events, {"loop_budget": {"active_seconds": 6}})
    assert (metrics["model_seconds"], metrics["tool_seconds"], metrics["approval_seconds"]) == (4, 3, 2)
    assert metrics["model_tool_union_seconds"] == 8
    assert metrics["provider_requests"] is None
    assert duration([(0, 4), (3, 8)]) == 8 and without([(0, 8)], [(2, 5), (4, 6)]) == 4


@pytest.mark.parametrize("case", ["missing", "reversed", "clock", "duplicate"])
def test_metrics_missing_invalid_clock_and_duplicate_not_zero(case):
    events = [event("model.requested", 1, attempt_id="a"), event("model.output.finished", 2, attempt_id="a")]
    if case == "missing":
        events.pop()
    elif case == "clock":
        events[1]["payload"]["timing"]["clock_id"] = "another-machine"
    elif case == "reversed":
        events[1]["payload"]["timing"]["monotonic_seconds"] = 0
    else:
        events.insert(1, copy.deepcopy(events[0]))
    metrics = process_metrics(events, {})
    assert metrics["model_seconds"] is None and metrics["missing_reasons"]["model_seconds"]


def test_resource_sample_missing_is_explicit(tmp_path):
    (tmp_path / "one").write_bytes(b"abc")
    with ResourceSampler(SimpleNamespace(), tmp_path, interval=0.01) as sample:
        pass
    result = sample.snapshot()
    assert result["peak_processes"] is None and result["peak_sampled_storage_bytes"] == 3
    assert "processes_sampling_incomplete" in result["missing_reasons"]




def test_context_limits_defaults_compatible_and_reject_invalid_tokens():
    assert ContextLimits().max_total_tokens is None
    for value in (True, 0, -1, 1.5):
        with pytest.raises(ValueError):
            ContextLimits(max_total_tokens=value)


def test_active_budget_excludes_ongoing_approval_wait(monkeypatch):
    import private_agent_local.context_manager as module

    clock = SimpleNamespace(now=10.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    run = {"tool_call_count": 0, "approval_wait_seconds": 0}
    context = module.LocalContext(SimpleNamespace(store=SimpleNamespace(context=None)), run, None)
    clock.now = 12
    context.approval_started = 12
    clock.now = 20
    assert context.budget_snapshot()["active_seconds"] == 2
    context.approval_started = None
    run["approval_wait_seconds"] = 8
    clock.now = 25
    assert context.budget_snapshot()["active_seconds"] == 7


@pytest.mark.parametrize("protocol", ["openai", "ollama"])
def test_legacy_local_unbilled_config_runs_through_agent(protocol, tmp_path):
    import run_coding_acceptance as runner

    task = load_catalog()["tasks"][0]
    with Fixture(protocol) as fixture:
        fixture.responses.extend(runner.script(task))
        path = tmp_path / "local.json"
        path.write_text(json.dumps({"model": "s6-fixture", "protocol": protocol, "endpoint": fixture.endpoint,
                                   "context_tokens": 131072, "local_unbilled": True, "max_total_tokens": 10000}))
        result = runner.run(Namespace(mode="probe", tasks="PY01", repetitions=1, protocol="service", model_config=path,
                                      bundle=None, work_dir=tmp_path))
        directory = next(tmp_path.glob("probe-*"))
        rows = [json.loads(line) for line in (directory / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
        assert result == 0, rows
        assert rows[0]["connection_mode"] == "local_unbilled" and rows[0]["within_budget"]
        assert len(fixture.calls) > 1


def test_product_probe_uses_agent_ipc_isolation_and_bound_evidence(tmp_path, monkeypatch):
    import run_coding_acceptance as runner
    from coding_acceptance_evidence import verify_ledger

    catalog_path = Path(__file__).parent / "external_public/catalog.json"
    task = load_catalog(catalog_path)["tasks"][0]
    task["_execution_mode"] = "restricted"
    from test_s6_direct_evaluation import prepare_direct_evaluation

    with Fixture("openai") as fixture:
        path, parsed = prepare_direct_evaluation(tmp_path, fixture, monkeypatch)
        fixture.responses.extend(runner.script(task))
        result = runner.run(Namespace(mode="probe", tasks="PY01", repetitions=1, protocol="service", model_config=path,
                                      bundle=None, work_dir=tmp_path, isolation="appcontainer", catalog=catalog_path, authorize_model_calls=True))
        directory = next(tmp_path.glob("probe-*"))
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (directory / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
        assert result == 0, (rows, manifest.get("runner_exception"))
        row = rows[0]
        assert row["run_status"] == "completed" and row["system_behavior_passed"]
        assert row["connection_mode"] == "direct_provider" and row["actual_permission_mode"] == "confirm"
        assert row["isolation_verified"] and row["within_budget"]
        assert row["tokens"] > 0 and row["cost_usd"] is None
        assert row["process_metrics"]["model_requests"] == len(fixture.calls)
        assert row["process_metrics"]["provider_retries"] == 0
        assert row["process_metrics"]["model_seconds"] > 0 and row["process_metrics"]["tool_seconds"] > 0
        assert row["peak_processes"] >= 1 and row["peak_sampled_storage_bytes"] > 0
        assert manifest["experiment_budget"]["usage"]["tokens"] == row["tokens"]
        assert manifest["model"]["model"] == parsed["model"]
        verify_ledger(directory, manifest, rows)
        for name in ("manifest.json", "starts.jsonl", "attempts.jsonl", "metrics.json", "report.md"):
            assert fixture.token not in (directory / name).read_text(encoding="utf-8")
            assert "S6_SYNTHETIC_PROVIDER_VALUE" not in (directory / name).read_text(encoding="utf-8")
        assert json.loads((directory / "metrics.json").read_text(encoding="utf-8"))["delivery_decision"] == "blocked"


