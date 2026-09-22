"""S6 交付证据：真实进程重开、断流、合成旧库和不可改写的审阅。"""
import json
import sqlite3
import time
from argparse import Namespace

import pytest
from coding_acceptance_evidence import Evidence, digest, write_json
from coding_acceptance_review import review
from coding_acceptance_transport import Fixture, RuntimeClient, reply
from run_coding_acceptance import control, events

from private_agent_local.store import INLINE_BYTES, SCHEMA_VERSION, Store


def create(client, directory, message):
    directory.mkdir()
    project = client.request("/projects", "POST", {"name": "S6 交付", "root_path": str(directory)})
    workspace = client.request(f"/projects/{project['id']}/workspaces")[0]
    binding = {"project_id": project["id"], "workspace_id": workspace["id"]}
    session = client.request("/sessions", "POST", {**binding, "title": message})
    return client.request("/agent-runs", "POST", {**binding, "session_id": session["id"], "message": message,
                           "model_profile_id": client.fixture.profile_id, "execution_contract_version": "1.0", "recovery_contract_version": "1.0"})


def until(client, run_id, statuses):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = client.request(f"/agent-runs/{run_id}")
        if run["status"] in statuses:
            return run
        time.sleep(0.05)
    pytest.fail("正式 IPC 运行未在期限内达到预期状态")


def test_stream_interruption_is_not_replayed_as_complete(tmp_path):
    with Fixture() as fixture:
        fixture.responses.append({**reply("尚未完成"), "interrupt_stream": True})
        with RuntimeClient(tmp_path, fixture) as client:
            client.request("/identity/local", "POST")
            run = create(client, tmp_path / "project", "创建 result.txt")
            final = until(client, run["id"], {"failed", "completed"})
            assert final["goal_outcome"] != "verified"
            assert final["error_code"] == "model_stream_interrupted"
            assert fixture.calls == [{"path": "/v1/chat/completions", "stream": True}]
            assert not (tmp_path / "project/result.txt").exists()


def test_reopen_closes_old_approval_and_explicit_resume_links_new_run(tmp_path):
    with Fixture() as fixture:
        fixture.responses.append(reply(name="write_project_file", arguments={"rel_path": "result.txt", "content": "旧意图"}))
        with RuntimeClient(tmp_path, fixture) as client:
            client.request("/identity/local", "POST")
            run = create(client, tmp_path / "project", "创建 result.txt")
            until(client, run["id"], {"waiting_approval"})
            approval = client.request(f"/agent-runs/{run['id']}/approvals")[0]
        assert not (tmp_path / "project/result.txt").exists()
        with RuntimeClient(tmp_path, fixture) as client:
            client.request("/identity/local", "POST")
            old = client.request(f"/agent-runs/{run['id']}")
            assert old["status"] in {"cancelled", "interrupted"}
            old_events = events(client, old)
            client.request(f"/agent-runs/{run['id']}/approvals/{approval['id']}/approve", "POST", expected=422)
            fixture.responses.extend([reply(name="write_project_file", arguments={"rel_path": "result.txt", "content": "新授权意图"}), reply("已写入文件。")])
            resumed = control(client, run["id"], "resume")["result_run_id"]
            assert resumed != run["id"]
            until(client, resumed, {"waiting_approval"})
            approval = client.request(f"/agent-runs/{resumed}/approvals")[0]
            client.request(f"/agent-runs/{resumed}/approvals/{approval['id']}/approve", "POST")
            final = until(client, resumed, {"completed", "failed"})
            assert final["goal_outcome"] == "verified"
            assert final["logical_task_id"] == run["id"] and final["loop_budget"]["model_requests"] >= 3
            assert events(client, client.request(f"/agent-runs/{run['id']}")) == old_events
            assert (tmp_path / "project/result.txt").read_text(encoding="utf-8") == "新授权意图"


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_synthetic_legacy_upgrade_keeps_unverified_history_and_backup(tmp_path, version):
    path = tmp_path / "account-one/projects.sqlite3"
    original = Store(path)
    project = original.create("project", {"name": "旧中文项目", "root_path": "old workspace"})
    message = original.create("message", {"session_id": 1, "content": "长输出" * INLINE_BYTES})
    for status in ("completed", "failed", "running", "waiting_approval"):
        original.save_run({"id": status, "status": status, "session_id": 1,
                           "events": [], "executions": [], "approvals": [], "output": "历史记录"})
    for added, tables in ((4, ("context_items", "context_checkpoints")),
                          (5, ("file_snapshots", "patch_sets", "patch_journal")),
                          (6, ("managed_executions", "execution_chunks")),
                          (7, ("run_checkpoints", "run_control_requests", "workspace_leases"))):
        if added > version:
            for table in tables:
                original.db.execute(f"DROP TABLE {table}")
    original.db.execute("DELETE FROM schema_migrations")
    original.db.execute(f"PRAGMA user_version={version}")
    original.db.commit()
    original.db.close()
    migrated = Store(path)
    try:
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert migrated.get("project", project["id"]) == project
        assert migrated.get("message", message["id"]) == message
        assert len(migrated.runs()) == 4
        assert migrated.run("completed").get("goal_outcome") is None
        migration = json.loads(migrated.db.execute("SELECT evidence FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)).fetchone()[0])
        backup = path.parent / migration["backup"]["filename"]
        assert digest(backup) == migration["backup"]["sha256"]
        with sqlite3.connect(backup) as saved:
            assert saved.execute("PRAGMA user_version").fetchone()[0] == version
            assert saved.execute("SELECT count(*) FROM runs").fetchone()[0] == 4
    finally:
        migrated.db.close()
    other = Store(tmp_path / "account-two/projects.sqlite3")
    try:
        assert not other.runs() and not other.list("project")
    finally:
        other.db.close()


def test_fact_review_is_bound_to_evidence_and_does_not_rewrite_attempts(tmp_path):
    plan = {"attempt_id": "one", "task_id": "PY01", "mode": "quality", "model": "local", "family": "python",
            "category": "bug", "split": "development", "coding_goal": True}
    evidence = Evidence(tmp_path, {"mode": "quality", "schedule": [plan], "product": {}})
    write_json(tmp_path / "artifacts/one.json", {"fixture": "已核对的原始事实"})
    hashes = {"artifacts/one.json": digest(tmp_path / "artifacts/one.json")}
    evidence.append({**plan, "started": True, "evidence_complete": True, "evidence_sha256": hashes,
                     "functional_passed": True, "validation_passed": True, "scope_preserved": True, "within_budget": True,
                     "model_identity_matches": True, "system_behavior_passed": True, "run_status": "completed", "goal_outcome": "verified"})
    evidence.finish()
    original_hash = digest(tmp_path / "attempts.jsonl")
    receipt = {"manifest_sha256": digest(tmp_path / "manifest.json"), "attempts_sha256": original_hash,
               "reviewer_role": "独立验收人员", "reviewed_at": "2026-09-09T12:00:00+08:00", "attempts": [
                   {"attempt_id": "one", "evidence_sha256": hashes, "report_matches_facts": True, "human_interventions": 0,
                    "constraints_satisfied": True, "note": "核对实现约束及最终文字与命令事实一致。"}]}
    write_json(tmp_path / "receipt.json", receipt)
    destination = review(tmp_path, tmp_path / "receipt.json")
    result = json.loads((destination / "metrics.json").read_text())
    assert result["models"]["local"]["overall"]["independent_completed"] == 1
    assert result["delivery_decision"] == "blocked" and digest(tmp_path / "attempts.jsonl") == original_hash
    (tmp_path / "artifacts/one.json").write_text("被修改", encoding="utf-8")
    with pytest.raises(ValueError, match="证据已改变"):
        review(tmp_path, tmp_path / "receipt.json")


def test_failed_preflight_records_every_unstarted_attempt(tmp_path, monkeypatch):
    import run_coding_acceptance as runner

    monkeypatch.setattr(runner, "preflight", lambda _tasks: {"passed": False, "missing": ["fixture-tool"]})
    result = runner.run(Namespace(mode="control", tasks="PY01", repetitions=3, protocol="service", model_config=None,
                                  bundle=None, work_dir=tmp_path))
    directory = next(tmp_path.glob("control-*"))
    attempts = [json.loads(line) for line in (directory / "attempts.jsonl").read_text().splitlines()]
    assert result == 1 and len(attempts) == 3 and all(row["started"] is False for row in attempts)
    assert json.loads((directory / "metrics.json").read_text())["integrity_passed"] is False


def termination_case(tmp_path, monkeypatch, scenario):
    import threading

    import run_coding_acceptance as runner

    entered, release = threading.Event(), threading.Event()
    requests = []
    final_approvals = []

    def scenario_script(_task):
        reading = reply(name="read_code_file", arguments={"rel_path": "src/domain.py"})
        reading["usage"] = {"input_tokens": 120001, "output_tokens": 20}
        writing = reply(name="write_project_file", arguments={"rel_path": "src/domain.py", "content": "不应落盘"})
        if scenario == "pending_approval":
            # 先完成真实读取，使写入预览满足版本绑定要求，再在待审批状态触发预算取消。
            reading["usage"] = {"input_tokens": 100, "output_tokens": 20}
            writing.update(usage={"input_tokens": 120001, "output_tokens": 20}, response_gate=(entered, release))
            return [reading, writing]
        if scenario in {"cancel_first", "cancel_response_lost", "runtime_after_cancel_requested"}:
            if scenario == "runtime_after_cancel_requested":
                # 第二个响应释放后校准到超出窗口；取消请求必须等真实终态落盘再进入。
                writing = reply(name="read_code_file", arguments={"rel_path": "src/domain.py"})
                writing["usage"] = {"input_tokens": 9999999, "output_tokens": 20}
            writing["response_gate"] = (entered, release)
            return [reading, writing]
        response = reading if scenario == "context_first" else writing
        response["response_gate"] = (entered, release)
        return [response]

    class ControlledFixture(Fixture):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if scenario in {"cancel_first", "cancel_response_lost", "runtime_after_cancel_requested"}:
                self.context_tokens = 1_000_000

    class ControlledClient(RuntimeClient):
        synchronized = False

        def wait_status(self, run_id, statuses=runner.TERMINAL):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                current = super().request(f"/agent-runs/{run_id}")
                if current["status"] in statuses:
                    return current
                time.sleep(0.01)
            pytest.fail(f"同步点未观察到预期状态 {statuses}，实际为 {current['status']} / {current.get('error_code')}")

        def request(self, path, method="GET", body=None, **kwargs):
            requests.append((path, method))
            if path == "/agent-runs" and method == "POST" and scenario == "runtime_timeout_first":
                body = {**body, "context_limits": {**body["context_limits"], "max_active_seconds": 1}}
            if method == "GET" and path.startswith("/agent-runs/") and path.count("/") == 2 and not self.synchronized:
                self.synchronized = True
                assert entered.wait(10), "模型请求未到达受控响应门闩"
                if scenario == "context_first":
                    release.set()
                    assert self.wait_status(path.rsplit("/", 1)[1])["status"] == "limit_exceeded"
                elif scenario == "pending_approval":
                    release.set()
                    assert self.wait_status(path.rsplit("/", 1)[1], {"waiting_approval"})["status"] == "waiting_approval"
                elif scenario == "runtime_timeout_first":
                    assert self.wait_status(path.rsplit("/", 1)[1])["error_code"] == "max_active_seconds"
                elif scenario == "user_cancel_first":
                    super().request(path + "/cancel", "POST")
                    assert self.wait_status(path.rsplit("/", 1)[1])["status"] == "cancelled"
            if path.endswith("/cancel") and method == "POST" and scenario == "runtime_after_cancel_requested":
                release.set()
                assert self.wait_status(path.split("/")[2])["status"] == "limit_exceeded"
            result = super().request(path, method, body, **kwargs)
            if method == "GET" and path.startswith("/agent-runs/") and path.count("/") == 2 and result["status"] in runner.TERMINAL:
                final_approvals.append(super().request(path + "/approvals"))
            if path.endswith("/cancel") and method == "POST" and scenario == "cancel_response_lost":
                raise TimeoutError("已执行取消，但评测客户端丢失回执")
            return result

    monkeypatch.setattr(runner, "script", scenario_script)
    monkeypatch.setattr(runner, "Fixture", ControlledFixture)
    monkeypatch.setattr(runner, "RuntimeClient", ControlledClient)
    if scenario == "evaluator_timeout_first":
        monkeypatch.setattr(runner, "ATTEMPT_TIMEOUT_SECONDS", 0)
    result = runner.run(Namespace(mode="control", tasks="PY01", repetitions=1, protocol="service", model_config=None,
                                  bundle=None, work_dir=tmp_path))
    directory = next(tmp_path.glob("control-*"))
    row = json.loads((directory / "attempts.jsonl").read_text())
    assert row["failure_class"] != "runner_error", row
    artifacts = json.loads((directory / "artifacts/service-PY01-1.json").read_text())
    history = json.loads((directory / "events/service-PY01-1.json").read_text())
    assert result == 1, row
    assert row["evidence_complete"] is True and row["event_integrity_errors"] == []
    assert row["scope_preserved"] is True and artifacts["before"] == artifacts["after"]
    assert row["approvals"] == 0 and final_approvals
    if scenario == "pending_approval":
        assert all(len(items) == 1 and items[0]["status"] == "cancelled" for items in final_approvals)
        assert sum(event["type"] == "tool.approval_required" for event in history) == 1
        assert [item["tool_name"] for item in artifacts["executions"]] == ["read_code_file", "write_project_file"]
    else:
        assert all(items == [] for items in final_approvals)
        assert not any(event["type"] == "tool.approval_required" for event in history)
        assert all(item["tool_name"] == "read_code_file" for item in artifacts["executions"])
    assert not any("/approvals/" in path or path.endswith(("/resume", "/pause")) for path, _method in requests)
    assert history[-1]["type"] == "run." + row["run_status"]
    assert not json.loads((directory / "metrics.json").read_text())["runner_errors"]
    assert row["elapsed_seconds"] < 30, row
    return row, requests


@pytest.mark.parametrize("response_lost", [False, True])
def test_token_budget_cancels_without_replaying_or_approving_tools(tmp_path, monkeypatch, response_lost):
    row, requests = termination_case(tmp_path, monkeypatch, "cancel_response_lost" if response_lost else "cancel_first")
    assert row["run_status"] == "cancelled" and row["run_error_code"] == "cancelled", row
    assert row["failure_class"] == "budget_exhausted" and row["within_budget"] is False
    assert len(row["model_protocol_calls"]) == 2 and row["tool_calls"] == 1
    assert row["termination"]["cancel_response"] == ("unknown" if response_lost else "accepted")
    assert row["termination"]["terminal_observed"] is True
    assert sum(path.endswith("/cancel") for path, _method in requests) == 1


@pytest.mark.parametrize("scenario,code,failure", [
    ("context_first", "context_limit", "budget_exhausted"),
    ("runtime_timeout_first", "max_active_seconds", "runtime_timeout"),
])
def test_ipc_runtime_limit_finishes_before_evaluator_cancel(tmp_path, monkeypatch, scenario, code, failure):
    row, requests = termination_case(tmp_path, monkeypatch, scenario)
    assert row["run_status"] == "limit_exceeded" and row["run_error_code"] == code, row
    assert row["failure_class"] == failure and row["within_budget"] is False
    assert row["termination"]["cancel_requested"] is False and row["termination"]["stop_reason"] is None
    assert len(row["model_protocol_calls"]) == 1
    assert not any(path.endswith("/cancel") for path, _method in requests)


def test_ipc_runtime_wins_after_budget_cancel_decision(tmp_path, monkeypatch):
    row, requests = termination_case(tmp_path, monkeypatch, "runtime_after_cancel_requested")
    assert row["run_status"] == "limit_exceeded" and row["run_error_code"] == "context_limit", row
    assert row["failure_class"] == "budget_exhausted"
    assert row["termination"]["stop_reason"] == "budget_exhausted"
    assert row["termination"]["cancel_response"] == "not_accepted"
    assert len(row["model_protocol_calls"]) == 2
    assert sum(path.endswith("/cancel") for path, _method in requests) == 1


def test_ipc_evaluator_timeout_is_distinct_from_user_cancel(tmp_path, monkeypatch):
    row, requests = termination_case(tmp_path, monkeypatch, "evaluator_timeout_first")
    assert row["run_status"] == "cancelled" and row["failure_class"] == "attempt_timeout", row
    assert row["termination"]["stop_reason"] == "attempt_timeout"
    assert row["termination"]["cancel_response"] == "accepted"
    assert len(row["model_protocol_calls"]) == 1 and row["tool_calls"] == 0
    assert sum(path.endswith("/cancel") for path, _method in requests) == 1


def test_ipc_user_cancel_is_not_attributed_to_evaluator(tmp_path, monkeypatch):
    row, requests = termination_case(tmp_path, monkeypatch, "user_cancel_first")
    assert row["run_status"] == "cancelled" and row["failure_class"] == "user_cancelled", row
    assert row["termination"]["stop_reason"] is None and not row["termination"]["cancel_requested"]
    assert len(row["model_protocol_calls"]) == 1 and row["tool_calls"] == 0
    assert not any(path.endswith("/cancel") for path, _method in requests)


def test_ipc_budget_cancel_closes_pending_approval_without_consuming_it(tmp_path, monkeypatch):
    row, requests = termination_case(tmp_path, monkeypatch, "pending_approval")
    assert row["run_status"] == "cancelled" and row["failure_class"] == "budget_exhausted", row
    assert row["termination"]["cancel_response"] == "accepted"
    assert len(row["model_protocol_calls"]) == 2 and row["tool_calls"] == 2
    assert sum(path.endswith("/cancel") for path, _method in requests) == 1


def test_judge_rejects_self_modification_and_bounds_output(tmp_path):
    import sys

    from coding_acceptance_catalog import (
        execute,
        judge,
        load_catalog,
        rebuild,
        storage_usage,
    )
    from run_coding_validation import isolated_environment

    task = load_catalog()["tasks"][0]
    project = tmp_path / "project"
    (tmp_path / "tmp").mkdir()
    before = rebuild(task, project)
    (project / "src/domain.py").write_text("from pathlib import Path\nPath(__file__).write_text('broken', encoding='utf-8')\n" + task["reference_files"]["src/domain.py"], encoding="utf-8")
    assert judge(task, project, tmp_path, before)["reason"] == "validation_changed_files"
    result = execute([sys.executable, "-c", "import time; print('x'*100000,flush=True); time.sleep(20)"], project, isolated_environment(tmp_path), timeout=1)
    assert result["passed"] is False and result["reason"] == "judge_output_quota"
    with pytest.raises(ValueError, match="配额"):
        storage_usage(tmp_path, max_bytes=1)


@pytest.mark.parametrize("disappearing", ["file", "directory", "directory_listing"])
def test_storage_sampling_tolerates_removed_compiler_outputs(tmp_path, monkeypatch, disappearing):
    from pathlib import Path

    from coding_acceptance_catalog import storage_usage

    (tmp_path / "kept").write_bytes(b"123")
    removed = tmp_path / "removed"
    if disappearing == "file":
        removed.write_bytes(b"temporary")
    else:
        removed.mkdir()
    original_stat, original_iterdir = Path.lstat, Path.iterdir
    observations = 0

    def transient_stat(path):
        nonlocal observations
        if path == removed:
            observations += 1
            if disappearing == "file" or disappearing == "directory" and observations == 2:
                raise FileNotFoundError("编译中间文件已删除")
        return original_stat(path)

    def transient_iterdir(path):
        if path == removed and disappearing == "directory_listing":
            raise FileNotFoundError("编译中间目录已删除")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "lstat", transient_stat)
    monkeypatch.setattr(Path, "iterdir", transient_iterdir)
    assert storage_usage(tmp_path) == 3


@pytest.mark.parametrize("failure", ["permission", "link"])
def test_storage_sampling_still_rejects_links_and_permission_errors(tmp_path, monkeypatch, failure):
    import stat
    from pathlib import Path
    from types import SimpleNamespace

    from coding_acceptance_catalog import storage_usage

    target = tmp_path / "target"
    target.write_bytes(b"x")
    original_stat = Path.lstat

    def invalid_stat(path):
        if path == target:
            if failure == "permission":
                raise PermissionError("资源不可读")
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_size=1)
        return original_stat(path)

    monkeypatch.setattr(Path, "lstat", invalid_stat)
    with pytest.raises(PermissionError if failure == "permission" else ValueError):
        storage_usage(tmp_path)


@pytest.mark.parametrize("destination,location", [("IE", "profile"), ("outside", "profile"), ("IE", "project")])
def test_storage_sampling_only_skips_known_profile_cache_alias(tmp_path, monkeypatch, destination, location):
    import stat
    from pathlib import Path
    from types import SimpleNamespace

    from coding_acceptance_catalog import storage_usage

    parent = tmp_path / ("home/AppData/Local/Microsoft/Windows/INetCache" if location == "profile" else "project")
    alias = parent / "Content.IE5"
    alias.mkdir(parents=True)
    (parent / "IE").mkdir()
    (parent / "IE/cache").write_bytes(b"123")
    original_stat, original_resolve = Path.lstat, Path.resolve

    def alias_stat(path):
        return (SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
                                st_reparse_tag=stat.IO_REPARSE_TAG_MOUNT_POINT) if path == alias else original_stat(path))

    def alias_resolve(path, strict=False):
        if path == alias:
            return parent / "IE" if destination == "IE" else tmp_path.parent
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "lstat", alias_stat)
    monkeypatch.setattr(Path, "resolve", alias_resolve)
    if destination == "IE" and location == "profile":
        assert storage_usage(tmp_path) == 3
    else:
        with pytest.raises(ValueError, match="链接"):
            storage_usage(tmp_path)
