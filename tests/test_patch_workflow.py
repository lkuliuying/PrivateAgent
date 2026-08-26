"""v0.5.0 B1：Patch 可信执行闭环测试。

覆盖主计划 B1 退出条件：
- 未审批时磁盘零写入；
- 审批参数与实际写入完全一致（参数篡改拒绝）；
- 过期 Diff、路径越界和链接逃逸均拒绝；
- 成功写入后回读 SHA 一致（verified=True）；
- 崩溃后的未知写入不自动重放（non_idempotent + unknown 人工处置）；
- 关闭 Patch flag 后只读工具仍可正常使用；
- 已有文件必须携带 expected_old_sha256；新建文件流程可用。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    ApprovedToolCall,
    CancellationToken,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    ToolApprovalRepository,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ValidatedToolDispatcher,
)
from personal_assistant.agents.result_verification import FileDiffResultVerifier
from personal_assistant.api import routes_agent_runs
from personal_assistant.core.code_tools import normalize_patch_content
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import Project
from personal_assistant.core.patch_workflow import build_patch_tool_registry

PROJECT_PATH: str | None = None  # 由 fixture 设置，供 resolve_root 闭包使用


async def _make_project(db, tmp_path: Path) -> int:
    project = Project(name=f"b1-proj-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def _create_run(db, *, tool_call_id: str = "call-patch-1") -> str:
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    await repository.create_run(run_id=run_id, limits=AgentRunLimits())
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
                "name": "apply_patch_to_workspace",
            },
        )
    )
    return run_id


async def _cleanup(db, run_id: str, project_id: int | None = None) -> None:
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if project_id:
        await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()


def _patch_arguments(
    project_id: int,
    rel_path: str = "a.txt",
    new_content: str = "new content\n",
    **extra,
) -> dict:
    arguments = {
        "project_id": project_id,
        "rel_path": rel_path,
        "new_content": new_content,
    }
    arguments.update(extra)
    return arguments


def _old_sha256_of(target: Path) -> str:
    # 与执行器读取语义一致：通用换行文本按 UTF-8 计算
    return hashlib.sha256(
        target.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()


def test_normalize_patch_content_decodes_only_extra_serialization_layer():
    escaped = (
        r"#include \u003cstdio.h\u003e\n\nint main() {\n"
        r"    printf(\"Hello World!\\n\");\n    return 0;\n}\n"
    )
    expected = (
        "#include <stdio.h>\n\nint main() {\n"
        '    printf("Hello World!\\n");\n    return 0;\n}\n'
    )
    assert normalize_patch_content("hello.c", escaped) == expected
    assert normalize_patch_content("hello.c", expected) == expected
    assert normalize_patch_content("hello.c", f"```c\n{expected}```\n") == expected
    assert normalize_patch_content("README.md", f"```c\n{expected}```\n").startswith("```c")


@pytest.mark.asyncio
async def test_double_escaped_source_is_previewed_written_and_verified_as_raw_text(
    db, tmp_path
):
    escaped = (
        r"#include \u003cstdio.h\u003e\n\nint main() {\n"
        r"    printf(\"Hello World!\\n\");\n    return 0;\n}\n"
    )
    expected = (
        "#include <stdio.h>\n\nint main() {\n"
        '    printf("Hello World!\\n");\n    return 0;\n}\n'
    )
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                rel_path="hello.c",
                new_content=escaped,
                create=True,
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db,
            run_id,
            approval_id=approved.approval_id,
            approval_token=approved.token,
        ).execute(call, cancellation=CancellationToken())
        assert result.success is True
        assert (tmp_path / "hello.c").read_text(encoding="utf-8") == expected
        assert result.output["new_sha256"] == hashlib.sha256(
            expected.encode("utf-8")
        ).hexdigest()
    finally:
        await _cleanup(db, run_id, project_id)


def _dispatcher(
    db,
    run_id: str,
    *,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> ValidatedToolDispatcher:
    global PROJECT_PATH

    async def resolve_root(project_id: int) -> str:
        return str(PROJECT_PATH)

    registry = build_patch_tool_registry(db)
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
        result_verifier=FileDiffResultVerifier(resolve_root),
    )


async def _request_approval_and_approve(db, run_id: str, call: ToolCall) -> ApprovedToolCall:
    """执行一次会进入 waiting_approval 的调用，批准后返回审批绑定（含一次性 token）。"""
    pending = await _dispatcher(db, run_id).execute(call, cancellation=CancellationToken())
    assert pending.success is False
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    return await ToolApprovalRepository(db).approve(approvals[0].id)


@pytest.fixture(autouse=True)
def _patch_project_path(tmp_path, monkeypatch):
    global PROJECT_PATH
    PROJECT_PATH = str(tmp_path)
    yield
    PROJECT_PATH = None


@pytest.mark.asyncio
async def test_requires_approval_and_no_disk_write_without_approval(db, tmp_path):
    """未审批时磁盘零写入。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(project_id),
        )
        result = await _dispatcher(db, run_id).execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert result.error_code == "approval_required"
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_approved_apply_writes_atomically_and_readback_verified(db, tmp_path):
    """审批通过 → 原子写入 + 回读 verified=True，无临时文件残留。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                expected_old_sha256=_old_sha256_of(target),
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        resumed = _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        )
        result = await resumed.execute(call, cancellation=CancellationToken())
        assert result.success is True
        output = result.output
        assert output["rel_path"] == "a.txt"
        assert output["verified"] is True
        assert output["new_sha256"] != output["old_sha256"]  # 内容已变化
        assert target.read_text(encoding="utf-8") == "new content\n"
        leftovers = [p for p in tmp_path.iterdir() if ".pa-tmp" in p.name]
        assert leftovers == []
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_approval_binds_exact_arguments_and_rejects_tampering(db, tmp_path):
    """审批参数与实际写入完全一致：篡改参数后消费失败。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(project_id, new_content="content A\n"),
        )
        approved = await _request_approval_and_approve(db, run_id, call)

        tampered = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(project_id, new_content="content B\n"),
        )
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(tampered, cancellation=CancellationToken())
        assert result.success is False
        assert result.error_code == "approval_consume_failed"
        assert target.read_text(encoding="utf-8") == "old\n"
        assert (
            await ToolApprovalRepository(db).get(approved.approval_id)
        ).status == "approved"
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_stale_diff_rejected_without_disk_write(db, tmp_path):
    """过期 Diff（expected_old_sha256 与磁盘不符）→ 拒绝，磁盘不变。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                expected_old_sha256="0" * 64,  # 与真实内容不符
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert result.error_code == "executor_error"
        assert "拒绝应用过期补丁" in (result.error or "")
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_existing_file_requires_expected_old_sha256(db, tmp_path):
    """已有文件缺少 expected_old_sha256 → 拒绝写入。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(project_id),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert "必须携带 expected_old_sha256" in (result.error or "")
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rel_path",
    ["../escape.txt", "sub/../../escape.txt", "C:/windows/win.ini", "/etc/passwd"],
)
async def test_path_escape_rejected(db, tmp_path, rel_path):
    """路径越界（.. / 绝对路径 / 盘符）→ 拒绝且不写入任何位置。"""
    outside = tmp_path.parent / "escape.txt"
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                rel_path=rel_path,
                new_content="escaped\n",
                create=True,
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert result.error_code == "executor_error"
        assert "越界" in (result.error or "") or "相对路径" in (result.error or "")
        assert not outside.exists()
        assert not (tmp_path / "escape.txt").exists()
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_symlink_target_rejected(db, tmp_path):
    """链接逃逸：最终组件是符号链接 → 拒绝写入链接目标。"""
    outside = tmp_path.parent / "linked-target.txt"
    outside.write_text("secret\n", encoding="utf-8")
    link = tmp_path / "a.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("当前环境不允许创建符号链接")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                expected_old_sha256="0" * 64,
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert "符号链接" in (result.error or "")
        assert outside.read_text(encoding="utf-8") == "secret\n"
    finally:
        await _cleanup(db, run_id, project_id)
        with open(link, "rb"):
            pass
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_link_rejection_logic_without_os_privilege(monkeypatch, tmp_path):
    """无需系统权限验证链接拒绝逻辑：最终组件为链接/重解析点时一律拒绝。

    E2E 符号链接用例（test_symlink_target_rejected）需要 Developer Mode 或管理员
    权限，本环境不具备时跳过；此用例直接注入 islink/isjunction 事实。
    """
    from personal_assistant.core import patch_workflow as pw
    from personal_assistant.core.permissions import PermissionError_

    target = tmp_path / "linked.txt"
    target.write_text("real\n", encoding="utf-8")

    monkeypatch.setattr(pw, "_ISLINK", lambda path: Path(path) == target)
    monkeypatch.setattr(pw, "_ISJUNCTION", lambda path: False)
    with pytest.raises(PermissionError_, match="符号链接"):
        pw._reject_link_target(target)

    monkeypatch.setattr(pw, "_ISLINK", lambda path: False)
    monkeypatch.setattr(pw, "_ISJUNCTION", lambda path: Path(path) == target)
    with pytest.raises(PermissionError_, match="目录联接|重解析点"):
        pw._reject_link_target(target)


@pytest.mark.asyncio
async def test_create_new_file_flow(db, tmp_path):
    """create=True 新文件：不要求 old SHA，成功创建并回读验证。"""
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(project_id, rel_path="new/file.txt", create=True),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is True
        assert result.output["verified"] is True
        assert result.output["rel_path"] == "new/file.txt"
        assert (tmp_path / "new" / "file.txt").read_text(encoding="utf-8") == (
            "new content\n"
        )
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_unknown_execution_is_not_replayed(db, tmp_path):
    """崩溃后的未知写入不自动重放（non_idempotent + unknown 状态）。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                expected_old_sha256=_old_sha256_of(target),
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)

        # 第一次完整执行成功（模拟崩溃前的正常写入）。
        first = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert first.success is True
        assert target.read_text(encoding="utf-8") == "new content\n"

        # 手动把 execution 状态改为 unknown（模拟崩溃窗口：结果已落盘但事件未提交，
        # 或执行被中断状态不明）。
        repository = ToolExecutionRepository(db, run_id=run_id)
        records = await repository.list_for_run()
        assert len(records) == 1 and records[0].status == "succeeded"
        records[0].status = "unknown"
        records[0].error_code = "state_unknown"
        await db.commit()

        # 第二次执行：同审批绑定 + 同参数 → unknown 拒绝自动重放。
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=None
        ).execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert result.error_code == "execution_state_unknown"
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_patch_flag_off_keeps_read_only_tools_working(db, tmp_path, monkeypatch):
    """关闭 Patch flag：只读工具仍可注册与执行，apply_patch 不可见。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", False)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", True
    )
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert "propose_patch" in names
    assert "apply_patch_to_workspace" not in names

    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db, tool_call_id="call-readonly-1")
    try:
        dispatcher = await bundle.dispatcher_factory(db, run_id)
        call = ToolCall(
            id="call-readonly-1",
            name="propose_patch",
            arguments={
                "project_id": project_id,
                "rel_path": "a.txt",
                "new_content": "new content\n",
            },
        )
        result = await dispatcher.execute(call, cancellation=CancellationToken())
        assert result.success is True
        assert result.output["old_sha256"]
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_patch_flag_on_registers_tool_and_grants_write(db, monkeypatch):
    """开启 Patch flag：工具注册且 grant 含 filesystem.write（default-deny 校验）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", False
    )
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert "apply_patch_to_workspace" in names

    spec = build_patch_tool_registry(db).get("apply_patch_to_workspace")
    policy = ToolCapabilityPolicy(
        granted_capabilities=frozenset(
            {
                ToolCapability.FILESYSTEM_READ,
                ToolCapability.FILESYSTEM_WRITE,
            }
        )
    )
    from personal_assistant.agents.tools import ToolPolicyDecision

    assert policy.evaluate(spec) == ToolPolicyDecision.REQUIRE_APPROVAL
    denied = ToolCapabilityPolicy(
        granted_capabilities=frozenset({ToolCapability.FILESYSTEM_READ})
    )
    assert denied.evaluate(spec) == ToolPolicyDecision.DENY


@pytest.mark.asyncio
async def test_installed_coding_defaults_register_single_file_patch_pair(
    db, monkeypatch
):
    """安装版同时开启只读与 Patch flags 时，单文件预览/应用工具成对可见。"""
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", True
    )
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert {"propose_patch", "apply_patch_to_workspace"} <= names


@pytest.mark.asyncio
async def test_approval_preview_endpoint(db, tmp_path, client, monkeypatch):
    """B1：审批预览 API 返回基于磁盘事实的 diff；未开启工作流时 404。"""
    from personal_assistant.agents import ToolApprovalRepository

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                expected_old_sha256=_old_sha256_of(target),
            ),
        )
        pending = await _dispatcher(db, run_id).execute(
            call, cancellation=CancellationToken()
        )
        assert pending.error_code == "approval_required"
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)

        resp = await client.get(
            f"/agent-runs/{run_id}/approvals/{approvals[0].id}/preview"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["previewable"] is True
        assert body["tool_name"] == "apply_patch_to_workspace"
        assert body["rel_path"] == "a.txt"
        assert body["creates_file"] is False
        assert body["old_sha256"] == _old_sha256_of(target)
        assert body["new_sha256"]
        assert "-old" in body["diff"] and "+new" in body["diff"]
        assert body["truncated"] is False

        # 非文件类工具不可预览
        other = await client.get(
            f"/agent-runs/{run_id}/approvals/not-exist/preview"
        )
        assert other.status_code == 404

        # 未开启工作流时与工具可见性一致：404
        monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", False)
        monkeypatch.setattr(
            routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", False
        )
        hidden = await client.get(
            f"/agent-runs/{run_id}/approvals/{approvals[0].id}/preview"
        )
        assert hidden.status_code == 404
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_executions_endpoint_returns_redacted_output(db, tmp_path, client, monkeypatch):
    """B1：executions API 返回已脱敏/限长并持久化的工具结果（UI 事实源）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db)
    try:
        call = ToolCall(
            id="call-patch-1",
            name="apply_patch_to_workspace",
            arguments=_patch_arguments(
                project_id,
                expected_old_sha256=_old_sha256_of(target),
            ),
        )
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is True

        resp = await client.get(f"/agent-runs/{run_id}/executions")
        assert resp.status_code == 200
        executions = resp.json()
        assert len(executions) == 1
        item = executions[0]
        assert item["tool_name"] == "apply_patch_to_workspace"
        assert item["tool_version"] == "1.0.0"
        assert item["status"] == "succeeded"
        assert item["output"]["rel_path"] == "a.txt"
        assert item["output"]["verified"] is True
        assert "approval" not in str(item) and "token" not in str(item).lower()

        missing = await client.get(f"/agent-runs/{run_id}/executions/missing")
        assert missing.status_code == 404
    finally:
        await _cleanup(db, run_id, project_id)


@pytest.mark.asyncio
async def test_registry_rejects_legacy_risk_drift(monkeypatch):
    """legacy 风险等级与契约不一致时拒绝迁移（防止弱化）。"""
    from personal_assistant.core import tools as tools_module

    class FakeLegacy:
        name = "apply_patch_to_workspace"
        risk_level = "safe"  # 与契约 confirm 不一致

    monkeypatch.setattr(tools_module.default_registry, "get", lambda name: FakeLegacy())
    with pytest.raises(RuntimeError, match="风险等级与审核后的 Agent 契约不一致"):
        build_patch_tool_registry(None)


@pytest.mark.asyncio
async def test_patch_spec_matches_frozen_contract():
    """registry 产出的 ToolSpec 与 B0 冻结契约完全一致。"""
    from personal_assistant.agents.workflow_contracts import WORKFLOW_CONTRACT_BY_NAME

    contract = WORKFLOW_CONTRACT_BY_NAME["apply_patch_to_workspace"]
    from personal_assistant.core.patch_workflow import _build_patch_tool_spec

    spec = _build_patch_tool_spec(None)
    assert spec.name == contract.name
    assert spec.version == contract.version
    assert spec.risk_level == contract.risk_level
    assert spec.required_capabilities == contract.required_capabilities
    assert spec.idempotency == contract.idempotency
    assert spec.timeout_ms == contract.timeout_ms
    assert spec.max_input_bytes == contract.max_input_bytes
    assert spec.max_output_bytes == contract.max_output_bytes
    assert spec.supports_cancellation == contract.supports_cancellation
    assert dict(spec.input_schema) == dict(contract.input_schema)
    assert dict(spec.output_schema) == dict(contract.output_schema)
