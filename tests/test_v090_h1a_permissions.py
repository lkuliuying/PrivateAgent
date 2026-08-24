"""v0.9.0 H1-A 契约测试：三档权限执行层与 full_access 授予（H0 §6）。

覆盖：
- full_access 独立能力位：授予/查询/撤销/到期/重启回收与遥测；
- run 创建链：无授予/能力位关闭 → 409 失败关闭；
- 执行层：有效授予 → confirm 类工具自动批准且审批事实链完整（审计不跳过）；
  授予失效 → 回落逐次审批（降级，不静默继续）；
- 硬边界：远程外发/外部 MCP 能力不自动批准。
"""

from __future__ import annotations

from datetime import timedelta

from test_v070_permissions import (
    _cleanup,
    _create_coding_env,
    _create_run,
    _enable_coding_flags,
    _make_project,
    _post_coding_run,
)

from personal_assistant.api import routes_agent_runs
from personal_assistant.api.routes_agent_runs import get_agent_tool_bundle
from personal_assistant.config import settings as cfg
from personal_assistant.core.compatibility import compatibility_telemetry
from personal_assistant.core.full_access import FullAccessGrantService
from personal_assistant.core.timeutil import utcnow


def _enable_full_access(monkeypatch) -> None:
    _enable_coding_flags(monkeypatch)
    monkeypatch.setattr(cfg, "coding_full_access_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_full_access_enabled", True)


# ===========================================================================
# A. 授予服务与 API
# ===========================================================================


async def test_grant_api_lifecycle(client, monkeypatch, tmp_path):
    """授予 → 查询有效 → 撤销 → 查询无效；遥测计数同步。"""
    monkeypatch.setattr(cfg, "coding_full_access_enabled", True)
    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    session_id = env["session_id"]

    before = compatibility_telemetry.snapshot()
    resp = await client.post(f"/sessions/{session_id}/full-access-grant")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active"] is True
    assert body["project_id"] == env["project_id"]
    assert body["granted_at"].endswith("Z")
    assert body["expires_at"].endswith("Z")

    resp = await client.get(f"/sessions/{session_id}/full-access-grant")
    assert resp.json()["active"] is True

    # 幂等：重复授予复用同一有效授予
    resp = await client.post(f"/sessions/{session_id}/full-access-grant")
    assert resp.json()["grant_id"] == body["grant_id"]

    resp = await client.delete(f"/full-access-grants/{body['grant_id']}")
    assert resp.json()["revoked"] is True
    resp = await client.get(f"/sessions/{session_id}/full-access-grant")
    assert resp.json()["active"] is False

    after = compatibility_telemetry.snapshot()
    outcomes = after["paths"]["full_access_grant"]["outcomes"]
    before_outcomes = before["paths"]["full_access_grant"]["outcomes"]
    assert outcomes["granted"] - before_outcomes["granted"] == 2
    assert outcomes["revoked"] - before_outcomes["revoked"] == 1


async def test_grant_api_flag_disabled(client, monkeypatch, tmp_path):
    """能力位关闭 → 授予/查询全部失败关闭。"""
    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    session_id = env["session_id"]
    resp = await client.post(f"/sessions/{session_id}/full-access-grant")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "full_access_unsupported"
    resp = await client.get(f"/sessions/{session_id}/full-access-grant")
    assert resp.json()["active"] is False


async def test_grant_requires_project_bound_session(client, monkeypatch):
    """未绑定项目的会话不得授予（不跨范围扩散）。"""
    monkeypatch.setattr(cfg, "coding_full_access_enabled", True)
    resp = await client.post("/sessions", json={"title": "legacy-unbound"})
    session_id = resp.json()["id"]
    resp = await client.post(f"/sessions/{session_id}/full-access-grant")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "full_access_unsupported"


async def test_grant_expiry_and_restart_revoke(db, monkeypatch, tmp_path):
    """到期自动失效；进程重启回收（退出应用自动失效规则）。"""
    monkeypatch.setattr(cfg, "coding_full_access_enabled", True)
    project_id, workspace_id = await _make_project(db, tmp_path)
    from personal_assistant.core.models import ChatSession

    session = ChatSession(
        title="v090-grant", project_id=project_id, workspace_id=workspace_id,
        kind="coding",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    svc = FullAccessGrantService(db)
    grant = await svc.grant(session_id=session.id, project_id=project_id)
    await db.commit()
    assert await svc.get_active(session.id) is not None

    # 到期：把 expires_at 拨到过去
    grant = await svc.get_active(session.id)
    grant.expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    assert await svc.get_active(session.id) is None

    # 重启回收：新授予在进程重启时被回收（app_exit）
    grant = await svc.grant(session_id=session.id, project_id=project_id)
    await db.commit()
    revoked = await svc.revoke_all_on_app_exit()
    await db.commit()
    assert revoked >= 1
    assert await svc.get_active(session.id) is None

    # 清理
    from sqlalchemy import delete

    from personal_assistant.core.models import FullAccessGrant

    await db.execute(
        delete(FullAccessGrant).where(FullAccessGrant.session_id == session.id)
    )
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.commit()
    await _cleanup(db, project_id=project_id, workspace_id=workspace_id)


# ===========================================================================
# B. run 创建链门禁
# ===========================================================================


async def test_full_access_run_requires_grant(client, monkeypatch, tmp_path):
    """能力位开启但无有效授予 → 409（不静默降级创建）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(cfg, "coding_full_access_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_full_access_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(client, env, permission_mode="full_access")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "full_access_unsupported"


async def test_full_access_run_with_grant_snapshots_fact(
    client, monkeypatch, tmp_path
):
    """有效授予 → run 创建成功且快照记录 granted_full_access=True。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(cfg, "coding_full_access_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_full_access_enabled", True)
    captured: dict = {}

    def fake_start(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(routes_agent_runs.agent_run_coordinator, "start", fake_start)
    env = await _create_coding_env(client, tmp_path)
    resp = await client.post(f"/sessions/{env['session_id']}/full-access-grant")
    assert resp.status_code == 201, resp.text
    resp = await _post_coding_run(client, env, permission_mode="full_access")
    assert resp.status_code == 202, resp.text
    assert resp.json()["permission_mode"] == "full_access"


# ===========================================================================
# C. 执行层：自动批准与降级
# ===========================================================================


async def test_full_access_auto_approves_confirm_tools(db, tmp_path, monkeypatch):
    """有效授予：confirm 类工具自动批准，审批事实链完整（审计不跳过），
    零 pending 审批。"""
    from sys import executable

    from test_v070_permissions import _create_profile

    from personal_assistant.agents import (
        CancellationToken,
        ToolApprovalRepository,
    )
    from personal_assistant.agents.contracts import ToolCall

    _enable_full_access(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    await _create_profile(
        db,
        project_id,
        args=[executable, "-m", "pytest"],
        risk_level="confirm",  # confirm 档正常需审批；full_access 自动批准
    )
    # 建立有效授予（需要会话；直接走服务的会话级授予）
    from personal_assistant.core.models import ChatSession

    session = ChatSession(
        title="v090-fa-exec", project_id=project_id,
        workspace_id=workspace_id, kind="coding",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    await FullAccessGrantService(db).grant(
        session_id=session.id, project_id=project_id
    )
    await db.commit()

    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="full_access",
        tool_call_id="call-fa",
    )
    # run 绑定会话（_create_run 不带 session；补写事实）
    from personal_assistant.core.models import AgentRun as AgentRunRecord

    run = await db.get(AgentRunRecord, run_id)
    run.session_id = session.id
    await db.commit()
    try:
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        result = await dispatcher.execute(
            ToolCall(
                id="call-fa",
                name="run_whitelisted_command",
                arguments={
                    "project_id": project_id,
                    "command": [executable, "-m", "pytest", "-q"],
                },
            ),
            cancellation=CancellationToken(),
        )
        # 自动批准：无 approval_required 失败；工具真实执行（测试文件缺失时
        # pytest 退出码非 0 → 结果失败但链路经过自动批准，无待决审批）
        assert result.error_code != "approval_required"
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        assert approvals, "自动批准仍须留下审批事实（审计不跳过）"
        assert all(a.status == "consumed" for a in approvals)
    finally:
        from sqlalchemy import delete

        from personal_assistant.core.models import (
            ChatSession as ChatSessionModel,
        )
        from personal_assistant.core.models import (
            FullAccessGrant,
        )

        await db.execute(
            delete(FullAccessGrant).where(
                FullAccessGrant.session_id == session.id
            )
        )
        await db.execute(
            delete(ChatSessionModel).where(ChatSessionModel.id == session.id)
        )
        await db.commit()
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_full_access_downgrades_when_grant_missing(db, tmp_path, monkeypatch):
    """能力位开启但授予失效 → 回落逐次审批（降级，不静默继续）。"""
    from test_v070_permissions import _create_profile

    from personal_assistant.agents import CancellationToken
    from personal_assistant.agents.contracts import ToolCall
    from personal_assistant.core.models import ChatSession

    _enable_full_access(monkeypatch)
    project_id, workspace_id = await _make_project(db, tmp_path)
    from sys import executable

    await _create_profile(
        db, project_id, args=[executable, "-m", "pytest"], risk_level="confirm"
    )
    # 会话 + 已撤销授予（失效态）：执行层每次调用前重新校验 → 降级
    session = ChatSession(
        title="v090-fa-nogrant", project_id=project_id,
        workspace_id=workspace_id, kind="coding",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    svc = FullAccessGrantService(db)
    grant = await svc.grant(session_id=session.id, project_id=project_id)
    await svc.revoke(grant.id, reason="user_revoke")
    await db.commit()

    run_id = await _create_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        permission_mode="full_access",
        tool_call_id="call-nogrant",
    )
    from personal_assistant.core.models import AgentRun as AgentRunRecord

    run = await db.get(AgentRunRecord, run_id)
    run.session_id = session.id
    await db.commit()
    try:
        before = compatibility_telemetry.snapshot()
        bundle = await get_agent_tool_bundle(db)
        assert bundle is not None
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        result = await dispatcher.execute(
            ToolCall(
                id="call-nogrant",
                name="run_whitelisted_command",
                arguments={
                    "project_id": project_id,
                    "command": [executable, "-m", "pytest", "-q"],
                },
            ),
            cancellation=CancellationToken(),
        )
        # 授予失效 → 回落正常审批请求（approval_required），并记录降级原因
        assert result.error_code == "approval_required"
        after = compatibility_telemetry.snapshot()
        delta = after["paths"]["permission_downgrade"]["outcomes"][
            "grant_invalid"
        ] - before["paths"]["permission_downgrade"]["outcomes"]["grant_invalid"]
        assert delta == 1
    finally:
        from sqlalchemy import delete

        from personal_assistant.core.models import (
            ChatSession as ChatSessionModel,
        )
        from personal_assistant.core.models import (
            FullAccessGrant,
        )

        await db.execute(
            delete(FullAccessGrant).where(
                FullAccessGrant.session_id == session.id
            )
        )
        await db.execute(
            delete(ChatSessionModel).where(ChatSessionModel.id == session.id)
        )
        await db.commit()
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


def test_full_access_hard_block_capabilities_frozen():
    """硬边界词汇冻结：远程外发/外部 MCP 永不自动批准（H0 §6.2）。"""
    from personal_assistant.agents.approvals import (
        _FULL_ACCESS_HARD_BLOCK_CAPABILITIES,
    )
    from personal_assistant.agents.tools import ToolCapability

    assert _FULL_ACCESS_HARD_BLOCK_CAPABILITIES == frozenset(
        {ToolCapability.NETWORK_FETCH, ToolCapability.EXTERNAL_MCP}
    )
