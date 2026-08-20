"""v0.6.0 C5：project-bound/legacy 路由 telemetry + 诊断快照脱敏 + flag 顺序校验。

覆盖（C0 契约 §9/§10、C5 任务 1/2/5）：
- coding_session_create / workspace_resolve / run_event_stream 计数标签；
- 诊断快照 coding_agent 摘要只计数，不记录项目正文、绝对路径或 Git 快照；
- 错误响应不含本地绝对路径；
- flag 开启顺序 project-bound → plan → stream 由 Settings 校验强制。
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents.contracts import ModelResponse, TokenUsage
from personal_assistant.core.compatibility import compatibility_telemetry
from personal_assistant.core.models import AgentRun


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
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as session:
        await session.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await session.commit()


def _telemetry_delta(before: dict, path: str, mode: str, outcome: str) -> int:
    """统计两次快照间指定标签的增量（全局单例无 reset，必须用增量断言）。"""
    after = compatibility_telemetry.snapshot()
    entry = after["paths"].get(path)
    prev = before["paths"].get(path)
    if entry is None:
        return 0
    count = entry["outcomes"].get(outcome, 0)
    if prev is None:
        return count
    return count - prev["outcomes"].get(outcome, 0)


async def _enable_flags(monkeypatch, *, project=True, plan=False, stream=False):
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", project)
    monkeypatch.setattr(settings, "agent_run_plan_enabled", plan)
    monkeypatch.setattr(settings, "agent_run_event_stream_enabled", stream)


async def _make_project_with_workspace(client, name: str, root: str) -> tuple[int, int]:
    resp = await client.post("/projects", json={"name": name, "root_path": root})
    project_id = resp.json()["id"]
    resp = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    return project_id, resp.json()["id"]


# ===========================================================================
# C0 §10：coding_session_create telemetry
# ===========================================================================


async def test_coding_session_create_records_created(client, monkeypatch, tmp_path):
    await _enable_flags(monkeypatch, project=True)
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "t1", root)

    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        "/sessions",
        json={
            "title": "coding",
            "project_id": project_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "coding"
    assert _telemetry_delta(before, "coding_session_create", "project_bound", "created") == 1
    assert _telemetry_delta(before, "coding_session_create", "project_bound", "rejected") == 0


async def test_coding_session_rejected_when_flag_disabled(client, monkeypatch):
    await _enable_flags(monkeypatch, project=False)

    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        "/sessions",
        json={"title": "coding", "project_id": 1, "workspace_id": 1, "kind": "coding"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json().get("error_code") == "coding_mode_disabled"
    assert _telemetry_delta(before, "coding_session_create", "project_bound", "rejected") == 1


async def test_coding_session_rejected_when_binding_incomplete(client, monkeypatch):
    await _enable_flags(monkeypatch, project=True)

    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        "/sessions",
        json={"title": "coding", "project_id": 1, "kind": "coding"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json().get("error_code") == "coding_context_incomplete"
    assert _telemetry_delta(before, "coding_session_create", "project_bound", "rejected") == 1


async def test_coding_session_rejected_when_workspace_mismatch(client, monkeypatch, tmp_path):
    await _enable_flags(monkeypatch, project=True)
    root1 = str((tmp_path / "p1").resolve())
    root2 = str((tmp_path / "p2").resolve())
    (tmp_path / "p1").mkdir()
    (tmp_path / "p2").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "t2", root1)
    project2_id, _ = await _make_project_with_workspace(client, "t3", root2)

    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        "/sessions",
        json={
            "title": "coding",
            "project_id": project2_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json().get("error_code") == "workspace_outside_trust"
    assert _telemetry_delta(before, "coding_session_create", "project_bound", "rejected") == 1


async def test_coding_session_rejects_unknown_kind(client, monkeypatch):
    await _enable_flags(monkeypatch, project=True)

    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        "/sessions", json={"title": "chat", "kind": "chat"}
    )
    assert resp.status_code == 422, resp.text
    assert _telemetry_delta(before, "coding_session_create", "project_bound", "rejected") == 1


async def test_legacy_session_unaffected_by_new_kind_rules(client, monkeypatch):
    await _enable_flags(monkeypatch, project=True)

    before = compatibility_telemetry.snapshot()
    resp = await client.post("/sessions", json={"title": "legacy"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "legacy"
    assert body["project_id"] is None
    assert body["workspace_id"] is None
    assert _telemetry_delta(before, "coding_session_create", "project_bound", "created") == 0


# ===========================================================================
# C0 §10：workspace_resolve telemetry
# ===========================================================================


async def test_workspace_resolve_records_resolved_and_missing(client, monkeypatch, tmp_path):
    await _enable_flags(monkeypatch, project=True)
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "t4", root)

    before = compatibility_telemetry.snapshot()
    resp = await client.get(f"/projects/{project_id}/workspaces")
    assert resp.status_code == 200
    resp = await client.get(f"/projects/{project_id}/workspaces/{ws_id}")
    assert resp.status_code == 200
    resp = await client.get(f"/projects/{project_id}/workspaces/999999999")
    assert resp.status_code == 404
    assert _telemetry_delta(before, "workspace_resolve", "project_bound", "resolved") == 2
    assert _telemetry_delta(before, "workspace_resolve", "project_bound", "missing") == 1


async def test_workspace_resolve_records_mismatch(client, monkeypatch, tmp_path):
    await _enable_flags(monkeypatch, project=True)
    root1 = str((tmp_path / "p1").resolve())
    root2 = str((tmp_path / "p2").resolve())
    (tmp_path / "p1").mkdir()
    (tmp_path / "p2").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "t5", root1)
    project2_id, _ = await _make_project_with_workspace(client, "t6", root2)

    before = compatibility_telemetry.snapshot()
    resp = await client.get(f"/projects/{project2_id}/workspaces/{ws_id}")
    assert resp.status_code == 404
    assert _telemetry_delta(before, "workspace_resolve", "project_bound", "mismatch") == 1


async def test_run_create_workspace_failures_record_resolve_outcomes(
    client, monkeypatch, tmp_path
):
    """创建链中 workspace 解析失败同时记录 agent_run_create 与 workspace_resolve。"""
    await _enable_flags(monkeypatch, project=True)
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "t7", root)

    # coding session 供归属校验通过（请求走完整 coding 链）
    resp = await client.post(
        "/sessions",
        json={
            "title": "coding",
            "project_id": project_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    assert resp.status_code == 201, resp.text

    from sqlalchemy import update as sql_update

    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import ProjectWorkspace

    # workspace 归属错配 → mismatch（session 创建后 workspace 被改绑到其他项目）
    root2 = str((tmp_path / "p2").resolve())
    (tmp_path / "p2").mkdir()
    resp = await client.post("/projects", json={"name": "t7b", "root_path": root2})
    project2_id = resp.json()["id"]
    resp = await client.post(f"/projects/{project2_id}/workspaces/root/ensure")
    ws2_id = resp.json()["id"]
    # 先把 ws2 改绑到 project_id，使 coding session 创建校验通过（绑定 ws2）
    async with async_session_factory() as session:
        await session.execute(
            sql_update(ProjectWorkspace)
            .where(ProjectWorkspace.id == ws2_id)
            .values(project_id=project_id)
        )
        await session.commit()
    resp = await client.post(
        "/sessions",
        json={
            "title": "coding2",
            "project_id": project_id,
            "workspace_id": ws2_id,
            "kind": "coding",
        },
    )
    assert resp.status_code == 201, resp.text
    session2_id = resp.json()["id"]
    # 再改回 project2：请求时 workspace 归属错配 → workspace_outside_trust
    async with async_session_factory() as session:
        await session.execute(
            sql_update(ProjectWorkspace)
            .where(ProjectWorkspace.id == ws2_id)
            .values(project_id=project2_id)
        )
        await session.commit()
    before = compatibility_telemetry.snapshot()
    resp = await client.post(
        "/agent-runs",
        json={
            "session_id": session2_id,
            "message": "test",
            "project_id": project_id,
            "workspace_id": ws2_id,
            "permission_mode": "confirm",
            "client_request_id": str(uuid4()),
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json().get("error_code") == "workspace_outside_trust"
    assert _telemetry_delta(before, "workspace_resolve", "project_bound", "mismatch") == 1
    assert (
        _telemetry_delta(before, "agent_run_create", "project_bound", "rejected") == 1
    )


# ===========================================================================
# C0 §10：run_event_stream telemetry
# ===========================================================================


async def test_run_event_stream_records_connected_and_reconnected(client, monkeypatch):
    await _enable_flags(monkeypatch, project=True)

    resp = await client.post(
        "/agent-runs",
        json={"message": "stream", "client_request_id": str(uuid4())},
    )
    run_id = resp.json()["id"]

    page = await client.get(f"/agent-runs/{run_id}/events?after_sequence=0")
    last_seq = page.json()["last_sequence"]

    # 首次连接（after_sequence=0）→ connected；run 终态 → completed
    before = compatibility_telemetry.snapshot()
    async with client.stream(
        "GET", f"/agent-runs/{run_id}/events/stream?after_sequence=0"
    ) as stream:
        assert stream.status_code == 200
    assert _telemetry_delta(before, "run_event_stream", "project_bound", "connected") == 1

    # 等后台任务写入事件（ImmediateModel 异步完成），使 last_sequence > 0
    import asyncio

    for _ in range(50):
        page = await client.get(f"/agent-runs/{run_id}/events?after_sequence=0")
        last_seq = page.json()["last_sequence"]
        if last_seq > 0:
            break
        await asyncio.sleep(0.1)
    assert last_seq > 0, "run 未产生任何 durable 事件"

    # 续读（after_sequence>0）→ reconnected
    before = compatibility_telemetry.snapshot()
    async with client.stream(
        "GET", f"/agent-runs/{run_id}/events/stream?after_sequence={last_seq}"
    ) as stream:
        assert stream.status_code == 200
    assert _telemetry_delta(before, "run_event_stream", "project_bound", "reconnected") == 1

    await _cleanup_run(run_id)


# ===========================================================================
# C5 任务 2：诊断快照 coding_agent 摘要（脱敏，只计数）
# ===========================================================================


async def test_diagnostics_coding_agent_summary_counts_without_secrets(
    client, monkeypatch, tmp_path
):
    """诊断快照包含 v0.6.0 计数摘要；项目正文/绝对路径/Git 快照不泄露。"""
    await _enable_flags(monkeypatch, project=True, plan=True)
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "t8", root)

    # 创建 coding session + coding run，注入敏感 message
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
    secret_message = "修复测试失败 secret-message-7749"
    resp = await client.post(
        "/agent-runs",
        json={
            "session_id": session_id,
            "message": secret_message,
            "project_id": project_id,
            "workspace_id": ws_id,
            "permission_mode": "confirm",
            "client_request_id": str(uuid4()),
        },
    )
    run_id = resp.json()["id"]

    # 计划 + artifact
    resp = await client.post(
        f"/agent-runs/{run_id}/plan",
        json={
            "expected_plan_version": 1,
            "items": [{"item_key": "fix_bug", "title": "修复缺陷", "status": "pending"}],
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"/agent-runs/{run_id}/artifacts",
        json={"kind": "summary", "title": "总结"},
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get("/diagnostics")
    assert resp.status_code == 200
    body = resp.json()
    coding = body.get("coding_agent")
    assert coding is not None, "诊断快照缺少 coding_agent 摘要"
    assert coding["runs"]["project_bound"] >= 1
    assert coding["runs"]["by_status"].get("created", 0) >= 0
    assert coding["coding_sessions"] >= 1
    assert coding["workspaces"]["total"] >= 1
    assert coding["plans"]["runs_with_plan"] >= 1
    assert coding["plans"]["items"] >= 1
    assert coding["artifacts"] >= 1

    # 脱敏：绝对路径、message 正文、Git 快照、权限正文不得出现
    dumped = json.dumps(body, ensure_ascii=False)
    assert root not in dumped, "诊断快照泄露了绝对路径"
    assert "secret-message-7749" not in dumped, "诊断快照泄露了 message 正文"
    assert "permission_snapshot" not in dumped
    assert "base_head_sha" not in dumped

    await _cleanup_run(run_id)


# ===========================================================================
# C0 §9：错误响应不含本地绝对路径
# ===========================================================================


async def test_coding_errors_never_expose_absolute_paths(client, monkeypatch, tmp_path):
    """编码错误响应（git/workspace 路径类）不含本地绝对路径。"""
    await _enable_flags(monkeypatch, project=True)
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project_id, ws_id = await _make_project_with_workspace(client, "t9", root)

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

    # workspace 路径缺失 → 409 workspace_unavailable（C1 退出条件：失败关闭不自动改绑）
    from sqlalchemy import update

    from personal_assistant.core.db import async_session_factory
    from personal_assistant.core.models import ProjectWorkspace

    async with async_session_factory() as session:
        await session.execute(
            update(ProjectWorkspace)
            .where(ProjectWorkspace.id == ws_id)
            .values(root_path=str(tmp_path / "gone-away"))
        )
        await session.commit()

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
    assert resp.status_code == 409, resp.text
    assert resp.json().get("error_code") == "workspace_unavailable"
    # 错误响应不得包含本地绝对路径（C0 §9）
    dumped = json.dumps(resp.json(), ensure_ascii=False)
    assert root not in dumped
    assert str(tmp_path) not in dumped
    assert "gone-away" not in dumped


# ===========================================================================
# C0 §10：flag 开启顺序校验（Settings 层）
# ===========================================================================


def test_v060_flag_order_validation_rejects_plan_without_project_bound():
    from personal_assistant.config import Settings

    with pytest.raises(ValueError, match="PA_AGENT_RUN_PLAN_ENABLED"):
        Settings(agent_run_plan_enabled=True)


def test_v060_flag_order_validation_rejects_stream_without_plan():
    from personal_assistant.config import Settings

    with pytest.raises(ValueError, match="PA_AGENT_RUN_EVENT_STREAM_ENABLED"):
        Settings(
            project_bound_runs_enabled=True,
            agent_run_event_stream_enabled=True,
        )


def test_v060_flag_order_validation_accepts_valid_order():
    from personal_assistant.config import Settings

    s = Settings(
        project_bound_runs_enabled=True,
        agent_run_plan_enabled=True,
        agent_run_event_stream_enabled=True,
    )
    assert s.project_bound_runs_enabled is True
    assert s.agent_run_event_stream_enabled is True
