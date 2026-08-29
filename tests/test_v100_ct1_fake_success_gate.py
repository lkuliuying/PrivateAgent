"""v1.0.0 CT1 契约测试：不会说谎的工具主链（专项计划 §17 CT1-01/§18.2）。

固化 ``hello.py`` 零工具假成功回归场景：

- F-001：hello.py 创建审批落盘 → 磁盘 SHA 链 + 完成契约满足；
- F-002：Patch 工具不可用 → run 创建即 ``tool_capability_unavailable``，
  不调用模型、磁盘零变更；
- F-003：模型只回复"已创建"、0 次工具 → ``required_effect_missing``；
- F-004：只调用 propose_patch → ``completion_not_met`` + 立即 apply 纠偏；
- F-007：写入声称成功但回读不一致 → ``side_effect_unverified``；
- F-008：显式仅预览 → 清除写入要求，proposal 即可完成。

完成判定唯一实现为 ``agent_v2.domain.completion.evaluate_completion``
（ADR-007 §2）；本文件同时锁定契约的确定性重建（create/resume 同 ID）。
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete
from test_v070_permissions import _create_coding_env, _post_coding_run

from personal_assistant.agent_v2.application.contract_factory import (
    build_completion_contract_from_conditions,
)
from personal_assistant.agent_v2.application.intent_rules import classify_message
from personal_assistant.agent_v2.application.preflight import (
    assess_workspace_file_write,
)
from personal_assistant.agent_v2.domain.completion import (
    CompletionContract,
    evaluate_completion,
)
from personal_assistant.agent_v2.domain.effects import EffectClass, EffectRecord
from personal_assistant.agent_v2.domain.intents import IntentTag
from personal_assistant.agents import (
    AgentEvent,
    AgentEventType,
    AgentRunLimits,
    AgentRunRepository,
    CancellationToken,
    ToolCall,
    ToolCapability,
    ToolCapabilityPolicy,
    ToolExecutionRepository,
    ValidatedToolDispatcher,
)
from personal_assistant.agents.approvals import (
    SqlToolApprovalConsumer,
    SqlToolApprovalRequester,
    ToolApprovalRepository,
)
from personal_assistant.agents.result_verification import FileDiffResultVerifier
from personal_assistant.agents.verification import (
    CompletionContractOutputVerifier,
    WorkflowCompletionFacts,
)
from personal_assistant.api import routes_agent_runs
from personal_assistant.core.models import AgentRun as AgentRunRecord
from personal_assistant.core.models import Project
from personal_assistant.core.patch_workflow import build_patch_tool_registry

HELLO_PY = "print('hello world')\n"


# ===========================================================================
# 辅助
# ===========================================================================


async def _make_project(db, tmp_path) -> int:
    project = Project(name=f"ct1-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def _cleanup(db, run_id: str, project_id: int | None = None) -> None:
    if run_id:
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
    if project_id:
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.execute(delete(AgentRunRecord).where(AgentRunRecord.session_id == -1))
    await db.commit()


def _write_contract() -> CompletionContract:
    return build_completion_contract_from_conditions(
        {"min_tool_executions": 1, "require_successful_file_write": True}
    )


def _facts(*executions: dict) -> WorkflowCompletionFacts:
    return WorkflowCompletionFacts(executions=list(executions))


def _facts_loader(facts: WorkflowCompletionFacts):
    async def load() -> WorkflowCompletionFacts:
        return facts

    return load


async def _verify_facts(facts: WorkflowCompletionFacts):
    verifier = CompletionContractOutputVerifier(
        _facts_loader(facts), _write_contract()
    )
    return await verifier.verify("已创建 hello.py", attempt=1)


# ===========================================================================
# A. 规则层意图分类（CT1-02，专项计划 §7.4）
# ===========================================================================


@pytest.mark.parametrize(
    ("message", "expected_tag", "preview_only"),
    [
        ("在根目录创建一个 hello.py 文件", IntentTag.FILE_MUTATE, False),
        ("只预览 hello.txt 的修改，不要写入", IntentTag.FILE_PREVIEW, True),
        ("如何创建 hello.txt 文件", IntentTag.ANSWER_ONLY, False),
        ("运行项目测试", IntentTag.COMMAND_RUN, False),
        ("你好", IntentTag.ANSWER_ONLY, False),
    ],
)
def test_classify_message_matrix(message, expected_tag, preview_only):
    intent = classify_message(message)
    assert expected_tag in intent.tags
    assert intent.preview_only is preview_only


def test_preview_only_clears_file_write_requirement():
    """F-008 规则层口径：显式仅预览不得强制真实落盘。"""
    intent = classify_message("只预览 hello.txt 的修改，不要写入")
    assert not intent.requires_file_write
    assert EffectClass.FILESYSTEM_WRITE not in intent.required_effects


def test_model_tags_can_only_add_not_reduce():
    """模型补充 tag 只增不减 required effects（§7.4）。"""
    intent = classify_message("在根目录创建一个 hello.py 文件")
    merged = intent.merge_model_tags(frozenset({IntentTag.COMMAND_TEST}))
    assert IntentTag.COMMAND_TEST in merged.tags
    assert EffectClass.FILESYSTEM_WRITE in merged.required_effects


# ===========================================================================
# B. 完成契约引擎单元（CT1-03，F-003/F-004/F-007）
# ===========================================================================


async def test_zero_tool_calls_claiming_success_is_required_effect_missing():
    """F-003：模型宣称已创建但零工具调用 → 必须失败关闭。"""
    verification = await _verify_facts(_facts())
    assert verification.passed is False
    assert verification.code == "required_effect_missing"


async def test_proposal_only_is_completion_not_met_with_apply_correction():
    """F-004：只有 propose_patch 成功 → completion_not_met + 立即 apply。"""
    verification = await _verify_facts(
        _facts({"tool_name": "propose_patch", "status": "succeeded"})
    )
    assert verification.passed is False
    assert verification.code == "completion_not_met"
    assert "apply_patch_to_workspace" in (verification.correction or "")


async def test_unverified_write_is_side_effect_unverified():
    """F-007：写入声称成功但回读验证不成立 → 证据不可信。"""
    verification = await _verify_facts(
        _facts(
            {
                "tool_name": "apply_patch_to_workspace",
                "status": "succeeded",
                "verified": False,
            }
        )
    )
    assert verification.passed is False
    assert verification.code == "side_effect_unverified"


async def test_failed_command_counts_as_evidence_but_not_as_write():
    """失败命令是执行证据（H1-B 语义），但不能冒充文件写入完成。"""
    evaluation = evaluate_completion(
        _write_contract(),
        [
            EffectRecord(
                tool_name="run_whitelisted_command",
                status="failed",
                effects=(EffectClass.PROCESS_SPAWN,),
            )
        ],
    )
    assert evaluation.satisfied is False
    assert evaluation.evidence_count == 1
    assert evaluation.failure_code == "completion_not_met"
    assert evaluation.missing_effects == (EffectClass.FILESYSTEM_WRITE,)


async def test_unknown_tool_counts_as_evidence_only():
    """未分类工具（如 MCP）计入证据数，但不满足 filesystem.write。"""
    evaluation = evaluate_completion(
        _write_contract(),
        [EffectRecord(tool_name="mcp.unknown_thing", status="succeeded")],
    )
    assert evaluation.evidence_count == 1
    assert evaluation.satisfied is False


async def test_verified_write_satisfies_contract():
    """succeeded + verified=True 的写入满足契约（含后置谓词语义）。"""
    verifier = CompletionContractOutputVerifier(
        _facts_loader(
            _facts(
                {
                    "tool_name": "apply_patch_to_workspace",
                    "status": "succeeded",
                    "verified": True,
                }
            )
        ),
        _write_contract(),
    )
    verification = await verifier.verify("done", attempt=1)
    assert verification.passed is True, verification.message


def test_contract_rejects_unknown_postcondition():
    """未知完成谓词必须构造失败（失败关闭，不允许静默弱化）。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CompletionContract(contract_id="cc-" + "0" * 32, postconditions=("model_says_so",))


def test_contract_engine_direct_evaluation_matrix():
    """引擎直评矩阵：无门槛契约恒满足；多写次数门槛生效。"""
    empty = evaluate_completion(_write_contract(), [])
    assert empty.satisfied is False and empty.evidence_count == 0

    contract = build_completion_contract_from_conditions(
        {"min_tool_executions": 2}
    )
    assert contract is not None
    one = evaluate_completion(
        contract,
        [EffectRecord(tool_name="run_whitelisted_command", status="failed")],
    )
    assert one.satisfied is False and one.evidence_count == 1
    two = evaluate_completion(
        contract,
        [
            EffectRecord(tool_name="run_whitelisted_command", status="failed"),
            EffectRecord(tool_name="read_code_file", status="succeeded"),
        ],
    )
    assert two.satisfied is True


# ===========================================================================
# C. 契约确定性重建（ADR-007 §1-3：随 Turn 恢复、不按新设置重算）
# ===========================================================================


def test_contract_id_stable_across_rebuild_and_json_roundtrip():
    conditions = {"require_successful_file_write": True, "min_tool_executions": 1}
    first = build_completion_contract_from_conditions(conditions)
    reordered = build_completion_contract_from_conditions(
        {"min_tool_executions": 1, "require_successful_file_write": True}
    )
    assert first is not None and reordered is not None
    assert first.contract_id == reordered.contract_id
    # resume 路径从 DB JSON 反序列化字典重建 → 同一契约。
    roundtrip = build_completion_contract_from_conditions(json.loads(json.dumps(conditions)))
    assert roundtrip is not None
    assert roundtrip.contract_id == first.contract_id


def test_no_gates_yields_no_contract():
    assert build_completion_contract_from_conditions(None) is None
    assert build_completion_contract_from_conditions({}) is None
    assert build_completion_contract_from_conditions({"final_git_diff": "any"}) is None


# ===========================================================================
# D. 预检门禁单元（CT1-04，F-002）
# ===========================================================================


def test_preflight_blocks_when_all_write_flags_disabled():
    decision = assess_workspace_file_write(
        patch_workflow_enabled=False,
        patchset_enabled=False,
        permission_mode="confirm",
        model_supports_tools=True,
    )
    assert decision.blocked is True
    assert decision.error_code == "tool_capability_unavailable"
    assert "PA_AGENT_PATCH_WORKFLOW_ENABLED" in decision.public_message
    assert "未对磁盘进行任何更改" in decision.public_message


def test_preflight_blocks_readonly_mode_even_with_flags_on():
    decision = assess_workspace_file_write(
        patch_workflow_enabled=True,
        patchset_enabled=True,
        permission_mode="readonly",
        model_supports_tools=True,
    )
    assert decision.blocked is True
    assert decision.error_code == "tool_capability_unavailable"
    assert "只读权限模式" in decision.public_message


def test_preflight_passes_when_write_tool_exposed():
    decision = assess_workspace_file_write(
        patch_workflow_enabled=True,
        patchset_enabled=False,
        permission_mode="confirm",
        model_supports_tools=True,
    )
    assert decision.blocked is False


def test_preflight_reports_unsupported_model_first():
    decision = assess_workspace_file_write(
        patch_workflow_enabled=True,
        patchset_enabled=True,
        permission_mode="confirm",
        model_supports_tools=False,
    )
    assert decision.blocked is True
    assert decision.error_code == "tool_model_unsupported"


# ===========================================================================
# E. F-001：hello.py 真实落盘链（审批 → 原子写入 → 回读 SHA → 契约满足）
# ===========================================================================


_PROJECT_ROOT: str | None = None


def _dispatcher_factory(db, run_id: str):
    def build(
        *,
        approval_id: str | None = None,
        approval_token: str | None = None,
    ) -> ValidatedToolDispatcher:
        async def resolve_root(project_id: int) -> str:
            return str(_PROJECT_ROOT)

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

    return build


async def _create_run_with_events(db, *, tool_call_id: str) -> str:
    run_id = str(uuid4())
    repo = AgentRunRepository(db)
    await repo.create_run(run_id=run_id, limits=AgentRunLimits())
    await repo.record_event(
        AgentEvent(run_id=run_id, sequence=1, type=AgentEventType.RUN_STARTED)
    )
    await repo.record_event(
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


async def _request_approval_and_approve(db, run_id: str, call: ToolCall):
    pending = await _dispatcher_factory(db, run_id)().execute(
        call, cancellation=CancellationToken()
    )
    assert pending.success is False
    assert pending.error_code == "approval_required"
    approvals = await ToolApprovalRepository(db).list_for_run(run_id)
    assert len(approvals) == 1
    return await ToolApprovalRepository(db).approve(approvals[0].id)


@pytest.fixture(autouse=True)
def _ct1_project_root(tmp_path, monkeypatch):
    global _PROJECT_ROOT
    _PROJECT_ROOT = str(tmp_path)
    yield
    _PROJECT_ROOT = None


async def test_hello_py_end_to_end_disk_evidence_chain(db, tmp_path):
    """F-001 主链：审批写入 hello.py → 磁盘事实 → 完成契约满足。"""
    project_id = await _make_project(db, tmp_path)
    call = ToolCall(
        id="call-hello-1",
        name="apply_patch_to_workspace",
        arguments={
            "project_id": project_id,
            "rel_path": "hello.py",
            "new_content": HELLO_PY,
            "create": True,
        },
    )
    run_id = await _create_run_with_events(db, tool_call_id=call.id)
    try:
        approved = await _request_approval_and_approve(db, run_id, call)
        result = await _dispatcher_factory(db, run_id)(
            approval_id=approved.approval_id,
            approval_token=approved.token,
        ).execute(call, cancellation=CancellationToken())
        assert result.success is True, result.error

        # 磁盘事实：内容与回读 SHA 一致。
        target = tmp_path / "hello.py"
        assert target.read_text(encoding="utf-8") == HELLO_PY
        assert result.output["verified"] is True
        assert result.output["new_sha256"] == hashlib.sha256(
            HELLO_PY.encode("utf-8")
        ).hexdigest()

        # durable executions 事实 → v2 契约求值满足（此时 completed 才合法）。
        records = await ToolExecutionRepository(db, run_id=run_id).list_for_run()
        executions = [
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
        verifier = CompletionContractOutputVerifier(
            _facts_loader(_facts(*executions)), _write_contract()
        )
        verification = await verifier.verify("done", attempt=1)
        assert verification.passed is True, verification.message
    finally:
        await _cleanup(db, run_id, project_id)


# ===========================================================================
# F. run 创建链路由级（F-002 / 持久化门槛 / F-008 注入豁免）
# ===========================================================================


async def test_create_run_blocked_without_any_write_tool(client, monkeypatch, tmp_path):
    """F-002：明确文件写入意图 + 无任何写工具入口 → 409 结构化预检失败。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", False)
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_patchset_enabled", False)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client,
        env,
        message="在根目录创建 hello.py 文件，写入打印 hello world 的代码",
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "tool_capability_unavailable"
    assert "没有可用的文件写入工具" in body["detail"]
    assert "PA_AGENT_PATCH_WORKFLOW_ENABLED" in body["detail"]
    assert "未对磁盘进行任何更改" in body["detail"]


async def test_create_run_blocked_in_readonly_mode_despite_flags(
    client, monkeypatch, tmp_path
):
    """F-002 变体：flag 全开但权限只读 → 预检同样阻断（模型不可见=零写入）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "coding_patchset_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client,
        env,
        permission_mode="readonly",
        message="在根目录创建 hello.py 文件",
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "tool_capability_unavailable"
    assert "只读权限模式" in body["detail"]


async def test_file_mutation_gate_persisted_when_write_tool_available(
    client, monkeypatch, tmp_path
):
    """写工具可用时正常创建并持久化 v2 收口条件（原 H1-B 用例新契约版）。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_patch_workflow_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client,
        env,
        message="在根目录创建 hello.txt 文件，内容为 hello world",
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as db:
        record = await db.get(AgentRunRecord, run_id)
        assert record is not None
        conditions = record.completion_conditions_json or {}
        assert conditions.get("min_tool_executions") == 1
        assert conditions.get("require_successful_file_write") is True
        # v2 收口：由持久化条件可重建同一契约（resume 一致性）。
        contract = build_completion_contract_from_conditions(conditions)
        assert contract is not None
        assert contract.required_effects == frozenset({EffectClass.FILESYSTEM_WRITE})


async def test_preview_only_request_skips_write_gate_and_preflight(
    client, monkeypatch, tmp_path
):
    """F-008：显式仅预览 → 不阻断创建、也不注入 require_successful_file_write。"""
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client,
        env,
        message="只预览 hello.txt 的修改，不要写入",
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    from personal_assistant.core.db import async_session_factory

    async with async_session_factory() as db:
        record = await db.get(AgentRunRecord, run_id)
        conditions = record.completion_conditions_json or {}
        assert conditions.get("min_tool_executions") == 1
        assert "require_successful_file_write" not in conditions
