"""S6 证据与统计：缺失、失败和人工介入都不能变成成功。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

from coding_acceptance_schema import fingerprint, plain_path, read_json, strict_json

GATES = {
    "S6-T01": "完成真实性", "S6-T02": "写入保护", "S6-T03": "副作用恢复",
    "S6-T04": "事件一致性", "S6-T05": "取消与清理", "S6-T06": "终端能力",
    "S6-T07": "交互延迟", "S6-T08": "权限边界", "S6-T09": "编码质量",
    "S6-T10": "协议兼容", "S6-T11": "安装升级", "S6-T12": "文档一致性",
}
SECRET_KEYS = re.compile(r"authorization|password|api[_-]?key|access[_-]?token|refresh[_-]?token|nonce|secret", re.I)
TERMINAL_EVENTS = {status: "run." + status for status in (
    "completed", "failed", "cancelled", "timed_out", "limit_exceeded", "interrupted",
)}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SECRET_KEYS.search(key) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Bearer\s+[^\s\"'<>]+", "Bearer [REDACTED]", value)
        return re.sub(r"(?i)((?:api[_-]?key|password|access_token|refresh_token|secret)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", value)
    return value


def write_json(path: Path, value) -> None:
    body = json.dumps(redact(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(body.encode()) > 8 * 1024 * 1024:
        raise ValueError("证据文件超过 8 MiB 配额")
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    temporary.replace(path)


def event_integrity_errors(events: list[dict], last_sequence: int, run_status: str | None = None) -> list[str]:
    errors = []
    if type(last_sequence) is not int or last_sequence < 1:
        errors.append("invalid_last_sequence")
    if not events:
        errors.append("empty_events")
    if (len(events) != last_sequence or any(not isinstance(event, dict)
            or type(event.get("sequence")) is not int or event["sequence"] != index
            for index, event in enumerate(events, 1))):
        errors.append("sequence_mismatch")
    terminals = [(index, event["type"]) for index, event in enumerate(events)
                 if isinstance(event, dict) and event.get("type") in TERMINAL_EVENTS.values()]
    if not terminals:
        errors.append("missing_terminal")
    elif len(terminals) > 1:
        errors.append("duplicate_terminal")
    # 本机协议在原运行终态后不再追加事件；恢复产生关联的新运行。
    if terminals and terminals[0][0] != len(events) - 1:
        errors.append("event_after_terminal")
    if run_status is not None:
        if run_status not in TERMINAL_EVENTS:
            errors.append("run_not_terminal")
        elif len(terminals) == 1 and terminals[0][1] != TERMINAL_EVENTS[run_status]:
            errors.append("terminal_status_mismatch")
    return errors


def event_integrity(events: list[dict], last_sequence: int, run_status: str | None = None) -> bool:
    return not event_integrity_errors(events, last_sequence, run_status)


def independent(attempt: dict) -> bool:
    return (attempt.get("mode") == "quality" and attempt.get("started") is True
            and ("isolation_sha256" not in attempt.get("binding", {}) or attempt.get("isolation_verified") is True)
            and attempt.get("holdout_exposure") not in {"public_calibration", "contaminated"}
            and attempt.get("coding_goal") is True
            and attempt.get("run_status") == "completed" and attempt.get("goal_outcome") == "verified"
            and attempt.get("system_behavior_passed") is True and not attempt.get("failure_class")
            and all(attempt.get(key) is True for key in (
                "functional_passed", "scope_preserved", "validation_passed", "report_matches_facts",
                "within_budget", "evidence_complete", "reviewed_constraints", "model_identity_matches"))
            and attempt.get("human_interventions") == 0)


def aggregate(attempts: list[dict], expected: list[dict], *, runner_errors: list[str] | None = None) -> dict:
    expected_ids = {item["attempt_id"] for item in expected}
    actual = Counter(item["attempt_id"] for item in attempts)
    errors = list(runner_errors or [])
    if len(expected_ids) != len(expected):
        errors.append("duplicate_schedule")
    errors.extend(f"duplicate_attempt:{key}" for key, count in actual.items() if count > 1)
    errors.extend(f"unexpected_attempt:{key}" for key in actual.keys() - expected_ids)
    missing = sorted(expected_ids - actual.keys())
    if missing:
        errors.append("missing_attempts")
    planned = {item["attempt_id"]: item for item in expected}
    mismatched = set()
    for item in attempts:
        plan = planned.get(item["attempt_id"])
        if plan and any(item.get(key) != plan.get(key) for key in (
                "task_id", "model", "coding_goal", "split", "category", "family", "mode", "connection_mode", "binding", "holdout_exposure")):
            errors.append("attempt_identity_mismatch:" + item["attempt_id"])
            mismatched.add(item["attempt_id"])

    def summarize(rows):
        # 分母取冻结计划中的身份字段，篡改行内 coding_goal 不能删掉已经启动的失败。
        rows = [{**row, **{key: value for key, value in planned.get(row["attempt_id"], {}).items()
                          if key not in {"started", "failure_class", "human_interventions"}},
                 **({"report_matches_facts": False} if row["attempt_id"] in mismatched else {}),
                 **({"holdout_exposure": "contaminated"} if row.get("holdout_exposure") == "contaminated" else {})} for row in rows]
        started = [row for row in rows if row.get("started") is True]
        coding = [row for row in started if row.get("coding_goal") is True and row.get("mode") == "quality"]
        completed = sum(independent(row) for row in coding)
        costs = [row.get("cost_usd") for row in started]
        measured = [value for value in costs if type(value) in {int, float} and math.isfinite(value) and value >= 0]
        return {"scheduled": len(rows), "started": len(started), "coding_denominator": len(coding),
                "not_started": len(rows) - len(started),
                "contaminated_started": sum(row.get("holdout_exposure") in {"public_calibration", "contaminated"} for row in started),
                "coding_goal_started": sum(row.get("coding_goal") is True for row in started),
                "coding_task_count": len({row["task_id"] for row in coding}), "independent_completed": completed,
                "independent_completion_rate": completed / len(coding) if coding else None,
                "system_behavior_passed": sum(row.get("system_behavior_passed") is True for row in started),
                "human_interventions": sum(row.get("human_interventions", 0) for row in started),
                "failures": dict(Counter(row["failure_class"] for row in rows if row.get("failure_class"))),
                "cost_usd": sum(measured) if len(measured) == len(costs) and costs else None,
                "known_cost_subtotal_usd": sum(measured), "cost_unknown_attempts": len(costs) - len(measured),
                "elapsed_seconds": sum(row.get("elapsed_seconds", 0) for row in rows),
                "known_tokens_subtotal": sum(row.get("tokens") or 0 for row in started),
                "usage_unknown_attempts": sum(row.get("tokens") is None for row in started)}

    models = {}
    for model in sorted({item["model"] for item in expected}):
        rows = [item for item in attempts if planned.get(item["attempt_id"], item).get("model") == model]
        models[model] = {"overall": summarize(rows)}
        for group in ("family", "category", "split"):
            models[model][group] = {value: summarize([row for row in rows if planned.get(row["attempt_id"], row).get(group) == value])
                                    for value in sorted({item[group] for item in expected if item["model"] == model})}
    failures = [{**{key: planned.get(row["attempt_id"], row).get(key) for key in
                    ("attempt_id", "task_id", "model", "family", "category", "split", "holdout_exposure")},
                 "failure_class": row["failure_class"], "started": row.get("started", False),
                 "attribution": row.get("failure_attribution", "unresolved_requires_review")}
                for row in attempts if row.get("failure_class")]
    return {"models": models, "missing_attempts": missing, "runner_errors": errors, "integrity_passed": not errors,
            "failure_records": failures}


def verify_ledger(directory: Path, manifest: dict, attempts: list[dict]) -> None:
    plans = {plan["attempt_id"]: plan for plan in manifest["schedule"]}
    ids = [row["attempt_id"] for row in attempts]
    if len(plans) != len(manifest["schedule"]) or len(set(ids)) != len(ids):
        raise ValueError("实验包含重复计划或尝试")
    for row in attempts:
        if row["attempt_id"] not in plans or any(row.get(key) != value for key, value in plans[row["attempt_id"]].items()):
            raise ValueError("尝试身份与冻结计划不符")
    if manifest.get("statistics_version") != "s6-attempt-ledger-1" and all("record_sha256" not in row for row in attempts):
        return
    previous = None
    for row in attempts:
        if (row.get("previous_record_sha256") != previous
                or row.get("record_sha256") != fingerprint({key: value for key, value in row.items() if key != "record_sha256"})):
            raise ValueError("尝试记录摘要链变化")
        previous = row["record_sha256"]
    if manifest.get("statistics_version") != "s6-attempt-ledger-1":
        return
    metrics = read_json(directory / "metrics.json")
    for name in ("manifest.json", "attempts.jsonl", "starts.jsonl"):
        if digest(plain_path(directory / name)) != metrics["evidence_files_sha256"].get(name):
            raise ValueError("实验清单或尝试日志摘要变化")
    starts_path = plain_path(directory / "starts.jsonl")
    if starts_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("启动日志超过配额")
    starts = [strict_json(line) for line in starts_path.read_text(encoding="utf-8").splitlines()]
    seen = set()
    for start in starts:
        if (start["attempt_id"] in seen or start["attempt_id"] not in plans
                or start.get("start_sha256") != fingerprint({key: value for key, value in start.items() if key != "start_sha256"})
                or any(start.get(key) != value for key, value in plans[start["attempt_id"]].items())):
            raise ValueError("启动日志与冻结计划不符")
        seen.add(start["attempt_id"])
    for row in attempts:
        if (row.get("started") is True) != (row["attempt_id"] in seen):
            raise ValueError("已启动状态不得重分类")
    if not seen <= {row["attempt_id"] for row in attempts}:
        raise ValueError("已启动尝试缺少结束记录")


def experiment_status(rows: list[dict], manifest: dict, metrics: dict) -> dict:
    schedule = manifest.get("schedule", [])
    schedule_complete = (metrics["integrity_passed"] and len(rows) == len(schedule)
                         and all(row.get("started") is True for row in rows))
    model_schedules = [[row for row in schedule if row["model"] == model] for model in {row["model"] for row in schedule}]
    complete_design = bool(model_schedules) and all(len(items) == 90
        and len({row["task_id"] for row in items}) == 30
        and all({row.get("repetition") for row in items if row["task_id"] == task_id} == {1, 2, 3}
                for task_id in {row["task_id"] for row in items}) for items in model_schedules)
    return {"schedule_complete": schedule_complete,
            "experiment_complete": (schedule_complete and complete_design
                and manifest.get("purpose") == "independent_evaluation"
                and manifest.get("isolation", {}).get("verified") is True
                and manifest.get("custody", {}).get("verified") is True
                and all(row.get("mode") == "quality" and row.get("holdout_exposure") == "unexposed" for row in rows))}


class Evidence:
    def __init__(self, directory: Path, manifest: dict):
        self.directory = directory
        self.rows: list[dict] = []
        self.errors: list[str] = []
        self.manifest = manifest
        self.starts: dict[str, dict] = {}
        for name in ("events", "artifacts"):
            (directory / name).mkdir()
        write_json(directory / "manifest.json", manifest)
        (directory / "attempts.jsonl").touch(exist_ok=False)
        (directory / "starts.jsonl").touch(exist_ok=False)
        # 初始报告先落盘；父进程被强制关闭时不能留下一个看似通过的空目录。
        self.finish()

    def append(self, row: dict) -> None:
        if any(item["attempt_id"] == row["attempt_id"] for item in self.rows):
            raise ValueError("尝试已记录；重跑必须使用新实验目录，不得覆盖")
        row = redact(row)
        row["previous_record_sha256"] = self.rows[-1]["record_sha256"] if self.rows else None
        row["record_sha256"] = fingerprint(row)
        with (self.directory / "attempts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.rows.append(row)

    def start(self, plan: dict) -> None:
        if plan["attempt_id"] in self.starts:
            raise ValueError("尝试不得重复启动")
        row = {**plan, "started": True, "failure_class": "started_without_final_record", "human_interventions": 0}
        row["start_sha256"] = fingerprint(row)
        with (self.directory / "starts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.starts[plan["attempt_id"]] = row
        self.finish()

    def finish(self) -> dict:
        rows = list(self.rows)
        recorded = {row["attempt_id"] for row in rows}
        rows.extend(row for key, row in self.starts.items() if key not in recorded)
        errors = list(self.errors)
        for row in rows:
            if row["attempt_id"] in self.starts and row.get("started") is not True:
                errors.append("started_attempt_reclassified")
        rows = [{**row, "started": True} if row["attempt_id"] in self.starts else row for row in rows]
        if any(row.get("failure_class") == "started_without_final_record" for row in rows):
            errors.append("unfinished_started_attempt")
        metrics = aggregate(rows, self.manifest.get("schedule", []), runner_errors=errors)
        metrics.update(experiment_status(rows, self.manifest, metrics))
        metrics["evidence_files_sha256"] = {name: digest(self.directory / name)
                                           for name in ("manifest.json", "attempts.jsonl", "starts.jsonl")}
        gates = {key: {"name": name, "status": "not_run", "reason": "尚无覆盖完整门禁的本轮证据"} for key, name in GATES.items()}
        for key in ("S6-T02", "S6-T04", "S6-T09", "S6-T10"):
            gates[key]["partial_evidence"] = [row["attempt_id"] for row in self.rows if row.get("evidence_complete")]
        gates["S6-T09"]["reason"] = "公开校准集不具备盲评资格；真实模型、人工审阅及完整重复实验分别核对"
        gates["S6-T11"]["reason"] = "本机 IPC 产物执行不能代替干净 OS 安装、旧数据升级和旧程序回退"
        metrics.update(gates=gates, delivery_decision="blocked", real_model_called=any(
            row.get("connection_mode") in {"product_proxy", "local_unbilled", "direct_provider"} and (row.get("model_requests") or 0) > 0
            if "connection_mode" in row else row.get("mode") == "quality" and row.get("started") for row in self.rows))
        metrics["connection_mode"] = self.manifest.get("connection_mode", "legacy_unspecified")
        metrics["account_mode"] = self.manifest.get("account_mode", "legacy_unspecified")
        metrics["experiment_budget"] = self.manifest.get("experiment_budget")
        metrics["process_metrics"] = {row["attempt_id"]: row.get("process_metrics") for row in self.rows}
        metrics["resource_metrics"] = {row["attempt_id"]: row.get("resource_metrics") for row in self.rows}
        # 确定性成绩、局部兼容检查与公开任务的正对照不解除 M3 门禁。
        write_json(self.directory / "metrics.json", metrics)
        lines = ["# S6 评测报告", "", "交付决议：**继续验收，M3 未放行**。", "",
                 f"运行模式：`{self.manifest['mode']}`；证据完整性：{'通过' if metrics['integrity_passed'] else '失败'}。",
                 f"连接模式：`{metrics['connection_mode']}`；能力预检与真实推理结果分别记录。",
                 "真实模型质量、桌面 UI、干净安装和程序回退分别判定。未测用量与成本保留 unknown。", "",
                 "| 模型 | 启动 | 编码分母 | 独立完成 | 系统行为通过 |", "| --- | ---: | ---: | ---: | ---: |"]
        for model, groups in metrics["models"].items():
            data = groups["overall"]
            lines.append(f"| {model.replace('|', '/')} | {data['started']} | {data['coding_denominator']} | {data['independent_completed']} | {data['system_behavior_passed']} |")
        lines += ["", "## 失败与阻断", ""]
        lines.extend(f"- {value}" for value in metrics["runner_errors"])
        lines.extend(f"- {row['attempt_id']}: {row['failure_class']}" for row in self.rows if row.get("failure_class"))
        if metrics["account_mode"] == "isolated_local_test":
            lines += ["", "## 本机临时测试身份", "",
                      "本次使用仅提供身份的回环账号服务，云 API 经本机 Agent 直连供应商。",
                      "本记录不证明真实服务器账号、原生桌面或最终候选验收通过。"]
        lines += ["", "## 证据边界", "", "公开校准任务及其参考实现已暴露，保留集盲评性未验证；不得据此推荐默认模型。",
                  "最终说明的自然语言真实性需要独立审阅；未审阅时 report_matches_facts 为 null。",
                  "端到端原生桌面、真实远程 Provider、支持 Windows 矩阵及完整安装升级/回退须补充独立证据。",
                  "本目录保留独立工作区及哈希；只在确认不再需要后由所有者处理，不自动清理旧证据。", ""]
        (self.directory / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return metrics
