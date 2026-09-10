"""S6 运行器的真实判定、统计、防护及私有进程协议回归。"""
import json
from collections import Counter

import pytest
from coding_acceptance_catalog import judge, load_catalog, preflight, rebuild, snapshot
from coding_acceptance_evidence import (
    TERMINAL_EVENTS,
    Evidence,
    aggregate,
    event_integrity,
    event_integrity_errors,
    independent,
    redact,
)
from coding_acceptance_transport import Fixture, RuntimeClient, reply
from run_coding_acceptance import approved, model_config, product_identity


def test_s6_frozen_denominator_and_distribution():
    catalog = load_catalog()
    assert Counter(task["split"] for task in catalog["tasks"]) == {"development": 18, "holdout": 12}
    assert sum(task["coding_goal"] for task in catalog["tasks"]) * catalog["repetitions"] == 81
    assert catalog["blind_quality_eligible"] is False
    assert preflight(catalog["tasks"])["passed"], preflight(catalog["tasks"])


@pytest.mark.parametrize("task", load_catalog()["tasks"], ids=lambda task: task["id"])
def test_s6_fixture_oracles_and_protected_files(tmp_path, task):
    directory = tmp_path / "project"
    (tmp_path / "tmp").mkdir()
    baseline = rebuild(task, directory)
    initial = judge(task, directory, tmp_path, baseline)
    assert initial["passed"] == task["initial_should_pass"], initial
    for name, content in task["reference_files"].items():
        (directory / name).write_text(content, encoding="utf-8", newline="\n")
    accepted = judge(task, directory, tmp_path, baseline)
    assert accepted["passed"], accepted
    (directory / "user-notes.txt").write_text("覆盖用户工作", encoding="utf-8")
    assert judge(task, directory, tmp_path, baseline)["reason"] == "user_work_changed"


def plan(identity="one", **overrides):
    return {"attempt_id": identity, "task_id": "PY01", "model": "selected", "coding_goal": True,
            "mode": "quality", "family": "python", "category": "bug", "split": "development", **overrides}


def passed(identity="one", **overrides):
    return {**plan(identity), "started": True, "human_interventions": 0, "functional_passed": True,
            "scope_preserved": True, "validation_passed": True, "report_matches_facts": True,
            "within_budget": True, "evidence_complete": True, "reviewed_constraints": True,
            "model_identity_matches": True, "system_behavior_passed": True, "run_status": "completed", "goal_outcome": "verified", **overrides}


def test_failure_denominators_unknown_usage_and_provider_groups():
    expected = [plan(), plan("timeout"), plan("denied", coding_goal=False), plan("other", model="other-model")]
    attempts = [passed(), {**expected[1], "started": True, "failure_class": "provider_timeout"},
                {**expected[2], "started": True, "system_behavior_passed": True},
                {**expected[3], "started": False, "failure_class": "preflight"}]
    result = aggregate(attempts, expected)
    selected = result["models"]["selected"]["overall"]
    assert result["integrity_passed"]
    assert selected["coding_denominator"] == 2 and selected["independent_completion_rate"] == 0.5
    assert selected["cost_usd"] is None and selected["cost_unknown_attempts"] == 3
    assert result["models"]["other-model"]["overall"]["coding_denominator"] == 0


@pytest.mark.parametrize("change", [{"mode": "control"}, {"human_interventions": 1}, {"coding_goal": False},
                                    {"report_matches_facts": None}, {"within_budget": False}, {"evidence_complete": False},
                                    {"model_identity_matches": False}, {"goal_outcome": "unknown"}, {"run_status": "failed"}])
def test_non_independent_results_cannot_raise_quality_rate(change):
    assert not independent(passed(**change))


def test_missing_duplicate_and_reclassified_attempts_fail_closed():
    assert not aggregate([], [plan()])["integrity_passed"]
    assert not aggregate([passed(), passed()], [plan()])["integrity_passed"]
    assert not aggregate([passed(coding_goal=False)], [plan()])["integrity_passed"]


def test_redaction_keeps_token_usage_and_removes_credentials():
    result = redact({"input_tokens": 20, "Authorization": "test-value", "nested": [{"password": "test-value"}],
                     "output": "Bearer test-value api_key=test-value"})
    assert result["input_tokens"] == 20
    assert "test-value" not in json.dumps(result)


def test_interrupted_runner_already_has_failing_report(tmp_path):
    evidence = Evidence(tmp_path, {"mode": "control", "schedule": [plan()], "product": {}})
    assert json.loads((tmp_path / "metrics.json").read_text())["integrity_passed"] is False
    evidence.append({**plan(), "started": True, "failure_class": "runner_error"})
    evidence.errors.append("child_cleanup_failed")
    result = evidence.finish()
    assert not result["integrity_passed"] and result["delivery_decision"] == "blocked"


def test_event_gaps_and_duplicate_terminals_are_rejected():
    events = [{"sequence": 1, "type": "run.started"}, {"sequence": 2, "type": "run.completed"}]
    assert event_integrity(events, 2)
    assert not event_integrity(events[1:], 2)
    assert not event_integrity([*events, {"sequence": 3, "type": "run.completed"}], 3)


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "timed_out", "limit_exceeded", "interrupted"])
def test_all_runtime_terminals_end_polling_and_have_complete_events(status):
    from run_coding_acceptance import TERMINAL

    assert status in TERMINAL
    history = [{"sequence": 1, "type": "run.started"}, {"sequence": 2, "type": "run." + status}]
    assert event_integrity(history, 2)


def test_local_runtime_terminal_contract_does_not_drift():
    import ast

    from run_coding_acceptance import TERMINAL
    from run_coding_validation import ROOT

    # 只解析纯常量，契约检查不为获取状态集合而导入或启动业务运行时。
    module = ast.parse((ROOT / "src/private_agent_local/runtime.py").read_text(encoding="utf-8"))
    runtime_terminal = next(ast.literal_eval(node.value) for node in module.body
                            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "TERMINAL"
                                                                     for target in node.targets))
    assert TERMINAL == runtime_terminal
    from private_agent_core.contracts import AgentEventType, AgentRunStatus

    core_terminal = {item.value for item in AgentRunStatus} - {"created", "running", "waiting_approval"}
    assert core_terminal == TERMINAL - {"interrupted"}
    assert {TERMINAL_EVENTS[status] for status in core_terminal} <= {item.value for item in AgentEventType}


@pytest.mark.parametrize("history,last,status,expected", [
    ([], 0, "completed", {"invalid_last_sequence", "empty_events", "missing_terminal"}),
    ([{"sequence": 1, "type": "run.started"}], 1, "failed", {"missing_terminal"}),
    ([{"sequence": 2, "type": "run.failed"}], 2, "failed", {"sequence_mismatch"}),
    ([{"sequence": True, "type": "run.failed"}], 1, "failed", {"sequence_mismatch"}),
    ([{"sequence": 1, "type": "run.failed"}], 1, "completed", {"terminal_status_mismatch"}),
    ([{"sequence": 1, "type": "run.failed"}], 1, "running", {"run_not_terminal"}),
    ([{"sequence": 1, "type": "run.cancelled"}, {"sequence": 2, "type": "run.limit_exceeded"}], 2,
     "limit_exceeded", {"duplicate_terminal", "event_after_terminal"}),
    ([{"sequence": 1, "type": "run.timed_out"}, {"sequence": 2, "type": "model.started"}], 2,
     "timed_out", {"event_after_terminal"}),
    ([{"sequence": 1, "type": "run.completed"}, {"sequence": 2, "type": "control.received"}], 2,
     "completed", {"event_after_terminal"}),
])
def test_terminal_event_integrity_has_explicit_failure_reasons(history, last, status, expected):
    assert set(event_integrity_errors(history, last, status)) == expected
    assert event_integrity(history, last, status) is False


class PollingClock:
    def __init__(self, monkeypatch):
        import run_coding_acceptance as runner

        self.now = 100.0
        monkeypatch.setattr(runner.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(runner.time, "sleep", self.advance)

    def advance(self, seconds):
        self.now += seconds


class PollingClient:
    def __init__(self, states, *, receipt=None):
        self.states = list(states)
        self.receipt = {"accepted": True} if receipt is None else receipt
        self.calls = []

    def request(self, path, method="GET", **kwargs):
        self.calls.append((path, method, kwargs))
        if method == "POST":
            assert path == "/agent-runs/one/cancel"
            if isinstance(self.receipt, Exception):
                raise self.receipt
            return self.receipt
        assert path == "/agent-runs/one"
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        if isinstance(state, Exception):
            raise state
        return dict(state)


def polling_state(status="running", **extra):
    return {"id": "one", "status": status, "usage_complete": True, "input_tokens": 120001, "output_tokens": 20, **extra}


@pytest.mark.parametrize("status,code,failure", [
    ("completed", None, None), ("failed", "model_stream_interrupted", "runtime_failed"),
    ("cancelled", "cancelled", "user_cancelled"), ("timed_out", "wall_time", "runtime_timeout"),
    ("limit_exceeded", "context_limit", "budget_exhausted"),
    ("limit_exceeded", "max_active_seconds", "runtime_timeout"), ("interrupted", "process_interrupted", "runtime_interrupted"),
])
def test_polling_checks_latest_terminal_before_expired_deadline_or_cancel(monkeypatch, status, code, failure):
    from run_coding_acceptance import poll_run, run_failure

    clock = PollingClock(monkeypatch)
    current = polling_state(status, error_code=code, input_tokens=100)
    client = PollingClient([current])
    final, observed = poll_run(client, polling_state(), deadline=clock.now - 1,
                              on_active=lambda _run: pytest.fail("已结束任务不得审批或继续执行"))
    assert final == current and run_failure(final, observed) == failure
    assert observed["terminal_observed"] and not observed["cancel_requested"]
    assert observed["stop_reason"] is None and len(client.calls) == 1


@pytest.mark.parametrize("reason", ["budget_exhausted", "attempt_timeout"])
@pytest.mark.parametrize("receipt", [{"accepted": True}, TimeoutError("取消响应丢失"), RuntimeError("取消返回 503")])
def test_polling_cancellation_is_sent_once_and_confirmed_by_final_state(monkeypatch, reason, receipt):
    from run_coding_acceptance import poll_run, run_failure

    clock = PollingClock(monkeypatch)
    active = polling_state(input_tokens=120001 if reason == "budget_exhausted" else 100)
    client = PollingClient([active, active, polling_state("cancelled", error_code="cancelled")], receipt=receipt)
    final, observed = poll_run(client, active, deadline=clock.now + (60 if reason == "budget_exhausted" else -1),
                              on_active=lambda _run: pytest.fail("停止条件成立后不得审批或恢复"))
    assert final["status"] == "cancelled" and final["error_code"] == "cancelled"
    assert run_failure(final, observed) == reason and observed["stop_reason"] == reason
    assert observed["terminal_observed"]
    assert observed["cancel_response"] == ("unknown" if isinstance(receipt, Exception) else "accepted")
    assert sum(method == "POST" for _path, method, _kwargs in client.calls) == 1
    assert len(client.calls) == 4


@pytest.mark.parametrize("status,code,failure", [
    ("limit_exceeded", "context_limit", "budget_exhausted"),
    ("limit_exceeded", "max_active_seconds", "runtime_timeout"),
    ("timed_out", "wall_time", "runtime_timeout"), ("failed", "model_invalid_response", "runtime_failed"),
    ("cancelled", "cancelled", "user_cancelled"),
])
def test_polling_cancellation_race_preserves_runtime_terminal(monkeypatch, status, code, failure):
    from run_coding_acceptance import poll_run, run_failure

    clock = PollingClock(monkeypatch)
    current = polling_state(status, error_code=code)
    client = PollingClient([polling_state(), current], receipt={"accepted": False})
    final, observed = poll_run(client, polling_state(), deadline=clock.now - 1)
    assert final == current and run_failure(final, observed) == failure
    assert observed["cancel_response"] == "not_accepted"
    assert sum(method == "POST" for _path, method, _kwargs in client.calls) == 1


def test_polling_cancellation_unknown_is_bounded_without_replay(monkeypatch):
    from run_coding_acceptance import CANCEL_OBSERVE_SECONDS, poll_run, run_failure

    clock = PollingClock(monkeypatch)
    client = PollingClient([polling_state()], receipt=TimeoutError("取消响应未知"))
    final, observed = poll_run(client, polling_state(), deadline=clock.now + 630)
    assert final["status"] == "running" and observed["terminal_observed"] is False
    assert run_failure(final, observed) == "budget_exhausted"
    assert observed["observation_error"]["type"] == "TimeoutError"
    assert clock.now == pytest.approx(100 + CANCEL_OBSERVE_SECONDS)
    assert sum(method == "POST" for _path, method, _kwargs in client.calls) == 1
    assert all(0 < kwargs["timeout"] <= 30 for _path, _method, kwargs in client.calls)


def test_polling_completed_over_budget_keeps_terminal_without_cancel(monkeypatch):
    from run_coding_acceptance import poll_run, run_failure

    clock = PollingClock(monkeypatch)
    client = PollingClient([polling_state("completed")])
    final, observed = poll_run(client, polling_state(), deadline=clock.now + 630)
    assert final["status"] == "completed" and run_failure(final, observed) == "budget_exhausted"
    assert observed["stop_reason"] is None and not observed["cancel_requested"]
    assert len(client.calls) == 1


def test_polling_transport_timeout_keeps_unknown_state_distinct(monkeypatch):
    from run_coding_acceptance import poll_run, run_failure

    clock = PollingClock(monkeypatch)
    client = PollingClient([TimeoutError("状态响应超时")])
    final, observed = poll_run(client, polling_state(), deadline=clock.now + 630)
    assert not observed["terminal_observed"] and not observed["cancel_requested"]
    assert run_failure(final, observed) == "evaluator_transport_timeout"
    assert len(client.calls) == 1


def test_polling_deadline_expires_during_status_request_without_claiming_cancel(monkeypatch):
    from run_coding_acceptance import poll_run, run_failure

    clock = PollingClock(monkeypatch)

    class Client(PollingClient):
        def request(self, *args, **kwargs):
            clock.advance(kwargs["timeout"])
            return super().request(*args, **kwargs)

    client = Client([TimeoutError("状态查询耗尽评测剩余期限")])
    final, observed = poll_run(client, polling_state(), deadline=clock.now + 1)
    assert final["status"] == "running" and observed["terminal_observed"] is False
    assert observed["stop_reason"] == "attempt_timeout" and run_failure(final, observed) == "attempt_timeout"
    assert not observed["cancel_requested"] and len(client.calls) == 1


@pytest.mark.parametrize("page", [[], [{"sequence": 0}], [{"sequence": 2}], [{"sequence": 1}, {"sequence": 1}]])
def test_event_pages_reject_missing_duplicate_or_nonadvancing_cursor(page):
    from run_coding_acceptance import events

    class Client:
        def request(self, *_args):
            return {"items": page}

    with pytest.raises(ValueError, match="分页"):
        events(Client(), {"id": "one", "last_event_sequence": 2})


@pytest.mark.parametrize("late", ["complete", "chunks", "error", "missing"])
def test_late_ipc_cancel_response_does_not_break_followup_read(late):
    import queue
    from types import SimpleNamespace

    client = RuntimeClient.__new__(RuntimeClient)
    client.fixture = SimpleNamespace(token="s6-isolated-placeholder")
    client.frames, client.expired_requests, client.reader_error = queue.Queue(), set(), None
    sent = []

    class Input:
        def write(self, data):
            frame = json.loads(data)
            sent.append(frame)
            if len(sent) == 2:
                if late == "error":
                    client.frames.put({"id": sent[0]["id"], "error": "取消响应丢失"})
                elif late != "missing":
                    if late == "chunks":
                        client.frames.put({"id": sent[0]["id"], "data": "迟到的分块", "done": False})
                    client.frames.put({"id": sent[0]["id"], "status": 200, "data": "{}", "done": True})
                client.frames.put({"id": frame["id"], "status": 200, "data": '{"status":"cancelled"}', "done": True})

        def flush(self):
            pass

    client.process = SimpleNamespace(stdin=Input())
    with pytest.raises(TimeoutError):
        client.request("/agent-runs/one/cancel", "POST", timeout=0.001)
    assert client.request("/agent-runs/one") == {"status": "cancelled"}
    assert [item["params"]["method"] for item in sent] == ["POST", "GET"]
    assert len(client.expired_requests) == (1 if late == "missing" else 0)


def test_late_ipc_unknown_response_id_still_fails_closed():
    import queue
    import time

    client = RuntimeClient.__new__(RuntimeClient)
    client.frames, client.expired_requests, client.reader_error = queue.Queue(), {"expired"}, None
    client.frames.put({"id": "unrelated", "status": 200, "data": "{}", "done": True})
    with pytest.raises(RuntimeError, match="不匹配"):
        client._response("current", "/agent-runs/one", None, time.monotonic() + 1)


def test_approval_does_not_expand_scope():
    task = load_catalog()["tasks"][0]
    approval = {"tool_name": "write_project_file"}
    assert approved(task, approval, {"rel_path": "src/domain.py"})
    assert not approved(task, approval, {"rel_path": "user-notes.txt"})
    assert not approved(task, {"tool_name": "exec_command"}, {"argv": ["python", "unplanned.py"]})
    assert not approved({**task, "scenario": "deny"}, approval, {"rel_path": "src/domain.py"})


@pytest.mark.parametrize("endpoint", ["https://example.com/v1", "http://localhost:1234/v1", "http://127.0.0.1/v1?api_key=x", "http://x:y@127.0.0.1/v1"])
def test_quality_config_refuses_remote_or_secret_endpoints(tmp_path, endpoint):
    path = tmp_path / "model.json"
    path.write_text(json.dumps({"endpoint": endpoint, "model": "test", "protocol": "openai", "context_tokens": 8192,
                                "local_unbilled": True, "max_total_tokens": 1000}))
    with pytest.raises(ValueError):
        model_config(path)


def test_linked_or_unexpected_files_are_not_ignored(tmp_path):
    task = load_catalog()["tasks"][0]
    directory = tmp_path / "project"
    before = rebuild(task, directory)
    (directory / "unexpected.txt").write_text("新增范围外文件", encoding="utf-8")
    assert judge(task, directory, tmp_path, before)["reason"] == "user_work_changed"
    assert "unexpected.txt" in snapshot(directory)


@pytest.mark.parametrize("protocol,legacy", [("service", False), ("service", True), ("openai", False), ("ollama", False)])
def test_formal_ipc_streaming_and_false_completion(tmp_path, protocol, legacy):
    with Fixture(protocol, legacy_stream=legacy) as fixture:
        fixture.responses.extend(reply("已创建 missing.py，全部完成。") for _ in range(3))
        with RuntimeClient(tmp_path, fixture) as client:
            assert client.request("/identity", "POST")["ready"]
            project = tmp_path / "project"
            project.mkdir()
            created = client.request("/projects", "POST", {"name": "S6 IPC", "root_path": str(project)})
            workspace = client.request(f"/projects/{created['id']}/workspaces")[0]
            binding = {"project_id": created["id"], "workspace_id": workspace["id"]}
            session = client.request("/sessions", "POST", {**binding, "title": "完成真实性"})
            run = client.request("/agent-runs", "POST", {**binding, "session_id": session["id"], "message": "创建 missing.py",
                                 "model_profile_id": "s6-profile", "execution_contract_version": "1.0", "recovery_contract_version": "1.0"})
            import time
            deadline = time.monotonic() + 30
            while run["status"] not in {"failed", "completed", "cancelled"} and time.monotonic() < deadline:
                time.sleep(0.05)
                run = client.request(f"/agent-runs/{run['id']}")
            assert run["goal_outcome"] == "unmet", run
            assert not (project / "missing.py").exists()
            assert len(fixture.calls) == 3
            assert not fixture.errors
            if protocol == "service":
                assert all(call["path"].endswith("/complete" if legacy else "/stream") for call in fixture.calls)


def test_source_identity_is_concrete():
    identity = product_identity(None)
    assert len(identity["sha256"]) == 64
    assert "src/private_agent_local/runtime.py" in identity["files"]
    assert identity["installed_desktop_verified"] is False
