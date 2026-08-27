"""v0.9.0 H1-A 契约测试：execution 视图聚合端点（H0 §8）。

覆盖：
- flag 关闭 → 409；
- 按 turn 聚合：决策摘要/工具/验证齐全，无决策时 decision=None（不伪造）；
- 命令执行事实脱敏（敏感键/路径不泄露）；
- 无命令的 turn → executions 为空（前端呈现「本轮未执行命令」）。
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from personal_assistant.agents.contracts import AgentEvent, AgentEventType
from personal_assistant.agents.repository import AgentRunRepository
from personal_assistant.config import settings as cfg


async def _make_run_with_events(db) -> str:
    run_id = str(uuid4())
    repo = AgentRunRepository(db)
    from personal_assistant.agents.contracts import AgentRunLimits

    await repo.create_run(
        run_id=run_id,
        limits=AgentRunLimits(),
        session_id=None,
        knowledge_base=False,
    )

    async def emit(seq: int, event_type: AgentEventType, payload=None, step_id=None):
        await repo.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=seq,
                type=event_type,
                step_id=step_id,
                payload=payload or {},
            )
        )

    await emit(1, AgentEventType.RUN_STARTED)
    model_step_1 = str(uuid4())
    await emit(
        2,
        AgentEventType.MODEL_STARTED,
        {"ordinal": 1, "kind": "model", "name": "model"},
        step_id=model_step_1,
    )
    await emit(
        3,
        AgentEventType.MODEL_COMPLETED,
        {"input_tokens": 10, "output_tokens": 5},
        step_id=model_step_1,
    )
    await emit(
        4,
        AgentEventType.DECISION_SUMMARY,
        {"goal": "修复构建失败", "method": "本轮决策：调用工具 run_build"},
    )
    tool_step_1 = str(uuid4())
    await emit(
        5,
        AgentEventType.TOOL_REQUESTED,
        {
            "ordinal": 2,
            "kind": "tool",
            "tool_call_id": "tc-1",
            "name": "run_whitelisted_command",
        },
        step_id=tool_step_1,
    )
    await emit(
        6,
        AgentEventType.TOOL_COMPLETED,
        {"tool_call_id": "tc-1", "name": "run_whitelisted_command"},
        step_id=tool_step_1,
    )
    model_step_2 = str(uuid4())
    await emit(
        7,
        AgentEventType.MODEL_STARTED,
        {"ordinal": 3, "kind": "model", "name": "model"},
        step_id=model_step_2,
    )
    await emit(
        8,
        AgentEventType.MODEL_COMPLETED,
        {"input_tokens": 12, "output_tokens": 6},
        step_id=model_step_2,
    )
    # 第二轮无决策摘要（模型未产生公开摘要 → decision 为 None，不伪造）
    # 终态投影要求 token 与 run 累计一致（两轮 MODEL_COMPLETED 累计 22/11）
    await emit(
        9,
        AgentEventType.RUN_COMPLETED,
        {
            "output": "构建已修复",
            "tool_call_count": 1,
            "input_tokens": 22,
            "output_tokens": 11,
            "cached_tokens": 0,
        },
    )
    return run_id


async def _add_execution(db, run_id: str) -> None:
    """直接写入脱敏前的执行事实行（模拟已完成的命令执行）。"""
    import json

    from personal_assistant.core.models import AgentToolExecution
    from personal_assistant.core.timeutil import utcnow

    arguments = {
        "project_id": 1,
        "command": ["npm", "run", "build"],
        "api_token": "secret-token-value",
        "path": "C:/Users/someone/project",
    }
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    db.add(
        AgentToolExecution(
            id=str(uuid4()),
            run_id=run_id,
            step_id=None,
            tool_call_id="tc-1",
            tool_name="run_whitelisted_command",
            tool_version="1.0.0",
            arguments_json=arguments,
            arguments_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            risk_level="confirm",
            required_capabilities_json=["process.execute"],
            approval_id=None,
            status="succeeded",
            attempt_count=1,
            started_at=utcnow(),
            output_json={"returncode": 0, "verified": True},
        )
    )
    await db.commit()


async def test_execution_detail_flag_disabled(client, db, monkeypatch):
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    run_id = await _make_run_with_events(db)
    await db.commit()
    resp = await client.get(f"/agent-runs/{run_id}/execution-detail")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"


async def test_execution_detail_turns_and_decision_summaries(
    client, db, monkeypatch
):
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(cfg, "coding_execution_detail_enabled", True)
    run_id = await _make_run_with_events(db)
    await db.commit()

    resp = await client.get(f"/agent-runs/{run_id}/execution-detail")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["final_answer"] == "构建已修复"
    assert len(body["turns"]) == 2

    first, second = body["turns"]
    # 第一轮：公开决策摘要 + 工具事实
    assert first["decision"]["goal"] == "修复构建失败"
    assert first["decision"]["method"].startswith("本轮决策")
    assert [tool["name"] for tool in first["tools"]] == [
        "run_whitelisted_command",
        "run_whitelisted_command",
    ]
    # 第二轮：无公开摘要 → None（不伪造），且无命令
    assert second["decision"] is None
    assert second["executions"] == []


async def test_execution_detail_redacts_arguments(client, db, monkeypatch):
    """命令参数脱敏：敏感键与绝对路径不以原文进入响应（零容忍）。"""
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(cfg, "coding_execution_detail_enabled", True)
    run_id = await _make_run_with_events(db)
    await _add_execution(db, run_id)
    await db.commit()

    resp = await client.get(f"/agent-runs/{run_id}/execution-detail")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    executions = body["turns"][0]["executions"]
    assert len(executions) == 1
    raw = str(body)
    assert "secret-token-value" not in raw, "敏感参数泄露"
    assert "C:/Users/someone" not in raw, "绝对路径泄露"
    args = executions[0]["arguments"]
    assert args["api_token"] == "[REDACTED]"
    assert args["path"] == "[PATH]"
    # 命令本身保留结构（公开事实）
    assert args["command"] == ["npm", "run", "build"]
