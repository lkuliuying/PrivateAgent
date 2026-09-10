"""独立验收侧的题集正负控制及摘要回执；不把来源声明自动当作盲评证据。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from coding_acceptance_schema import (
    assessment_for,
    fields,
    file_hash,
    fingerprint,
    nonempty,
    plain_path,
    read_json,
    safe_relative,
    sha256,
    verify_catalog,
)
from run_coding_validation import ROOT, new_directory


def judge_identity() -> dict:
    identity = {name: file_hash(ROOT / "scripts" / name) for name in (
        "coding_acceptance_schema.py", "coding_acceptance_catalog.py", "coding_acceptance_judge.py",
        "coding_acceptance_isolation.py", "coding_acceptance_pytest.py", "coding_acceptance_dataset.py")}
    for name in ("scripts/run_coding_validation.py", "scripts/coding_validation_process.py",
                 "src/private_agent_local/windows_sandbox.py", "src/private_agent_local/windows_process.py",
                 "src/private_agent_local/executor.py", "src/private_agent_core/execution/contracts.py",
                 "src/private_agent_core/execution/exec_host_client.py"):
        identity[name] = file_hash(ROOT / name)
    return identity


def write_new(path: Path, value) -> None:
    plain_path(path, must_exist=False)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def append_record(path: Path, row: dict, previous: str | None) -> str:
    row = {**row, "previous_sha256": previous}
    row["record_sha256"] = fingerprint(row)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return row["record_sha256"]


def wrong_files(task: dict, references: dict) -> dict:
    result = dict(references)
    if "src/service.py" in result:
        result["src/service.py"] = "def respond(value):\n    return None\n"
    elif "src/Result.vue" in result:
        result["src/Result.vue"] = "<template><output>S6_WRONG_CONTROL</output></template>\n"
    elif "src/lib.rs" in result:
        result["src/lib.rs"] = "pub fn solve(_: &[i64]) -> Vec<i64> {vec![]}\npub fn evaluate(_: &[i64]) -> Vec<i64> {vec![]}\n"
    else:
        result[next(iter(result))] = "S6_WRONG_CONTROL\n"
    return result


def control_passed(control: str, verdict: dict) -> bool:
    if (verdict.get("passed") is not (control == "reference")
            or verdict.get("scope_preserved") is not (control != "protected")):
        return False
    if control == "protected":
        return verdict.get("reason") == "user_work_changed"
    if verdict.get("isolation_verified") is not True:
        return False
    if control == "reference":
        return verdict.get("reason") is None
    # 资源耗尽和基础设施失败不是隐藏断言有效的证据。
    return verdict.get("reason") in {"assertion_failed", "candidate_failed", "invalid_candidate_output", "refactor_constraint_failed"}


def qualify(catalog: dict, directory: Path, isolation) -> dict:
    from coding_acceptance_catalog import judge, rebuild, snapshot

    if catalog["catalog_source"] != "external_json":
        raise ValueError("验收侧只接受严格外部 JSON")
    verify_catalog(catalog)
    identity = judge_identity()
    assessment = Path(catalog["tasks"][0]["assessment_path"])
    probes = isolation.probe([assessment, Path(__file__), ROOT / "scripts/coding_acceptance_judge.py"], directory / "permission")
    checks, previous = [], None
    ledger = directory / "qualification-attempts.jsonl"
    ledger.touch(exist_ok=False)
    write_new(directory / "qualification-start.json", {
        "catalog_sha256": catalog["catalog_sha256"], "assessment_sha256": catalog["assessment"]["sha256"],
        "judge_sha256": identity, "task_ids": [task["id"] for task in catalog["tasks"]],
        "controls": ["initial", "reference", "wrong", "protected"], "isolation": probes})
    if not probes["verified"]:
        raise ValueError("验收侧实际材料权限探针失败")
    for task in catalog["tasks"]:
        runtime = isolation.runtime(task["family"])
        assessment_item = assessment_for(task)
        outcomes = {}
        for control in ("initial", "reference", "wrong", "protected"):
            area = new_directory(directory, task["id"] + "-" + control)
            project = area / "p"
            before = rebuild(task, project, runtime=runtime)
            if control != "initial":
                files = (wrong_files(task, assessment_item["reference_files"]) if control == "wrong"
                         else assessment_item["reference_files"])
                for name, content in files.items():
                    (project / name).write_text(content, encoding="utf-8", newline="\n")
            if control == "protected":
                (project / "user-notes.txt").write_text("S6_PROTECTED_FILE_CHANGED", encoding="utf-8")
            binding = {"task_id": task["id"], "task_sha256": task["task_sha256"], "control": control,
                       "candidate_sha256": fingerprint(snapshot(project))}
            previous = append_record(ledger, {**binding, "status": "started"}, previous)
            try:
                result = judge(task, project, area, before, isolation=isolation)
                write_new(area / "verdict.json", result)
                accepted = control_passed(control, result)
                outcome = {**binding, "status": "finished", "accepted": accepted,
                           "verdict_sha256": file_hash(area / "verdict.json"),
                           "verdict_path": (area / "verdict.json").relative_to(directory).as_posix(), "reason": result.get("reason")}
            except (OSError, ValueError, RuntimeError) as error:
                outcome = {**binding, "status": "finished", "accepted": False, "error_type": type(error).__name__}
            previous = append_record(ledger, outcome, previous)
            outcomes[control] = outcome
        checks.append({"task_id": task["id"], "task_sha256": task["task_sha256"],
                       "passed": all(item["accepted"] for item in outcomes.values()), "controls": outcomes})
        print(f"{task['id']} 验收侧正负控制：{'通过' if checks[-1]['passed'] else '失败'}", flush=True)
    verify_catalog(catalog)
    isolation.verify()
    if judge_identity() != identity:
        raise ValueError("正负控制期间判定器发生变化")
    result = {"schema_version": 1, "catalog_sha256": catalog["catalog_sha256"],
              "assessment_sha256": catalog["assessment"]["sha256"], "judge_sha256": identity,
              "created_at": datetime.now(timezone.utc).isoformat(), "checks": checks, "isolation": probes,
              "runtime_sha256": isolation.identity(), "ledger_sha256": file_hash(ledger),
              "passed": all(item["passed"] for item in checks), "blind_quality_eligible": False,
              "independence": "requires_separate_curator_receipt"}
    write_new(directory / "qualification.json", result)
    contamination = {"schema_version": 1, "catalog_sha256": catalog["catalog_sha256"], "events": []}
    if catalog["purpose"] == "public_calibration":
        contamination["events"] = [{"task_ids": [task["id"] for task in catalog["tasks"]],
                                    "cause": "public_calibration", "recorded_at": result["created_at"]}]
    write_new(directory / "contamination.json", contamination)
    write_new(directory / "custody-template.json", {
        "schema_version": 1, "curator_id": "", "independence_statement": "", "prepared_at": result["created_at"],
        "catalog_sha256": catalog["catalog_sha256"], "assessment_sha256": catalog["assessment"]["sha256"],
        "qualification": {"path": "qualification.json", "sha256": file_hash(directory / "qualification.json")},
        "contamination": {"path": "contamination.json", "sha256": file_hash(directory / "contamination.json")},
        "tasks": {task["id"]: {"task_sha256": task["task_sha256"], "source": task["source"], "license": task["license"],
                              "source_artifact_sha256": "", "not_used_for_agent_debugging": False} for task in catalog["tasks"]}})
    return result


def verify_custody(catalog: dict, receipt_path: Path, receipt_sha256: str) -> dict:
    """调用方固定回执摘要；人员独立性仍由验收方承担，不由 JSON 布尔值证明。"""
    sha256(receipt_sha256)
    receipt_path = plain_path(receipt_path)
    if file_hash(receipt_path) != receipt_sha256:
        raise ValueError("独立验收回执摘要不符")
    receipt = read_json(receipt_path)
    fields(receipt, {"schema_version", "curator_id", "independence_statement", "prepared_at",
                     "catalog_sha256", "assessment_sha256", "qualification", "tasks", "contamination"})
    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1:
        raise ValueError("独立验收回执版本无效")
    for key in ("curator_id", "independence_statement", "prepared_at"):
        nonempty(receipt[key])
    if not datetime.fromisoformat(receipt["prepared_at"]).tzinfo:
        raise ValueError("验收回执时间缺少时区")
    if (receipt["catalog_sha256"] != catalog["catalog_sha256"]
            or receipt["assessment_sha256"] != catalog["assessment"]["sha256"]):
        raise ValueError("验收回执与题集版本不符")
    for key in ("qualification", "contamination"):
        fields(receipt[key], {"path", "sha256"})
        safe_relative(receipt[key]["path"])
        sha256(receipt[key]["sha256"])
        if file_hash(receipt_path.parent / receipt[key]["path"]) != receipt[key]["sha256"]:
            raise ValueError("验收回执引用摘要变化")
    qualification_path = receipt_path.parent / receipt["qualification"]["path"]
    qualification = read_json(qualification_path)
    fields(qualification, {"schema_version", "catalog_sha256", "assessment_sha256", "judge_sha256",
                          "created_at", "checks", "isolation", "runtime_sha256", "ledger_sha256",
                          "passed", "blind_quality_eligible", "independence"})
    if (type(qualification.get("schema_version")) is not int or qualification.get("schema_version") != 1
            or qualification.get("passed") is not True
            or qualification.get("catalog_sha256") != catalog["catalog_sha256"]
            or qualification.get("assessment_sha256") != catalog["assessment"]["sha256"]
            or qualification.get("judge_sha256") != judge_identity()
            or qualification.get("isolation", {}).get("verified") is not True
            or file_hash(qualification_path.parent / "qualification-attempts.jsonl") != qualification.get("ledger_sha256")):
        raise ValueError("验收侧正负控制缺失、失败或判定器版本变化")
    tasks = {task["id"]: task for task in catalog["tasks"]}
    checks = qualification.get("checks")
    if (not isinstance(checks, list) or len(checks) != len(tasks) or any(not isinstance(item, dict) for item in checks)
            or {item.get("task_id") for item in checks} != tasks.keys()):
        raise ValueError("正负控制任务不完整或重复")
    for item in checks:
        if (item.get("task_sha256") != tasks[item["task_id"]]["task_sha256"] or item.get("passed") is not True
                or set(item.get("controls", {})) != {"initial", "reference", "wrong", "protected"}
                or any(control.get("accepted") is not True for control in item["controls"].values())):
            raise ValueError("正负控制未全部通过")
    verify_qualification_ledger(qualification_path.parent, qualification)
    declarations = receipt["tasks"]
    fields(declarations, set(tasks))
    public = read_json(ROOT / "tests/coding_acceptance/external_public/catalog.json")
    known_public = {fingerprint(task["files"]) for task in public["tasks"]}
    for task_id, declaration in declarations.items():
        fields(declaration, {"task_sha256", "source", "license", "source_artifact_sha256", "not_used_for_agent_debugging"})
        task = tasks[task_id]
        sha256(declaration["source_artifact_sha256"])
        if (any(declaration[key] != task[key] for key in ("task_sha256", "source", "license"))
                or declaration["not_used_for_agent_debugging"] is not True
                or task["holdout_exposure"] != "unexposed"):
            raise ValueError("独立来源、许可或未污染声明与任务不符")
        if fingerprint(task["files"]) in known_public:
            raise ValueError("已知公开校准内容不得重新标为未暴露题")
    contamination = read_json(receipt_path.parent / receipt["contamination"]["path"])
    fields(contamination, {"schema_version", "catalog_sha256", "events"})
    if (type(contamination["schema_version"]) is not int or contamination["schema_version"] != 1
            or contamination["catalog_sha256"] != catalog["catalog_sha256"] or contamination["events"] != []):
        raise ValueError("题集已有污染事件或登记格式无效，不能继续盲评")
    return {"verified": True, "receipt_sha256": receipt_sha256, "curator_id": receipt["curator_id"],
            "qualification_sha256": receipt["qualification"]["sha256"],
            "contamination_sha256": receipt["contamination"]["sha256"],
            "scope": "operator_pinned_independent_curator_attestation"}


def verify_qualification_ledger(directory: Path, qualification: dict) -> None:
    path = plain_path(directory / "qualification-attempts.jsonl")
    if file_hash(path) != qualification["ledger_sha256"]:
        raise ValueError("正负控制日志摘要变化")
    expected = {(item["task_id"], key): value for item in qualification["checks"] for key, value in item["controls"].items()}
    previous, started, finished = None, {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        record_hash = row.pop("record_sha256", None)
        if row.get("previous_sha256") != previous or fingerprint(row) != record_hash:
            raise ValueError("正负控制日志摘要链中断")
        previous = record_hash
        row.pop("previous_sha256")
        key = (row.get("task_id"), row.get("control"))
        if key not in expected or row.get("status") not in {"started", "finished"}:
            raise ValueError("正负控制日志包含未知任务或状态")
        if row["status"] == "started":
            if key in started:
                raise ValueError("正负控制不得重复启动")
            started[key] = row
        else:
            if key not in started or key in finished or row != expected[key]:
                raise ValueError("正负控制结果重复或与报告不符")
            if any(row.get(name) != started[key].get(name) for name in ("task_sha256", "candidate_sha256")):
                raise ValueError("正负控制候选发生换绑")
            for name in ("task_sha256", "candidate_sha256"):
                sha256(row.get(name))
            safe_relative(row["verdict_path"])
            verdict_path = directory / row["verdict_path"]
            if file_hash(verdict_path) != row["verdict_sha256"]:
                raise ValueError("正负控制判定产物摘要变化")
            verdict = read_json(verdict_path)
            if not control_passed(row["control"], verdict):
                raise ValueError("正负控制判定产物与报告不符")
            if (verdict.get("binding") != {"task_sha256": row["task_sha256"], "candidate_sha256": row["candidate_sha256"],
                                           "assessment_sha256": qualification["assessment_sha256"]}
                    or verdict.get("verifier_sha256") != qualification["judge_sha256"]["coding_acceptance_judge.py"]):
                raise ValueError("正负控制判定产物的候选、材料或判定器发生换绑")
            finished[key] = row
    if started.keys() != expected.keys() or finished.keys() != expected.keys():
        raise ValueError("正负控制有缺失或未结束的尝试")


def record_contamination(source: Path, destination: Path, expected_sha256: str, task_ids: list[str], cause: str) -> dict:
    sha256(expected_sha256)
    if file_hash(source) != expected_sha256:
        raise ValueError("污染登记基线已变化")
    data = read_json(source)
    fields(data, {"schema_version", "catalog_sha256", "events"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or not isinstance(data["events"], list):
        raise ValueError("污染登记格式无效")
    sha256(data["catalog_sha256"])
    if not task_ids or any(not isinstance(value, str) or not value for value in task_ids) or len(set(task_ids)) != len(task_ids):
        raise ValueError("污染任务为空或重复")
    nonempty(cause)
    data["events"].append({"task_ids": task_ids, "cause": cause, "recorded_at": datetime.now(timezone.utc).isoformat(),
                           "previous_version_sha256": expected_sha256})
    write_new(destination, data)
    return data


def main() -> int:
    from coding_acceptance_catalog import load_catalog
    from coding_acceptance_isolation import WindowsIsolation

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    validation = commands.add_parser("qualify", help="在验收侧运行三语言正负控制")
    validation.add_argument("--catalog", type=Path, required=True)
    validation.add_argument("--work-dir", type=Path, default=ROOT / ".run/coding-dataset-validation")
    pollution = commands.add_parser("contaminate", help="追加污染登记的新版本，保留原记录")
    pollution.add_argument("--source", type=Path, required=True)
    pollution.add_argument("--source-sha256", required=True)
    pollution.add_argument("--output", type=Path, required=True)
    pollution.add_argument("--tasks", required=True)
    pollution.add_argument("--cause", required=True)
    args = parser.parse_args()
    if args.action == "contaminate":
        record_contamination(args.source, args.output, args.source_sha256, args.tasks.split(","), args.cause)
        return 0
    catalog = load_catalog(args.catalog)
    parent = plain_path(args.work_dir, must_exist=False)
    parent.mkdir(parents=True, exist_ok=True)
    directory = new_directory(parent, "dataset")
    print(f"验收侧证据目录：{directory}", flush=True)
    try:
        result = qualify(catalog, directory, WindowsIsolation(directory / "tools"))
    except (OSError, ValueError, RuntimeError) as error:
        write_new(directory / "failure.json", {"error_type": type(error).__name__, "passed": False})
        print(f"题集验收未通过：{type(error).__name__}", file=sys.stderr)
        return 1
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
