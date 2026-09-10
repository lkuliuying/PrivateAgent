"""阶段 B：严格清单、独立比较、泄露探针及不可覆盖的尝试记录。"""
import json
import os
import shutil
import subprocess
import time
from argparse import Namespace

import pytest
from coding_acceptance_catalog import judge, load_catalog, preflight, rebuild, snapshot
from coding_acceptance_evidence import (
    Evidence,
    aggregate,
    digest,
    independent,
    verify_ledger,
)
from coding_acceptance_judge import permission_probe
from coding_acceptance_schema import (
    assessment_for,
    fingerprint,
    plain_path,
    safe_relative,
    verify_catalog,
)
from coding_acceptance_transport import Fixture, RuntimeClient, reply
from run_coding_validation import ROOT

PUBLIC = ROOT / "tests/coding_acceptance/external_public/catalog.json"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def copy_catalog(tmp_path):
    destination = tmp_path / "dataset"
    shutil.copytree(PUBLIC.parent, destination)
    return destination / "catalog.json"


def change_assessment(path, callback):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    assessment_path = path.parent / catalog["assessment"]["path"]
    data = json.loads(assessment_path.read_text(encoding="utf-8"))
    callback(data["tasks"]["PY01"])
    save(assessment_path, data)
    catalog["assessment"]["sha256"] = digest(assessment_path)
    save(path, catalog)


def test_external_distribution_and_public_identity():
    catalog = load_catalog(PUBLIC)
    assert len(catalog["tasks"]) == 30 and not catalog["blind_quality_eligible"]
    assert catalog["catalog_source"] == "external_json"
    assert sum(task["split"] == "development" for task in catalog["tasks"]) == 18
    assert sum(task["coding_goal"] for task in catalog["tasks"]) == 27
    assert all("reference_files" not in task and "cases" not in task for task in catalog["tasks"])
    assert preflight(catalog["tasks"])["passed"]


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(tasks=[]),
    lambda data: data.update(tasks=[data["tasks"][0]] * 30),
    lambda data: data.update(schema_version=True),
    lambda data: data.update(module="untrusted_config"),
    lambda data: data.pop("version"),
    lambda data: data.update(repetitions=True),
    lambda data: data.update(quality_target=1),
    lambda data: data["tasks"][0].pop("source"),
    lambda data: data["tasks"][0].update(license=""),
    lambda data: data["tasks"][0].update(coding_goal=1),
    lambda data: data["tasks"][0].update(family=[]),
    lambda data: data["tasks"][0].update(split="test"),
    lambda data: data["tasks"][0].update(holdout_exposure="unexposed"),
    lambda data: data["tasks"][0].update(validation_command=["python", "-m", "untrusted"]),
    lambda data: data["tasks"][0].update(editable_files=["user-notes.txt"]),
    lambda data: data["tasks"][0].update(editable_files=["src/domain.py", "src/domain.py"]),
    lambda data: data["tasks"][0]["budget"].update(max_model_requests=True),
    lambda data: data["tasks"][0]["budget"].update(max_active_seconds=601),
    lambda data: data["tasks"][0]["files"].update({"../escape": "unsafe"}),
    lambda data: data["tasks"][0]["files"].update({"src/DOMAIN.py": "unsafe"}),
    lambda data: data["tasks"][0]["files"].update({".git/config": "unsafe"}),
    lambda data: data["tasks"][0]["files"].update({"src/domain.py/nested": "unsafe"}),
    lambda data: data["tasks"][0]["files"].update({"src/domain.py": "changed"}),
    lambda data: data["tasks"][0].update(source_revision="0" * 64),
    lambda data: data["assessment"].update(path="../assessment.json"),
    lambda data: data["assessment"].update(sha256="0" * 64),
])
def test_strict_external_manifest_rejects_invalid_data(tmp_path, mutation):
    path = copy_catalog(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    mutation(data)
    save(path, data)
    with pytest.raises(ValueError):
        load_catalog(path)
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("body", ["", "[]", '{"version":1,"version":2}', '{"value":NaN}', "null"])
def test_invalid_or_duplicate_json_never_imports_modules(tmp_path, body):
    path = tmp_path / "catalog.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        load_catalog(path)


@pytest.mark.parametrize("name", ["", ".", "..", "a/../b", "/absolute", "C:/x", "a\\b", "a//b", "a/./b",
                                 "a/", "a.txt:stream", "NUL", "aux.py", "COM1.txt", "x. ", "a./x", "a\nb"])
def test_windows_and_traversal_aliases_rejected(name):
    with pytest.raises(ValueError):
        safe_relative(name)


@pytest.mark.parametrize("mutation", [
    lambda item: item.update(module="untrusted"),
    lambda item: item.update(cases=[]),
    lambda item: item.update(cases=[[1]]),
    lambda item: item.update(timeout_seconds=0),
    lambda item: item.update(output_bytes=64001),
    lambda item: item.update(reference_files={"../outside.py": "unsafe"}),
    lambda item: item.update(forbidden_fragments={"user-notes.txt": ["x"]}),
    lambda item: item.update(exception_cases=[{"input": 1, "error": "SystemExit"}]),
])
def test_strict_assessment_rejects_invalid_data(tmp_path, mutation):
    path = copy_catalog(tmp_path)
    change_assessment(path, mutation)
    with pytest.raises(ValueError):
        load_catalog(path)


@pytest.mark.parametrize("location", ["catalog", "assessment"])
def test_frozen_source_and_assessment_changes_rejected(tmp_path, location):
    path = copy_catalog(tmp_path)
    catalog = load_catalog(path)
    target = path if location == "catalog" else path.parent / "assessment.json"
    with target.open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="摘要变化"):
        verify_catalog(catalog)


def test_real_directory_link_and_hardlink_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "project"
    root.mkdir()
    alias = root / "target"
    if os.name == "nt":
        subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(outside)],
                       check=True, capture_output=True, timeout=10)
    else:
        alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        snapshot(root)
    with pytest.raises(ValueError):
        plain_path(alias)
    original = outside / "source.json"
    original.write_text("{}")
    hardlink = tmp_path / "linked.json"
    os.link(original, hardlink)
    with pytest.raises(ValueError):
        load_catalog(hardlink)
    assert original.read_text() == "{}"


def test_cargo_internal_hardlinks_allowed_but_external_alias_rejected(tmp_path):
    project = tmp_path / "project"
    target = project / "target/debug"
    target.mkdir(parents=True)
    artifact = target / "library.rlib"
    artifact.write_bytes(b"synthetic cargo artifact")
    os.link(artifact, target / "library-hash.rlib")
    assert snapshot(project) == {}
    os.link(artifact, tmp_path / "external-library.rlib")
    with pytest.raises(ValueError, match="工作区外"):
        snapshot(project)


@pytest.mark.parametrize("task", load_catalog(PUBLIC)["tasks"], ids=lambda task: task["id"])
def test_external_initial_reference_wrong_and_user_protection(tmp_path, task):
    project = tmp_path / "project"
    before = rebuild(task, project)
    assessment = assessment_for(task)
    assert not judge(task, project, tmp_path, before)["passed"]
    assert all("assessment" not in name and "observe" not in name for name in before)
    for name, content in assessment["reference_files"].items():
        (project / name).write_text(content, encoding="utf-8", newline="\n")
    result = judge(task, project, tmp_path, before)
    assert result["passed"], result
    assert result["binding"]["candidate_sha256"] == fingerprint(snapshot(project))
    assert result["binding"]["assessment_sha256"] == task["assessment_sha256"]
    target = project / task["editable_files"][0]
    wrong = {"python": "def solve(value):\n    return None\n",
             "vue-typescript": "export function solve(value:any):any { return null; }\n",
             "rust": "pub fn solve(_values:&[i64])->Vec<i64>{vec![999]}\n"}[task["family"]]
    target.write_text(wrong, encoding="utf-8")
    assert not judge(task, project, tmp_path, before)["passed"]
    for name, content in assessment["reference_files"].items():
        (project / name).write_text(content, encoding="utf-8", newline="\n")
    (project / "user-notes.txt").write_text("被覆盖", encoding="utf-8")
    assert judge(task, project, tmp_path, before)["reason"] == "user_work_changed"


@pytest.mark.parametrize("attack,reason", [
    ("print('SYNTHETIC_PRIVATE_MARKER')", "invalid_candidate_output"),
    ("import sys\nfrom pathlib import Path\nPath(sys.argv[0]).write_text('changed')", "judge_changed_during_validation"),
    ("print('x'*128000)", "judge_output_quota"),
    ("import time\ntime.sleep(5)", "judge_timeout"),
    ("from pathlib import Path\nPath('src/domain.py').write_text('changed')", "validation_changed_files"),
])
def test_judge_output_timeout_self_modification_and_log_boundary(tmp_path, attack, reason):
    path = copy_catalog(tmp_path)
    if reason == "judge_timeout":
        change_assessment(path, lambda item: item.update(timeout_seconds=0.1))
    task = load_catalog(path)["tasks"][0]
    project = tmp_path / "project"
    before = rebuild(task, project)
    (project / "src/domain.py").write_text(attack + "\ndef solve(value):\n    return list(dict.fromkeys(value))\n", encoding="utf-8")
    started = time.monotonic()
    result = judge(task, project, tmp_path, before)
    assert not result["passed"] and result["reason"] == reason, result
    assert "SYNTHETIC_PRIVATE_MARKER" not in json.dumps(result)
    assert "output" not in result and "command" not in result
    assert time.monotonic() - started < 5


def test_judge_rejects_assessment_modification_by_candidate(tmp_path):
    path = copy_catalog(tmp_path)
    task = load_catalog(path)["tasks"][0]
    project = tmp_path / "project"
    before = rebuild(task, project)
    (project / "src/domain.py").write_text(
        f"from pathlib import Path\nPath({task['assessment_path']!r}).write_text('{{}}')\n"
        "def solve(value):\n    return list(dict.fromkeys(value))\n", encoding="utf-8")
    assert judge(task, project, tmp_path, before)["reason"] == "judge_changed_during_validation"


def args(directory, **values):
    return Namespace(mode="preflight", tasks="PY01", repetitions=1, protocol="service", model_config=None,
                     bundle=None, work_dir=directory, catalog=values.pop("catalog", PUBLIC), **values)


def test_external_preflight_uses_external_end_hash_and_records_permissions(tmp_path):
    import run_coding_acceptance as runner

    assert runner.run(args(tmp_path)) == 0
    directory = next(tmp_path.glob("preflight-*"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["catalog_sha256"] == digest(PUBLIC)
    assert manifest["isolation"]["verified"] is False
    assert manifest["isolation"]["probe"]["readable"] is True
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["delivery_decision"] == "blocked" and not metrics["experiment_complete"]


def test_independent_claim_cannot_bypass_missing_execution_isolation(tmp_path):
    import run_coding_acceptance as runner

    path = copy_catalog(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["purpose"] = "independent_evaluation"
    for task in data["tasks"]:
        task["holdout_exposure"] = "unexposed"
    save(path, data)
    assert runner.run(args(tmp_path, catalog=path)) == 1
    directory = next(tmp_path.glob("preflight-*"))
    rows = [json.loads(line) for line in (directory / "attempts.jsonl").read_text().splitlines()]
    assert all(not row["started"] for row in rows)
    assert not (directory / "starts.jsonl").read_text()


def test_external_final_check_detects_change_after_preflight(tmp_path, monkeypatch):
    import run_coding_acceptance as runner

    path = copy_catalog(tmp_path)
    def mutate(_tasks):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(" ")
        return {"passed": True, "missing": []}
    monkeypatch.setattr(runner, "preflight", mutate)
    assert runner.run(args(tmp_path, catalog=path)) == 1
    metrics = json.loads(next(tmp_path.glob("preflight-*/metrics.json")).read_text(encoding="utf-8"))
    assert "catalog_or_assessment_changed_during_experiment" in metrics["runner_errors"]


def plan(identity="one", **values):
    return {"attempt_id": identity, "task_id": "PY01", "model": "selected", "mode": "quality",
            "coding_goal": True, "family": "python", "category": "bug", "split": "holdout",
            "holdout_exposure": "unexposed", "binding": {"catalog_sha256": "frozen"}, **values}


def test_missing_dependency_blocks_external_attempts(tmp_path, monkeypatch):
    import run_coding_acceptance as runner

    monkeypatch.setattr(runner, "preflight", lambda _tasks: {"passed": False, "missing": ["pytest"]})
    options = args(tmp_path)
    options.mode = "control"
    options.repetitions = 3
    assert runner.run(options) == 1
    directory = next(tmp_path.glob("control-*"))
    rows = [json.loads(line) for line in (directory / "attempts.jsonl").read_text().splitlines()]
    assert len(rows) == 3 and all(not row["started"] for row in rows)
    assert not (directory / "starts.jsonl").read_text()


def test_rebuild_keeps_frozen_files_and_never_overwrites_existing_workspace(tmp_path):
    task = load_catalog(PUBLIC)["tasks"][0]
    project = tmp_path / "project"
    before = rebuild(task, project)
    assert all(before[name] == sha for name, sha in task["file_sha256"].items())
    with pytest.raises(ValueError):
        rebuild(task, project)
    assert snapshot(project) == before


@pytest.mark.parametrize("task_id,wrong", [
    ("PY01", "def solve(value):\n    return [3,1,2]\n"),
    ("VT01", "export function solve(value:any):any { return [3,1]; }\n"),
    ("RS01", "pub fn solve(_values:&[i64])->Vec<i64>{vec![3,1,2]}\n"),
])
def test_public_case_only_implementation_fails_independent_comparison(tmp_path, task_id, wrong):
    task = next(task for task in load_catalog(PUBLIC)["tasks"] if task["id"] == task_id)
    project = tmp_path / "project"
    before = rebuild(task, project)
    (project / task["editable_files"][0]).write_text(wrong, encoding="utf-8")
    assert judge(task, project, tmp_path, before)["reason"] == "assertion_failed"


def test_expected_values_and_references_are_absent_from_observer(tmp_path):
    from coding_acceptance_judge import observer

    task = load_catalog(PUBLIC)["tasks"][0]
    private_expected = "SYNTHETIC_EXPECTED_ONLY_ON_ASSESSMENT_SIDE"
    project = tmp_path / "project"
    rebuild(task, project)
    source, command, expected = observer(task, [[[], private_expected]], project, tmp_path)
    assert private_expected not in source.read_text(encoding="utf-8")
    assert private_expected not in " ".join(command)
    assert private_expected in json.dumps(expected)


def test_isolated_python_keeps_unicode_outputs(tmp_path):
    path = copy_catalog(tmp_path)
    change_assessment(path, lambda item: item["cases"].append([["中文", "🙂", "中文"], ["中文", "🙂"]]))
    task = load_catalog(path)["tasks"][0]
    project = tmp_path / "project"
    before = rebuild(task, project)
    for name, content in assessment_for(task)["reference_files"].items():
        (project / name).write_text(content, encoding="utf-8")
    assert judge(task, project, tmp_path, before)["passed"]


def test_two_reruns_keep_separate_attempt_records(tmp_path):
    import run_coding_acceptance as runner

    assert runner.run(args(tmp_path)) == 0
    first = next(tmp_path.glob("preflight-*"))
    before = digest(first / "attempts.jsonl")
    assert runner.run(args(tmp_path)) == 0
    directories = list(tmp_path.glob("preflight-*"))
    assert len(directories) == 2 and digest(first / "attempts.jsonl") == before
    assert {json.loads((path / "manifest.json").read_text(encoding="utf-8"))["experiment_id"] for path in directories} == {path.name for path in directories}


def test_started_failure_and_pollution_cannot_shrink_frozen_denominator():
    schedule = [plan(), plan("failed"), plan("preflight")]
    rows = [{**schedule[0], "started": True, "coding_goal": False},
            {**schedule[1], "started": True, "failure_class": "runtime_failed", "human_interventions": 1},
            {**schedule[2], "started": False, "failure_class": "missing_dependency"}]
    result = aggregate(rows, schedule)
    assert not result["integrity_passed"]
    assert result["models"]["selected"]["overall"]["coding_denominator"] == 2
    assert result["models"]["selected"]["overall"]["not_started"] == 1
    assert not independent({**rows[0], "holdout_exposure": "contaminated"})


def test_start_ledger_preserves_crash_and_rejects_overwriting(tmp_path):
    item = plan()
    evidence = Evidence(tmp_path, {"mode": "quality", "schedule": [item], "product": {},
                                   "statistics_version": "s6-attempt-ledger-1"})
    evidence.start(item)
    persisted = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert persisted["models"]["selected"]["overall"]["coding_denominator"] == 1
    metrics = evidence.finish()
    assert metrics["models"]["selected"]["overall"]["coding_denominator"] == 1
    assert "unfinished_started_attempt" in metrics["runner_errors"]
    with pytest.raises(ValueError):
        evidence.start(item)
    evidence.append({**item, "started": True, "failure_class": "runtime_failed"})
    saved = digest(tmp_path / "attempts.jsonl")
    with pytest.raises(ValueError):
        evidence.append({**item, "started": True})
    assert saved == digest(tmp_path / "attempts.jsonl")
    evidence.finish()
    assert evidence.finish()["experiment_complete"] is False
    verify_ledger(tmp_path, evidence.manifest, evidence.rows)
    with pytest.raises(ValueError):
        verify_ledger(tmp_path, evidence.manifest, [{**evidence.rows[0], "started": False}])


def test_detected_contamination_cannot_be_reset_by_frozen_plan():
    item = plan()
    row = {**item, "started": True, "human_interventions": 0, "run_status": "completed", "goal_outcome": "verified",
           "functional_passed": True, "scope_preserved": True, "validation_passed": True, "report_matches_facts": True,
           "within_budget": True, "evidence_complete": True, "reviewed_constraints": True, "model_identity_matches": True,
           "system_behavior_passed": True}
    assert independent(row)
    row["holdout_exposure"] = "contaminated"
    metrics = aggregate([row], [item])
    assert not metrics["integrity_passed"]
    summary = metrics["models"]["selected"]["overall"]
    assert summary["coding_denominator"] == 1 and summary["independent_completed"] == 0
    assert summary["contaminated_started"] == 1


def test_review_rejects_rebound_candidate_artifact(tmp_path):
    from coding_acceptance_review import review

    item = plan()
    evidence = Evidence(tmp_path, {"mode": "quality", "schedule": [item], "product": {},
                                   "statistics_version": "s6-attempt-ledger-1"})
    evidence.start(item)
    artifact = tmp_path / "artifacts/one.json"
    save(artifact, {"binding": {"catalog_sha256": "different"}, "candidate_sha256": "candidate"})
    hashes = {"artifacts/one.json": digest(artifact)}
    evidence.append({**item, "started": True, "evidence_complete": True, "evidence_sha256": hashes,
                     "candidate_sha256": "candidate", "human_interventions": 0})
    evidence.finish()
    receipt = {"manifest_sha256": digest(tmp_path / "manifest.json"), "attempts_sha256": digest(tmp_path / "attempts.jsonl"),
               "reviewer_role": "测试验收角色", "reviewed_at": "2026-09-10T00:00:00+08:00", "attempts": [{
                   "attempt_id": "one", "evidence_sha256": hashes, "report_matches_facts": True,
                   "human_interventions": 0, "constraints_satisfied": True, "note": "验证候选绑定不可替换。"}]}
    save(tmp_path / "receipt.json", receipt)
    with pytest.raises(ValueError, match="候选产物"):
        review(tmp_path, tmp_path / "receipt.json")


def test_actual_ipc_read_and_trusted_command_exposure(tmp_path):
    from run_coding_acceptance import events

    project = tmp_path / "project"
    project.mkdir()
    private = tmp_path / "assessment-canary.txt"
    private.write_text("SYNTHETIC_PRIVATE_CANARY", encoding="utf-8")
    (project / "public.txt").write_text("PUBLIC_READ_ALLOWED", encoding="utf-8")
    probe = permission_probe(private, tmp_path)
    program = ("import hashlib,os,subprocess;from pathlib import Path;"
               "identity=subprocess.check_output(['whoami','/user','/fo','csv','/nh']) if os.name=='nt' else str(os.geteuid()).encode();"
               "print('IDENTITY_SHA256='+hashlib.sha256(identity).hexdigest());"
               f"print(Path({str(private)!r}).read_text())")
    (project / "probe.py").write_text(program, encoding="utf-8")
    with Fixture() as fixture:
        fixture.responses.extend([
            reply(name="read_code_file", arguments={"rel_path": "../assessment-canary.txt"}),
            reply(name="read_code_file", arguments={"rel_path": "public.txt"}),
            reply(name="exec_command", arguments={"argv": ["python", "-I", "-B", "probe.py"],
                  "yield_time_ms": 30000, "timeout_ms": 60000, "execution_mode": "trusted_project", "network_policy": "approved"}),
            reply("探针结束。"),
        ])
        with RuntimeClient(tmp_path, fixture) as client:
            client.request("/identity", "POST")
            info = client.request("/projects", "POST", {"name": "隔离探针", "root_path": str(project)})
            workspace = client.request(f"/projects/{info['id']}/workspaces")[0]
            binding = {"project_id": info["id"], "workspace_id": workspace["id"]}
            session = client.request("/sessions", "POST", {**binding, "title": "隔离探针"})
            run = client.request("/agent-runs", "POST", {**binding, "session_id": session["id"], "message": "执行合成权限探针",
                                 "model_profile_id": "s6-profile", "execution_contract_version": "1.0"})
            deadline = time.monotonic() + 20
            approval_seen = False
            while time.monotonic() < deadline:
                run = client.request(f"/agent-runs/{run['id']}")
                if run["status"] == "waiting_approval":
                    history = json.dumps(client.request(f"/agent-runs/{run['id']}/executions"), ensure_ascii=False)
                    assert "SYNTHETIC_PRIVATE_CANARY" not in history
                    assert "PUBLIC_READ_ALLOWED" in history
                    for approval in client.request(f"/agent-runs/{run['id']}/approvals"):
                        if approval["status"] == "pending":
                            assert not approval_seen
                            approval_seen = True
                            client.request(f"/agent-runs/{run['id']}/approvals/{approval['id']}/approve", "POST")
                if run["status"] in {"completed", "failed", "cancelled", "limit_exceeded", "timed_out", "interrupted"}:
                    break
                time.sleep(0.05)
            assert approval_seen and run["status"] == "completed", (run["status"], run.get("error_code"))
            execution = json.dumps(client.request(f"/agent-runs/{run['id']}/executions"), ensure_ascii=False)
            assert "SYNTHETIC_PRIVATE_CANARY" in execution
            assert probe["probe"]["identity_sha256"] in execution
            assert not probe["verified"]
            history = events(client, run)
            assert any(item["type"] == "tool.failed" and item["payload"]["name"] == "read_code_file" for item in history)
            save(tmp_path / "ipc-isolation.json", {"identity_sha256": probe["probe"]["identity_sha256"],
                 "same_identity": True, "read_tool_traversal_denied": True, "public_read_passed": True,
                 "trusted_command_read_private_canary": True, "command_log_contains_canary": True, "isolation_verified": False})
