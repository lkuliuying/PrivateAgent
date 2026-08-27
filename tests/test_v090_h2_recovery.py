"""v0.9.0 H2 契约测试：恢复与 unknown 人工处置（计划 §6）。

覆盖：
- unknown 执行人工处置三决策（succeeded/failed/not_executed）；
- 非 unknown 状态拒绝处置（不得静默改判）；
- not_executed 不自动重试（系统只记录事实，无重跑路径）；
- revalidate 只读事实端点（不改变执行状态）；
- 人工处置遥测低基数计数。
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from personal_assistant.agents.repository import AgentRunRepository
from personal_assistant.config import settings as cfg
from personal_assistant.core.compatibility import compatibility_telemetry
from personal_assistant.core.models import AgentToolExecution
from personal_assistant.core.timeutil import utcnow


async def _make_run(db) -> str:
    from personal_assistant.agents.contracts import AgentRunLimits

    run_id = str(uuid4())
    await AgentRunRepository(db).create_run(
        run_id=run_id, limits=AgentRunLimits(), session_id=None
    )
    await db.commit()
    return run_id


async def _make_unknown_execution(db, run_id: str) -> str:
    arguments = {"project_id": 1, "command": ["echo", "hi"]}
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    execution = AgentToolExecution(
        id=str(uuid4()),
        run_id=run_id,
        step_id=None,
        tool_call_id=f"tc-{uuid4().hex[:8]}",
        tool_name="run_whitelisted_command",
        tool_version="1.0.0",
        arguments_json=arguments,
        arguments_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        risk_level="confirm",
        required_capabilities_json=["process.execute"],
        approval_id=None,
        status="unknown",
        attempt_count=1,
        started_at=utcnow(),
        output_json=None,
    )
    db.add(execution)
    await db.commit()
    return execution.id


async def test_resolve_unknown_not_executed_records_fact(client, db, monkeypatch):
    """not_executed：记录为失败终态 + 事实备注；不自动重试（无重跑路径）。"""
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    run_id = await _make_run(db)
    execution_id = await _make_unknown_execution(db, run_id)

    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        f"/agent-runs/{run_id}/executions/{execution_id}/resolve",
        json={"decision": "not_executed", "note": "确认命令未实际启动"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "resolved_manually"
    assert "not_executed" in body["error_message"]
    after = compatibility_telemetry.snapshot()
    delta = after["paths"]["manual_execution_resolution"]["outcomes"][
        "not_executed"
    ] - before["paths"]["manual_execution_resolution"]["outcomes"]["not_executed"]
    assert delta == 1


async def test_resolve_unknown_succeeded_requires_output(client, db, monkeypatch):
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    run_id = await _make_run(db)
    execution_id = await _make_unknown_execution(db, run_id)

    # 无 output → 409（不猜测成功）
    resp = await client.post(
        f"/agent-runs/{run_id}/executions/{execution_id}/resolve",
        json={"decision": "succeeded"},
    )
    assert resp.status_code == 409

    resp = await client.post(
        f"/agent-runs/{run_id}/executions/{execution_id}/resolve",
        json={"decision": "succeeded", "output": {"returncode": 0}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "succeeded"


async def test_resolve_rejects_non_unknown_execution(client, db, monkeypatch):
    """非 unknown 状态不得被人工处置改判（防静默篡改事实）。"""
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    run_id = await _make_run(db)
    execution_id = await _make_unknown_execution(db, run_id)
    # 先处置为 failed（终态）
    resp = await client.post(
        f"/agent-runs/{run_id}/executions/{execution_id}/resolve",
        json={"decision": "failed", "note": "x"},
    )
    assert resp.status_code == 200
    # 再次处置 → 409，且计入 rejected 遥测（快照在请求前取）
    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        f"/agent-runs/{run_id}/executions/{execution_id}/resolve",
        json={"decision": "succeeded", "output": {"returncode": 0}},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]
    after = compatibility_telemetry.snapshot()
    delta = after["paths"]["manual_execution_resolution"]["outcomes"][
        "rejected"
    ] - before["paths"]["manual_execution_resolution"]["outcomes"]["rejected"]
    assert delta == 1


async def test_revalidate_is_readonly_and_reports_git_facts(
    client, db, monkeypatch, tmp_path
):
    """revalidate：只读返回工作区路径/ Git 事实，不改变执行状态。"""
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    run_id = await _make_run(db)
    execution_id = await _make_unknown_execution(db, run_id)

    resp = await client.post(
        f"/agent-runs/{run_id}/executions/{execution_id}/revalidate"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["execution_id"] == execution_id
    assert body["execution_status"] == "unknown", "revalidate 不得改变状态"
    assert isinstance(body["checks"], list)
    assert body["revalidated_at"].endswith("Z")

    # 遥测计数
    before = compatibility_telemetry.snapshot()
    await client.post(
        f"/agent-runs/{run_id}/executions/{execution_id}/revalidate"
    )
    after = compatibility_telemetry.snapshot()
    delta = after["paths"]["manual_execution_resolution"]["outcomes"][
        "revalidated"
    ] - before["paths"]["manual_execution_resolution"]["outcomes"]["revalidated"]
    assert delta == 1


def test_resolve_decision_vocabulary_frozen():
    """处置决策词汇冻结：不得出现自动重试类决策（零容忍）。"""
    from personal_assistant.api.routes_agent_runs import (
        AgentExecutionResolveRequest,
    )

    allowed = set(
        AgentExecutionResolveRequest.model_fields["decision"].annotation.__args__
    )
    assert allowed == {"succeeded", "failed", "not_executed"}
    # 反向断言：不存在自动重试/跳过类决策
    assert "retry" not in allowed
    assert "auto_retry" not in allowed
    assert "skip" not in allowed
