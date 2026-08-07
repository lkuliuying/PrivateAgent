"""M0 门槛判定共享逻辑（runner 与聚合器共用）。

"有效 Agent run" 定义（0.3.0 M0 门槛）：
    status == "completed" AND output.validation_passed
取消、预期的故障 run、超时只作为故障样本，不计入有效 run。
"""
from __future__ import annotations

from typing import Any


def is_valid_completed_run(run: dict[str, Any]) -> bool:
    """有效 run：completed 且输出验证通过（events 含 output.validation_passed）。"""
    return run.get("status") == "completed" and bool(run.get("validation_passed"))


def count_valid_runs(runs: list[dict[str, Any]]) -> int:
    return sum(1 for run in runs if is_valid_completed_run(run))


def runs_by_status(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        status: sum(1 for run in runs if run.get("status") == status)
        for status in sorted({run.get("status") for run in runs})
    }


def latency_percentiles(
    runs: list[dict[str, Any]], percentiles: tuple[float, ...] = (50.0, 95.0)
) -> dict[str, float | None]:
    """completed run 的 latency_s 分位数；样本不足返回 None。"""
    values = sorted(
        float(run["latency_s"])
        for run in runs
        if run.get("status") == "completed" and run.get("latency_s") is not None
    )
    if not values:
        return {f"p{int(p)}": None for p in percentiles}
    out: dict[str, float | None] = {}
    for p in percentiles:
        idx = min(len(values) - 1, int(len(values) * p / 100.0))
        out[f"p{int(p)}"] = round(values[idx], 1)
    return out


def observation_days(timestamps: list[str]) -> float | None:
    """按 ISO 时间戳列表估算观察跨度（天）；空输入返回 None。"""
    from datetime import datetime

    parsed: list[datetime] = []
    for value in timestamps:
        try:
            parsed.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return None
    span = (max(parsed) - min(parsed)).total_seconds()
    return round(span / 86_400.0, 2)


def gate_verdict(*, aggregate: dict[str, Any]) -> dict[str, Any]:
    """按 M0 门槛逐项判定并输出 gate_pass。

    aggregate 字段：
    - valid_completed_runs: int
    - observation_days: float | None
    - rag_runs: int
    - cancel_sample: bool
    - approval_sample: bool
    - ollama_outage_sample: bool
    - windows_ended_cycles: int
    - stale_open_windows: int
    - negative_duration_windows: int
    - stuck_runs_over_10min: int
    - p0p1_blockers: list[str]
    """
    checks: list[dict[str, Any]] = [
        {
            "key": "observation_days",
            "label": "连续观察 >= 7 天",
            "passed": (aggregate.get("observation_days") or 0) >= 7.0,
            "detail": aggregate.get("observation_days"),
        },
        {
            "key": "valid_completed_runs",
            "label": "有效 completed run >= 100",
            "passed": aggregate.get("valid_completed_runs", 0) >= 100,
            "detail": aggregate.get("valid_completed_runs"),
        },
        {
            "key": "rag_runs",
            "label": "RAG run 样本 >= 1",
            "passed": (aggregate.get("rag_runs") or 0) >= 1,
            "detail": aggregate.get("rag_runs"),
        },
        {
            "key": "cancel_sample",
            "label": "用户取消样本",
            "passed": bool(aggregate.get("cancel_sample")),
            "detail": aggregate.get("cancel_sample"),
        },
        {
            "key": "approval_sample",
            "label": "审批暂停/恢复样本",
            "passed": bool(aggregate.get("approval_sample")),
            "detail": aggregate.get("approval_sample"),
        },
        {
            "key": "ollama_outage_sample",
            "label": "Ollama 中断/恢复样本",
            "passed": bool(aggregate.get("ollama_outage_sample")),
            "detail": aggregate.get("ollama_outage_sample"),
        },
        {
            "key": "windows_ended_cycles",
            "label": "正常启动/退出周期 >= 3",
            "passed": (aggregate.get("windows_ended_cycles") or 0) >= 3,
            "detail": aggregate.get("windows_ended_cycles"),
        },
        {
            "key": "stale_open_windows",
            "label": "陈旧 open 窗口 = 0",
            "passed": (aggregate.get("stale_open_windows") or 0) == 0,
            "detail": aggregate.get("stale_open_windows"),
        },
        {
            "key": "negative_duration_windows",
            "label": "负时长窗口 = 0",
            "passed": (aggregate.get("negative_duration_windows") or 0) == 0,
            "detail": aggregate.get("negative_duration_windows"),
        },
        {
            "key": "stuck_runs_over_10min",
            "label": "超过 10 分钟无推进 run = 0",
            "passed": (aggregate.get("stuck_runs_over_10min") or 0) == 0,
            "detail": aggregate.get("stuck_runs_over_10min"),
        },
        {
            "key": "p0p1_blockers",
            "label": "P0/P1 关闭或有明确处置",
            "passed": not aggregate.get("p0p1_blockers"),
            "detail": aggregate.get("p0p1_blockers"),
        },
    ]
    return {
        "checks": checks,
        "gate_pass": all(check["passed"] for check in checks),
    }
