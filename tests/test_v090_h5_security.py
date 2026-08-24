"""v0.9.0 H5 契约测试：三档权限反向安全与可靠性（计划 §8 H5）。

反向安全（零容忍防线验证）：
- full_access 硬边界：远程外发/外部 MCP 能力工具永不自动批准；
- 授予中途撤销/到期 → 下一次工具调用立即降级为逐次审批（竞态安全）；
- full_access 自动批准仍保留完整审批事实链（审计不跳过）；
- workspace 与 full_access 能力位互相独立（不互相别名）；
- 上下文预算负数/超限域防护（不允许 >100 或负数裸值进入呈现）。
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from personal_assistant.agents.approvals import FullAccessAutoApproveConsumer
from personal_assistant.agents.contracts import ToolCall
from personal_assistant.agents.tools import (
    ToolCapability,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
)
from personal_assistant.config import settings as cfg
from personal_assistant.core.context_budget import ContextBudget, UsageSource
from personal_assistant.core.full_access import FullAccessGrantService
from personal_assistant.core.models import ChatSession, Project
from personal_assistant.core.timeutil import utcnow


async def _noop_executor(arguments, cancellation):
    return {"ok": True}


def _spec(name: str, capabilities: set) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1.0.0",
        description="test tool",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset(capabilities),
        timeout_ms=5000,
        max_output_bytes=1024,
        idempotency=ToolIdempotency.NON_IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.NONE,
        executor=_noop_executor,
    )


async def _make_session_with_grant(db, monkeypatch, *, ttl_minutes: int = 240):
    monkeypatch.setattr(cfg, "coding_full_access_enabled", True)
    monkeypatch.setattr(cfg, "coding_full_access_ttl_minutes", ttl_minutes)
    project = Project(name=f"h5-{uuid4().hex[:6]}", root_path="C:/h5-fake")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    session = ChatSession(
        title="h5-session", project_id=project.id, kind="coding"
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    grant = await FullAccessGrantService(db).grant(
        session_id=session.id, project_id=project.id
    )
    await db.commit()
    return project, session, grant


async def _make_run(db, session_id: int) -> str:
    """创建真实 run 记录（审批表 run_id 外键要求）。"""
    from personal_assistant.agents.contracts import AgentRunLimits
    from personal_assistant.agents.repository import AgentRunRepository

    run_id = str(uuid4())
    await AgentRunRepository(db).create_run(
        run_id=run_id, limits=AgentRunLimits(), session_id=session_id
    )
    await db.commit()
    return run_id


async def test_full_access_hard_blocks_network_and_mcp(db, monkeypatch):
    """硬边界：NETWORK_FETCH / EXTERNAL_MCP 工具永不自动批准。"""
    project, session, grant = await _make_session_with_grant(db, monkeypatch)
    consumer = FullAccessAutoApproveConsumer(
        db, run_id=str(uuid4()), session_id=session.id
    )
    call = ToolCall(id="call-net", name="fetch_url", arguments={})

    net_spec = _spec("fetch_url", {ToolCapability.NETWORK_FETCH})
    result = await consumer.consume(net_spec, call, {})
    assert result is None, "远程外发工具不得自动批准"

    mcp_spec = _spec("mcp_tool", {ToolCapability.EXTERNAL_MCP})
    result = await consumer.consume(mcp_spec, call, {})
    assert result is None, "外部 MCP 工具不得自动批准"

    from sqlalchemy import delete

    from personal_assistant.core.models import FullAccessGrant

    await db.execute(
        delete(FullAccessGrant).where(FullAccessGrant.session_id == session.id)
    )
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.execute(delete(Project).where(Project.id == project.id))
    await db.commit()


async def test_full_access_revoked_mid_run_downgrades(db, monkeypatch):
    """竞态安全：授予在执行中途被撤销 → 下一次调用降级为逐次审批。"""
    project, session, grant = await _make_session_with_grant(db, monkeypatch)
    run_id = await _make_run(db, session.id)
    consumer = FullAccessAutoApproveConsumer(
        db, run_id=run_id, session_id=session.id
    )
    fs_spec = _spec("write_file", {ToolCapability.FILESYSTEM_WRITE})
    call = ToolCall(id="call-1", name="write_file", arguments={})

    # 授予有效 → 自动批准
    assert await consumer.consume(fs_spec, call, {}) is not None

    # 中途撤销
    svc = FullAccessGrantService(db)
    assert await svc.revoke(grant.id, reason="user_revoke") is True
    await db.commit()

    # 下一次调用 → 降级（返回 None → 回落审批请求链）
    call2 = ToolCall(id="call-2", name="write_file", arguments={})
    assert await consumer.consume(fs_spec, call2, {}) is None

    from sqlalchemy import delete

    from personal_assistant.core.models import (
        AgentRun as AgentRunRecord,
    )
    from personal_assistant.core.models import FullAccessGrant, ToolApproval

    await db.execute(
        delete(FullAccessGrant).where(FullAccessGrant.session_id == session.id)
    )
    await db.execute(delete(ToolApproval).where(ToolApproval.run_id == run_id))
    await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.execute(delete(Project).where(Project.id == project.id))
    await db.commit()


async def test_full_access_expiry_downgrades(db, monkeypatch):
    """到期失效：expires_at 过期后自动降级（不需要显式撤销）。"""
    project, session, grant = await _make_session_with_grant(
        db, monkeypatch, ttl_minutes=60
    )
    # 把到期时间拨到过去
    grant.expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()

    consumer = FullAccessAutoApproveConsumer(
        db, run_id=str(uuid4()), session_id=session.id
    )
    fs_spec = _spec("write_file", {ToolCapability.FILESYSTEM_WRITE})
    call = ToolCall(id="call-x", name="write_file", arguments={})
    assert await consumer.consume(fs_spec, call, {}) is None

    from sqlalchemy import delete

    from personal_assistant.core.models import FullAccessGrant

    await db.execute(
        delete(FullAccessGrant).where(FullAccessGrant.session_id == session.id)
    )
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.execute(delete(Project).where(Project.id == project.id))
    await db.commit()


async def test_full_access_auto_approval_keeps_audit_trail(db, monkeypatch):
    """自动批准仍创建完整审批事实（pending→approved→consumed），审计不跳过。"""
    project, session, grant = await _make_session_with_grant(db, monkeypatch)
    run_id = await _make_run(db, session.id)
    consumer = FullAccessAutoApproveConsumer(db, run_id=run_id, session_id=session.id)
    fs_spec = _spec("write_file", {ToolCapability.FILESYSTEM_WRITE})
    call = ToolCall(id="call-audit", name="write_file", arguments={})
    approval_id = await consumer.consume(fs_spec, call, {})
    assert approval_id is not None

    from sqlalchemy import select

    from personal_assistant.core.models import ToolApproval

    record = (
        await db.execute(select(ToolApproval).where(ToolApproval.id == approval_id))
    ).scalar_one()
    assert record.status == "consumed", "自动批准的审批记录必须走完事实链"

    from sqlalchemy import delete

    from personal_assistant.core.models import AgentRun as AgentRunRecord
    from personal_assistant.core.models import FullAccessGrant

    await db.execute(delete(ToolApproval).where(ToolApproval.id == approval_id))
    await db.execute(
        delete(FullAccessGrant).where(FullAccessGrant.session_id == session.id)
    )
    await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.execute(delete(Project).where(Project.id == project.id))
    await db.commit()


def test_workspace_and_full_access_capabilities_independent():
    """能力位互相独立，不是别名（零容忍：不得冒充）。"""
    from personal_assistant.api.routes_health import RuntimeCapabilities

    fields = RuntimeCapabilities.model_fields
    assert "coding_workspace_auto_approve" in fields
    assert "coding_full_access_supported" in fields
    # 两个字段默认都关闭，且是不同字段（非别名）
    assert fields["coding_workspace_auto_approve"] is not fields[
        "coding_full_access_supported"
    ]
    assert fields["coding_workspace_auto_approve"].default is False
    assert fields["coding_full_access_supported"].default is False


def test_context_budget_domain_protections():
    """预算域防护：百分比封顶 100、不可用无百分比（无负数/无 >100 裸值）。"""
    over = ContextBudget(
        used_tokens=999_999,
        max_context_tokens=1000,
        reserved_output_tokens=256,
        source=UsageSource.PROVIDER_USAGE,
        compaction_state="idle",
    )
    assert over.usage_percent == 100

    zero_window = ContextBudget(
        used_tokens=100,
        max_context_tokens=0,
        reserved_output_tokens=0,
        source=UsageSource.UNAVAILABLE,
        compaction_state="idle",
    )
    assert zero_window.usage_percent is None

    normal = ContextBudget(
        used_tokens=500,
        max_context_tokens=1000,
        reserved_output_tokens=256,
        source=UsageSource.PROVIDER_USAGE,
        compaction_state="idle",
    )
    assert 0 <= normal.usage_percent <= 100
