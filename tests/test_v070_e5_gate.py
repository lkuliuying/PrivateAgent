"""v0.7.0 E5：Coding E2E 与恢复门禁。

冻结依据：``docs/releases/v0.7.0/v0.7.0-development-plan-20260820.md``
E5 节（任务 1–5 与退出条件）：

- 任务 1 完整真实示例项目 E2E：读取（read_file）→ 计划（update_run_plan）
  → 修改（propose/apply PatchSet）→ 测试（真实 pytest）→ 报告（final_report）
  七步闭环（版本结论 1–7 项能力逐项覆盖）；
- 任务 2 故障注入：文件冲突（apply 前外部编辑）、Git HEAD 漂移（apply 前
  外部 commit）、命令失败（alpha.2 已冻结）、sidecar 重启（reconcile）；
- 任务 3 审批过期集成级：过期后 approve 抛 ToolApprovalExpiredError、
  run 保持可解释状态、只能人工处置（取消），不自动重放；
- 任务 4 全链恢复：waiting_approval run 重启后 reconcile 不失败关闭、
  审批仍可批准并 resume 续跑完成；重启失败关闭后 Artifact 终态重建且幂等；
- 任务 5 flag 独立回退矩阵：每类 flag 单独关闭只影响对应工具族，
  只读工具与单文件可信工作流始终保留。

退出条件：
- 一个真实任务可以可信完成（测试 1）；
- 失败路径无重复副作用和幽灵状态（测试 2/3/4/5/6 的零写入/无重放断言）。
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
    ModelMessage,
    ModelResponse,
    PersistentAgentRunner,
    SqlAgentRunEventSink,
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    ToolApprovalExpiredError,
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
from personal_assistant.config import settings
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
    ToolApproval,
)
from personal_assistant.core.patch_set_tool import build_patch_set_tool_registry
from personal_assistant.core.repo_coding_patch_sets import CodingPatchSetRepository
from personal_assistant.core.run_artifact import RunArtifactService
from personal_assistant.core.run_plan_tool import build_run_plan_tool_spec
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
# 公共 helper（复用 alpha.2 门禁约定）
# ===========================================================================


async def _make_project(db, tmp_path: Path) -> tuple[int, int]:
    # 镜像真实应用 ProjectService.authorize：同步 trusted_paths（read_file/
    # propose 等只读工具的路径授权依据）。
    from personal_assistant.core.repo_tools import TrustedPathRepository

    await TrustedPathRepository(db).authorize(str(tmp_path.resolve()), "directory")
    project = Project(name=f"e5-{uuid4().hex[:8]}", root_path=str(tmp_path))
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
    """创建 project-bound coding run（E4：confirm 模式 + 完整权限快照）。"""
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
        permission_snapshot_json={
            "permission_mode": "confirm",
            "capabilities": ["filesystem.read", "filesystem.write", "process.execute"],
            "remote_provider_data_policy": "no_send",
            "patch_limits": {"max_files": 32, "max_total_bytes": 1_000_000},
        },
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
    """只读 + run_plan + PatchSet + 命令工具注册表（E5 完整工具面）。"""
    registry = build_read_only_tool_registry(db)
    registry.register(build_run_plan_tool_spec(db, run_id))
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
                    # 只读工具（read_file/grep_code/git）均声明 DATABASE_QUERY
                    # （trusted_paths 查询），与 routes_agent_runs 授予集一致。
                    ToolCapability.DATABASE_QUERY,
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

    与 alpha.2 门禁同款；apply 参数依赖 propose 的 durable 输出，不能预构造。
    tail 由调用方持有引用，resume 轮次的新模型实例继续消费剩余调用。
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


class _FullLoopModel:
    """E5 完整闭环脚本模型：read_file → update_run_plan → propose → apply → test。

    每个阶段先从历史消息中取出上一步工具结果并做事实断言（模型"看到"的是
    真实磁盘与 durable 事实），再发出下一步调用；最后返回完成文本。
    """

    def __init__(
        self,
        *,
        read_call: ToolCall,
        plan_call: ToolCall,
        propose_call: ToolCall,
        test_call: ToolCall,
        final_text: str = "闭环完成",
    ) -> None:
        self._calls = [read_call, plan_call, propose_call]
        self._test_call = test_call
        self._final_text = final_text
        self._next_index = 0
        self.results: dict[str, dict] = {}

    async def complete(self, request, *, cancellation):
        del cancellation
        if self._next_index < len(self._calls):
            call = self._calls[self._next_index]
            if self._next_index > 0:
                prev = self._calls[self._next_index - 1]
                self._capture(request, prev)
            self._next_index += 1
            return ModelResponse(tool_calls=(call,))
        if self._next_index == len(self._calls):
            prev = self._calls[-1]
            self._capture(request, prev)
            self._next_index += 1
            # 从 propose 结果动态构造 apply（参数依赖 durable 输出）
            propose = self.results[self._calls[-1].id]
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="call-apply",
                        name="apply_patch_set",
                        arguments={
                            "patch_set_id": propose["patch_set_id"],
                            "preview_version": propose["preview_version"],
                            "expected_parameters_hash": propose["parameters_hash"],
                        },
                    ),
                )
            )
        if self._next_index == len(self._calls) + 1:
            self._capture(request, ToolCall(id="call-apply", name="apply_patch_set", arguments={}))
            self._next_index += 1
            return ModelResponse(tool_calls=(self._test_call,))
        if self._next_index == len(self._calls) + 2:
            self._capture(request, self._test_call)
            self._next_index += 1
        return ModelResponse(text=self._final_text)

    def _capture(self, request, call: ToolCall) -> None:
        for message in request.messages:
            if message.role == "tool" and message.tool_call_id == call.id:
                payload = json.loads(message.content)
                output = payload.get("output")
                assert isinstance(output, dict), f"{call.name} 工具结果必须含 output"
                self.results[call.id] = output
                return
        raise AssertionError(f"未找到 {call.name} 工具结果消息")


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
    """循环：批准 → 新 runner（消费剩余脚本）→ 直到终态。"""
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


def _no_pa_leftovers(root: Path) -> list[str]:
    """工作区不应残留任何补丁备份/临时文件（原子应用零残留）。"""
    return sorted(
        p.name
        for p in root.iterdir()
        if p.name.startswith(".pa-") or p.name.endswith(".pa-orig")
    )


# ===========================================================================
# 任务 1：真实示例项目完整闭环 E2E（读取→计划→修改→测试→报告）
# ===========================================================================


@pytest.mark.asyncio
async def test_e5_full_loop_read_plan_modify_test_report(db, tmp_path, monkeypatch):
    """E5 完整闭环：read_code_file → update_run_plan → propose → apply → pytest → 报告。

    覆盖版本结论 1–7 项能力：搜索读取（read_code_file 事实断言）、可审查 PatchSet
    （propose 预览/apply 原子应用）、权限审批（confirm 双审批）、项目测试
    （真实 pytest + 完成条件）、可信验证（verified/parsed 事实）、可恢复
    Artifact（五类终态投影）、收敛状态（completed）。
    """
    if not _git_available():
        pytest.skip("git 不可用，跳过主链 E2E")
    monkeypatch.setattr(settings, "coding_artifacts_enabled", True)

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
        # ① 读取：模型先读 calc.py（read_code_file，confirm 审批），
        #    从结果断言磁盘事实（project_id + rel_path，不暴露绝对路径）
        read_call = ToolCall(
            id="call-read",
            name="read_code_file",
            arguments={"project_id": project_id, "rel_path": "calc.py"},
        )
        # ② 计划：update_run_plan 创建计划 v1（safe 直接执行）
        plan_call = ToolCall(
            id="call-plan",
            name="update_run_plan",
            arguments={
                "expected_plan_version": 1,
                "items": [
                    {
                        "item_key": "add-mul",
                        "title": "添加乘法函数并补充测试",
                        "status": "pending",
                    }
                ],
            },
        )
        # ③ 修改：propose 多文件 PatchSet（safe 零写入）
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
        # ④ 测试：真实 pytest（白名单 profile，argv 数组不经 shell）
        test_call = ToolCall(
            id="call-test",
            name="run_whitelisted_command",
            arguments={
                "project_id": project_id,
                "command": [sys.executable, "-m", "pytest", "-q"],
            },
        )
        full_loop_model = _FullLoopModel(
            read_call=read_call,
            plan_call=plan_call,
            propose_call=propose_call,
            test_call=test_call,
        )
        runtime = AgentRuntime(full_loop_model, _dispatcher(db, run_id))
        waiting = await runtime.run(
            [ModelMessage(role="user", content="读取代码后制定计划并添加乘法")],
            run_id=run_id,
            tool_definitions=_dispatcher(db, run_id).model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"
        # 首个审批是 read_code_file（confirm 读取审批）；此时磁盘零写入
        assert (tmp_path / "calc.py").read_text(encoding="utf-8") == calc_v1

        # ⑤ 验证：完成条件基于 durable 事实（模型不能宣称成功）
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
            _dispatcher(db, run_id),
            repository,
            [],
            verifier=verifier,
            model=full_loop_model,
        )
        assert result.status.value == "completed"

        # 闭环事实（模型在对话中"看到"的是真实磁盘与 durable 输出）：
        # read_code_file 结果：模型从磁盘事实学习到 calc_v1
        read_out = full_loop_model.results[read_call.id]
        assert "def add" in read_out["content"]
        # 计划事实：plan_version=1（plan.created durable 事件）
        plan_out = full_loop_model.results[plan_call.id]
        assert plan_out["plan_version"] == 1
        assert plan_out["items"][0]["item_key"] == "add-mul"
        plan_events = [
            e
            for e in await repository.list_events(run_id)
            if e.event_type == AgentEventType.PLAN_CREATED
        ]
        assert len(plan_events) == 1
        # propose 事实：文件数（多文件 PatchSet 原子预览）
        assert full_loop_model.results[propose_call.id]["file_count"] == 2

        # 磁盘事实：PatchSet 原子应用 + apply verified
        assert (tmp_path / "calc.py").read_text(encoding="utf-8") == calc_v2
        assert "def test_mul" in (tmp_path / "test_mul.py").read_text(
            encoding="utf-8"
        )
        assert _no_pa_leftovers(tmp_path) == []
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        by_name = {r.tool_name: r for r in records}
        assert by_name["read_code_file"].status == "succeeded"
        assert by_name["update_run_plan"].status == "succeeded"
        assert by_name["apply_patch_set"].status == "succeeded"
        assert by_name["apply_patch_set"].output_json["verified"] is True
        command = by_name["run_whitelisted_command"]
        assert command.status == "succeeded"
        assert command.output_json["profile"] == "py-tests"
        assert command.output_json["parsed"]["passed"] >= 2
        assert command.output_json["processes_remaining"] == 0
        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1 and patch_sets[0].status == "applied"

        # ⑥ 报告：五类终态 Artifact（E3 投影契约）
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
        assert "root_path" not in str(final_report["metadata"])
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 任务 2：故障注入——文件冲突（apply 前外部编辑，E2E 级）
# ===========================================================================


@pytest.mark.asyncio
async def test_e5_conflict_injection_fails_closed(db, tmp_path, monkeypatch):
    """E2E 级冲突注入：apply 审批等待期间外部编辑 → 冲突 → run 失败关闭。

    断言：磁盘保持外部编辑、apply execution failed（无重复）、patch_set
    failed、无 .pa 残留、run 以 output_validation_failed 失败关闭
    （must_succeed_tools 不满足，零容忍：不得 completed）。
    """
    monkeypatch.setattr(settings, "coding_artifacts_enabled", True)
    calc_v1 = "def add(a, b):\n    return a + b\n"
    (tmp_path / "calc.py").write_text(calc_v1, encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    conditions = {
        "must_succeed_tools": ["apply_patch_set"],
        "require_verified": True,
        "final_git_diff": "any",
    }
    run_id = await _create_coding_run(
        db,
        project_id=project_id,
        workspace_id=workspace_id,
        completion_conditions=conditions,
        start_event=False,
    )
    repository = AgentRunRepository(db)
    try:
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
                    }
                ]
            },
        )
        chain_model = _ChainScriptedModel(
            propose_call, [], final_text="修改完成"
        )
        runtime = AgentRuntime(chain_model, _dispatcher(db, run_id))
        waiting = await runtime.run(
            [ModelMessage(role="user", content="修改 calc.py")],
            run_id=run_id,
            tool_definitions=_dispatcher(db, run_id).model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"
        assert chain_model.propose_output is not None
        # 磁盘此时仍是 v1（apply 未审批零写入）
        assert (tmp_path / "calc.py").read_text(encoding="utf-8") == calc_v1

        # —— 故障注入：人类/IDE 在审批等待期间外部编辑文件 ——
        external = "def add(a, b):\n    return a + b + 100\n"
        (tmp_path / "calc.py").write_text(external, encoding="utf-8")

        # 批准 → resume → apply 冲突失败 → run 失败关闭
        verifier = WorkflowCompletionOutputVerifier(
            await _facts_loader(db, run_id, tmp_path),
            must_succeed_tools=("apply_patch_set",),
            require_verified=True,
        )
        result, _ = await _resume_until_terminal(
            db,
            run_id,
            _dispatcher(db, run_id),
            repository,
            [],
            verifier=verifier,
            model=chain_model,
        )
        assert result.status.value == "failed"
        stored = await repository.get_run(run_id)
        assert stored is not None and stored.status == "failed"
        assert stored.error_code == "output_validation_failed"

        # 磁盘保持外部编辑；零写入、零残留
        assert (tmp_path / "calc.py").read_text(encoding="utf-8") == external
        assert _no_pa_leftovers(tmp_path) == []
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        apply_records = [r for r in records if r.tool_name == "apply_patch_set"]
        assert len(apply_records) == 1
        assert apply_records[0].status == "failed"
        assert apply_records[0].error_code == "executor_error"
        assert "内容已变化" in (apply_records[0].error_message or "")
        # patch_set failed（人工处置事实，不自动重放）
        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1 and patch_sets[0].status == "failed"
        assert patch_sets[0].error_code == "patchset_conflict"
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 任务 2：故障注入——Git HEAD 漂移（apply 前外部 commit，E2E 级）
# ===========================================================================


@pytest.mark.asyncio
async def test_e5_head_drift_injection_fails_closed(db, tmp_path, monkeypatch):
    """E2E 级 HEAD 漂移注入：apply 审批等待期间外部 commit → 拒绝。

    run 创建时冻结 base_head_sha；apply 时 HEAD 已漂移 → git_snapshot_failed，
    零写入，run 失败关闭，不自动重放。
    """
    if not _git_available():
        pytest.skip("git 不可用，跳过 HEAD 漂移 E2E")
    monkeypatch.setattr(settings, "coding_artifacts_enabled", True)
    calc_v1 = "def add(a, b):\n    return a + b\n"
    (tmp_path / "calc.py").write_text(calc_v1, encoding="utf-8")
    head_sha = _git_init_and_commit(tmp_path)

    project_id, workspace_id = await _make_project(db, tmp_path)
    conditions = {
        "must_succeed_tools": ["apply_patch_set"],
        "require_verified": True,
        "final_git_diff": "any",
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
                            "new_content": calc_v1 + "def mul(a, b):\n    return a * b\n",
                        },
                    }
                ]
            },
        )
        chain_model = _ChainScriptedModel(propose_call, [], final_text="修改完成")
        runtime = AgentRuntime(chain_model, _dispatcher(db, run_id))
        waiting = await runtime.run(
            [ModelMessage(role="user", content="修改 calc.py")],
            run_id=run_id,
            tool_definitions=_dispatcher(db, run_id).model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"

        # —— 故障注入：外部提交改变 HEAD（如他人合并/手动修改后提交）——
        (tmp_path / "external.md").write_text("external\n", encoding="utf-8")
        _git(tmp_path, "add", ".")
        _git(
            tmp_path,
            "-c", "user.name=gate-test",
            "-c", "user.email=gate-test@example.test",
            "commit", "-m", "external drift",
        )
        drifted = _git(tmp_path, "rev-parse", "HEAD")
        assert drifted != head_sha

        verifier = WorkflowCompletionOutputVerifier(
            await _facts_loader(db, run_id, tmp_path),
            must_succeed_tools=("apply_patch_set",),
            require_verified=True,
        )
        result, _ = await _resume_until_terminal(
            db,
            run_id,
            _dispatcher(db, run_id),
            repository,
            [],
            verifier=verifier,
            model=chain_model,
        )
        assert result.status.value == "failed"
        stored = await repository.get_run(run_id)
        assert stored is not None and stored.status == "failed"
        assert stored.error_code == "output_validation_failed"

        # 零写入：calc.py 未被修改；无残留
        assert (tmp_path / "calc.py").read_text(encoding="utf-8") == calc_v1
        assert _no_pa_leftovers(tmp_path) == []
        apply_records = [
            r
            for r in await ToolExecutionRepository(db, run_id=run_id).list_for_run()
            if r.tool_name == "apply_patch_set"
        ]
        assert len(apply_records) == 1
        assert apply_records[0].status == "failed"
        assert apply_records[0].error_message
        # HEAD 漂移在进入应用前拦截：patch_set 保持 previewed（未进入应用，
        # 零部分状态）；人工处置入口 = 重新预览（E1 冻结语义）。
        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1
        assert patch_sets[0].status == "previewed"
        assert "HEAD" in (apply_records[0].error_message or "") or "漂移" in (
            apply_records[0].error_message or ""
        )
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 任务 3：审批过期（集成级，人工处置语义）
# ===========================================================================


@pytest.mark.asyncio
async def test_e5_approval_expiry_manual_disposition(db, tmp_path, monkeypatch):
    """审批过期恢复 fixture：过期后 approve 抛错、run 可解释、仅人工处置。

    断言：apply 审批等待 → 过期 → approve → ToolApprovalExpiredError；
    run 保持 waiting_approval；execution 零 apply 记录（未消费、不自动重放）；
    人工取消 → run cancelled 终态收敛。
    """
    monkeypatch.setattr(settings, "coding_artifacts_enabled", True)
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    project_id, workspace_id = await _make_project(db, tmp_path)
    run_id = await _create_coding_run(
        db, project_id=project_id, workspace_id=workspace_id, start_event=False
    )
    repository = AgentRunRepository(db)
    try:
        propose_call = ToolCall(
            id="call-propose",
            name="propose_patch_set",
            arguments={
                "operations": [
                    {
                        "operation": "update",
                        "update": {
                            "path": "a.py",
                            "expected_old_sha256": _sha256_text("v1\n"),
                            "new_content": "v2\n",
                        },
                    }
                ]
            },
        )
        chain_model = _ChainScriptedModel(propose_call, [], final_text="修改完成")
        runtime = AgentRuntime(chain_model, _dispatcher(db, run_id))
        waiting = await runtime.run(
            [ModelMessage(role="user", content="修改 a.py")],
            run_id=run_id,
            tool_definitions=_dispatcher(db, run_id).model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        pending = [a for a in approvals if a.status == "pending"]
        assert len(pending) == 1
        assert pending[0].tool_name == "apply_patch_set"

        # —— 过期：把 expires_at 拨到过去并批量处理 ——
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta

        await db.execute(
            update(ToolApproval)
            .where(ToolApproval.id == pending[0].id)
            .values(expires_at=now - timedelta(seconds=1))
        )
        await db.commit()

        # 过期后不可批准：approve 在事务内触发 TTL 检查 →
        # ToolApprovalExpiredError（一次性 token 语义 + TTL 双重失效），
        # 并把审批标记为 expired。
        with pytest.raises(ToolApprovalExpiredError):
            await ToolApprovalRepository(db).approve(pending[0].id)
        stored = await ToolApprovalRepository(db).get(pending[0].id)
        assert stored is not None and stored.status == "expired"

        # run 状态可解释：仍 waiting_approval（审批未决事实保留，人工处置入口）
        run = await db.get(AgentRunRecord, run_id)
        assert run is not None and run.status == "waiting_approval"
        # 零执行事实：apply 从未被消费/重放（expired 不自动重试）
        apply_records = [
            r
            for r in await ToolExecutionRepository(db, run_id=run_id).list_for_run()
            if r.tool_name == "apply_patch_set"
        ]
        assert apply_records == []
        # 磁盘零写入
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"

        # 人工处置：取消 run（唯一收敛路径；不自动重放、不自动重跑）
        await AgentRunRepository(db).cancel_waiting_approval(
            run_id, error="approval expired"
        )
        run = await db.get(AgentRunRecord, run_id)
        assert run is not None and run.status == "cancelled"
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        assert all(a.status in {"expired", "cancelled"} for a in approvals)
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 任务 4：重启后审批恢复（waiting_approval 保留，批准续跑完成）
# ===========================================================================


@pytest.mark.asyncio
async def test_e5_restart_preserves_waiting_approval_resumable(
    db, tmp_path, monkeypatch
):
    """sidecar 重启恢复全链：waiting_approval run 不被 reconcile 失败关闭。

    重启后 pending approval 仍可批准；resume 续跑至 completed；
    run/project/workspace/execution claim/Artifact 全链恢复。
    """
    if not _git_available():
        pytest.skip("git 不可用，跳过重启审批恢复 E2E")
    monkeypatch.setattr(settings, "coding_artifacts_enabled", True)
    # 清场：删除历史 running run（reconcile 清场会 rollback 使缓存对象过期）
    await db.execute(
        delete(AgentRunRecord).where(AgentRunRecord.status == "running")
    )
    await db.commit()

    calc_v1 = "def add(a, b):\n    return a + b\n"
    (tmp_path / "calc.py").write_text(calc_v1, encoding="utf-8")
    head_sha = _git_init_and_commit(tmp_path)
    project_id, workspace_id = await _make_project(db, tmp_path)
    conditions = {
        "must_succeed_tools": ["apply_patch_set"],
        "require_verified": True,
        "final_git_diff": "any",
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
                            "new_content": calc_v1 + "def mul(a, b):\n    return a * b\n",
                        },
                    }
                ]
            },
        )
        chain_model = _ChainScriptedModel(propose_call, [], final_text="修改完成")
        runtime = AgentRuntime(chain_model, _dispatcher(db, run_id))
        waiting = await runtime.run(
            [ModelMessage(role="user", content="修改 calc.py")],
            run_id=run_id,
            tool_definitions=_dispatcher(db, run_id).model_definitions(),
            event_sink=SqlAgentRunEventSink(repository),
        )
        assert waiting.status.value == "waiting_approval"
        assert chain_model.propose_output is not None

        # —— 模拟 sidecar 重启：reconcile 只处理 running，waiting_approval 保留 ——
        result = await reconcile_orphaned_agent_runs(db)
        assert result.failed_runs == 0
        assert result.failed_executions == 0
        assert result.unknown_executions == 0
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        assert any(a.status == "pending" for a in approvals)

        # —— 重启后人工批准 + resume 续跑（全链恢复）——
        verifier = WorkflowCompletionOutputVerifier(
            await _facts_loader(db, run_id, tmp_path),
            must_succeed_tools=("apply_patch_set",),
            require_verified=True,
        )
        final, _ = await _resume_until_terminal(
            db,
            run_id,
            _dispatcher(db, run_id),
            repository,
            [],
            verifier=verifier,
            model=chain_model,
        )
        assert final.status.value == "completed"

        # 全链事实恢复：apply verified、磁盘写入、approval consumed
        assert "def mul" in (tmp_path / "calc.py").read_text(encoding="utf-8")
        apply_records = [
            r
            for r in await ToolExecutionRepository(db, run_id=run_id).list_for_run()
            if r.tool_name == "apply_patch_set"
        ]
        assert len(apply_records) == 1
        assert apply_records[0].status == "succeeded"
        assert apply_records[0].output_json["verified"] is True
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        assert any(a.status == "consumed" for a in approvals)
        patch_sets = await CodingPatchSetRepository(db).list_for_run(run_id)
        assert len(patch_sets) == 1 and patch_sets[0].status == "applied"
        # Artifact 终态投影恢复
        await ArtifactProjectionService(db).rebuild_terminal(
            run_id=run_id, status="completed"
        )
        artifacts = await _list_artifacts(run_id)
        finals = [a for a in artifacts if a["kind"] == "final_report"]
        assert len(finals) == 1
        assert finals[0]["metadata"]["status"] == "completed"
        assert finals[0]["metadata"]["completion_satisfied"] is True
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 任务 4：重启失败关闭后 Artifact 终态重建（幂等）
# ===========================================================================


@pytest.mark.asyncio
async def test_e5_restart_terminal_artifacts_rebuilt(db, tmp_path, monkeypatch):
    """重启恢复 Artifact 全链：run 失败关闭后终态投影重建且幂等。

    模拟崩溃前已完成的 apply + 命令执行事实；reconcile 失败关闭 run →
    rebuild_terminal 重建 command_result/test_report/final_report（failed，
    completion_satisfied=False）；重复重建零重复引用。
    """
    monkeypatch.setattr(settings, "coding_artifacts_enabled", True)
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
        # 崩溃前 durable 事实：apply succeeded（verified）+ 命令 succeeded
        apply_exec = ExecutionRecord(
            id=str(uuid4()),
            run_id=run_id,
            tool_call_id="call-e5-apply",
            tool_name="apply_patch_set",
            tool_version="1.0",
            arguments_json={"patch_set_id": "ps-e5"},
            arguments_sha256="1" * 64,
            risk_level="confirm",
            required_capabilities_json=["filesystem.write"],
            status="succeeded",
            attempt_count=1,
            output_json={"verified": True, "file_count": 1},
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(apply_exec)
        await db.commit()
        command_exec = ExecutionRecord(
            id=str(uuid4()),
            run_id=run_id,
            tool_call_id="call-e5-cmd",
            tool_name="run_whitelisted_command",
            tool_version="1.0",
            arguments_json={"command": []},
            arguments_sha256="2" * 64,
            risk_level="confirm",
            required_capabilities_json=["process.execute"],
            status="succeeded",
            attempt_count=1,
            output_json={
                "profile": "py-tests",
                "parsed": {"parser": "pytest", "passed": 2, "failed": 0},
            },
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(command_exec)
        await db.commit()

        # 进程崩溃：run 仍 running → reconcile 失败关闭（process_restarted）
        result = await reconcile_orphaned_agent_runs(db)
        assert result.failed_runs == 1
        run = await db.get(AgentRunRecord, run_id)
        assert run is not None and run.status == "failed"
        assert run.error_code == "process_restarted"

        # 终态投影重建：failed 语义 + 命令事实重建（completed 执行仍投影）
        await ArtifactProjectionService(db).rebuild_terminal(
            run_id=run_id, status="failed"
        )
        artifacts = await _list_artifacts(run_id)
        kinds = [a["kind"] for a in artifacts]
        assert kinds.count("command_result") >= 1
        assert kinds.count("test_report") >= 1
        finals = [a for a in artifacts if a["kind"] == "final_report"]
        assert len(finals) == 1
        assert finals[0]["metadata"]["status"] == "failed"
        assert finals[0]["metadata"]["completion_satisfied"] is False

        # 幂等：重复重建零重复引用
        await ArtifactProjectionService(db).rebuild_terminal(
            run_id=run_id, status="failed"
        )
        artifacts2 = await _list_artifacts(run_id)
        kinds2 = [a["kind"] for a in artifacts2]
        assert kinds2.count("command_result") == kinds.count("command_result")
        assert kinds2.count("test_report") == kinds.count("test_report")
        assert len([a for a in artifacts2 if a["kind"] == "final_report"]) == 1
    finally:
        await _cleanup(
            db, run_id=run_id, project_id=project_id, workspace_id=workspace_id
        )


# ===========================================================================
# 任务 5：每类 flag 独立回退矩阵（计划 §10）
# ===========================================================================


async def _visibility_run(db, permission_mode: str = "confirm") -> str:
    """创建带权限模式的 run 记录，供 dispatcher 按模式重建模型可见定义集。"""
    from personal_assistant.agents import AgentRunLimits as _Limits

    run_id = str(uuid4())
    await AgentRunRepository(db).create_run(
        run_id=run_id,
        limits=_Limits(),
        permission_mode=permission_mode,
        permission_snapshot_json={
            "permission_mode": permission_mode,
            "capabilities": ["filesystem.read", "filesystem.write", "process.execute"],
        },
        client_request_id=str(uuid4()),
    )
    return run_id


async def _visible_names(db, run_id: str) -> set[str]:
    from personal_assistant.api import routes_agent_runs

    bundle = await routes_agent_runs.get_agent_tool_bundle(db)
    assert bundle is not None
    dispatcher = await bundle.dispatcher_factory(db, run_id)
    return {d.name for d in dispatcher.model_definitions()}


@pytest.mark.asyncio
async def test_e5_flag_matrix_independent_fallback(db, monkeypatch):
    """flag 独立回退矩阵：每类工具独立 flag，关闭只影响对应工具族。

    全关：只读工具 + 单文件可信工作流保留，PatchSet/命令/run_plan 不可见；
    单开 patchset：PatchSet 可见、命令不可见；单开 command：命令可见、
    PatchSet 不可见；单开 run_plan：update_run_plan 可见。
    """
    from personal_assistant.api import routes_agent_runs

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)
    monkeypatch.setattr(settings, "agent_run_read_only_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_patch_workflow_enabled", True)
    monkeypatch.setattr(settings, "agent_rag_tools_enabled", False)
    monkeypatch.setattr(settings, "mcp_enabled", False)
    monkeypatch.setattr(settings, "agent_http_workflow_enabled", False)
    monkeypatch.setattr(settings, "agent_sql_readonly_workflow_enabled", False)
    run_id = await _visibility_run(db, "confirm")
    try:
        # 场景 A：全关（patchset/command/run_plan/artifacts/permission-models）
        monkeypatch.setattr(settings, "coding_patchset_enabled", False)
        monkeypatch.setattr(settings, "agent_command_workflow_enabled", False)
        monkeypatch.setattr(settings, "agent_run_plan_enabled", False)
        names = await _visible_names(db, run_id)
        assert {"read_file", "search_files", "grep_code", "read_code_file"} <= names
        assert {"get_git_status", "get_git_diff", "propose_patch"} <= names
        assert "apply_patch_to_workspace" in names  # 单文件可信工作流保留
        for absent in (
            "propose_patch_set",
            "apply_patch_set",
            "run_whitelisted_command",
            "update_run_plan",
        ):
            assert absent not in names, absent

        # 场景 B：单开 patchset → PatchSet 可见，命令/run_plan 不可见
        monkeypatch.setattr(settings, "coding_patchset_enabled", True)
        names = await _visible_names(db, run_id)
        assert {"propose_patch_set", "apply_patch_set"} <= names
        assert "run_whitelisted_command" not in names
        assert "update_run_plan" not in names
        assert "read_file" in names

        # 场景 C：单开 command → 命令可见，PatchSet/run_plan 不可见
        monkeypatch.setattr(settings, "coding_patchset_enabled", False)
        monkeypatch.setattr(settings, "agent_command_workflow_enabled", True)
        names = await _visible_names(db, run_id)
        assert "run_whitelisted_command" in names
        assert "propose_patch_set" not in names
        assert "apply_patch_set" not in names
        assert "update_run_plan" not in names

        # 场景 D：单开 run_plan → update_run_plan 可见（其余不可见）
        monkeypatch.setattr(settings, "agent_command_workflow_enabled", False)
        monkeypatch.setattr(settings, "agent_run_plan_enabled", True)
        names = await _visible_names(db, run_id)
        assert "update_run_plan" in names
        assert "run_whitelisted_command" not in names
        assert "propose_patch_set" not in names
        assert "read_file" in names

        # 场景 E：flag 全关 + readonly 模式 → 只读工具保留（回退零破坏）
        monkeypatch.setattr(settings, "agent_run_plan_enabled", False)
        readonly_run = await _visibility_run(db, "readonly")
        names = await _visible_names(db, readonly_run)
        assert {"read_file", "search_files", "get_git_status"} <= names
        for absent in (
            "apply_patch_to_workspace",
            "propose_patch_set",
            "apply_patch_set",
            "run_whitelisted_command",
        ):
            assert absent not in names, absent
    finally:
        await db.execute(
            delete(AgentRunRecord).where(AgentRunRecord.id == run_id)
        )
        await db.commit()
