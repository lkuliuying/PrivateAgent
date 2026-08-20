"""v0.6.0 C5：进程重启/owner lock/orphan run 与 legacy 兼容覆盖。

覆盖（C5 任务 3/4，C0 契约 §7/§8）：
- 进程重启后 project-bound running run 失败关闭，plan/artifacts 保留（事实不丢）；
- reconcile 幂等，不重复执行副作用；
- SSE 断线不取消 run（无替代 run、无 cancel 副作用）；
- 旧 session / AgentTask 不受新关系影响；flag 全开时 legacy run 仍走 legacy。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, update

from personal_assistant.agents.contracts import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    ModelResponse,
    TokenUsage,
)
from personal_assistant.agents.recovery import reconcile_orphaned_agent_runs
from personal_assistant.agents.repository import AgentRunRepository
from personal_assistant.core.models import (
    AgentRun,
    AgentRunArtifact,
    AgentTask,
    Project,
    ProjectWorkspace,
    RunPlanItem,
)


@pytest.fixture(autouse=True)
def _inject_immediate_model():
    """注入立即完成的模型，避免触发真实模型调用与长时间后台任务。"""
    from personal_assistant.api.routes_agent_runs import get_agent_model_client
    from personal_assistant.main_api import app

    class _ImmediateModel:
        async def complete(self, request, *, cancellation):
            del request, cancellation
            return ModelResponse(
                text="C5 测试回答",
                usage=TokenUsage(input_tokens=4, output_tokens=2, cached_tokens=0),
                provider="fake",
                model="fake-model",
                request_id="fake-request",
                latency_ms=0.5,
            )

    app.dependency_overrides[get_agent_model_client] = lambda: _ImmediateModel()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)


async def _cleanup_run(run_id: str) -> None:
    """删除测试创建的 run（级联 events/plan/artifacts），保持共享测试库干净。"""
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as session:
        await session.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await session.commit()


async def _enable_all_flags(monkeypatch):
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", True)
    monkeypatch.setattr(settings, "agent_run_event_stream_enabled", True)


# ===========================================================================
# C5 任务 3：进程重启 → running run 失败关闭，plan/artifacts 事实保留
# ===========================================================================


@pytest.mark.asyncio
async def test_project_bound_run_reconciled_after_restart_keeps_plan(db):
    """进程重启后 project-bound running run → failed；plan/artifacts 保留为事实。"""
    # 先清场，避免其他测试残留的 running run 干扰全局计数
    await reconcile_orphaned_agent_runs(db)

    project = Project(name="restart-test", root_path="/tmp/restart-test")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    project_id_value = project.id  # reconcile 的 rollback 会过期 ORM 对象，先捕获 id
    workspace = ProjectWorkspace(
        project_id=project.id,
        kind="root",
        root_path="/tmp/restart-test",
        root_path_sha256="a" * 64,
        status="active",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    workspace_id_value = workspace.id

    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(
        run_id=run_id,
        limits=AgentRunLimits(),
        project_id=project.id,
        workspace_id=workspace.id,
        base_head_sha="a" * 40,
        base_branch_name="main",
        base_git_dirty=False,
        model_profile_id="local-coder",
        reasoning_effort="high",
        permission_mode="confirm",
        permission_snapshot_json={"mode": "confirm"},
        client_request_id=str(uuid4()),
    )
    await repository.record_event(
        AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
    )
    # 模拟进程崩溃前状态：run 正在运行，且已写入真实计划与产物
    await db.execute(
        update(AgentRun).where(AgentRun.id == run_id).values(status="running")
    )
    item_id = str(uuid4())
    db.add(
        RunPlanItem(
            id=item_id,
            run_id=run_id,
            plan_version=1,
            item_key="fix_bug",
            ordinal=1,
            title="修复缺陷",
            status="in_progress",
        )
    )
    artifact_id = str(uuid4())
    db.add(
        AgentRunArtifact(
            id=artifact_id,
            run_id=run_id,
            kind="summary",
            title="重启前产物",
            rel_path=None,
            step_id=None,
            content_sha256="b" * 64,
        )
    )
    await db.commit()

    try:
        # 重启后首次启动 reconcile：running run 失败关闭
        result = await reconcile_orphaned_agent_runs(db)
        assert result.failed_runs == 1

        run = await db.get(AgentRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "process_restarted"

        # 计划与产物是事实，保留（不回退到前端启发式状态，不删除）
        item = await db.get(RunPlanItem, item_id)
        assert item is not None and item.status == "in_progress"
        artifact = await db.get(AgentRunArtifact, artifact_id)
        assert artifact is not None and artifact.kind == "summary"

        # reconcile 幂等：再次执行不重复副作用
        again = await reconcile_orphaned_agent_runs(db)
        assert again.failed_runs == 0
        assert again.failed_executions == 0
    finally:
        # 与 test_agent_recovery 一致：全部用 db session 清理；用捕获的 id 值，
        # 避免访问已被 reconcile rollback 过期的 ORM 属性（sync 懒加载 MissingGreenlet）
        await db.execute(delete(RunPlanItem).where(RunPlanItem.run_id == run_id))
        await db.execute(delete(AgentRunArtifact).where(AgentRunArtifact.run_id == run_id))
        await db.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await db.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id_value)
        )
        await db.execute(delete(Project).where(Project.id == project_id_value))
        await db.commit()


# ===========================================================================
# C5 任务 3：SSE 断线不取消 run（C0 §8 零容忍：断线后创建替代 run / 取消）
# ===========================================================================


async def test_sse_disconnect_does_not_cancel_run(client, monkeypatch):
    """客户端断开 SSE 后 run 不被取消，也不产生替代 run。"""
    await _enable_all_flags(monkeypatch)

    resp = await client.post(
        "/agent-runs",
        json={"message": "disconnect-test", "client_request_id": str(uuid4())},
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    # 连接 SSE 后立即断开（AbortController 语义）
    async with client.stream(
        "GET", f"/agent-runs/{run_id}/events/stream?after_sequence=0"
    ) as stream:
        assert stream.status_code == 200

    # 断线不取消 run：不出现 cancelled，也无取消请求
    resp = await client.get(f"/agent-runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] != "cancelled"
    assert body["cancel_requested_at"] is None

    # 同一 client_request_id 重试 → 幂等重放同一 run，不创建替代 run
    resp2 = await client.post(
        "/agent-runs",
        json={"message": "disconnect-test", "client_request_id": resp.json()["client_request_id"]},
    )
    assert resp2.status_code == 202, resp2.text
    assert resp2.json()["id"] == run_id
    await _cleanup_run(run_id)


# ===========================================================================
# C5 任务 4：旧 session 与 AgentTask 不受新关系影响
# ===========================================================================


async def test_legacy_session_and_agent_task_unaffected_by_new_relations(
    client, monkeypatch
):
    """flag 全开时：legacy session 字段全 null，legacy run 正常，AgentTask 正常。"""
    await _enable_all_flags(monkeypatch)

    # legacy session：无 kind/绑定字段（契约 §6.2：旧 session 响应 kind=legacy）
    resp = await client.post("/sessions", json={"title": "旧会话"})
    assert resp.status_code == 201, resp.text
    legacy_session = resp.json()
    assert legacy_session["kind"] == "legacy"
    assert legacy_session["project_id"] is None
    assert legacy_session["workspace_id"] is None
    session_id = legacy_session["id"]

    # 旧 session 读回不变
    resp = await client.get(f"/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "legacy"

    # legacy run（无 coding 字段）在 flag 全开时仍走 legacy 模式
    resp = await client.post(
        "/agent-runs",
        json={"message": "legacy under flags on", "client_request_id": str(uuid4())},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["project_id"] is None
    assert body["workspace_id"] is None
    run_id = body["id"]

    # AgentTask 独立于新关系：创建与读取不受 project/workspace 影响
    task = AgentTask(
        title="旧任务",
        goal="不受新关系影响",
        status="planned",
    )
    db_task = None
    try:
        from personal_assistant.core.db import async_session_factory

        async with async_session_factory() as session:
            session.add(task)
            await session.commit()
            await session.refresh(task)
            db_task = task
            loaded = await session.get(AgentTask, task.id)
            assert loaded is not None and loaded.status == "planned"
    finally:
        if db_task is not None:
            from personal_assistant.core.db import async_session_factory

            async with async_session_factory() as session:
                await session.execute(
                    delete(AgentTask).where(AgentTask.id == db_task.id)
                )
                await session.commit()

    await _cleanup_run(run_id)
