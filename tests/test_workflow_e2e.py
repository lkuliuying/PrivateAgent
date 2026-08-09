"""v0.5.0 B5：多步骤工作流、恢复与人工处置测试。

覆盖主计划 B5 首批端到端场景与退出条件：
- 多工具链（propose→apply→command）完整执行 + 可信完成条件验证；
- 完成条件不满足（工具失败）→ run 失败关闭，不被包装成"已完成"；
- 审批等待时（模拟进程重启）→ 续跑恢复，完成条件与创建路径一致；
- unknown execution 人工处置 API（不自动猜测成功或重跑）；
- 取消/恢复不重复副作用（non_idempotent 语义由既有测试覆盖，此处验证
  恢复路径的完成条件事实一致）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    AgentRunRepository,
    AgentRuntime,
    ModelMessage,
    ModelResponse,
    PersistentAgentRunner,
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
from personal_assistant.api import routes_agent_runs
from personal_assistant.core.command_workflow import build_command_tool_registry
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import Project
from personal_assistant.core.patch_workflow import build_patch_tool_registry


async def _approve_and_resume_until_terminal(
    db, run_id: str, dispatcher, repository, script, *, verifier=None, final_text="完成"
):
    """循环：批准 → 用新 runner（当前 dispatcher + 剩余脚本）续跑 → 直到终态。

    每个 resume 轮次需要新的 runtime（持有带 approval consumer 的 dispatcher）
    与共享脚本列表的新模型实例（继续消费剩余工具调用）；``verifier`` 为
    OutputVerifier（如 WorkflowCompletionOutputVerifier）时在 runtime 构造注入。
    """
    current = dispatcher
    approval_id: str | None = None
    result = None
    for _ in range(8):
        current, approval_id = await _approve_all_pending(db, run_id, current)
        runner = PersistentAgentRunner(
            AgentRuntime(
                ScriptedModel(script, final_text=final_text),
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


async def _make_project(db, tmp_path: Path) -> int:
    project = Project(name=f"b5-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def _cleanup(db, run_id: str | None = None, project_id: int | None = None) -> None:
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if project_id:
        await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()


class ScriptedModel:
    """按共享脚本返回工具调用序列（pop 消费）；脚本耗尽后返回最终文本。

    脚本列表由调用方持有引用，resume 轮次的新模型实例继续消费剩余调用。
    """

    def __init__(self, script: list, final_text: str = "完成") -> None:
        self._script = script
        self._final_text = final_text

    async def complete(self, request, *, cancellation):
        del cancellation
        if self._script:
            return ModelResponse(tool_calls=(self._script.pop(0),))
        return ModelResponse(text=self._final_text)


def _dispatcher(
    db,
    run_id: str,
    *,
    approval_id: str | None = None,
    approval_token: str | None = None,
    project_id: int | None = None,
) -> ValidatedToolDispatcher:
    from personal_assistant.core.tool_adapter import build_read_only_tool_registry

    del project_id
    registry = build_read_only_tool_registry(db)
    for spec in build_patch_tool_registry(db).list():
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
    )


async def _approve_all_pending(db, run_id: str, dispatcher):
    """批准当前全部 pending 审批并用新 dispatcher 续跑（可多轮）。

    返回 (dispatcher, approval_id)；resume 需要 approval_id。
    """
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


# ---------------- 场景 1：多工具链 + 完成条件 ----------------

@pytest.mark.asyncio
async def test_multi_tool_workflow_completion_conditions_met(db, tmp_path):
    """propose→apply→command 多工具链完整执行；完成条件基于事实满足。"""
    (tmp_path / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    from personal_assistant.core.repo_patch_sets import ProjectCommandProfileRepository

    await ProjectCommandProfileRepository(db).create(
        project_id=project_id,
        name="py-c",
        command_json={"args": ["python", "-c"]},
        kind="custom",
    )
    run_id = str(uuid4())
    repository = AgentRunRepository(db)

    script = [
        ToolCall(
            id="call-propose",
            name="propose_patch",
            arguments={
                "project_id": project_id,
                "rel_path": "app.py",
                "new_content": "VALUE = 'new'\n",
            },
        ),
        ToolCall(
            id="call-apply",
            name="apply_patch_to_workspace",
            arguments={
                "project_id": project_id,
                "rel_path": "app.py",
                "new_content": "VALUE = 'new'\n",
                "expected_old_sha256": __import__("hashlib").sha256(
                    "VALUE = 'old'\n".encode()
                ).hexdigest(),
            },
        ),
        ToolCall(
            id="call-test",
            name="run_whitelisted_command",
            arguments={
                "project_id": project_id,
                "command": ["python", "-c", "print('all checks passed')"],
            },
        ),
    ]
    dispatcher = _dispatcher(db, run_id, project_id=project_id)
    runner = PersistentAgentRunner(
        AgentRuntime(ScriptedModel(script, final_text="已修改并验证"), dispatcher),
        repository,
    )
    try:
        result = await runner.run(
            [ModelMessage(role="user", content="修改文件并运行测试")],
            run_id=run_id,
            tool_definitions=dispatcher.model_definitions(),
        )
        # propose 无需审批执行；apply/command 触发审批
        assert result.status.value == "waiting_approval"
        result, _ = await _approve_and_resume_until_terminal(
            db, run_id, dispatcher, repository, script, final_text="已修改并验证"
        )
        assert result.status.value == "completed"
        assert "已修改并验证" in (result.output or "")
        assert (tmp_path / "app.py").read_text(encoding="utf-8") == "VALUE = 'new'\n"

        # 完成条件：基于 durable executions 事实求值
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        facts = WorkflowCompletionFacts(
            executions=[
                {
                    "tool_name": record.tool_name,
                    "status": record.status,
                    "verified": (
                        record.output_json.get("verified")
                        if isinstance(record.output_json, dict)
                        else None
                    ),
                }
                for record in records
            ]
        )
        verifier = WorkflowCompletionOutputVerifier(
            lambda: _facts(facts),
            must_succeed_tools=("apply_patch_to_workspace", "run_whitelisted_command"),
            require_verified=True,
        )
        decision = await verifier.verify("ok", attempt=1)
        assert decision.passed is True
    finally:
        await _cleanup(db, run_id, project_id)


async def _facts(facts: WorkflowCompletionFacts) -> WorkflowCompletionFacts:
    return facts


@pytest.mark.asyncio
async def test_completion_conditions_unmet_run_fails_closed(db, tmp_path):
    """完成条件不满足（必需工具失败）→ 验证失败，run 不进入 completed。"""

    project_id = await _make_project(db, tmp_path)
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    script = [
        ToolCall(
            id="call-fail",
            name="run_whitelisted_command",
            arguments={
                "project_id": project_id,
                "command": [sys.executable, "-c", "import sys; sys.exit(3)"],
            },
        ),
    ]
    dispatcher = _dispatcher(db, run_id, project_id=project_id)
    runner = PersistentAgentRunner(
        AgentRuntime(ScriptedModel(script, final_text="搞定了"), dispatcher),
        repository,
    )
    try:
        result = await runner.run(
            [ModelMessage(role="user", content="跑一下测试")],
            run_id=run_id,
            tool_definitions=dispatcher.model_definitions(),
        )
        assert result.status.value == "waiting_approval"
        # 注入完成条件验证器后继续（命令失败 → 条件不满足）
        verifier = WorkflowCompletionOutputVerifier(
            lambda: _facts_from_db(db, run_id),
            must_succeed_tools=("run_whitelisted_command",),
            max_failed_tools=0,
        )
        result, _ = await _approve_and_resume_until_terminal(
            db,
            run_id,
            _dispatcher(db, run_id),
            repository,
            [],
            verifier=verifier,
        )
        assert result.status.value == "failed"
        stored = await repository.get_run(run_id)
        assert stored is not None and stored.status == "failed"
        assert stored.error_code == "output_validation_failed"
        assert "完成条件未满足" in (stored.error_message or "")
    finally:
        await _cleanup(db, run_id, project_id)


async def _facts_from_db(db, run_id: str) -> WorkflowCompletionFacts:
    records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
    return WorkflowCompletionFacts(
        executions=[
            {
                "tool_name": record.tool_name,
                "status": record.status,
                "verified": (
                    record.output_json.get("verified")
                    if isinstance(record.output_json, dict)
                    else None
                ),
            }
            for record in records
        ]
    )


def _dispatcher_with_verifier(db, run_id: str, verifier) -> ValidatedToolDispatcher:
    dispatcher = _dispatcher(db, run_id)
    dispatcher._output_verifier = verifier  # noqa: SLF001 - 测试注入
    return dispatcher


# ---------------- 场景 5：审批等待 → 重启 → 续跑 ----------------

@pytest.mark.asyncio
async def test_approval_wait_survives_restart_and_resumes(db, tmp_path):
    """审批等待时（模拟进程重启：新 runner/dispatcher）→ 加载未决审批 → 续跑完成。"""
    (tmp_path / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    script = [
        ToolCall(
            id="call-apply",
            name="apply_patch_to_workspace",
            arguments={
                "project_id": project_id,
                "rel_path": "app.py",
                "new_content": "VALUE = 'new'\n",
                "expected_old_sha256": __import__("hashlib").sha256(
                    "VALUE = 'old'\n".encode()
                ).hexdigest(),
            },
        ),
    ]
    first_dispatcher = _dispatcher(db, run_id, project_id=project_id)
    runner = PersistentAgentRunner(
        AgentRuntime(ScriptedModel(script, final_text="完成"), first_dispatcher),
        repository,
    )
    try:
        waiting = await runner.run(
            [ModelMessage(role="user", content="改文件")],
            run_id=run_id,
            tool_definitions=first_dispatcher.model_definitions(),
        )
        assert waiting.status.value == "waiting_approval"

        # —— 模拟应用/进程重启：用新的 session 事实重新加载 ——
        approvals = await ToolApprovalRepository(db).list_for_run(run_id)
        assert approvals and approvals[0].status == "pending"
        # 先批准（原进程持有 token），模拟"重启后 token 丢失" → reissue
        approved_once = await ToolApprovalRepository(db).approve(approvals[0].id)
        reissued = await ToolApprovalRepository(db).reissue_approved(
            approved_once.approval_id
        )
        resumed_dispatcher = _dispatcher(
            db,
            run_id,
            approval_id=reissued.approval_id,
            approval_token=reissued.token,
        )
        resumed_runner = PersistentAgentRunner(
            AgentRuntime(ScriptedModel([], final_text="完成"), resumed_dispatcher),
            repository,
        )
        completed = await resumed_runner.resume(
            run_id=run_id,
            approval_id=reissued.approval_id,
            tool_definitions=resumed_dispatcher.model_definitions(),
        )
        assert completed.status.value == "completed"
        assert (tmp_path / "app.py").read_text(encoding="utf-8") == "VALUE = 'new'\n"
        # 副作用只发生一次：单一 succeeded execution
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        assert len(records) == 1 and records[0].status == "succeeded"
    finally:
        await _cleanup(db, run_id, project_id)


# ---------------- 人工处置 unknown execution ----------------

@pytest.mark.asyncio
async def test_resolve_unknown_execution_manual_disposition(db, tmp_path, client, monkeypatch):
    """unknown execution 只能人工处置：succeeded 需输出事实；处置后审计保留。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    (tmp_path / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    project_id = await _make_project(db, tmp_path)
    run_id = str(uuid4())
    repository = AgentRunRepository(db)
    script = [
        ToolCall(
            id="call-apply",
            name="apply_patch_to_workspace",
            arguments={
                "project_id": project_id,
                "rel_path": "app.py",
                "new_content": "VALUE = 'new'\n",
                "expected_old_sha256": __import__("hashlib").sha256(
                    "VALUE = 'old'\n".encode()
                ).hexdigest(),
            },
        ),
    ]
    dispatcher = _dispatcher(db, run_id, project_id=project_id)
    runner = PersistentAgentRunner(
        AgentRuntime(ScriptedModel(script, final_text="完成"), dispatcher),
        repository,
    )
    try:
        waiting = await runner.run(
            [ModelMessage(role="user", content="改文件")],
            run_id=run_id,
            tool_definitions=dispatcher.model_definitions(),
        )
        assert waiting.status.value == "waiting_approval"
        # 审批后续跑执行成功 → 手动置为 unknown（模拟崩溃窗口）
        completed, _ = await _approve_and_resume_until_terminal(
            db, run_id, dispatcher, repository, []
        )
        assert completed.status.value == "completed"
        assert (tmp_path / "app.py").read_text(encoding="utf-8") == "VALUE = 'new'\n"
        store = ToolExecutionRepository(db, run_id=run_id)
        records = await store.list_for_run()
        assert len(records) == 1 and records[0].status == "succeeded"
        records[0].status = "unknown"
        records[0].error_code = "state_unknown"
        await db.commit()
        claim_execution_id = records[0].id

        # succeeded 无输出事实 → 409
        missing = await client.post(
            f"/agent-runs/{run_id}/executions/{claim_execution_id}/resolve",
            json={"decision": "succeeded", "note": "确认成功"},
        )
        assert missing.status_code == 409

        # 人工确认成功（带输出事实）→ succeeded + 审计
        resolved = await client.post(
            f"/agent-runs/{run_id}/executions/{claim_execution_id}/resolve",
            json={
                "decision": "succeeded",
                "output": {"rel_path": "app.py", "verified": True},
                "note": "用户人工确认写入成功",
            },
        )
        assert resolved.status_code == 200
        body = resolved.json()
        assert body["status"] == "succeeded"
        assert "人工处置" in (body["error_message"] or "")
        assert body["output"]["verified"] is True

        # 已处置后再次处置 → 409
        again = await client.post(
            f"/agent-runs/{run_id}/executions/{claim_execution_id}/resolve",
            json={"decision": "failed", "note": "再处置"},
        )
        assert again.status_code == 409
    finally:
        await _cleanup(db, run_id, project_id)


# ---------------- HTTP/SQL 多步骤（场景 2/3 的后端等价物） ----------------

@pytest.mark.asyncio
async def test_http_and_sql_tools_register_together(db, monkeypatch):
    """四类工作流工具可同时注册（独立 flag 组合 + 已启用 profile，无总开关）。"""
    from personal_assistant.core.http_profiles import HttpProfileService
    from personal_assistant.core.sql_profiles import SqlProfileService

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_command_workflow_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_http_workflow_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_sql_readonly_workflow_enabled", True
    )
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_run_read_only_tools_enabled", True
    )
    # HTTP/SQL 工具要求存在已启用 profile；先创建
    from sqlalchemy import delete as sql_delete

    from personal_assistant.core.models import HttpEndpointProfile, SqlReadonlyProfile

    http_profile = await HttpProfileService(db).create(
        {
            "name": f"b5-http-{uuid4().hex[:6]}",
            "scheme": "https",
            "host": "api.example.test",
            "port": 443,
            "allowed_methods": ["GET"],
            "headers": {},
            "secret_slots": [],
            "enabled": True,
        }
    )
    sql_profile = await SqlProfileService(db).create(
        {
            "name": f"b5-sql-{uuid4().hex[:6]}",
            "dialect": "mysql",
            "host": "127.0.0.1",
            "port": 3306,
            "database": "app",
            "username": "root",
            "password_secret_ref": "secret://os-keyring/sql/b5-x/password",
            "max_rows": 100,
            "max_bytes": 262144,
            "timeout_ms": 3000,
            "enabled": True,
        }
    )
    try:
        bundle = await routes_agent_runs.get_agent_tool_bundle(db)
        assert bundle is not None
        names = {definition.name for definition in bundle.definitions}
        for expected in (
            "propose_patch",
            "apply_patch_to_workspace",
            "run_whitelisted_command",
            "call_allowlisted_api",
            "query_readonly_sql",
        ):
            assert expected in names, expected
    finally:
        await db.execute(
            sql_delete(HttpEndpointProfile).where(HttpEndpointProfile.id == http_profile.id)
        )
        await db.execute(
            sql_delete(SqlReadonlyProfile).where(SqlReadonlyProfile.id == sql_profile.id)
        )
        await db.commit()
