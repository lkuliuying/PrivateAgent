"""v0.7.0 E3-alpha.2 门禁：主链 E2E + 恢复 fixture 冻结。

冻结依据：``docs/releases/v0.7.0/v0.7.0-development-plan-20260820.md``
「0.7.0-alpha.2」节（E2–E3 完成后）：

- “修改 → 测试 → 验证 → 报告”后端主链通过：真实 git 项目 + 真实 pytest
  命令 + PatchSet 原子应用 + 完成条件（must_succeed_tools /
  must_pass_command_profiles / no_pending_patchsets / final_git_diff）
  求值 + 终态 Artifact 投影（patch_preview / patch_applied /
  command_result / test_report / final_report）。
- 审批、取消、失败和重启恢复 fixture 冻结：
  - 审批：等待 → 批准 → resume 续跑完成；拒绝 → PatchSet rejected 零写入；
  - 取消：run cancelled 终态 → final_report(cancelled)，不再自动推进；
  - 失败：完成条件不满足 → run 以 output_validation_failed 失败关闭，
    final_report completion_satisfied=False（零容忍：不得 completed）；
  - 重启：reconcile 后 running run → failed、无 key execution → unknown
    （state_unknown，人工处置）、previewed PatchSet 保留且不自动重放。

安全契约（计划 §4/§11）：命令只经 argv 数组与白名单 profile（真实
pytest 进程树清理 processes_remaining==0）；完成条件全部基于 durable
事实（executions / coding_patch_sets / Git 快照）求值，模型文本不能
宣称验证成功；审批消费一次性 token，拒绝零写入。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, update

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    AgentRuntime,
    CancellationToken,
    ModelMessage,
    ModelResponse,
    PersistentAgentRunner,
    SqlAgentRunEventSink,
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
from personal_assistant.agents.recovery import reconcile_orphaned_agent_runs
from personal_assistant.agents.result_verification import (
    CompositeToolResultVerifier,
    PatchSetResultVerifier,
    ShellResultVerifier,
)
from personal_assistant.config import settings as cfg
from personal_assistant.core.artifact_projection import ArtifactProjectionService
from personal_assistant.core.command_workflow import build_command_tool_registry
from personal_assistant.core.git_snapshot import GitSnapshotError, read_git_snapshot
from personal_assistant.core.models import (
    AgentRun as AgentRunRecord,
)
from personal_assistant.core.models import (
    AgentToolExecution as ExecutionRecord,
)
from personal_assistant.core.models import (
    Project,
    ProjectCommandProfile,
    ProjectWorkspace,
)
from personal_assistant.core.patch_set_service import PatchSetService
from personal_assistant.core.patch_set_tool import build_patch_set_tool_registry
from personal_assistant.core.repo_coding_patch_sets import CodingPatchSetRepository
from personal_assistant.core.run_artifact import RunArtifactService
from personal_assistant.core.tool_adapter import build_read_only_tool_registry


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_available() -> bool:
    return shutil.which("git") is not None


def _git(root: Path, *args: str) -> str:
    """在 root 内执行只读/本地 git 命令，返回 stdout 首行。"""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


def _git_init_and_commit(root: Path) -> str:
    """初始化真实 git 仓库并提交初始文件，返回 HEAD sha。"""
    _git(root, "init")
    _git(root, "add", ".")
    _git(
        root,
        "-c", "user.name=gate-test",
        "-c", "user.email=gate-test@example.test",
        "commit", "-m", "initial",
    )
    return _git(root, "rev-parse", "HEAD")


# ===========================================================================
# 公共 helper
# ===========================================================================


async def _make_project(db, tmp_path: Path) -> tuple[int, int]:
    project = Project(name=f"a2-{uuid4().hex[:8]}", root_path=str(tmp_path))
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


async def _create_profile(
    db,
    project_id: int,
    *,
    name: str,
    args: list[str],
    kind: str = "test",
    parser: str = "plain",
    timeout_seconds: int = 60,
) -> int:
    profile = ProjectCommandProfile(
        project_id=project_id,
        name=name,
        command_json={"args": args},
        kind=kind,
        timeout_seconds=timeout_seconds,
        enabled=True,
        profile_version=1,
        result_parser=parser,
        max_output_bytes=64 * 1024,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile.id


async def _create_coding_run(
    db,
    *,
    project_id: int,
    workspace_id: int,
    base_head_sha: str | None = None,
    completion_conditions: dict | None = None,
    start_event: bool = True,
) -> str:
    """创建 project-bound coding run（含权限快照）。

    start_event=True（默认）：手动发 run.started（不经 runtime 驱动的测试用）；
    start_event=False：首个 run.started 由 AgentRuntime.run 发出（与
    test_workflow_e2e 的 runner.run 语义一致，避免重复 create_run 导致
    agent_runs 主键冲突）。
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
        completion_conditions=completion_conditions,
    )
    if start_event:
        await repository.record_event(
            AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
        )
    return run_id


async def _cleanup(
    db,
    *,
    run_id: str | None = None,
    project_id: int | None = None,
    workspace_id: int | None = None,
) -> None:
    """清理测试数据（run 级联删除 patch sets/executions/artifacts/events）。"""
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if workspace_id:
        await db.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id)
        )
    if project_id:
        await db.execute(
            delete(ProjectCommandProfile).where(
                ProjectCommandProfile.project_id == project_id
            )
        )
        await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()


def _dispatcher(
    db,
    run_id: str,
    *,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> ValidatedToolDispatcher:
    """只读 + PatchSet + 命令工具注册表（带 PatchSet 磁盘事实复核）。"""
    registry = build_read_only_tool_registry(db)
    for spec in build_patch_set_tool_registry(db, run_id).list():
        registry.register(spec)
    for spec in build_command_tool_registry(db).list():
        registry.register(spec)
    return ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset(
                {
                    ToolCapability.FILESYSTEM_READ,
                    ToolCapability.FILESYSTEM_WRITE,
                    ToolCapability.PROCESS_EXECUTE,
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
        # 复用 E2 verifier：PatchSet 磁盘事实 + Shell 退出码/超时/截断校验
        # （命令 returncode!=0 → 验证拒绝 → execution failed，完成条件不满足）
        result_verifier=CompositeToolResultVerifier(
            (
                PatchSetResultVerifier(db),
                ShellResultVerifier(),
            )
        ),
    )


class _ScriptedModel:
    """按共享脚本返回工具调用序列（pop 消费）；耗尽后返回最终文本。"""

    def __init__(self, script: list, final_text: str = "完成") -> None:
        self._script = script
        self._final_text = final_text

    async def complete(self, request, *, cancellation):
        del request, cancellation
        if self._script:
            return ModelResponse(tool_calls=(self._script.pop(0),))
        return ModelResponse(text=self._final_text)


class _ChainScriptedModel:
    """链式脚本模型：先发 propose（safe 直接执行），从工具结果消息解析
    patch_set_id 动态构造 apply（confirm 需审批），随后消费共享 tail 脚本。

    apply 参数依赖 propose 的 durable 输出（patch_set_id / preview_version /
    parameters_hash），不能预构造；全部经 runtime 驱动，TOOL_REQUESTED
    投影创建 tool step，execution claim 契约完整。tail 由调用方持有引用，
    resume 轮次的新模型实例继续消费剩余调用（同 _ScriptedModel 语义）。
    """

    def __init__(
        self, propose_call: ToolCall, tail: list, final_text: str = "完成"
    ) -> None:
        self._propose_call = propose_call
        self._tail = tail
        self._final_text = final_text
        self._propose_sent = False
        self.propose_output: dict | None = None

    async def complete(self, request, *, cancellation):
        del cancellation
        if not self._propose_sent:
            self._propose_sent = True
            return ModelResponse(tool_calls=(self._propose_call,))
        if self.propose_output is None:
            for message in request.messages:
                if (
                    message.role == "tool"
                    and message.tool_call_id == self._propose_call.id
                ):
                    payload = json.loads(message.content)
                    output = payload.get("output")
                    assert isinstance(output, dict), "propose 工具结果必须含 output"
                    self.propose_output = output
                    break
            assert self.propose_output is not None, "未找到 propose 工具结果消息"
            self._tail.insert(
                0,
                ToolCall(
                    id="call-apply",
                    name="apply_patch_set",
                    arguments={
                        "patch_set_id": self.propose_output["patch_set_id"],
                        "preview_version": self.propose_output["preview_version"],
                        "expected_parameters_hash": self.propose_output[
                            "parameters_hash"
                        ],
                    },
                ),
            )
            return ModelResponse(tool_calls=(self._tail.pop(0),))
        if self._tail:
            return ModelResponse(tool_calls=(self._tail.pop(0),))
        return ModelResponse(text=self._final_text)


async def _approve_all_pending(db, run_id: str, dispatcher):
    """批准当前全部 pending 审批并返回带消费 token 的新 dispatcher。"""
    current = dispatcher
    last_approval_id: str | None = None
    for _ in range(6):
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        pending = [a for a in approvals if a.status == "pending"]
        if not pending:
            break
        approved = await ToolApprovalRepository(db).approve(pending[0].id)
        last_approval_id = approved.approval_id
        current = _dispatcher(
            db,
            run_id,
            approval_id=approved.approval_id,
            approval_token=approved.token,
        )
    return current, last_approval_id


async def _resume_until_terminal(
    db,
    run_id: str,
    dispatcher,
    repository,
    script: list,
    *,
    verifier=None,
    final_text: str = "完成",
    model=None,
) -> "tuple[object, ValidatedToolDispatcher]":
    """循环：批准 → 新 runner（消费剩余脚本）→ 直到终态。

    model：共享模型实例（如 _ChainScriptedModel，跨 resume 轮次保持状态）；
    默认每次新建 _ScriptedModel（共享 script 引用）。
    """
    current = dispatcher
    result = None
    for _ in range(8):
        current, approval_id = await _approve_all_pending(db, run_id, current)
        runner = PersistentAgentRunner(
            AgentRuntime(
                model
                if model is not None
                else _ScriptedModel(script, final_text=final_text),
                current,
                output_verifier=verifier,
            ),
            repository,
        )
        result = await runner.resume(
            run_id=run_id,
            approval_id=approval_id,
            tool_definitions=current.model_definitions(),
        )
        if result.status.value in {"completed", "failed", "cancelled", "timed_out"}:
            return result, current
        if approval_id is None:
            return result, current
    return result, current


async def _facts_loader(db, run_id: str, root: Path):
    """镜像 routes_agent_runs 的事实 loader（executions + patch sets + Git diff）。"""

    async def load() -> WorkflowCompletionFacts:
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        executions = []
        for record in records:
            output = (
                record.output_json if isinstance(record.output_json, dict) else None
            )
            executions.append(
                {
                    "tool_name": record.tool_name,
                    "status": record.status,
                    "error_code": record.error_code,
                    "verified": (
                        output.get("verified") if output is not None else None
                    ),
                    "profile": output.get("profile") if output is not None else None,
                }
            )
        patch_records = await CodingPatchSetRepository(db).list_for_run(run_id)
        patch_sets = [{"id": r.id, "status": r.status} for r in patch_records]
        git_diff_empty: bool | None = None
        if root is not None:
            try:
                snapshot = await read_git_snapshot(str(root))
            except GitSnapshotError:
                snapshot = None
            if snapshot is not None:
                git_diff_empty = not snapshot.dirty
        return WorkflowCompletionFacts(
            executions=executions,
            patch_sets=patch_sets,
            git_diff_empty=git_diff_empty,
        )

    return load


async def _list_artifacts(run_id: str) -> list[dict]:
    """独立 session 读 Artifact（投影经独立事务写入，纠偏 REPEATABLE READ）。"""
    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as s:
        return await RunArtifactService(s).list_artifacts(run_id)


async def _insert_running_execution(
    db,
    run_id: str,
    *,
    tool_name: str,
    execution_key_sha256: str | None = None,
) -> str:
    """插入一条 running execution（重启恢复 fixture 用）。"""
    record = ExecutionRecord(
        id=str(uuid4()),
        run_id=run_id,
        tool_call_id=f"call-a2-{uuid4().hex[:8]}",
        tool_name=tool_name,
        tool_version="1.0",
        arguments_json={"args": []},
        arguments_sha256="0" * 64,
        risk_level="confirm",
        required_capabilities_json=[],
        status="running",
        attempt_count=1,
        output_json=None,
        execution_key_sha256=execution_key_sha256,
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record.id


# ===========================================================================
# 主链：修改 → 测试 → 验证 → 报告（真实 git + 真实 pytest）
# ===========================================================================


@pytest.mark.asyncio
async def test_main_chain_modify_test_verify_report(db, tmp_path, monkeypatch):
    """后端主链完整闭环：PatchSet 原子修改 → 真实 pytest → 完成条件 → 报告。

    恢复 fixture（审批）：apply/command 各等待审批 → 批准 → resume 续跑完成；
    终态重建投影：patch_preview / patch_applied / command_result / test_report /
    final_report（completion_satisfied=True，来源引用齐全）。
    """
    if not _git_available():
        pytest.skip("git 不可用，跳过主链 E2E")
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)

    # —— 真实 git 项目：calc.py + test_calc.py（初始测试通过）——
    calc_v1 = "def add(a, b):\n    return a + b\n"
    test_calc = (
        "from calc import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
    )
    (tmp_path / "calc.py").write_text(calc_v1, encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(test_calc, encoding="utf-8")
    head_sha = _git_init_and_commit(tmp_path)

    project_id, workspace_id = await _make_project(db, tmp_path)
    await _create_profile(
        db,
        project_id,
        name="py-tests",
        args=[sys.executable, "-m", "pytest", "-q"],
        kind="test",
        parser="pytest",
    )
    conditions = {
        "must_succeed_tools": ["apply_patch_set"],
        "must_pass_command_profiles": ["py-tests"],
        "no_pending_patchsets": True,
        "final_git_diff": "nonempty",
        "require_verified": True,
    }
    run_id = await _create_coding_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        base_head_sha=head_sha,
        completion_conditions=conditions,
        start_event=False,
    )
    repository = AgentRunRepository(db)
    try:
        # —— 修改：propose（safe，零写入）→ 磁盘只读 ——
        dispatcher = _dispatcher(db, run_id)
        calc_v2 = calc_v1 + "def mul(a, b):\n    return a * b\n"
        propose_call = ToolCall(
            id="call-propose",
            name="propose_patch_set",
            arguments={
                "operations": [
                    {
                        "operation": "update",
                        "update": {
                            "path": "calc.py",
                            "expected_old_sha256": _sha256_text(calc_v1),
                            "new_content": calc_v2,
                        },
                    },
                    {
                        "operation": "create",
                        "create": {
                            "path": "test_mul.py",
                            "new_content": (
                                "from calc import mul\n\n"
                                "def test_mul():\n    assert mul(2, 3) == 6\n"
                            ),
                        },
                    },
                ]
            },
        )
        # —— 测试：真实 pytest（白名单 profile 前缀匹配，argv 数组不经 shell）——
        test_call = ToolCall(
            id="call-test",
            name="run_whitelisted_command",
            arguments={
                "project_id": project_id,
                "command": [sys.executable, "-m", "pytest", "-q"],
            },
        )
        # 链式模型：propose（safe 直接执行）→ 从工具结果消息解析 patch_set_id
        # 动态构造 apply（confirm 需审批）→ test。全部经 runtime 驱动，
        # TOOL_REQUESTED 投影创建 tool step，execution claim 契约完整。
        chain_model = _ChainScriptedModel(
            propose_call, [test_call], final_text="修改并验证完成"
        )
        runtime = AgentRuntime(chain_model, dispatcher)
        waiting = await runtime.run(
            [ModelMessage(role="user", content="添加乘法并跑测试")],
            run_id=run_id,
            tool_definitions=dispatcher.model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"
        # propose 执行事实：durable execution record + 磁盘零写入
        assert chain_model.propose_output is not None
        assert chain_model.propose_output["file_count"] == 2
        assert chain_model.propose_output["truncated"] is False
        propose_records = [
            r
            for r in await ToolExecutionRepository(db, run_id=run_id).list_for_run()
            if r.tool_name == "propose_patch_set"
        ]
        assert len(propose_records) == 1
        assert propose_records[0].status == "succeeded"
        assert (tmp_path / "calc.py").read_text(encoding="utf-8") == calc_v1

        # —— 验证：完成条件基于 durable 事实求值（模型文本不能宣称成功）——
        verifier = WorkflowCompletionOutputVerifier(
            await _facts_loader(db, run_id, tmp_path),
            must_succeed_tools=("apply_patch_set",),
            must_pass_command_profiles=("py-tests",),
            no_pending_patchsets=True,
            final_git_diff="nonempty",
            require_verified=True,
        )
        result, _ = await _resume_until_terminal(
            db,
            run_id,
            dispatcher,
            repository,
            [],
            verifier=verifier,
            final_text="修改并验证完成",
            model=chain_model,
        )
        assert result.status.value == "completed"

        # —— 磁盘事实：PatchSet 原子应用 + 回读 verified ——
        assert (tmp_path / "calc.py").read_text(encoding="utf-8") == calc_v2
        assert "def test_mul" in (tmp_path / "test_mul.py").read_text(
            encoding="utf-8"
        )
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        by_name = {r.tool_name: r for r in records}
        assert by_name["apply_patch_set"].status == "succeeded"
        assert by_name["apply_patch_set"].output_json["verified"] is True
        command = by_name["run_whitelisted_command"]
        assert command.status == "succeeded"
        assert command.output_json["profile"] == "py-tests"
        assert command.output_json["parsed"]["parser"] == "pytest"
        assert command.output_json["parsed"]["passed"] >= 2
        assert command.output_json["processes_remaining"] == 0
        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1 and patch_sets[0].status == "applied"
        snapshot = await read_git_snapshot(str(tmp_path))
        assert snapshot is not None and snapshot.dirty is True

        # —— 报告：终态投影（coordinator 接线同款）——
        await ArtifactProjectionService(db).rebuild_terminal(
            run_id=run_id, status="completed"
        )
        artifacts = await _list_artifacts(run_id)
        kinds = [a["kind"] for a in artifacts]
        for expected in (
            "patch_preview",
            "patch_applied",
            "command_result",
            "test_report",
            "final_report",
        ):
            assert kinds.count(expected) >= 1, expected
        final_report = next(a for a in artifacts if a["kind"] == "final_report")
        assert final_report["metadata"]["completion_satisfied"] is True
        assert final_report["metadata"]["status"] == "completed"
        assert "run_whitelisted_command" in final_report["metadata"]["tool_names"]
        assert any(
            item["kind"] == "test_report" for item in final_report["metadata"]["artifacts"]
        )
        test_report = next(a for a in artifacts if a["kind"] == "test_report")
        assert test_report["metadata"]["parser"] == "pytest"
        assert test_report["metadata"]["parsed"]["passed"] >= 2
        # 脱敏：报告不内嵌完整命令输出/绝对路径
        assert "processes_remaining" not in test_report["metadata"]
        assert "root_path" not in str(final_report["metadata"])
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_main_chain_completion_unmet_fails_closed(db, tmp_path, monkeypatch):
    """主链负向：命令失败 → 完成条件不满足 → run 失败关闭（不得 completed）。

    恢复 fixture（失败）：final_report 终态投影 completion_satisfied=False。
    """
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    project_id, workspace_id = await _make_project(db, tmp_path)
    await _create_profile(
        db,
        project_id,
        name="py-echo",
        args=[sys.executable, "-c"],
        kind="custom",
        parser="plain",
    )
    conditions = {"must_pass_command_profiles": ["py-echo"], "max_failed_tools": 0}
    run_id = await _create_coding_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        completion_conditions=conditions,
        start_event=False,
    )
    repository = AgentRunRepository(db)
    try:
        dispatcher = _dispatcher(db, run_id)
        fail_call = ToolCall(
            id="call-fail",
            name="run_whitelisted_command",
            arguments={
                "project_id": project_id,
                "command": [sys.executable, "-c", "import sys; sys.exit(3)"],
            },
        )
        runtime = AgentRuntime(
            _ScriptedModel([fail_call], final_text="搞定了"), dispatcher
        )
        waiting = await runtime.run(
            [ModelMessage(role="user", content="跑一下测试")],
            run_id=run_id,
            tool_definitions=dispatcher.model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"
        verifier = WorkflowCompletionOutputVerifier(
            await _facts_loader(db, run_id, None),
            must_pass_command_profiles=("py-echo",),
            max_failed_tools=0,
        )
        result, _ = await _resume_until_terminal(
            db,
            run_id,
            dispatcher,
            repository,
            [],
            verifier=verifier,
            final_text="搞定了",
        )
        assert result.status.value == "failed"
        stored = await repository.get_run(run_id)
        assert stored is not None and stored.status == "failed"
        assert stored.error_code == "output_validation_failed"
        assert "完成条件未满足" in (stored.error_message or "")

        await ArtifactProjectionService(db).rebuild_terminal(
            run_id=run_id, status="failed"
        )
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
# 恢复 fixture 冻结：审批拒绝（rejected 零写入）
# ===========================================================================


@pytest.mark.asyncio
async def test_approval_reject_marks_patchset_rejected_zero_write(db, tmp_path, monkeypatch):
    """审批拒绝 → PatchSet rejected 终态 + 磁盘零写入（人工处置后不自动应用）。"""
    monkeypatch.setattr(cfg, "coding_patchset_enabled", True)
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id, start_event=False
    )
    repository = AgentRunRepository(db)
    try:
        preview = await PatchSetService(db).propose(
            run_id,
            [
                {
                    "operation": "update",
                    "update": {
                        "path": "a.py",
                        "new_content": "v2\n",
                        "expected_old_sha256": _sha256_text("v1\n"),
                    },
                }
            ],
        )
        call = ToolCall(
            id="call-apply",
            name="apply_patch_set",
            arguments={
                "patch_set_id": preview["patch_set_id"],
                "preview_version": preview["preview_version"],
                "expected_parameters_hash": preview["parameters_hash"],
            },
        )
        # 修改：apply 经 runtime 驱动（step 由事件投影创建，requester 可定位
        # running step）→ 审批等待；用户拒绝走 cancel_waiting_approval
        runtime = AgentRuntime(_ScriptedModel([call], final_text="完成"), _dispatcher(db, run_id))
        waiting = await runtime.run(
            [ModelMessage(role="user", content="应用补丁")],
            run_id=run_id,
            tool_definitions=_dispatcher(db, run_id).model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"

        # 用户拒绝：approval 置 rejected + run 走 cancel_waiting_approval
        # （routes reject_agent_run_tool 同款路径，E0 §2.4 previewed → rejected）
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        assert len(approvals) == 1 and approvals[0].status == "pending"
        await ToolApprovalRepository(db).reject(approvals[0].id)
        cancelled = await repository.cancel_waiting_approval(
            run_id, error="tool approval rejected", error_code="approval_rejected"
        )
        assert cancelled is True

        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1 and patch_sets[0].status == "rejected"
        # 磁盘零写入（未审批零写入 + 拒绝后不自动重放）
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"
        from personal_assistant.core.patch_set_service import PatchSetError

        with pytest.raises(PatchSetError) as excinfo:
            await PatchSetService(db).apply(
                run_id,
                preview["patch_set_id"],
                preview["preview_version"],
                preview["parameters_hash"],
            )
        assert excinfo.value.error_code == "patchset_partial_unknown"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 恢复 fixture 冻结：取消（cancelled 终态 + 不再自动推进）
# ===========================================================================


@pytest.mark.asyncio
async def test_cancel_run_terminal_projection(db, tmp_path, monkeypatch):
    """取消恢复 fixture：run cancelled 终态 → final_report(cancelled)。

    取消后 reconcile 不再触碰（cancelled 非 running）；previewed PatchSet
    保留为人工处置事实（no_pending 条件会让后续 run 无法 completed）。
    """
    monkeypatch.setattr(cfg, "coding_artifacts_enabled", True)
    # 先清场：删除历史 running run（避免残留干扰 reconcile 断言；测试库
    # 专用，与 restart fixture 清场模式一致）
    await db.execute(
        delete(AgentRunRecord).where(AgentRunRecord.status == "running")
    )
    await db.commit()
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        await PatchSetService(db).propose(
            run_id,
            [{"operation": "create", "create": {"path": "b.py", "new_content": "x\n"}}],
        )
        # 模拟用户取消：run 进入 cancelled 终态（cancel_requested_at 已置位）
        await db.execute(
            update(AgentRunRecord)
            .where(AgentRunRecord.id == run_id)
            .values(status="cancelled")
        )
        await db.commit()

        await ArtifactProjectionService(db).rebuild_terminal(
            run_id=run_id, status="cancelled"
        )
        artifacts = await _list_artifacts(run_id)
        finals = [a for a in artifacts if a["kind"] == "final_report"]
        assert len(finals) == 1
        assert finals[0]["metadata"]["status"] == "cancelled"
        assert finals[0]["metadata"]["completion_satisfied"] is False

        # 取消后 reconcile 不触碰（非 running），PatchSet 未决事实保留
        result = await reconcile_orphaned_agent_runs(db)
        assert result.failed_runs == 0 and result.failed_executions == 0
        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1 and patch_sets[0].status == "previewed"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 恢复 fixture 冻结：进程重启（reconcile 语义，unknown 不自动重放）
# ===========================================================================


@pytest.mark.asyncio
async def test_restart_reconcile_patchset_and_execution_facts(db, tmp_path):
    """重启恢复 fixture：running run → failed；无 key execution → unknown。

    previewed PatchSet 保留（人工处置），executions 不自动重放、不重复
    副作用；reconcile 幂等。
    """
    # 先清场：删除历史 running run（避免残留干扰计数；测试库专用，
    # reconcile 清场会因内部 rollback 使本 session 缓存对象过期）
    await db.execute(
        delete(AgentRunRecord).where(AgentRunRecord.status == "running")
    )
    await db.commit()

    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id
    )
    try:
        # 模拟进程崩溃前状态：run running + 一条 apply 执行（无幂等 key）
        await db.execute(
            update(AgentRunRecord)
            .where(AgentRunRecord.id == run_id)
            .values(status="running")
        )
        await db.commit()
        await _insert_running_execution(
            db, run_id, tool_name="apply_patch_set", execution_key_sha256=None
        )
        await PatchSetService(db).propose(
            run_id,
            [{"operation": "create", "create": {"path": "b.py", "new_content": "x\n"}}],
        )

        # 重启后 reconcile：run 失败关闭；apply 执行无 key → unknown（人工处置）
        result = await reconcile_orphaned_agent_runs(db)
        assert result.failed_runs == 1
        assert result.unknown_executions == 1
        assert result.failed_executions == 0

        run = await db.get(AgentRunRecord, run_id)
        assert run is not None and run.status == "failed"
        assert run.error_code == "process_restarted"
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert len(records) == 1
        assert records[0].status == "unknown"
        assert records[0].error_code == "state_unknown"
        assert records[0].claim_token_sha256 is None
        # 不自动重放：仍是同一条记录（无重复 execution、无自动续跑）
        assert records[0].attempt_count == 1

        # previewed PatchSet 保留为人工处置事实，不被自动应用/回滚
        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1 and patch_sets[0].status == "previewed"

        # reconcile 幂等：再次执行零副作用
        again = await reconcile_orphaned_agent_runs(db)
        assert again.failed_runs == 0
        assert again.failed_executions == 0
        assert again.unknown_executions == 0
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )
