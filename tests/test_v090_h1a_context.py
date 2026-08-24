"""v0.9.0 H1-A 契约测试：上下文 budget/压缩（H0 §7）。

覆盖：
- flag 关闭 → 409；会话无执行 → 不可用+原因（不伪造百分比）；
- provider usage 真实计量与 0..100 域（超限封顶 + budget_exceeded）；
- 阈值压缩：保留最近消息、删除最旧、发 durable 事件；
- run 创建链：压缩后仍超限 → 409 停止新执行（不静默截断）。
"""

from __future__ import annotations

from test_v070_permissions import _create_coding_env, _post_coding_run

from personal_assistant.config import settings as cfg


def _enable_budget(monkeypatch) -> None:
    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(cfg, "coding_context_budget_enabled", True)


async def _create_session_with_run(client, monkeypatch, tmp_path, input_tokens: int):
    from personal_assistant.api import routes_agent_runs
    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import AgentRun as AgentRunRecord

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "project_bound_runs_enabled", True
    )

    def fake_start(**kwargs) -> None:
        pass

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(client, env, permission_mode="confirm")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    async with async_session_factory() as db:
        run = await db.get(AgentRunRecord, run_id)
        run.input_tokens = input_tokens
        await db.commit()
        # 模拟真实已启动的 run：记录 run.started（压缩事件才能挂载）
        from personal_assistant.agents.contracts import (
            AgentEvent,
            AgentEventType,
        )
        from personal_assistant.agents.repository import AgentRunRepository

        await AgentRunRepository(db).record_event(
            AgentEvent(
                run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED
            )
        )
    return env, run_id


async def test_budget_flag_disabled(client, monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await client.get(f"/sessions/{env['session_id']}/context-budget")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "coding_mode_disabled"


async def test_budget_unavailable_without_usage(client, monkeypatch, tmp_path):
    """无执行记录 → 不可用 + 原因；绝不伪造百分比。"""
    _enable_budget(monkeypatch)
    env = await _create_coding_env(client, tmp_path)
    resp = await client.get(f"/sessions/{env['session_id']}/context-budget")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "unavailable"
    assert body["usage_percent"] is None
    assert body["error_reason"]
    assert body["compaction_state"] == "idle"
    assert body["reserved_output_tokens"] == cfg.coding_context_reserved_output_tokens


async def test_budget_real_usage_percent(client, monkeypatch, tmp_path):
    """provider usage 真实计量：百分比 = used/max（0..100 域）。"""
    _enable_budget(monkeypatch)
    env, run_id = await _create_session_with_run(
        client, monkeypatch, tmp_path, input_tokens=1000
    )
    resp = await client.get(f"/sessions/{env['session_id']}/context-budget")
    body = resp.json()
    assert body["source"] == "provider_usage"
    assert body["used_tokens"] == 1000
    assert body["max_context_tokens"] == cfg.llm_context_length
    expected = round(1000 * 100 / cfg.llm_context_length)
    assert body["usage_percent"] == min(expected, 100)


async def test_budget_caps_at_100_with_error_code(client, monkeypatch, tmp_path):
    """超限封顶 100 并携带 budget_exceeded（禁止 >100 裸数值）。"""
    _enable_budget(monkeypatch)
    huge = cfg.llm_context_length * 2
    env, run_id = await _create_session_with_run(
        client, monkeypatch, tmp_path, input_tokens=huge
    )
    resp = await client.get(f"/sessions/{env['session_id']}/context-budget")
    body = resp.json()
    assert body["usage_percent"] == 100
    assert body["error_code"] == "budget_exceeded"


async def test_compaction_keeps_recent_and_emits_events(
    client, monkeypatch, tmp_path
):
    """阈值压缩：删最旧留最近，压缩事件入 durable 事件流。"""
    from sqlalchemy import select

    from personal_assistant.api import routes_agent_runs
    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.history import MessageRepository
    from personal_assistant.core.models import AgentRunEvent as EventRecord

    _enable_budget(monkeypatch)
    monkeypatch.setattr(cfg, "coding_context_compaction_threshold", 50)
    monkeypatch.setattr(cfg, "coding_context_keep_recent_messages", 4)
    # 大用量触发阈值（默认窗口 8192，2000/8192 < 50% → 用更大值）
    env, run_id = await _create_session_with_run(
        client, monkeypatch, tmp_path, input_tokens=cfg.llm_context_length
    )
    session_id = env["session_id"]

    # 造 12 条历史消息
    async with async_session_factory() as db:
        repo = MessageRepository(db)
        for i in range(12):
            await repo.add(session_id, "user", f"历史消息 {i}")

    # 再发起一次 run → 创建链触发压缩
    def fake_start(**kwargs) -> None:
        pass

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    resp = await _post_coding_run(client, env, permission_mode="confirm")
    assert resp.status_code == 202, resp.text

    async with async_session_factory() as db:
        from personal_assistant.core.models import Message

        rows = (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.id.asc())
            )
        ).scalars().all()
        # 12 条压缩到保留 4 条，且保留的是最新（最旧被删）
        assert len(rows) == 4
        assert rows[0].content == "历史消息 8"

        events = (
            await db.execute(
                select(EventRecord).where(
                    EventRecord.event_type.in_(
                        [
                            "context.compaction_started",
                            "context.compaction_completed",
                        ]
                    )
                )
            )
        ).scalars().all()
        assert len(events) >= 2

    # 压缩后查询状态为 compacted
    resp = await client.get(f"/sessions/{session_id}/context-budget")
    assert resp.json()["compaction_state"] == "compacted"


async def test_run_create_stops_when_budget_exceeded(client, monkeypatch, tmp_path):
    """压缩后仍超限（无可压缩历史）→ 409 停止新执行。"""
    from personal_assistant.api import routes_agent_runs

    _enable_budget(monkeypatch)
    env, run_id = await _create_session_with_run(
        client, monkeypatch, tmp_path, input_tokens=cfg.llm_context_length * 2
    )

    def fake_start(**kwargs) -> None:
        raise AssertionError("预算超限不得启动新执行")

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    resp = await _post_coding_run(client, env, permission_mode="confirm")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "budget_exceeded"
