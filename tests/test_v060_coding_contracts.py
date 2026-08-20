"""v0.6.0 Coding Agent 契约测试（C0 §11 冻结清单）。

这些测试定义 v0.6.0 新增的公开契约。第一批提交以 ``xfail`` 形态进入，
实现完成后移除 ``xfail`` 标记并保持全绿。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.agents.contracts import ModelResponse, TokenUsage
from personal_assistant.core.models import (
    AgentRun,
    ChatSession,
    Project,
    ProjectWorkspace,
)


@pytest.fixture(autouse=True)
def _inject_immediate_model():
    """所有契约测试注入立即完成的模型，避免触发真实模型调用。"""
    from personal_assistant.api.routes_agent_runs import get_agent_model_client
    from personal_assistant.main_api import app

    class _ImmediateModel:
        async def complete(self, request, *, cancellation):
            del request, cancellation
            return ModelResponse(
                text="契约测试回答",
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
    """删除测试创建的 run（级联 events/plan/artifacts），保持共享测试库干净。

    共享 DB 无事务回滚，coordinator 后台任务在 client teardown 时可能被中断，
    残留 running run 会污染其他文件的全局断言（如 recovery 的孤儿计数），
    因此每个创建 run 的测试必须自清理。
    """
    from sqlalchemy import delete

    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import AgentRun

    async with async_session_factory() as session:
        await session.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await session.commit()


# ===========================================================================
# C0 §11：test_coding_run_rejects_partial_context
# ===========================================================================


async def test_coding_run_rejects_partial_context(client, monkeypatch):
    """Coding 字段只提供一部分 → 422 coding_context_incomplete，零 run 创建。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

    before = len((await client.get("/agent-runs?limit=1000")).json())
    resp = await client.post(
        "/agent-runs",
        json={
            "message": "test",
            "project_id": 1,
            # workspace_id / client_request_id / permission_mode 缺失
        },
    )
    assert resp.status_code == 422
    assert resp.json().get("error_code") == "coding_context_incomplete"
    after = len((await client.get("/agent-runs?limit=1000")).json())
    assert after == before


# ===========================================================================
# C0 §11：test_coding_run_never_uses_most_recent_project
# ===========================================================================


async def test_coding_run_never_uses_most_recent_project(client, monkeypatch, tmp_path):
    """legacy 请求不携带 coding 字段时，不得被绑定到最近项目。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)

    # 创建两个项目（模拟“最近打开”）
    for name, folder in (("recent-a", "a"), ("recent-b", "b")):
        root = str((tmp_path / folder).resolve())
        (tmp_path / folder).mkdir()
        resp = await client.post(
            "/projects",
            json={"name": name, "root_path": root},
        )
        assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/agent-runs",
        json={"message": "legacy request", "client_request_id": str(uuid4())},
    )
    # 不携带 project_id/workspace_id → 按 legacy 处理（不报错也不绑定）
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["project_id"] is None
    assert data["workspace_id"] is None
    await _cleanup_run(data["id"])


# ===========================================================================
# C0 §11：test_session_workspace_mismatch_fails_closed
# ===========================================================================


async def test_session_workspace_mismatch_fails_closed(
    client, monkeypatch, tmp_path
):
    """session 的 project/workspace 与请求不一致 → 409 session_workspace_mismatch。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

    root = str((tmp_path / "p1").resolve())
    (tmp_path / "p1").mkdir()
    resp = await client.post("/projects", json={"name": "p1", "root_path": root})
    project_id = resp.json()["id"]
    resp = await client.post(
        f"/projects/{project_id}/workspaces/root/ensure"
    )
    ws_id = resp.json()["id"]

    # coding session 绑定另一个 workspace（错配）
    resp = await client.post(
        "/sessions",
        json={
            "title": "coding",
            "project_id": project_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    session_id = resp.json()["id"]

    # 请求使用不同的 workspace
    resp = await client.post(
        "/agent-runs",
        json={
            "session_id": session_id,
            "message": "test",
            "project_id": project_id,
            "workspace_id": ws_id + 999999,
            "permission_mode": "confirm",
            "client_request_id": str(uuid4()),
        },
    )
    assert resp.status_code == 409
    assert resp.json().get("error_code") in {
        "session_workspace_mismatch",
        "workspace_not_found",
    }


# ===========================================================================
# C0 §11：test_client_request_id_replays_same_run_once
# ===========================================================================


async def test_client_request_id_replays_same_run_once(client, monkeypatch):
    """相同 client_request_id 重复请求返回原 run（idempotent_replay=true）。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)

    client_id = str(uuid4())
    resp1 = await client.post(
        "/agent-runs",
        json={"message": "same", "client_request_id": client_id},
    )
    assert resp1.status_code == 202, resp1.text
    run_id = resp1.json()["id"]
    assert resp1.json().get("idempotent_replay") is False

    resp2 = await client.post(
        "/agent-runs",
        json={"message": "same", "client_request_id": client_id},
    )
    assert resp2.status_code == 202, resp2.text
    assert resp2.json()["id"] == run_id
    assert resp2.json().get("idempotent_replay") is True
    await _cleanup_run(run_id)


# ===========================================================================
# C0 §11：test_client_request_id_rejects_different_payload
# ===========================================================================


async def test_client_request_id_rejects_different_payload(client, monkeypatch):
    """相同幂等键对应不同请求 → 409 client_request_conflict。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)

    client_id = str(uuid4())
    resp1 = await client.post(
        "/agent-runs",
        json={"message": "payload-a", "client_request_id": client_id},
    )
    assert resp1.status_code == 202, resp1.text

    resp2 = await client.post(
        "/agent-runs",
        json={"message": "payload-b", "client_request_id": client_id},
    )
    assert resp2.status_code == 409
    assert resp2.json().get("error_code") == "client_request_conflict"
    await _cleanup_run(resp1.json()["id"])


# ===========================================================================
# C0 §11：test_workspace_backfill_is_idempotent
# ===========================================================================


async def test_workspace_backfill_is_idempotent(db: AsyncSession):
    """旧项目 ensure_root_workspace 幂等，不重复创建多个 root workspace。"""
    from personal_assistant.core.repo_workspaces import ProjectWorkspaceRepository
    from personal_assistant.core.workspaces import ProjectWorkspaceService

    project = Project(name="backfill", root_path="/tmp/backfill")
    db.add(project)
    await db.commit()
    await db.refresh(project)

    svc = ProjectWorkspaceService(db)
    ws1 = await svc.ensure_root_workspace(project)
    ws2 = await svc.ensure_root_workspace(project)
    assert ws1.id == ws2.id

    rows = await ProjectWorkspaceRepository(db).list_by_project(project.id)
    roots = [r for r in rows if r.kind == "root"]
    assert len(roots) == 1


# ===========================================================================
# C0 §11：test_missing_workspace_path_fails_closed
# ===========================================================================


async def test_missing_workspace_path_fails_closed(client, monkeypatch, tmp_path):
    """workspace 路径缺失 → 409 workspace_unavailable，不自动改绑。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

    root = str((tmp_path / "p1").resolve())
    (tmp_path / "p1").mkdir()
    resp = await client.post("/projects", json={"name": "p1", "root_path": root})
    project_id = resp.json()["id"]
    resp = await client.post(
        f"/projects/{project_id}/workspaces/root/ensure"
    )
    ws_id = resp.json()["id"]

    # 删除路径后创建 coding session 并请求 run
    import shutil

    shutil.rmtree(root)

    resp = await client.post(
        "/sessions",
        json={
            "title": "coding",
            "project_id": project_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    session_id = resp.json()["id"]

    resp = await client.post(
        "/agent-runs",
        json={
            "session_id": session_id,
            "message": "test",
            "project_id": project_id,
            "workspace_id": ws_id,
            "permission_mode": "confirm",
            "client_request_id": str(uuid4()),
        },
    )
    assert resp.status_code == 409
    assert resp.json().get("error_code") == "workspace_unavailable"


# ===========================================================================
# C0 §11：test_plan_rejects_stale_version
# ===========================================================================


async def test_plan_rejects_stale_version(client, monkeypatch):
    """expected_plan_version 过期 → 409 plan_version_conflict。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "plan-test", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]

    # 版本 1
    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [
                {
                    "item_key": "inspect_failure",
                    "title": "定位失败测试",
                    "detail": "读取测试和实现",
                    "status": "in_progress",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text

    # 基于 v1 更新（expected == 当前版本）→ v2
    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [
                {
                    "item_key": "inspect_failure",
                    "title": "定位失败测试",
                    "detail": "读取测试和实现",
                    "status": "completed",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version"] == 2

    # 过期版本 1 再更新 → 冲突
    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [
                {
                    "item_key": "inspect_failure",
                    "title": "覆盖计划",
                    "detail": "旧模型回合",
                    "status": "completed",
                }
            ],
        },
    )
    assert resp.status_code == 409
    assert resp.json().get("error_code") == "plan_version_conflict"
    await _cleanup_run(run_id)


# ===========================================================================
# C0 §11：test_plan_allows_at_most_one_in_progress_item
# ===========================================================================


async def test_plan_allows_at_most_one_in_progress_item(client, monkeypatch):
    """同时最多一个 in_progress → 422 plan_transition_invalid。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "plan-test", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]

    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [
                {
                    "item_key": "item_a",
                    "title": "A",
                    "status": "in_progress",
                },
                {
                    "item_key": "item_b",
                    "title": "B",
                    "status": "in_progress",
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert resp.json().get("error_code") == "plan_transition_invalid"
    await _cleanup_run(run_id)


# ===========================================================================
# C0 §11：test_terminal_plan_item_cannot_regress
# ===========================================================================


async def test_terminal_plan_item_cannot_regress(client, monkeypatch):
    """completed/failed/cancelled 不能回到 pending 或 in_progress。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "plan-test", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]

    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [
                {"item_key": "item_a", "title": "A", "status": "completed"}
            ],
        },
    )
    assert resp.status_code == 201, resp.text

    # 同一版本内尝试把 completed 改回 pending
    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [
                {"item_key": "item_a", "title": "A", "status": "pending"}
            ],
        },
    )
    assert resp.status_code == 422
    assert resp.json().get("error_code") == "plan_transition_invalid"
    await _cleanup_run(run_id)


# ===========================================================================
# C0 §11：test_event_stream_replays_after_sequence_without_new_run
# ===========================================================================


async def test_event_stream_replays_after_sequence_without_new_run(
    client, monkeypatch
):
    """after_sequence 续读返回 sequence>N 的 durable 事件，不新建 run。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_event_stream_enabled", True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "stream-test", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]

    # 先取已有事件（分页接口）
    page = await client.get(f"/agent-runs/{run_id}/events?after_sequence=0")
    assert page.status_code == 200
    events = page.json()["items"]

    # SSE 从 last_sequence 续读（至少能建立连接并收到已结束/心跳）
    async with client.stream(
        "GET", f"/agent-runs/{run_id}/events/stream?after_sequence={len(events)}"
    ) as stream:
        assert stream.status_code == 200
    await _cleanup_run(run_id)


# ===========================================================================
# C0 §11：test_heartbeat_does_not_advance_sequence
# ===========================================================================


async def test_heartbeat_does_not_advance_sequence(client, monkeypatch):
    """SSE heartbeat 不写数据库、不增加 sequence。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_event_stream_enabled", True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "stream-test", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]

    page1 = await client.get(f"/agent-runs/{run_id}/events?after_sequence=0")
    seq1 = page1.json()["last_sequence"]
    page2 = await client.get(f"/agent-runs/{run_id}/events?after_sequence=0")
    seq2 = page2.json()["last_sequence"]
    assert seq1 == seq2
    await _cleanup_run(run_id)


# ===========================================================================
# C0 §11：test_flags_disabled_preserve_legacy_run
# ===========================================================================


async def test_flags_disabled_preserve_legacy_run(client, monkeypatch):
    """全部 v0.6.0 flag 关闭时 legacy run 创建照常工作。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", False)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", False)
    monkeypatch.setattr(settings, "agent_run_event_stream_enabled", False)

    resp = await client.post(
        "/agent-runs",
        json={"message": "legacy still works", "client_request_id": str(uuid4())},
    )
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["project_id"] is None
    assert data["workspace_id"] is None
    await _cleanup_run(data["id"])


# ===========================================================================
# 数据模型契约（C0 §4.1/4.2 表结构与约束）
# ===========================================================================


class TestProjectWorkspaceSchema:
    """project_workspaces 表结构契约。"""

    async def test_root_workspace_has_path_sha256(self, db: AsyncSession) -> None:
        """root workspace 必须携带规范化路径哈希。"""
        project = Project(name="sha-test", root_path="/tmp/sha-test")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        ws = ProjectWorkspace(
            project_id=project.id,
            root_path=project.root_path,
            root_path_sha256="a" * 64,
        )
        db.add(ws)
        await db.commit()
        await db.refresh(ws)
        assert ws.root_path_sha256 == "a" * 64
        assert ws.kind == "root"
        assert ws.status == "active"

    async def test_workspace_unique_project_path(self, db: AsyncSession) -> None:
        """同一 project 的同一路径哈希不能重复建 workspace。"""
        project = Project(name="unique-test", root_path="/tmp/unique-test")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        ws1 = ProjectWorkspace(
            project_id=project.id,
            root_path="/tmp/unique-test",
            root_path_sha256="b" * 64,
        )
        db.add(ws1)
        await db.commit()

        ws2 = ProjectWorkspace(
            project_id=project.id,
            root_path="/tmp/unique-test",
            root_path_sha256="b" * 64,
        )
        db.add(ws2)
        with pytest.raises(Exception):
            await db.commit()


class TestSessionSchema:
    """sessions 新字段契约。"""

    async def test_session_kind_defaults_legacy(self, db: AsyncSession) -> None:
        """旧 session 不设置 kind 时为 legacy（非空默认）。"""
        session = ChatSession(title="legacy-session")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        assert session.kind == "legacy"
        assert session.project_id is None
        assert session.workspace_id is None


class TestAgentRunSchema:
    """agent_runs 新字段契约。"""

    async def test_run_git_and_permission_snapshot(self, db: AsyncSession) -> None:
        """run 保存 Git HEAD/branch/dirty 与权限快照。"""
        project = Project(name="snap-test", root_path="/tmp/snap-test")
        db.add(project)
        await db.commit()
        await db.refresh(project)

        run = AgentRun(
            id=str(uuid4()),
            trace_id=str(uuid4()),
            project_id=project.id,
            base_head_sha="a" * 40,
            base_branch_name="main",
            base_git_dirty=True,
            model_profile_id="local-coder",
            reasoning_effort="high",
            permission_mode="confirm",
            permission_snapshot_json={"mode": "confirm"},
            client_request_id=str(uuid4()),
            max_steps=50,
            max_tool_calls=100,
            max_wall_time_ms=600_000,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        assert run.base_head_sha == "a" * 40
        assert run.base_branch_name == "main"
        assert run.base_git_dirty is True
        assert run.permission_mode == "confirm"


# ===========================================================================
# telemetry 标签（C0 §10）
# ===========================================================================


def test_v060_telemetry_labels_registered():
    """v0.6.0 telemetry 标签已注册。"""
    from personal_assistant.core.compatibility import _LABELS

    for label in (
        "agent_run_create",
        "coding_session_create",
        "run_plan_update",
        "run_event_stream",
        "workspace_resolve",
    ):
        assert label in _LABELS, label
    assert "project_bound" in _LABELS["agent_run_create"]["modes"]
    assert "legacy" in _LABELS["agent_run_create"]["modes"]
    assert {"created", "replayed", "rejected"} <= _LABELS["agent_run_create"][
        "outcomes"
    ]


def test_v060_error_codes_frozen():
    """C0 §9 错误码冻结。"""
    from personal_assistant.core.coding_errors import ERROR_CODES, http_status_for

    assert ERROR_CODES["coding_context_incomplete"] == 422
    assert ERROR_CODES["coding_mode_disabled"] == 409
    assert ERROR_CODES["workspace_outside_trust"] == 403
    assert ERROR_CODES["event_sequence_conflict"] == 500
    assert http_status_for("plan_version_conflict") == 409


# ===========================================================================
# C3 · update_run_plan 工具契约（C0 §7.1）
# ===========================================================================


def test_update_run_plan_tool_contract():
    """update_run_plan 是 safe 工具，不授予任何 capability。"""
    from personal_assistant.agents.tools import ToolRiskLevel
    from personal_assistant.core.run_plan_tool import build_run_plan_tool_spec

    spec = build_run_plan_tool_spec(None, "run-123")  # type: ignore[arg-type]
    assert spec.name == "update_run_plan"
    assert spec.risk_level == ToolRiskLevel.SAFE
    assert spec.required_capabilities == frozenset()
    assert spec.input_schema["required"] == ["expected_plan_version", "items"]
    assert spec.input_schema["properties"]["expected_plan_version"]["minimum"] == 1
    items = spec.input_schema["properties"]["items"]
    assert items["maxItems"] == 32
    assert "in_progress" in items["items"]["properties"]["status"]["enum"]


async def test_update_run_plan_tool_registered_by_flag(client, monkeypatch):
    """flag 开启时工具在模型定义中可见；关闭时不可见。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", False)
    monkeypatch.setattr(settings, "agent_command_workflow_enabled", False)
    monkeypatch.setattr(settings, "agent_http_workflow_enabled", False)
    monkeypatch.setattr(settings, "agent_sql_readonly_workflow_enabled", False)
    monkeypatch.setattr(settings, "agent_patch_workflow_enabled", False)
    monkeypatch.setattr(settings, "agent_rag_tools_enabled", False)
    monkeypatch.setattr(settings, "mcp_enabled", False)

    from personal_assistant.api.routes_agent_runs import get_agent_tool_bundle
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as session:
        monkeypatch.setattr(settings, "agent_run_plan_enabled", True)
        bundle = await get_agent_tool_bundle(session)
        assert bundle is not None
        on_names = {definition.name for definition in bundle.definitions}
        assert "update_run_plan" in on_names

        monkeypatch.setattr(settings, "agent_run_plan_enabled", False)
        bundle = await get_agent_tool_bundle(session)
        assert bundle is None

        # 仅开启 plan flag（其他工具 flag 全部关闭）时工具仍可见
        monkeypatch.setattr(settings, "agent_run_plan_enabled", True)
        monkeypatch.setattr(settings, "mcp_enabled", True)

        # mcp_enabled 但无活动记录：不影响 plan 工具注册
        bundle = await get_agent_tool_bundle(session)
        assert bundle is not None
        assert {
            definition.name for definition in bundle.definitions
        } >= {"update_run_plan"}


async def test_update_run_plan_tool_executor_paths(db: AsyncSession) -> None:
    """工具 executor：首次创建、版本递增更新、stale 版本转 RuntimeError。"""
    from personal_assistant.agents.contracts import AgentEvent, AgentEventType
    from personal_assistant.agents.repository import AgentRunRepository
    from personal_assistant.core.models import AgentRun
    from personal_assistant.core.run_plan_tool import build_run_plan_tool_spec

    run = AgentRun(
        id=str(uuid4()),
        trace_id=str(uuid4()),
        status="created",
        max_steps=10,
        max_tool_calls=20,
        max_wall_time_ms=60_000,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await AgentRunRepository(db).record_event(
        AgentEvent(
            run_id=run.id,
            sequence=1,
            type=AgentEventType.RUN_STARTED,
            payload={"status": "started"},
        )
    )

    spec = build_run_plan_tool_spec(db, run.id)

    class _NoCancel:
        is_cancelled = False

    cancellation = _NoCancel()
    # 首次创建（expected=1）
    result = await spec.executor(
        {"expected_plan_version": 1, "items": [{"item_key": "a", "title": "A"}]},
        cancellation,
    )
    assert result["plan_version"] == 1
    assert result["items"][0]["item_key"] == "a"

    # 版本递增更新（expected=1 == 当前版本）：pending → in_progress 合法
    result = await spec.executor(
        {
            "expected_plan_version": 1,
            "items": [{"item_key": "a", "title": "A", "status": "in_progress"}],
        },
        cancellation,
    )
    assert result["plan_version"] == 2
    assert result["items"][0]["status"] == "in_progress"

    # 版本递增更新（expected=2 == 当前版本）：in_progress → completed 合法
    result = await spec.executor(
        {
            "expected_plan_version": 2,
            "items": [{"item_key": "a", "title": "A", "status": "completed"}],
        },
        cancellation,
    )
    assert result["plan_version"] == 3
    assert result["items"][0]["status"] == "completed"

    # 非法转换：completed → in_progress 回退 → RuntimeError
    with pytest.raises(RuntimeError):
        await spec.executor(
            {
                "expected_plan_version": 3,
                "items": [{"item_key": "a", "title": "A", "status": "in_progress"}],
            },
            cancellation,
        )

    # stale 版本（同状态跳过转换检查）→ RuntimeError（不做 last-write-wins）
    with pytest.raises(RuntimeError):
        await spec.executor(
            {
                "expected_plan_version": 1,
                "items": [{"item_key": "a", "title": "A", "status": "completed"}],
            },
            cancellation,
        )
    await _cleanup_run(run.id)


# ===========================================================================
# C3 · artifact 契约（C0 §4.2/§7.2/§8）
# ===========================================================================


async def test_artifact_created_durable_event(db: AsyncSession) -> None:
    """artifact.created 以独立事务写入 durable 事件流（sequence 不重复）。"""

    from personal_assistant.agents.contracts import AgentEvent, AgentEventType
    from personal_assistant.agents.repository import AgentRunRepository
    from personal_assistant.core.models import AgentRun, AgentRunEvent
    from personal_assistant.core.run_artifact import RunArtifactService

    run = AgentRun(
        id=str(uuid4()),
        trace_id=str(uuid4()),
        status="created",
        max_steps=10,
        max_tool_calls=20,
        max_wall_time_ms=60_000,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    repo = AgentRunRepository(db)
    await repo.record_event(
        AgentEvent(
            run_id=run.id,
            sequence=1,
            type=AgentEventType.RUN_STARTED,
            payload={"status": "started"},
        )
    )

    result = await RunArtifactService(db).create_artifact(
        run_id=run.id,
        kind="test_report",
        title="单元测试报告",
        rel_path="reports/test.txt",
        content_sha256="a" * 64,
        metadata={"summary": "3 passed"},
    )
    assert result["kind"] == "test_report"
    assert result["rel_path"] == "reports/test.txt"

    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(AgentRunEvent).where(AgentRunEvent.run_id == run.id)
            )
        ).scalars().all()
    by_type = {row.event_type: row for row in rows}
    assert by_type["artifact.created"].payload_json["kind"] == "test_report"
    assert by_type["artifact.created"].payload_json["artifact_id"] == result["id"]
    assert "rel_path" not in by_type["artifact.created"].payload_json
    await _cleanup_run(run.id)


async def test_artifact_rejects_absolute_rel_path(client, monkeypatch):
    """rel_path 只允许 workspace 相对路径（C0 §4.2）。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "artifact-test", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]
    for bad in ("/etc/passwd", "../escape", "C:\\win\\x", "a\\b"):
        resp = await client.post(
            f"/agent-runs/{run_id}/artifacts",
            json={"kind": "file", "title": "x", "rel_path": bad},
        )
        assert resp.status_code == 422, (bad, resp.text)
        assert resp.json().get("error_code") == "artifact_invalid"
    await _cleanup_run(run_id)


async def test_run_snapshot_includes_plan_and_artifacts(client, monkeypatch):
    """C0 §7.2：GET /agent-runs/{id} 返回 plan/artifacts 重连纠偏快照。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "snapshot-test", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]
    assert resp.json().get("plan") is None
    assert resp.json().get("artifacts") == []

    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [
                {"item_key": "fix_bug", "title": "修复缺陷", "status": "in_progress"}
            ],
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        f"/agent-runs/{run_id}/artifacts",
        json={"kind": "summary", "title": "总结"},
    )
    assert resp.status_code == 201, resp.text
    artifact_id = resp.json()["id"]

    resp = await client.get(f"/agent-runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"]["version"] == 1
    assert body["plan"]["items"][0]["item_key"] == "fix_bug"
    assert body["artifacts"][0]["id"] == artifact_id
    assert body["artifacts"][0]["kind"] == "summary"
    await _cleanup_run(run_id)


async def test_artifact_events_replay_after_sequence(client, monkeypatch):
    """artifact.created 事件可通过 events 接口按 after_sequence 续读。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", True)

    # 手动构造确定性事件流（不经 coordinator，避免终态时序竞态）：
    # run.started(seq1) → artifact.created(seq2)
    from personal_assistant.agents.contracts import AgentEvent, AgentEventType
    from personal_assistant.agents.repository import AgentRunRepository
    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import AgentRun

    run_id = str(uuid4())
    async with async_session_factory() as session:
        session.add(
            AgentRun(
                id=run_id,
                trace_id=str(uuid4()),
                status="created",
                max_steps=10,
                max_tool_calls=20,
                max_wall_time_ms=60_000,
            )
        )
        await session.commit()
        repo = AgentRunRepository(session)
        await repo.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=1,
                type=AgentEventType.RUN_STARTED,
                payload={"status": "started"},
            )
        )
        await repo.record_event(
            AgentEvent(
                run_id=run_id,
                sequence=2,
                type=AgentEventType.ARTIFACT_CREATED,
                payload={
                    "artifact_id": str(uuid4()),
                    "kind": "summary",
                    "title": "t",
                    "step_id": None,
                },
            )
        )

    events = (await client.get(f"/agent-runs/{run_id}/events?after_sequence=0")).json()
    assert [e["type"] for e in events["items"]] == [
        "run.started",
        "artifact.created",
    ]

    # 续读：after_sequence=1 只返回后续事件，不重放旧事件
    tail = (await client.get(f"/agent-runs/{run_id}/events?after_sequence=1")).json()
    assert [e["type"] for e in tail["items"]] == ["artifact.created"]
    sequences = [e["sequence"] for e in events["items"]]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    await _cleanup_run(run_id)
