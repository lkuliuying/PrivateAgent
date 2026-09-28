"""回执绑定与污染登记的合成契约测试；合成角色不构成真实独立验收。"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from coding_acceptance_catalog import load_catalog
from coding_acceptance_dataset import (
    append_record,
    control_passed,
    judge_identity,
    record_contamination,
    verify_custody,
    write_new,
)
from coding_acceptance_schema import file_hash
from run_coding_validation import ROOT


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def receipt_fixture(tmp_path, *, copied_public=False):
    dataset = tmp_path / "data"
    shutil.copytree(ROOT / "tests/coding_acceptance/external_public", dataset)
    catalog_path = dataset / "catalog.json"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    data["purpose"] = "independent_evaluation"
    for task in data["tasks"]:
        task["holdout_exposure"] = "unexposed"
        if not copied_public:
            task["files"]["README.md"] += "\n合成契约测试版本，不作为正式题集。\n"
            task["file_sha256"]["README.md"] = hashlib.sha256(task["files"]["README.md"].encode()).hexdigest()
            task["source_revision"] = hashlib.sha256(json.dumps(task["files"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    save(catalog_path, data)
    catalog = load_catalog(catalog_path)
    identity = judge_identity()
    checks, previous = [], None
    ledger = tmp_path / "qualification-attempts.jsonl"
    for task in catalog["tasks"]:
        controls = {}
        for control in ("initial", "reference", "wrong", "protected"):
            binding = {"task_id": task["id"], "task_sha256": task["task_sha256"], "control": control, "candidate_sha256": "a" * 64}
            previous = append_record(ledger, {**binding, "status": "started"}, previous)
            path = tmp_path / f"{task['id']}-{control}.json"
            reason = None if control == "reference" else "user_work_changed" if control == "protected" else "assertion_failed"
            write_new(path, {"passed": control == "reference", "scope_preserved": control != "protected",
                             "reason": reason, "isolation_verified": control != "protected",
                             "binding": {"task_sha256": task["task_sha256"], "candidate_sha256": binding["candidate_sha256"],
                                         "assessment_sha256": catalog["assessment"]["sha256"]},
                             "verifier_sha256": identity["coding_acceptance_judge.py"]})
            row = {**binding, "status": "finished", "accepted": True, "verdict_sha256": file_hash(path), "verdict_path": path.name, "reason": reason}
            previous = append_record(ledger, row, previous)
            controls[control] = row
        checks.append({"task_id": task["id"], "task_sha256": task["task_sha256"], "passed": True, "controls": controls})
    qualification = {"schema_version": 1, "catalog_sha256": catalog["catalog_sha256"], "assessment_sha256": catalog["assessment"]["sha256"],
                     "judge_sha256": identity, "created_at": "2026-09-10T00:00:00+08:00", "checks": checks,
                     "isolation": {"verified": True}, "runtime_sha256": {}, "ledger_sha256": file_hash(ledger),
                     "passed": True, "blind_quality_eligible": False, "independence": "requires_separate_curator_receipt"}
    write_new(tmp_path / "qualification.json", qualification)
    write_new(tmp_path / "contamination.json", {"schema_version": 1, "catalog_sha256": catalog["catalog_sha256"], "events": []})
    receipt = {"schema_version": 1, "curator_id": "SYNTHETIC_CONTRACT_ROLE", "independence_statement": "合成契约测试，不能提交为正式验收。",
               "prepared_at": "2026-09-10T00:00:00+08:00", "catalog_sha256": catalog["catalog_sha256"],
               "assessment_sha256": catalog["assessment"]["sha256"],
               "qualification": {"path": "qualification.json", "sha256": file_hash(tmp_path / "qualification.json")},
               "contamination": {"path": "contamination.json", "sha256": file_hash(tmp_path / "contamination.json")},
               "tasks": {task["id"]: {"task_sha256": task["task_sha256"], "source": task["source"], "license": task["license"],
                                    "source_artifact_sha256": "b" * 64, "not_used_for_agent_debugging": True} for task in catalog["tasks"]}}
    path = tmp_path / "receipt.json"
    write_new(path, receipt)
    return catalog, path


def test_custody_requires_operator_pin_and_complete_bound_controls(tmp_path):
    catalog, path = receipt_fixture(tmp_path)
    result = verify_custody(catalog, path, file_hash(path))
    assert result["verified"] and result["scope"] == "operator_pinned_independent_curator_attestation"
    with pytest.raises(ValueError, match="摘要"):
        verify_custody(catalog, path, "0" * 64)
    assert "blind_quality_eligible" not in result


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(untrusted_module="module"),
    lambda value: value.update(curator_id=""),
    lambda value: value.update(prepared_at="2026-09-10"),
    lambda value: value.update(catalog_sha256="0"*64),
    lambda value: value["tasks"]["PY01"].update(not_used_for_agent_debugging=False),
    lambda value: value["tasks"]["PY01"].update(license="unknown"),
    lambda value: value["tasks"]["PY01"].update(source_artifact_sha256=""),
    lambda value: value["tasks"].pop("PY01"),
    lambda value: value["qualification"].update(path="../qualification.json"),
])
def test_invalid_custody_is_rejected_even_with_matching_file_pin(tmp_path, mutation):
    catalog, path = receipt_fixture(tmp_path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    mutation(receipt)
    save(path, receipt)
    with pytest.raises(ValueError):
        verify_custody(catalog, path, file_hash(path))


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(checks=value["checks"][:-1]),
    lambda value: value["checks"].append(value["checks"][0]),
    lambda value: value["checks"][0]["controls"].pop("wrong"),
    lambda value: value["checks"][0].update(task_sha256="0"*64),
    lambda value: value["checks"][0]["controls"]["reference"].update(candidate_sha256="0"*64),
    lambda value: value.update(judge_sha256={}),
    lambda value: value.update(passed=False),
    lambda value: value.update(isolation={"verified": False}),
])
def test_stale_failed_or_rebound_qualification_is_rejected(tmp_path, mutation):
    catalog, path = receipt_fixture(tmp_path)
    qualification_path = tmp_path / "qualification.json"
    value = json.loads(qualification_path.read_text(encoding="utf-8"))
    mutation(value)
    save(qualification_path, value)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["qualification"]["sha256"] = file_hash(qualification_path)
    save(path, receipt)
    with pytest.raises(ValueError):
        verify_custody(catalog, path, file_hash(path))


def test_public_task_relabel_cannot_gain_blind_eligibility(tmp_path):
    catalog, path = receipt_fixture(tmp_path, copied_public=True)
    with pytest.raises(ValueError, match="公开校准"):
        verify_custody(catalog, path, file_hash(path))


def test_contamination_preserves_old_record_and_invalidates_receipt(tmp_path):
    catalog, path = receipt_fixture(tmp_path)
    source = tmp_path / "contamination.json"
    original = file_hash(source)
    destination = tmp_path / "contamination-2.json"
    value = record_contamination(source, destination, original, ["PY09"], "用于调试后登记污染")
    assert file_hash(source) == original
    assert value["events"][0]["previous_version_sha256"] == original
    with pytest.raises(FileExistsError):
        record_contamination(source, destination, original, ["PY09"], "不能覆盖")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["contamination"] = {"path": destination.name, "sha256": file_hash(destination)}
    save(path, receipt)
    with pytest.raises(ValueError, match="污染"):
        verify_custody(catalog, path, file_hash(path))


def test_qualification_artifact_and_ledger_tampering_rejected(tmp_path):
    catalog, path = receipt_fixture(tmp_path)
    (tmp_path / "PY01-reference.json").write_text('{"passed":false}', encoding="utf-8")
    with pytest.raises(ValueError, match="产物摘要"):
        verify_custody(catalog, path, file_hash(path))


@pytest.mark.parametrize("reason", ["judge_timeout", "judge_output_quota", "isolation_execution_failed", "judge_changed_during_validation"])
def test_infrastructure_failure_is_not_a_valid_negative_control(reason):
    for control in ("initial", "wrong"):
        assert not control_passed(control, {"passed": False, "scope_preserved": True,
                                           "isolation_verified": True, "reason": reason})


def test_rehashed_verdict_cannot_bind_a_different_candidate(tmp_path):
    catalog, path = receipt_fixture(tmp_path)
    artifact = tmp_path / "PY01-reference.json"
    value = json.loads(artifact.read_text(encoding="utf-8"))
    value["binding"]["candidate_sha256"] = "0" * 64
    save(artifact, value)
    qualification_path = tmp_path / "qualification.json"
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    qualification["checks"][0]["controls"]["reference"]["verdict_sha256"] = file_hash(artifact)
    ledger = tmp_path / "qualification-attempts.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    ledger.write_text("", encoding="utf-8")
    previous = None
    for row in rows:
        row.pop("record_sha256")
        row.pop("previous_sha256")
        if row.get("verdict_path") == artifact.name:
            row["verdict_sha256"] = file_hash(artifact)
        previous = append_record(ledger, row, previous)
    qualification["ledger_sha256"] = file_hash(ledger)
    save(qualification_path, qualification)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["qualification"]["sha256"] = file_hash(qualification_path)
    save(path, receipt)
    with pytest.raises(ValueError, match="判定产物.*换绑"):
        verify_custody(catalog, path, file_hash(path))


def test_formal_control_refuses_answer_injection(tmp_path):
    from argparse import Namespace

    from run_coding_acceptance import run, script
    catalog, _ = receipt_fixture(tmp_path)
    with pytest.raises(ValueError, match="参考答案"):
        run(Namespace(catalog=Path(catalog["catalog_path"]), mode="control"))
    with pytest.raises(ValueError, match="参考实现"):
        script(catalog["tasks"][0])
