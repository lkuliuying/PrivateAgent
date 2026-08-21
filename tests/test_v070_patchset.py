"""v0.7.0 E1：PatchSet 预览与原子应用测试。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §2/§9。

覆盖 E1 退出条件与测试矩阵：
- 未审批零写入（approval_required，磁盘不变）；
- 成功写入全部 verified（回读 SHA 复核 + PatchSetResultVerifier 组合）；
- 四类操作全链路（create/update/delete/rename）与统一 Diff 预览；
- SHA 冲突（外部编辑 T3）/ HEAD 漂移（T4）→ 失败关闭，零写入；
- 原子回滚（T1）：提交/验证失败 → 磁盘恢复原状 + rolled_back；
- truncated（T7）/ stale（T6）/ partial_unknown（T8/T12）不可应用；
- 路径安全（T5）：越界/绝对/反斜杠/ADS/设备名/二进制/重复路径；
- feature flag 可见性（第 10 节回退性：关闭后保留单文件工作流）。
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
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
)
from personal_assistant.agents.result_verification import PatchSetResultVerifier
from personal_assistant.core import patch_set_service as patch_set_service_mod
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import Project, ProjectWorkspace
from personal_assistant.core.patch_set_service import PatchSetError, PatchSetService
from personal_assistant.core.patch_set_tool import build_patch_set_tool_registry
from personal_assistant.core.repo_coding_patch_sets import CodingPatchSetRepository


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _op_create(path: str, content: str) -> dict:
    return {"operation": "create", "create": {"path": path, "new_content": content}}


def _op_update(path: str, content: str, old_sha: str) -> dict:
    return {
        "operation": "update",
        "update": {
            "path": path,
            "new_content": content,
            "expected_old_sha256": old_sha,
        },
    }


def _op_delete(path: str, old_sha: str) -> dict:
    return {
        "operation": "delete",
        "delete": {"path": path, "expected_old_sha256": old_sha},
    }


def _op_rename(old_path: str, new_path: str, old_sha: str) -> dict:
    return {
        "operation": "rename",
        "rename": {
            "old_path": old_path,
            "new_path": new_path,
            "expected_old_sha256": old_sha,
        },
    }


async def _make_project(db, tmp_path: Path) -> tuple[int, int]:
    """创建 Project + root Workspace，返回 (project_id, workspace_id)。"""
    project = Project(name=f"ps-proj-{uuid4().hex[:8]}", root_path=str(tmp_path))
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
    tool_call_id: str = "call-apply-1",
) -> str:
    """创建 project-bound coding run（含 HEAD/权限快照与 running tool step）。

    审批请求要求存在 running tool step（TOOL_REQUESTED 投影），
    因此与 test_patch_workflow._create_run 一致地写入该事件。
    """
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
    """清理测试数据（run 级联删除 patch sets/events，再删 workspace/project）。"""
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if workspace_id:
        await db.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id)
        )
    if project_id:
        await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()


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


async def _request_approval_and_approve(
    db, run_id: str, call: ToolCall
) -> "ApprovedToolCall":
    """执行一次会进入 waiting_approval 的调用，批准后返回一次性 token 绑定。"""
    from personal_assistant.agents import ApprovedToolCall  # noqa: F401

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


def _no_pa_leftovers(tmp_path: Path) -> list[Path]:
    return [p for p in tmp_path.iterdir() if ".pa-" in p.name]


async def _run_events(run_id: str) -> list:
    """用独立 session 查询 run 事件。

    _emit_event 用独立事务写 durable 事件；测试主 session 在 REPEATABLE
    READ 下的读快照早于该写入，看不到新事件行（生产路径每请求独立
    session，无此问题），故此处经 conftest 重绑的 factory 新建 session 查询。
    """
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as s:
        return await AgentRunRepository(s).list_events(run_id)


# ===========================================================================
# 四类操作全链路：预览（零写入）→ 审批 → 原子应用 → 回读 verified
# ===========================================================================


@pytest.mark.asyncio
async def test_patch_set_four_operations_full_cycle(db, tmp_path):
    """create/update/delete/rename 混合 PatchSet：预览零写入 → 应用全 verified。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")  # update
    (tmp_path / "b.py").write_text("old b\n", encoding="utf-8")  # delete
    (tmp_path / "d.py").write_text("old d\n", encoding="utf-8")  # rename → e.py
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        operations = [
            _op_create("c.py", "new c\n"),
            _op_update("a.py", "v2\n", _sha256_text("v1\n")),
            _op_delete("b.py", _sha256_text("old b\n")),
            _op_rename("d.py", "e.py", _sha256_text("old d\n")),
        ]
        # ---- 预览：只读零写入，统一 Diff ----
        preview = await PatchSetService(db).propose(run_id, operations)
        assert preview["file_count"] == 4
        assert preview["truncated"] is False
        assert preview["preview_version"] == 1
        assert len(preview["parameters_hash"]) == 64
        assert [f["operation"] for f in preview["files"]] == [
            "create",
            "update",
            "delete",
            "rename",
        ]
        by_op = {f["operation"]: f for f in preview["files"]}
        assert by_op["create"]["old_sha256"] == _sha256_text("")
        assert by_op["create"]["new_sha256"] == _sha256_text("new c\n")
        assert by_op["update"]["new_sha256"] == _sha256_text("v2\n")
        assert "new_sha256" not in by_op["delete"]  # delete 无新内容
        assert by_op["rename"]["new_path"] == "e.py"
        assert by_op["rename"]["path"] == "d.py"
        assert by_op["update"]["diff_text"].startswith("--- a/a.py\n+++ b/a.py\n")
        # 预览零写入
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
        assert (tmp_path / "b.py").exists()
        assert not (tmp_path / "c.py").exists()
        assert _no_pa_leftovers(tmp_path) == []

        # ---- 应用：审批 → 原子提交 → 回读 verified ----
        call = _apply_call(preview)
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is True
        output = result.output
        assert output["status"] == "applied"
        assert output["verified"] is True
        assert {f["status"] for f in output["files"]} == {"applied"}

        # 磁盘事实
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v2\n"
        assert not (tmp_path / "b.py").exists()
        assert (tmp_path / "c.py").read_text(encoding="utf-8") == "new c\n"
        assert not (tmp_path / "d.py").exists()
        assert (tmp_path / "e.py").read_text(encoding="utf-8") == "old d\n"
        assert _no_pa_leftovers(tmp_path) == []

        # durable 事件：patch_set.applied（payload 与 E0 契约一致）
        events = await _run_events(run_id)
        applied = [e for e in events if e.event_type == "patch_set.applied"]
        assert len(applied) == 1
        assert applied[0].payload_json == {
            "patch_set_id": preview["patch_set_id"],
            "preview_version": 1,
            "verified": True,
        }
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_patch_set_preview_created_event_payload(db, tmp_path):
    """patch_set.preview_created 事件 payload 键与 E0 契约冻结集合一致。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id, [_op_update("a.py", "v2\n", _sha256_text("v1\n"))]
        )
        events = await _run_events(run_id)
        created = [e for e in events if e.event_type == "patch_set.preview_created"]
        assert len(created) == 1
        # base_head_sha 为空时不要求该键；其余键必须与契约一致
        assert created[0].payload_json == {
            "patch_set_id": preview["patch_set_id"],
            "preview_version": 1,
            "file_count": 1,
            "truncated": False,
        }
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 未审批零写入
# ===========================================================================


@pytest.mark.asyncio
async def test_apply_patch_set_unapproved_zero_write(db, tmp_path):
    """未审批时 apply_patch_set 零写入，返回 approval_required。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id, [_op_update("a.py", "v2\n", _sha256_text("v1\n"))]
        )
        result = await _dispatcher(db, run_id).execute(
            _apply_call(preview), cancellation=CancellationToken()
        )
        assert result.success is False
        assert result.error_code == "approval_required"
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
        assert _no_pa_leftovers(tmp_path) == []
        # 状态保持 previewed（未消费、未写入）
        record = await CodingPatchSetRepository(db).get_by_id(
            preview["patch_set_id"]
        )
        assert record is not None and record.status == "previewed"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# SHA 冲突（T3 外部编辑）与 HEAD 漂移（T4）
# ===========================================================================


@pytest.mark.asyncio
async def test_external_edit_conflict_detected(db, tmp_path):
    """预览后文件被外部编辑 → patchset_conflict 409，零写入，状态 failed。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id, [_op_update("a.py", "v2\n", _sha256_text("v1\n"))]
        )
        # 外部编辑：预览后磁盘内容变化
        (tmp_path / "a.py").write_text("external edit\n", encoding="utf-8")

        call = _apply_call(preview)
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher(
            db, run_id, approval_id=approved.approval_id, approval_token=approved.token
        ).execute(call, cancellation=CancellationToken())
        assert result.success is False
        assert result.error_code == "executor_error"
        assert "内容已变化" in (result.error or "")

        # 零写入：外部编辑内容保持原样
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "external edit\n"
        assert _no_pa_leftovers(tmp_path) == []

        # 状态 failed + patch_set.failed 事件携带冻结错误码
        record = await CodingPatchSetRepository(db).get_by_id(preview["patch_set_id"])
        assert record is not None and record.status == "failed"
        assert record.error_code == "patchset_conflict"
        events = await _run_events(run_id)
        failed = [e for e in events if e.event_type == "patch_set.failed"]
        assert len(failed) == 1
        assert failed[0].payload_json["error_code"] == "patchset_conflict"
        assert set(failed[0].payload_json.keys()) == {
            "patch_set_id",
            "error_code",
            "error_message",
        }
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_head_drift_rejected(db, tmp_path):
    """run 创建后 Git HEAD 漂移 → git_snapshot_failed，零写入。"""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git 不可用，跳过 HEAD 漂移测试")
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")

    def _git(*args: str) -> str:
        proc = subprocess.run(
            [git, "-C", str(tmp_path), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    _git("init")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "test")
    _git("add", ".")
    _git("commit", "-m", "init")
    head1 = _git("rev-parse", "HEAD")

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id, base_head_sha=head1
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id, [_op_update("a.py", "v2\n", _sha256_text("v1\n"))]
        )
        # HEAD 漂移：外部提交改变 HEAD
        (tmp_path / "a.py").write_text("v1.5\n", encoding="utf-8")
        _git("add", ".")
        _git("commit", "-m", "drift")

        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
        assert exc.value.error_code == "git_snapshot_failed"
        # 零写入：外部提交内容保持原样
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1.5\n"
        assert _no_pa_leftovers(tmp_path) == []
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 原子回滚（T1）与 partial_unknown（T12）
# ===========================================================================


@pytest.mark.asyncio
async def test_atomic_rollback_on_verify_failure(db, tmp_path, monkeypatch):
    """回读验证失败 → 完整逆序回滚，磁盘恢复原状，状态 rolled_back。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        operations = [
            _op_update("a.py", "v2\n", _sha256_text("v1\n")),
            _op_create("c.py", "new c\n"),
        ]
        preview = await PatchSetService(db).propose(run_id, operations)

        def _fake_verify(staged):
            return False, ["模拟回读验证失败"]

        monkeypatch.setattr(patch_set_service_mod, "_verify_all", _fake_verify)
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
        assert exc.value.error_code == "patchset_conflict"

        # 磁盘恢复原状：update 回退旧内容、create 回退不存在
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
        assert not (tmp_path / "c.py").exists()
        assert _no_pa_leftovers(tmp_path) == []

        # 状态机：rolled_back + 文件级全部 rolled_back + durable 事件
        record = await CodingPatchSetRepository(db).get_by_id(preview["patch_set_id"])
        assert record is not None and record.status == "rolled_back"
        assert {f.status for f in record.files} == {"rolled_back"}
        events = await _run_events(run_id)
        rolled_back = [e for e in events if e.event_type == "patch_set.rolled_back"]
        assert len(rolled_back) == 1
        assert set(rolled_back[0].payload_json.keys()) == {"patch_set_id", "reason"}
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_commit_failure_rolls_back(db, tmp_path, monkeypatch):
    """提交中途失败（_CommitFailed）→ 已执行部分完整回滚，状态 rolled_back。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        operations = [
            _op_update("a.py", "v2\n", _sha256_text("v1\n")),
            _op_create("c.py", "new c\n"),
        ]
        preview = await PatchSetService(db).propose(run_id, operations)

        real_commit = patch_set_service_mod._commit_all

        def _fake_commit(staged):
            # 只真实提交第一个 op（update），然后模拟第二个 op 提交失败
            first = [s for s in staged if s.ordinal == 0]
            executed = real_commit(first)
            raise patch_set_service_mod._CommitFailed(
                executed, "模拟提交失败: c.py"
            )

        monkeypatch.setattr(patch_set_service_mod, "_commit_all", _fake_commit)
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
        assert exc.value.error_code == "patchset_conflict"

        # 已执行部分回滚：update 回退旧内容、create 从未执行不存在
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
        assert not (tmp_path / "c.py").exists()
        assert _no_pa_leftovers(tmp_path) == []

        record = await CodingPatchSetRepository(db).get_by_id(preview["patch_set_id"])
        assert record is not None and record.status == "rolled_back"
        events = await _run_events(run_id)
        rolled_back = [e for e in events if e.event_type == "patch_set.rolled_back"]
        assert len(rolled_back) == 1
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_partial_unknown_never_auto_retried(db, tmp_path, monkeypatch):
    """回滚失败 → partial_unknown 终态，任何再次 apply 均被拒绝（不自动重放）。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [
                _op_update("a.py", "v2\n", _sha256_text("v1\n")),
                _op_create("c.py", "new c\n"),
            ],
        )
        service = PatchSetService(db)

        def _fake_verify(staged):
            return False, ["模拟回读验证失败"]

        def _fake_rollback(staged, executed):
            return False, {0}, ["模拟回滚失败"]

        monkeypatch.setattr(patch_set_service_mod, "_verify_all", _fake_verify)
        monkeypatch.setattr(patch_set_service_mod, "_rollback_all", _fake_rollback)
        with pytest.raises(PatchSetError) as exc:
            await service.apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
        assert exc.value.error_code == "patchset_partial_unknown"

        record = await CodingPatchSetRepository(db).get_by_id(preview["patch_set_id"])
        assert record is not None and record.status == "partial_unknown"
        # 文件级状态：回滚失败的文件 unknown，其余 rolled_back
        by_ordinal = {f.ordinal: f.status for f in record.files}
        assert by_ordinal[0] == "unknown"
        assert by_ordinal[1] == "rolled_back"
        events = await _run_events(run_id)
        unknown = [e for e in events if e.event_type == "patch_set.unknown"]
        assert len(unknown) == 1
        assert set(unknown[0].payload_json.keys()) == {"patch_set_id", "reason"}

        # 再次 apply（含新审批）必须被拒绝：NON_IDEMPOTENT + 状态检查双重阻止
        with pytest.raises(PatchSetError) as exc2:
            await service.apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
        assert exc2.value.error_code == "patchset_partial_unknown"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# truncated（T7）/ stale（T6）不可应用
# ===========================================================================


@pytest.mark.asyncio
async def test_truncated_preview_cannot_apply(db, tmp_path):
    """截断预览直接 apply → patchset_truncated 422，零写入。"""
    big_content = "x" * (400 * 1024)  # 单文件 diff 超 256KiB 截断阈值
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id, [_op_create("big.txt", big_content)]
        )
        assert preview["truncated"] is True
        assert preview["files"][0]["truncated"] is True
        assert preview["files"][0]["diff_text"].endswith("…（diff 已截断）")

        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
        assert exc.value.error_code == "patchset_truncated"
        # 零写入：文件未创建，状态保持 previewed（未进入应用流程）
        assert not (tmp_path / "big.txt").exists()
        record = await CodingPatchSetRepository(db).get_by_id(preview["patch_set_id"])
        assert record is not None and record.status == "previewed"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_stale_preview_rejected(db, tmp_path):
    """parameters_hash 或 preview_version 不匹配 → patchset_preview_stale 409。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        preview = await PatchSetService(db).propose(
            run_id, [_op_update("a.py", "v2\n", _sha256_text("v1\n"))]
        )
        service = PatchSetService(db)

        with pytest.raises(PatchSetError) as exc:
            await service.apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                "0" * 64,  # 伪造参数哈希
            )
        assert exc.value.error_code == "patchset_preview_stale"

        with pytest.raises(PatchSetError) as exc2:
            await service.apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"] + 1,  # 版本不匹配
                preview["parameters_hash"],
            )
        assert exc2.value.error_code == "patchset_preview_stale"

        # 零写入：磁盘不变，状态仍 previewed
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
        record = await CodingPatchSetRepository(db).get_by_id(preview["patch_set_id"])
        assert record is not None and record.status == "previewed"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 路径安全（T5）与内容校验
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.txt",
        "sub/../../escape.txt",
        "/abs/path.txt",
        "sub\\backslash.txt",
        "a:stream.txt",
        "nul",
        "dir/nul",
        "bad\x00path.txt",
    ],
)
async def test_path_safety_rejected(db, tmp_path, bad_path):
    """越界/绝对/反斜杠/ADS/设备名/NUL 路径 → patchset_invalid，零写入。"""
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id, [_op_create(bad_path, "x\n")]
            )
        assert exc.value.error_code == "patchset_invalid"
        assert list(tmp_path.iterdir()) == []  # 零写入
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_binary_content_rejected(db, tmp_path):
    """NUL 字节内容 → patchset_invalid（二进制 Patch 不做）。"""
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id, [_op_create("bin.dat", "abc\x00def")]
            )
        assert exc.value.error_code == "patchset_invalid"
        assert list(tmp_path.iterdir()) == []
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_duplicate_paths_rejected(db, tmp_path):
    """同一 PatchSet 内路径重复（含 rename 目标）→ patchset_invalid。"""
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        sha = _sha256_text("v1\n")
        with pytest.raises(PatchSetError) as exc:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_update("a.py", "v2\n", sha),
                    _op_create("a.py", "dup\n"),  # 与 update 撞路径
                ],
            )
        assert exc.value.error_code == "patchset_invalid"
        with pytest.raises(PatchSetError) as exc2:
            await PatchSetService(db).propose(
                run_id,
                [
                    _op_rename("a.py", "c.py", sha),
                    _op_delete("b.py", sha),
                    _op_create("c.py", "dup\n"),  # 与 rename 目标撞路径
                ],
            )
        assert exc2.value.error_code == "patchset_invalid"
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# feature flag 可见性（第 10 节回退性）
# ===========================================================================


@pytest.mark.asyncio
async def test_patchset_tools_invisible_when_flag_off(db, monkeypatch):
    """flag 关闭时两个 PatchSet 工具不可见；只读/单文件工具不受影响。"""
    from personal_assistant.api import routes_agent_runs
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "coding_patchset_enabled", False)
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_patch_workflow_enabled", True)

    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert "propose_patch_set" not in names
    assert "apply_patch_set" not in names
    # 单文件可信工作流与只读工具保留
    assert "propose_patch" in names
    assert "apply_patch_to_workspace" in names
    assert "read_file" in names


@pytest.mark.asyncio
async def test_patchset_tools_visible_when_flag_on(db, monkeypatch):
    """flag 开启时两个 PatchSet 工具注册；apply 工具不授予额外能力。"""
    from personal_assistant.api import routes_agent_runs
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "coding_patchset_enabled", True)
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", False)
    monkeypatch.setattr(settings, "agent_patch_workflow_enabled", False)

    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    names = {definition.name for definition in bundle.definitions}
    assert "propose_patch_set" in names
    assert "apply_patch_set" in names
    # 只读工具未开启时不可见（PatchSet 不隐式开放只读工具）
    assert "read_file" not in names
