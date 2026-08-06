"""R4 领域级工具结果验证器测试。

覆盖（§7.2 通用约束）：
- 每个验证器的成功/失败路径；
- 超时、截断、取消状态（Shell）；
- 重试边界（API attempts）；
- dispatcher 端到端：验证失败 → durable execution 记为 failed（error_code 可查）、
  模型收到有界反馈；恢复路径（同一 run 续跑不回放已失败执行）；
- 验证器不消费审批、不增加 capability（dispatcher 策略仍由调用方决定）。
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    CancellationToken,
    ModelMessage,
    ModelResponse,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
    ToolSpec,
    ValidatedToolDispatcher,
    VersionedToolRegistry,
)
from personal_assistant.agents.result_verification import (
    ApiResultVerifier,
    CodeCommandResultVerifier,
    CompositeToolResultVerifier,
    DatabaseResultVerifier,
    FileDiffResultVerifier,
    ResultVerification,
    ShellResultVerifier,
    WorkflowCompletionVerifier,
)
from personal_assistant.core.code_tools import apply_patch_to_workspace, propose_patch
from personal_assistant.core.models import AgentRun
from personal_assistant.core.models import AgentToolExecution as ExecutionRecord

# ---------------- 1. 文件 Diff 验证器 ----------------


def _verifier(tmp_path: Path, verifier_cls=FileDiffResultVerifier, **kwargs):
    async def resolve_root(project_id: int) -> str:
        del project_id
        return str(tmp_path)

    return verifier_cls(resolve_root, **kwargs)


def _preview_result(old_sha: str, new_sha: str, rel_path: str = "a.txt", **extra):
    base = {
        "project_id": 1,
        "rel_path": rel_path,
        "old_sha256": old_sha,
        "new_sha256": new_sha,
        "diff": "--- a/a.txt\n+++ b/a.txt\n",
        "creates_file": False,
        "changed": True,
        "truncated": False,
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_file_diff_preview_consistent_with_disk(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("old content\n", encoding="utf-8")
    import hashlib

    old_sha = hashlib.sha256("old content\n".encode()).hexdigest()
    new_sha = hashlib.sha256("new content\n".encode()).hexdigest()
    v = _verifier(tmp_path)
    decision = await v.verify(
        "propose_patch",
        {"project_id": 1, "rel_path": "a.txt", "new_content": "new content\n"},
        _preview_result(old_sha, new_sha),
    )
    assert decision.passed is True


@pytest.mark.asyncio
async def test_file_diff_rejects_stale_preview_after_disk_change(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("old content\n", encoding="utf-8")
    import hashlib

    old_sha = hashlib.sha256("old content\n".encode()).hexdigest()
    new_sha = hashlib.sha256("new content\n".encode()).hexdigest()
    v = _verifier(tmp_path)
    # 预览生成后磁盘内容被外部修改 → old_sha 不再匹配
    target.write_text("tampered content\n", encoding="utf-8")
    decision = await v.verify(
        "propose_patch",
        {"project_id": 1, "rel_path": "a.txt", "new_content": "new content\n"},
        _preview_result(old_sha, new_sha),
    )
    assert decision.passed is False
    assert decision.code == "content_changed_since_preview"


@pytest.mark.asyncio
async def test_file_diff_write_readback_matches(tmp_path, db):
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    try:
        result = await apply_patch_to_workspace(
            db,
            project_id,
            "a.txt",
            "new content\n",
            expected_old_sha256=None,
            create=False,
        )
        # 真实写入：磁盘回读 SHA 必须等于 new_sha256
        v = _verifier(tmp_path)
        decision = await v.verify(
            "apply_patch_to_workspace",
            {"project_id": project_id, "rel_path": "a.txt", "new_content": "new content\n"},
            result,
        )
        assert decision.passed is True
        assert target.read_text(encoding="utf-8") == "new content\n"
    finally:
        from personal_assistant.core.models import Project

        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


@pytest.mark.asyncio
async def test_file_diff_write_tamper_fails_readback(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    import hashlib

    new_sha = hashlib.sha256("declared content\n".encode()).hexdigest()
    v = _verifier(tmp_path)
    # 工具声明写入了 X，但磁盘实际是 Y → 回读失败
    decision = await v.verify(
        "apply_patch_to_workspace",
        {"project_id": 1, "rel_path": "a.txt", "new_content": "declared content\n"},
        _preview_result(
            "0" * 64, new_sha, rel_path="a.txt",
            size_bytes=5,
            **{"creates_file": False, "changed": True},
        ),
    )
    assert decision.passed is False
    assert decision.code == "write_verification_failed"


@pytest.mark.asyncio
async def test_file_diff_rejects_tampered_new_sha256(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    import hashlib

    old_sha = hashlib.sha256("old\n".encode()).hexdigest()
    wrong_new = hashlib.sha256("lie\n".encode()).hexdigest()
    v = _verifier(tmp_path)
    decision = await v.verify(
        "propose_patch",
        {"project_id": 1, "rel_path": "a.txt", "new_content": "honest content\n"},
        _preview_result(old_sha, wrong_new),
    )
    assert decision.passed is False
    assert decision.code == "new_sha256_mismatch"


@pytest.mark.asyncio
async def test_file_diff_rejects_path_escape(tmp_path):
    v = _verifier(tmp_path)
    import hashlib

    decision = await v.verify(
        "propose_patch",
        {"project_id": 1, "rel_path": "../outside.txt", "new_content": "x"},
        _preview_result("0" * 64, hashlib.sha256(b"x").hexdigest(), rel_path="../outside.txt"),
    )
    assert decision.passed is False


# ---------------- 3. Shell 验证器 ----------------


def _shell_result(returncode: int = 0, **extra):
    base = {
        "args": ["pytest", "-q"],
        "cwd": "C:\\work",
        "returncode": returncode,
        "stdout": "1 passed",
        "stderr": "",
        "output": "1 passed",
        "truncated": False,
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_shell_success_and_failure_codes():
    v = ShellResultVerifier()
    assert (await v.verify("run_whitelisted_command", {}, _shell_result())).passed is True
    failed = await v.verify(
        "run_whitelisted_command", {}, _shell_result(returncode=2, stderr="boom")
    )
    assert failed.passed is False
    assert failed.code == "shell_exit_code_unexpected"
    assert "boom" in failed.message


@pytest.mark.asyncio
async def test_shell_timeout_and_cancellation_are_rejected():
    v = ShellResultVerifier()
    timeout = await v.verify(
        "run_whitelisted_command", {}, _shell_result(timed_out=True)
    )
    assert timeout.passed is False and timeout.code == "shell_timeout"
    cancelled = await v.verify(
        "run_whitelisted_command", {}, _shell_result(cancelled=True)
    )
    assert cancelled.passed is False and cancelled.code == "shell_cancelled"


@pytest.mark.asyncio
async def test_shell_truncation_rejection_is_configurable():
    tolerant = ShellResultVerifier(reject_truncated=False)
    strict = ShellResultVerifier(reject_truncated=True)
    truncated = _shell_result(truncated=True)
    assert (await tolerant.verify("run_whitelisted_command", {}, truncated)).passed is True
    decision = await strict.verify("run_whitelisted_command", {}, truncated)
    assert decision.passed is False
    assert decision.code == "shell_output_truncated"


# ---------------- 2. 代码验证器 ----------------


@pytest.mark.asyncio
async def test_code_command_whitelist_and_markers():
    v = CodeCommandResultVerifier()
    ok = await v.verify(
        "run_whitelisted_command",
        {},
        _shell_result(output="1 passed, 0 failed in 0.1s", args=["pytest", "-q"]),
    )
    assert ok.passed is True

    not_whitelisted = await v.verify(
        "run_whitelisted_command",
        {},
        _shell_result(output="done", args=["rm", "-rf", "x"]),
    )
    assert not_whitelisted.passed is False
    assert not_whitelisted.code == "code_command_not_whitelisted"

    failed_marker = await v.verify(
        "run_whitelisted_command",
        {},
        _shell_result(returncode=0, output="FAILED: test_a", args=["pytest", "-q"]),
    )
    assert failed_marker.passed is False
    assert failed_marker.code == "code_check_failed"

    no_marker = await v.verify(
        "run_whitelisted_command",
        {},
        _shell_result(output="exit cleanly but no marker", args=["cargo", "check"]),
    )
    assert no_marker.passed is False
    assert no_marker.code == "code_check_no_success_marker"


# ---------------- 4. API 验证器 ----------------


@pytest.mark.asyncio
async def test_api_status_schema_and_retry_bounds():
    schema = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
        "additionalProperties": False,
    }
    v = ApiResultVerifier(
        response_schema=schema,
        max_attempts=3,
        require_idempotency_key=True,
    )
    ok = await v.verify(
        "call_api",
        {},
        {
            "status_code": 200,
            "body": {"id": 1},
            "attempts": 1,
            "idempotency_key": "key-1",
        },
    )
    assert ok.passed is True

    bad_status = await v.verify("call_api", {}, {"status_code": 503, "body": {}})
    assert bad_status.passed is False and bad_status.code == "api_status_unexpected"

    bad_schema = await v.verify(
        "call_api",
        {},
        {"status_code": 200, "body": {"id": "not-int"}, "attempts": 1, "idempotency_key": "k"},
    )
    assert bad_schema.passed is False and bad_schema.code == "api_schema_mismatch"

    too_many = await v.verify(
        "call_api",
        {},
        {"status_code": 200, "body": {"id": 1}, "attempts": 4, "idempotency_key": "k"},
    )
    assert too_many.passed is False and too_many.code == "api_retry_bound_exceeded"

    no_key = await v.verify(
        "call_api", {}, {"status_code": 200, "body": {"id": 1}, "attempts": 1}
    )
    assert no_key.passed is False and no_key.code == "api_missing_idempotency_key"


# ---------------- 5. 数据库验证器 ----------------


@pytest.mark.asyncio
async def test_database_commit_rows_and_readback():
    v = DatabaseResultVerifier(
        affected_min=1,
        affected_max=1,
        readback={"status": "applied"},
    )
    ok = await v.verify(
        "run_database_op",
        {},
        {
            "committed": True,
            "affected_rows": 1,
            "readback": {"id": 10, "status": "applied"},
        },
    )
    assert ok.passed is True

    not_committed = await v.verify(
        "run_database_op", {}, {"committed": False, "affected_rows": 1}
    )
    assert not_committed.passed is False and not_committed.code == "db_not_committed"

    rows = await v.verify(
        "run_database_op",
        {},
        {"committed": True, "affected_rows": 5},
    )
    assert rows.passed is False and rows.code == "db_affected_rows_unexpected"

    readback = await v.verify(
        "run_database_op",
        {},
        {"committed": True, "affected_rows": 1, "readback": {"status": "pending"}},
    )
    assert readback.passed is False and readback.code == "db_readback_mismatch"

    constraint = await v.verify(
        "run_database_op",
        {},
        {"committed": True, "affected_rows": 1, "constraint_error": "duplicate key"},
    )
    assert constraint.passed is False and constraint.code == "db_constraint_error"


# ---------------- 6. 多步骤完成条件 ----------------


@pytest.mark.asyncio
async def test_workflow_completion_requires_all_trusted_conditions():
    v = WorkflowCompletionVerifier(
        [
            ("file_applied", lambda: _true()),
            ("audit_written", lambda: _true()),
        ]
    )
    decision = await v.verify()
    assert decision.passed is True

    v2 = WorkflowCompletionVerifier(
        [
            ("file_applied", lambda: _true()),
            ("audit_written", lambda: _false()),
        ]
    )
    decision2 = await v2.verify()
    assert decision2.passed is False
    assert decision2.code == "completion_not_met"
    assert "audit_written" in decision2.message


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False


# ---------------- 组合验证器 ----------------


@pytest.mark.asyncio
async def test_composite_verifier_runs_supported_verifiers_in_order():
    v = CompositeToolResultVerifier(
        [
            ShellResultVerifier(supported=("cmd",)),
            ApiResultVerifier(supported=("api",), allowed_status_ranges=((200, 299),)),
        ]
    )
    assert v.supports("cmd") and v.supports("api") and not v.supports("other")
    shell_fail = await v.verify("cmd", {}, _shell_result(returncode=1))
    assert shell_fail.passed is False and shell_fail.code == "shell_exit_code_unexpected"
    api_ok = await v.verify("api", {}, {"status_code": 204})
    assert api_ok.passed is True
    other = await v.verify("other", {}, {})
    assert other.passed is True


# ---------------- dispatcher 端到端（真实工具 + durable execution） ----------------


def _patch_spec(db, executor) -> ToolSpec:
    return ToolSpec(
        name="apply_patch_to_workspace",
        version="1.0.0",
        description="Apply one authorized patch",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "minimum": 1},
                "rel_path": {"type": "string", "minLength": 1},
                "new_content": {"type": "string"},
                "expected_old_sha256": {"type": ["string", "null"]},
                "create": {"type": "boolean"},
            },
            "required": ["project_id", "rel_path", "new_content"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "rel_path": {"type": "string"},
                "old_sha256": {"type": "string"},
                "new_sha256": {"type": "string"},
                "size_bytes": {"type": "integer"},
                "diff": {"type": "string"},
                "truncated": {"type": "boolean"},
            },
            "required": [
                "project_id",
                "rel_path",
                "old_sha256",
                "new_sha256",
                "size_bytes",
                "diff",
                "truncated",
            ],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.SAFE,
        required_capabilities=frozenset(
            {ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}
        ),
        timeout_ms=10_000,
        max_output_bytes=128 * 1024,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=executor,
    )


async def _create_run(db, *, tool_call_id: str = "call-1") -> str:
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
                "name": "echo",
            },
        )
    )
    return run_id


async def _make_project(db, tmp_path: Path) -> int:
    from personal_assistant.core.models import Project

    project = Project(name=f"r4-proj-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


@pytest.mark.asyncio
async def test_dispatcher_persists_success_after_result_verification(db, tmp_path):
    """验证通过 → 执行成功且持久化 succeeded。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db, tool_call_id="call-apply-1")

    async def honest_executor(arguments, cancellation):
        del cancellation
        return await apply_patch_to_workspace(
            db,
            arguments["project_id"],
            arguments["rel_path"],
            arguments["new_content"],
            expected_old_sha256=arguments.get("expected_old_sha256"),
            create=bool(arguments.get("create", False)),
        )

    async def resolve_root(project_id: int) -> str:
        del project_id
        return str(tmp_path)

    registry = VersionedToolRegistry()
    registry.register(_patch_spec(db, honest_executor))
    repository = ToolExecutionRepository(db, run_id=run_id)
    dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset(
                {ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}
            )
        ),
        execution_store=repository,
        result_verifier=FileDiffResultVerifier(resolve_root),
    )
    call = ToolCall(
        id="call-apply-1",
        name="apply_patch_to_workspace",
        arguments={
            "project_id": project_id,
            "rel_path": "a.txt",
            "new_content": "new content\n",
        },
    )
    try:
        result = await dispatcher.execute(call, cancellation=CancellationToken())
        assert result.success is True
        records = await repository.list_for_run()
        assert len(records) == 1 and records[0].status == "succeeded"
        assert target.read_text(encoding="utf-8") == "new content\n"
    finally:
        from personal_assistant.core.models import Project

        await db.execute(delete(ExecutionRecord).where(ExecutionRecord.run_id == run_id))
        await db.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


@pytest.mark.asyncio
async def test_dispatcher_result_verification_failure_is_durable_and_bounded(
    db, tmp_path
):
    """陈旧结果（声明写入但磁盘不一致）→ 验证失败：有界反馈 + failed 持久化。"""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db, tool_call_id="call-apply-1")

    async def stale_executor(arguments, cancellation):
        del cancellation
        # 只生成预览（磁盘未被写入），模拟陈旧/伪造结果；字段对齐 apply 输出 schema
        preview = await propose_patch(db, project_id, "a.txt", arguments["new_content"])
        return {
            "project_id": preview["project_id"],
            "rel_path": preview["rel_path"],
            "old_sha256": preview["old_sha256"],
            "new_sha256": preview["new_sha256"],
            "size_bytes": 0,
            "diff": preview["diff"],
            "truncated": preview["truncated"],
        }

    async def resolve_root(project_id: int) -> str:
        del project_id
        return str(tmp_path)

    registry = VersionedToolRegistry()
    registry.register(_patch_spec(db, stale_executor))
    repository = ToolExecutionRepository(db, run_id=run_id)
    dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset(
                {ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}
            )
        ),
        execution_store=repository,
        result_verifier=FileDiffResultVerifier(resolve_root),
    )
    call = ToolCall(
        id="call-apply-1",
        name="apply_patch_to_workspace",
        arguments={
            "project_id": project_id,
            "rel_path": "a.txt",
            "new_content": "new content\n",
        },
    )
    try:
        failed = await dispatcher.execute(call, cancellation=CancellationToken())
        assert failed.success is False
        assert failed.error_code == "write_verification_failed"
        assert "new_sha256" in (failed.error or "")
        assert len(failed.error or "") <= 2_000

        records = await repository.list_for_run()
        assert len(records) == 1
        assert records[0].status == "failed"
        assert records[0].error_code == "write_verification_failed"
        # 失败执行不产生可回放的 succeeded 输出（非幂等拒绝自动重放）
        assert target.read_text(encoding="utf-8") == "old\n"
    finally:
        from personal_assistant.core.models import Project

        await db.execute(delete(ExecutionRecord).where(ExecutionRecord.run_id == run_id))
        await db.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


@pytest.mark.asyncio
async def test_runtime_model_receives_bounded_verification_feedback(db, tmp_path):
    """端到端：模型调用工具 → 结果验证失败 → 模型收到有界错误并完成回答。"""
    from personal_assistant.agents import AgentRuntime, ModelClient, TokenUsage
    from personal_assistant.agents.runtime import ModelRequest

    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = await _create_run(db, tool_call_id="rt-call-1")

    calls_seen: list[dict] = []

    class VerifyingModel(ModelClient):
        async def complete(self, request: ModelRequest, *, cancellation):
            del cancellation
            if not calls_seen:
                calls_seen.append({})
                return ModelResponse(
                    tool_calls=(
                        ToolCall(
                            id="rt-call-1",
                            name="apply_patch_to_workspace",
                            arguments={
                                "project_id": project_id,
                                "rel_path": "a.txt",
                                "new_content": "new content\n",
                            },
                        ),
                    ),
                    usage=TokenUsage(input_tokens=4, output_tokens=4),
                    provider="fake",
                    model="r4",
                )
            calls_seen.append({})
            return ModelResponse(
                text='{"answer": "done"}',
                usage=TokenUsage(input_tokens=4, output_tokens=4),
                provider="fake",
                model="r4",
            )

    async def failing_executor(arguments, cancellation):
        del cancellation
        # 模拟"声明写入但磁盘事实不一致"（陈旧结果）→ 验证器必须抓住
        preview = await propose_patch(db, project_id, "a.txt", arguments["new_content"])
        return {
            "project_id": preview["project_id"],
            "rel_path": preview["rel_path"],
            "old_sha256": preview["old_sha256"],
            "new_sha256": preview["new_sha256"],
            "size_bytes": 0,
            "diff": preview["diff"],
            "truncated": preview["truncated"],
        }

    async def resolve_root(project_id: int) -> str:
        del project_id
        return str(tmp_path)

    registry = VersionedToolRegistry()
    registry.register(
        _patch_spec(
            db,
            failing_executor,
        )
    )
    repository = ToolExecutionRepository(db, run_id=run_id)
    dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(
            granted_capabilities=frozenset(
                {ToolCapability.FILESYSTEM_READ, ToolCapability.DATABASE_QUERY}
            )
        ),
        execution_store=repository,
        result_verifier=FileDiffResultVerifier(resolve_root),
    )
    runtime = AgentRuntime(VerifyingModel(), dispatcher)
    try:
        outcome = await runtime.run(
            [ModelMessage(role="user", content="apply the patch")],
            run_id=run_id,
            tool_definitions=dispatcher.model_definitions(),
        )
        assert outcome.status.value == "completed"
        assert len(calls_seen) == 2  # 工具失败反馈后模型第二次给出最终回答
        records = await repository.list_for_run()
        failed = [r for r in records if r.tool_call_id == "rt-call-1"]
        assert len(failed) == 1
        assert failed[0].status == "failed"
        assert failed[0].error_code == "write_verification_failed"
    finally:
        from personal_assistant.core.models import Project

        await db.execute(delete(ExecutionRecord).where(ExecutionRecord.run_id == run_id))
        await db.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


@pytest.mark.asyncio
async def test_result_verification_never_consumes_approval(db):
    """验证失败发生在审批消费之后、持久化成功之前；失败不撤销已消费审批，
    但不会重复消费（审批一次消费语义由 ToolApprovalRepository 保证）。"""
    # 构造一个需要审批的工具，验证器永远拒绝
    from personal_assistant.agents import SqlToolApprovalRequester
    from personal_assistant.core.models import ToolApproval as ApprovalRecord

    run_id = await _create_run(db)

    async def never_pass_verifier_verify(tool_name, arguments, result):
        del tool_name, arguments, result
        return ResultVerification.fail("test_rejected", "验证器恒定拒绝")

    class NeverPassVerifier:
        name = "test_never_pass"

        def supports(self, tool_name: str) -> bool:
            return tool_name == "echo"

        async def verify(self, tool_name, arguments, result):
            return await never_pass_verifier_verify(tool_name, arguments, result)

    async def echo_executor(arguments, cancellation):
        del cancellation
        return {"value": arguments["value"]}

    spec = ToolSpec(
        name="echo",
        version="1.0.0",
        description="echo",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset(),
        timeout_ms=1_000,
        max_output_bytes=1_024,
        idempotency=ToolIdempotency.NON_IDEMPOTENT,
        supports_cancellation=False,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        executor=echo_executor,
    )
    registry = VersionedToolRegistry()
    registry.register(spec)
    requester = SqlToolApprovalRequester(db, run_id=run_id)
    repository = ToolExecutionRepository(db, run_id=run_id)
    dispatcher = ValidatedToolDispatcher(
        registry,
        policy=ToolCapabilityPolicy(),
        approval_requester=requester,
        execution_store=repository,
        result_verifier=NeverPassVerifier(),
    )
    call = ToolCall(id="call-1", name="echo", arguments={"value": "x"})
    try:
        first = await dispatcher.execute(call, cancellation=CancellationToken())
        assert first.success is False
        assert first.error_code == "approval_required"
        approvals = (
            (await db.execute(select(ApprovalRecord).where(ApprovalRecord.run_id == run_id)))
            .scalars()
            .all()
        )
        assert len(approvals) == 1
        approval_id = approvals[0].id
        # 消费审批后执行 → 验证失败（不通过），执行记为 failed
        from personal_assistant.agents import (
            SqlToolApprovalConsumer,
            ToolApprovalRepository,
        )

        approved = await ToolApprovalRepository(db).approve(approval_id)
        consumer = SqlToolApprovalConsumer(
            db, approval_id=approved.approval_id, token=approved.token
        )
        dispatcher2 = ValidatedToolDispatcher(
            registry,
            policy=ToolCapabilityPolicy(),
            approval_consumer=consumer,
            execution_store=repository,
            result_verifier=NeverPassVerifier(),
        )
        second = await dispatcher2.execute(call, cancellation=CancellationToken())
        assert second.success is False
        assert second.error_code == "test_rejected"
        records = await repository.list_for_run()
        assert records and records[-1].status == "failed"
        assert records[-1].error_code == "test_rejected"
    finally:
        await db.execute(delete(ApprovalRecord).where(ApprovalRecord.run_id == run_id))
        await db.execute(delete(ExecutionRecord).where(ExecutionRecord.run_id == run_id))
        await db.execute(delete(AgentRun).where(AgentRun.id == run_id))
        await db.commit()
