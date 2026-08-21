"""v0.7.0 E3：Artifact 与完成条件测试。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §3/§7。

覆盖 E3 范围与测试矩阵：
- Artifact repository/API：11 种 kind 冻结、输入校验（422 artifact_invalid）、
  limit/offset 分页、artifact.created durable 事件（与 runProjector 兼容）；
- Artifact 投影：patch_preview/patch_applied 即时投影（metadata 有界脱敏，
  不含 diff 原文与绝对路径）、rebuild_terminal 命令/报告投影（按 parser
  分类）、final_report 终态投影与来源引用、全部幂等去重、flag 关闭 no-op；
- 完成条件扩展（E0 §7）：must_pass_command_profiles / no_pending_patchsets /
  final_git_diff 求值（单元 + API allowed 集合 422 + 端到端接收）。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    CancellationToken,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    ToolApprovalRepository,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ValidatedToolDispatcher,
    WorkflowCompletionFacts,
    WorkflowCompletionOutputVerifier,
)
from personal_assistant.agents.result_verification import PatchSetResultVerifier
from personal_assistant.config import settings as cfg
from personal_assistant.core.artifact_projection import ArtifactProjectionService
from personal_assistant.core.models import (
    AgentRun as AgentRunRecord,
)
from personal_assistant.core.models import (
    AgentToolExecution as ExecutionRecord,
)
from personal_assistant.core.models import Project, ProjectWorkspace
from personal_assistant.core.patch_set_service import PatchSetService
from personal_assistant.core.patch_set_tool import build_patch_set_tool_registry
from personal_assistant.core.run_artifact import (
    ARTIFACT_KINDS,
    ArtifactValidationError,
    RunArtifactService,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _make_project(db, tmp_path: Path) -> tuple[int, int]:
    """创建 Project + root Workspace，返回 (project_id, workspace_id)。"""
    project = Project(name=f"e3-proj-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    workspace = ProjectWorkspace(
        project_id=project.id,
        kind="root",
        root_path=str(tmp_path),
        root_path_sha256=_sha256_text(str(tmp_path)),
        status="active",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return project.id, workspace.id


async def _create_coding_run(
    db,
    *,
    project_id: int,
    workspace_id: int,
    base_head_sha: str | None = None,
    completion_conditions: dict | None = None,
    tool_call_id: str = "call-e3-1",
) -> str:
    """创建 project-bound coding run（含 HEAD/权限快照与 running tool step）。"""
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(
        run_id=run_id,
        limits=AgentRunLimits(),
        project_id=project_id,
        workspace_id=workspace_id,
        base_head_sha=base_head_sha,
        base_branch_name="main" if base_head_sha else None,
        base_git_dirty=False,
        model_profile_id="local-coder",
        reasoning_effort="high",
        permission_mode="confirm",
        permission_snapshot_json={"mode": "confirm"},
        client_request_id=str(uuid4()),
        completion_conditions=completion_conditions,
    )
    await repository.record_event(
        AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
    )
    await repository.record_event(
        AgentEvent(
            run_id=run_id,
            sequence=2,
            type=AgentEventType.TOOL_REQUESTED,
            step_id=str(uuid4()),
            payload={
                "ordinal": 1,
                "kind": "tool",
                "tool_call_id": tool_call_id,
                "name": "apply_patch_set",
            },
        )
    )
    return run_id


async def _cleanup(
    db,
    *,
    run_id: str | None = None,
    project_id: int | None = None,
    workspace_id: int | None = None,
) -> None:
    """清理测试数据（run 级联删除 artifacts/executions/patch sets/events）。"""
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if workspace_id:
        await db.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id)
        )
    if project_id:
        await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()


async def _list_artifacts(run_id: str) -> list[dict]:
    """独立 session 读 Artifact（投影/事件经独立事务写入，纠偏 REPEATABLE READ）。"""
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as s:
        return await RunArtifactService(s).list_artifacts(run_id)


async def _run_events(run_id: str) -> list:
    """独立 session 查询 run durable 事件。"""
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as s:
        return await AgentRunRepository(s).list_events(run_id)


async def _insert_execution(
    db,
    run_id: str,
    *,
    tool_name: str,
    output: dict,
    status: str = "succeeded",
    step_id: str | None = None,
    tool_call_id: str | None = None,
) -> str:
    """直接插入一条执行事实（durable facts 源，投影测试数据）。"""
    record = ExecutionRecord(
        id=str(uuid4()),
        run_id=run_id,
        step_id=step_id,
        tool_call_id=tool_call_id or f"call-e3-{uuid4().hex[:8]}",
        tool_name=tool_name,
        tool_version="1.0",
        arguments_json={"args": []},
        arguments_sha256="0" * 64,
        risk_level="safe",
        required_capabilities_json=[],
        status=status,
        attempt_count=1,
        output_json=output,
        started_at=_utc_naive_now(),
        completed_at=_utc_naive_now(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record.id


def _command_output(
    *, profile: str, parser: str, returncode: int = 0, succeeded: bool = True
) -> dict:
    """命令执行事实输出（与 run_whitelisted_command_trusted 输出同构）。"""
    return {
        "profile": profile,
        "profile_version": 1,
        "args": [profile, "--quiet"],
        "returncode": returncode,
        "succeeded": succeeded,
        "cancelled": False,
        "truncated": False,
        "processes_remaining": 0,
        "parsed": {
            "parser": parser,
            "summary": f"{parser} 完成",
            "passed": 1,
            "failed": 0,
            "failures": [],
            "truncated": False,
        },
    }


# ===========================================================================
# §3：Artifact repository/API（11 种 kind / 校验 / 分页 / durable 事件）
# ===========================================================================


def test_artifact_kinds_frozen():
    """E0 §3：11 种 kind 冻结（v0.6.0 五类 + v0.7.0 六类，additive）。"""
    assert ARTIFACT_KINDS == frozenset(
        {
            "diff",
            "file",
            "command_output",
            "test_report",
            "summary",
            "patch_preview",
            "patch_applied",
            "command_result",
            "lint_report",
            "build_report",
            "final_report",
        }
    )


async def test_artifact_create_validation(db, tmp_path):
    """非法输入全部拒绝：kind/rel_path（绝对、..、反斜杠、盘符）/sha/超限 metadata。"""
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    svc = RunArtifactService(db)
    try:
        with pytest.raises(ArtifactValidationError, match="kind"):
            await svc.create_artifact(run_id=run_id, kind="unknown_kind", title="t")
        for bad_path in ("/abs.txt", "C:/abs.txt", "a\\b.txt", "../up.txt", "a/../b"):
            with pytest.raises(ArtifactValidationError, match="rel_path"):
                await svc.create_artifact(
                    run_id=run_id, kind="file", title="t", rel_path=bad_path
                )
        with pytest.raises(ArtifactValidationError, match="content_sha256"):
            await svc.create_artifact(
                run_id=run_id, kind="file", title="t", content_sha256="short"
            )
        with pytest.raises(ArtifactValidationError, match="metadata"):
            await svc.create_artifact(
                run_id=run_id,
                kind="file",
                title="t",
                metadata={"blob": "x" * (33 * 1024)},
            )
        # 合法 rel_path + 空 metadata 通过
        created = await svc.create_artifact(
            run_id=run_id, kind="file", title="ok", rel_path="src/a.py"
        )
        assert created["kind"] == "file"
        assert created["rel_path"] == "src/a.py"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_artifact_list_pagination(db, tmp_path):
    """E3：limit/offset 分页，按 created_at/id 稳定排序。"""
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    svc = RunArtifactService(db)
    try:
        for i in range(7):
            await svc.create_artifact(
                run_id=run_id, kind="file", title=f"a-{i}", rel_path=f"f{i}.py"
            )
        page1 = await svc.list_artifacts(run_id, limit=3, offset=0)
        assert [item["title"] for item in page1] == ["a-0", "a-1", "a-2"]
        page2 = await svc.list_artifacts(run_id, limit=3, offset=3)
        assert [item["title"] for item in page2] == ["a-3", "a-4", "a-5"]
        page3 = await svc.list_artifacts(run_id, limit=3, offset=6)
        assert [item["title"] for item in page3] == ["a-6"]
        # 分页不重叠、不遗漏
        titles = [item["title"] for item in page1 + page2 + page3]
        assert titles == [f"a-{i}" for i in range(7)]
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_artifact_created_durable_event(db, tmp_path):
    """写入后发 artifact.created durable 事件（payload 与 E0 契约一致）。"""
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    svc = RunArtifactService(db)
    try:
        created = await svc.create_artifact(
            run_id=run_id, kind="patch_preview", title="预览"
        )
        events = await _run_events(run_id)
        artifact_events = [
            e for e in events if e.event_type == AgentEventType.ARTIFACT_CREATED
        ]
        assert len(artifact_events) == 1
        assert artifact_events[0].payload_json == {
            "artifact_id": created["id"],
            "kind": "patch_preview",
            "title": "预览",
            "step_id": None,
        }
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_artifact_api_create_list_and_errors(client, db, tmp_path, monkeypatch):
    """API：POST 201 + GET 分页；未知 run 404；非法 kind 422 artifact_invalid。"""
    monkeypatch.setattr(cfg, "agent_run_plan_enabled", True)
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        resp = await client.post(
            f"/agent-runs/{run_id}/artifacts",
            json={"kind": "patch_preview", "title": "api 预览"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["kind"] == "patch_preview"

        resp = await client.post(
            f"/agent-runs/{run_id}/artifacts",
            json={"kind": "nope", "title": "t"},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error_code"] == "artifact_invalid"

        resp = await client.post(
            f"/agent-runs/{run_id}/artifacts",
            json={"kind": "file", "title": "t", "rel_path": "../evil.txt"},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error_code"] == "artifact_invalid"

        resp = await client.post(
            f"/agent-runs/{uuid4()}/artifacts",
            json={"kind": "file", "title": "t"},
        )
        assert resp.status_code == 404, resp.text

        # 分页
        for i in range(2):
            resp = await client.post(
                f"/agent-runs/{run_id}/artifacts",
                json={"kind": "file", "title": f"api-{i}"},
            )
            assert resp.status_code == 201, resp.text
        page = await client.get(f"/agent-runs/{run_id}/artifacts?limit=2&offset=1")
        assert page.status_code == 200, page.text
        assert [item["title"] for item in page.json()] == ["api-0", "api-1"]
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# §3：Artifact 投影（flag 门控 / 即时投影 / 终态重建 / 幂等）
# ===========================================================================


def _dispatcher(
    db,
    run_id: str,
    *,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> ValidatedToolDispatcher:
    """PatchSet 工具 dispatcher（含 PatchSetResultVerifier 复核磁盘事实）。"""
    registry = build_patch_set_tool_registry(db, run_id)
    return ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset(
                {
                    ToolCapability.FILESYSTEM_READ,
                    ToolCapability.FILESYSTEM_WRITE,
                }
            )
        ),
        approval_requester=SqlToolApprovalRequester(db, run_id=run_id),
        approval_consumer=(
            SqlToolApprovalConsumer(
                db,
                approval_id=approval_id,
                token=approval_token,
            )
            if approval_id is not None
            else None
        ),
        execution_store=ToolExecutionRepository(db, run_id=run_id),
        result_verifier=PatchSetResultVerifier(db),
    )


async def _request_approval_and_approve(db, run_id: str, call: ToolCall):
    pending = await _dispatcher(db, run_id).execute(call, cancellation=CancellationToken())
    assert pending.success is False
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    return await ToolApprovalRepository(db).approve(approvals[0].id)


def _apply_call(preview: dict) -> ToolCall:
    return ToolCall(
        id="call-apply-1",
        name="apply_patch_set",
        arguments={
            "patch_set_id": preview["patch_set_id"],
            "preview_version": preview["preview_version"],
            "expected_parameters_hash": preview["parameters_hash"],
        },
    )


async def test_projection_patch_preview_applied_bounded_metadata(db, tmp_path, monkeypatch):
    """E3：预览/应用即时投影 patch_preview + patch_applied。

    metadata 有界脱敏：只含文件清单与统计，不含 diff 原文与绝对路径；
    flag 关闭时（本文件其余用例）不产生任何 Artifact。
    """
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        tool_call_id="call-apply-1",
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [
                {
                    "operation": "create",
                    "create": {"path": "c.py", "new_content": "new c\n"},
                },
                {
                    "operation": "update",
                    "update": {
                        "path": "a.py",
                        "new_content": "v2\n",
                        "expected_old_sha256": _sha256_text("v1\n"),
                    },
                },
            ],
        )
        # 即时投影 patch_preview
        artifacts = await _list_artifacts(run_id)
        previews = [a for a in artifacts if a["kind"] == "patch_preview"]
        assert len(previews) == 1
        meta = previews[0]["metadata"]
        assert meta["patch_set_id"] == preview["patch_set_id"]
        assert meta["file_count"] == 2
        assert meta["additions"] >= 1
        assert meta["truncated"] is False
        assert [f["operation"] for f in meta["files"]] == ["create", "update"]
        # 有界脱敏：不含 diff 原文 / 新内容 / 绝对路径
        for key in ("diff_text", "new_content", "root_path"):
            assert key not in meta
        assert "a.py" in str(meta["files"])

        # 应用 → patch_applied（verified 事实）
        call = _apply_call(preview)
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is True
        assert result.output["verified"] is True

        artifacts = await _list_artifacts(run_id)
        applied = [a for a in artifacts if a["kind"] == "patch_applied"]
        assert len(applied) == 1
        ameta = applied[0]["metadata"]
        assert ameta["status"] == "applied"
        assert ameta["verified"] is True
        assert ameta["file_count"] == 2
        assert {f["status"] for f in ameta["files"]} == {"applied"}
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v2\n"
        assert (tmp_path / "c.py").read_text(encoding="utf-8") == "new c\n"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_projection_flag_off_noop(db, tmp_path):
    """E3 回退性（第 10 节）：flag 关闭时投影全部 no-op，零 Artifact 写入。"""
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        assert cfg.coding_artifacts_enabled is False
        await PatchSetService(db).propose(
            run_id,
            [{"operation": "create", "create": {"path": "c.py", "new_content": "x\n"}}],
        )
        exec_id = await _insert_execution(
            db,
            run_id,
            tool_name="run_whitelisted_command",
            output=_command_output(profile="py-tests", parser="pytest"),
        )
        assert exec_id
        await ArtifactProjectionService(db).rebuild_terminal(run_id=run_id, status="completed")
        assert await _list_artifacts(run_id) == []
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_projection_rebuild_terminal_commands_and_reports(db, tmp_path, monkeypatch):
    """E3：终态重建投影——命令按 parser 分类为 command_result + 报告。

    pytest→test_report、ruff→lint_report、npm_build→build_report、
    plain→仅 command_result；重复调用幂等（按 source_execution_id 去重）。
    """
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        pytest_id = await _insert_execution(
            db,
            run_id,
            tool_name="run_whitelisted_command",
            output=_command_output(profile="py-tests", parser="pytest"),
        )
        await _insert_execution(
            db,
            run_id,
            tool_name="run_whitelisted_command",
            output=_command_output(profile="py-lint", parser="ruff"),
        )
        await _insert_execution(
            db,
            run_id,
            tool_name="run_whitelisted_command",
            output=_command_output(profile="web-build", parser="npm_build"),
        )
        await _insert_execution(
            db,
            run_id,
            tool_name="run_whitelisted_command",
            output=_command_output(profile="plain-cmd", parser="plain"),
        )

        svc = ArtifactProjectionService(db)
        await svc.rebuild_terminal(run_id=run_id, status="completed")
        # 幂等：重复调用不产生重复引用
        await svc.rebuild_terminal(run_id=run_id, status="completed")

        artifacts = await _list_artifacts(run_id)
        kinds = [a["kind"] for a in artifacts]
        assert kinds.count("command_result") == 4
        assert kinds.count("test_report") == 1
        assert kinds.count("lint_report") == 1
        assert kinds.count("build_report") == 1

        test_report = next(a for a in artifacts if a["kind"] == "test_report")
        assert test_report["metadata"]["source_execution_id"] == pytest_id
        assert test_report["metadata"]["parser"] == "pytest"
        assert test_report["metadata"]["parsed"]["passed"] == 1
        # 脱敏有界：不内嵌完整输出原文
        assert "processes_remaining" not in test_report["metadata"]
        assert "args" not in test_report["metadata"]["parsed"]

        cmd = next(
            a for a in artifacts if a["kind"] == "command_result"
            and a["metadata"]["profile"] == "plain-cmd"
        )
        assert cmd["metadata"]["profile"] == "plain-cmd"
        assert cmd["metadata"]["profile_version"] == 1
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_projection_rebuild_terminal_ignores_non_terminal(db, tmp_path, monkeypatch):
    """E3：非终态 status 不重建投影（running 等不产生 Artifact）。"""
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        await _insert_execution(
            db,
            run_id,
            tool_name="run_whitelisted_command",
            output=_command_output(profile="py-tests", parser="pytest"),
        )
        await ArtifactProjectionService(db).rebuild_terminal(run_id=run_id, status="running")
        assert await _list_artifacts(run_id) == []
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_projection_final_report_sources_and_idempotent(db, tmp_path, monkeypatch):
    """E3：final_report 终态投影——来源引用 + 完成条件摘要；只生成一次。"""
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    project_id, workspace_id = await _make_project(db, tmp_path)
    conditions = {
        "must_succeed_tools": ["apply_patch_set"],
        "must_pass_command_profiles": ["py-tests"],
    }
    run_id = await _create_coding_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        completion_conditions=conditions,
    )
    # 复用 TOOL_REQUESTED 投影出的真实 step（run_steps 行已由投影创建）
    events = await AgentRunRepository(db).list_events(run_id)
    step_id = next(
        e.step_id
        for e in events
        if e.event_type == AgentEventType.TOOL_REQUESTED
    )
    try:
        await _insert_execution(
            db,
            run_id,
            tool_name="run_whitelisted_command",
            output=_command_output(profile="py-tests", parser="pytest"),
            step_id=step_id,
        )
        svc = ArtifactProjectionService(db)
        await svc.rebuild_terminal(run_id=run_id, status="completed")
        await svc.rebuild_terminal(run_id=run_id, status="completed")

        artifacts = await _list_artifacts(run_id)
        finals = [a for a in artifacts if a["kind"] == "final_report"]
        assert len(finals) == 1
        meta = finals[0]["metadata"]
        assert meta["run_id"] == run_id
        assert meta["status"] == "completed"
        assert meta["completion_satisfied"] is True
        assert meta["completion_conditions"] == conditions
        assert "run_whitelisted_command" in meta["tool_names"]
        assert any(
            item["kind"] == "command_result" for item in meta["artifacts"]
        )
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


async def test_projection_final_report_failed_run(db, tmp_path, monkeypatch):
    """E3：run 失败终态 → final_report 标记 completion_satisfied=False。"""
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        await ArtifactProjectionService(db).rebuild_terminal(run_id=run_id, status="failed")
        artifacts = await _list_artifacts(run_id)
        finals = [a for a in artifacts if a["kind"] == "final_report"]
        assert len(finals) == 1
        assert finals[0]["metadata"]["status"] == "failed"
        assert finals[0]["metadata"]["completion_satisfied"] is False
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# §7：完成条件扩展求值（must_pass_profiles / no_pending / final_git_diff）
# ===========================================================================


def _verifier(
    *,
    executions: list[dict] | None = None,
    patch_sets: list[dict] | None = None,
    git_diff_empty: bool | None = None,
    **kwargs,
) -> WorkflowCompletionOutputVerifier:
    facts = WorkflowCompletionFacts(
        executions=executions or [],
        patch_sets=patch_sets or [],
        git_diff_empty=git_diff_empty,
    )

    async def loader() -> WorkflowCompletionFacts:
        return facts

    return WorkflowCompletionOutputVerifier(loader, **kwargs)


async def _verify(verifier: WorkflowCompletionOutputVerifier) -> bool:
    result = await verifier.verify("", attempt=1)
    return result.passed


async def test_completion_verifier_must_pass_command_profiles():
    """must_pass_command_profiles：profile 无 succeeded 执行 → 完成条件不满足。"""
    ok_exec = {
        "tool_name": "run_whitelisted_command",
        "status": "succeeded",
        "profile": "py-tests",
    }
    verifier = _verifier(
        executions=[ok_exec], must_pass_command_profiles=("py-tests",)
    )
    assert await _verify(verifier) is True

    # profile 从未执行 → 失败关闭
    verifier = _verifier(
        executions=[ok_exec], must_pass_command_profiles=("py-lint",)
    )
    result = await verifier.verify("", attempt=1)
    assert result.passed is False
    assert result.code == "completion_not_met"
    assert "py-lint" in result.message

    # 执行过但失败 → 失败关闭（不信任模型文本，只看执行事实）
    verifier = _verifier(
        executions=[
            {"tool_name": "run_whitelisted_command", "status": "failed", "profile": "py-tests"}
        ],
        must_pass_command_profiles=("py-tests",),
    )
    assert await _verify(verifier) is False


async def test_completion_verifier_no_pending_patchsets():
    """no_pending_patchsets：存在 previewed 未决 PatchSet → 完成条件不满足。"""
    verifier = _verifier(
        patch_sets=[{"id": "ps-1", "status": "applied"}], no_pending_patchsets=True
    )
    assert await _verify(verifier) is True

    verifier = _verifier(
        patch_sets=[
            {"id": "ps-1", "status": "applied"},
            {"id": "ps-2", "status": "previewed"},
        ],
        no_pending_patchsets=True,
    )
    result = await verifier.verify("", attempt=1)
    assert result.passed is False
    assert "未决 PatchSet" in result.message

    # 条件未开启时未决不阻塞
    verifier = _verifier(patch_sets=[{"id": "ps-2", "status": "previewed"}])
    assert await _verify(verifier) is True


async def test_completion_verifier_final_git_diff():
    """final_git_diff：nonempty/empty 按 workspace 当前 dirty 事实判定；非 git 失败关闭。"""
    # nonempty + 非空 diff → 满足
    verifier = _verifier(git_diff_empty=False, final_git_diff="nonempty")
    assert await _verify(verifier) is True
    # nonempty + 空 diff → 不满足
    result = await _verifier(git_diff_empty=True, final_git_diff="nonempty").verify("", attempt=1)
    assert result.passed is False
    assert "Git Diff 为空" in result.message
    # empty + 空 diff → 满足
    verifier = _verifier(git_diff_empty=True, final_git_diff="empty")
    assert await _verify(verifier) is True
    # empty + 非空 diff → 不满足
    result = await _verifier(git_diff_empty=False, final_git_diff="empty").verify("", attempt=1)
    assert result.passed is False
    # 非 git 目录（None）→ nonempty/empty 不可判定即失败关闭
    result = await _verifier(git_diff_empty=None, final_git_diff="nonempty").verify("", attempt=1)
    assert result.passed is False
    assert "非 git" in result.message
    # any → 恒满足
    verifier = _verifier(git_diff_empty=None, final_git_diff="any")
    assert await _verify(verifier) is True
    # 非法取值构造即 ValueError
    with pytest.raises(ValueError, match="final_git_diff"):
        _verifier(final_git_diff="garbage")


async def test_api_completion_conditions_allowed_fields(client, monkeypatch, tmp_path):
    """API allowed 集合：未知字段/非法取值 422；合法扩展字段端到端接收（202）。"""
    monkeypatch.setattr(cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(cfg, "project_bound_runs_enabled", True)

    # 注入立即完成的模型，避免触发真实模型调用与长时间后台任务
    from personal_assistant.agents.contracts import ModelResponse, TokenUsage
    from personal_assistant.api.routes_agent_runs import get_agent_model_client
    from personal_assistant.main_api import app

    class _ImmediateModel:
        async def complete(self, request, *, cancellation):
            del request, cancellation
            return ModelResponse(
                text="E3 测试回答",
                usage=TokenUsage(input_tokens=4, output_tokens=2, cached_tokens=0),
                provider="fake",
                model="fake-model",
                request_id="fake-request",
                latency_ms=0.5,
            )

    app.dependency_overrides[get_agent_model_client] = lambda: _ImmediateModel()

    # 未知字段 → 422
    resp = await client.post(
        "/agent-runs",
        json={"message": "x", "completion_conditions": {"model_magic": True}},
    )
    assert resp.status_code == 422, resp.text
    # final_git_diff 非法取值 → 422
    resp = await client.post(
        "/agent-runs",
        json={"message": "x", "completion_conditions": {"final_git_diff": "huge"}},
    )
    assert resp.status_code == 422, resp.text
    # must_pass_command_profiles 非法 → 422
    resp = await client.post(
        "/agent-runs",
        json={
            "message": "x",
            "completion_conditions": {"must_pass_command_profiles": "py-tests"},
        },
    )
    assert resp.status_code == 422, resp.text
    # no_pending_patchsets 非布尔 → 422
    resp = await client.post(
        "/agent-runs",
        json={
            "message": "x",
            "completion_conditions": {"no_pending_patchsets": "yes"},
        },
    )
    assert resp.status_code == 422, resp.text

    # 合法扩展字段 → 202（run 创建接收）
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project = await client.post("/projects", json={"name": "e3-api", "root_path": root})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    ws = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    assert ws.status_code in (200, 201), ws.text
    ws_id = ws.json()["id"]
    session = await client.post(
        "/sessions",
        json={
            "title": "e3-api",
            "project_id": project_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    assert session.status_code == 201, session.text
    resp = await client.post(
        "/agent-runs",
        json={
            "session_id": session.json()["id"],
            "message": "e3-conditions",
            "project_id": project_id,
            "workspace_id": ws_id,
            "permission_mode": "confirm",
            "client_request_id": str(uuid4()),
            "completion_conditions": {
                "must_succeed_tools": ["apply_patch_set"],
                "max_failed_tools": 1,
                "require_verified": True,
                "must_pass_command_profiles": ["py-tests"],
                "no_pending_patchsets": True,
                "final_git_diff": "nonempty",
            },
        },
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    app.dependency_overrides.pop(get_agent_model_client, None)

    # 清理（run 后台任务可能仍在写，经重绑 factory 的独立 session 删除）
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as s:
        await s.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await s.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.project_id == project_id)
        )
        await s.execute(delete(Project).where(Project.id == project_id))
        await s.commit()
