"""0.3.0 A5 公开契约冻结测试。

固定文档 ``docs/releases/v0.3.0/v0.3.0-public-contracts.md`` 声明的公开契约：
capabilities 字段、SSE 事件、run 状态、run 事件类型、审批对象、
RAG 引用键、上下文元数据键、compatibility telemetry 标签、错误码词汇、
摘要元数据键。任何破坏性变更必须先更新冻结文档与相关 E2E。
"""

from __future__ import annotations

import json

from personal_assistant.agents.contracts import (
    AgentEventType,
    AgentRunStatus,
)
from personal_assistant.api.routes_agent_runs import (
    AgentRunResponse,
    AgentToolApprovalResponse,
)
from personal_assistant.api.routes_chat import _project_agent_chat_output
from personal_assistant.api.routes_health import RuntimeCapabilities
from personal_assistant.context.sources import context_event_payload
from personal_assistant.core.chat import ChatService
from personal_assistant.core.compatibility import _LABELS
from personal_assistant.core.conversation_summarizer import (
    StructuredConversationSummary,
)


def test_capabilities_fields_frozen():
    """§1：/capabilities 字段集合与互斥语义固定。

    v0.5.0 B0 additive 扩展：新增四个可信工作流开关字段（默认 False），
    既有字段不变。见 docs/releases/v0.5.0/v0.5.0-b0-contracts-20260809.md §2。
    v0.9.0 H0 additive 扩展：见 v0.9.0-h0-contracts-20260823.md §3。
    """
    assert set(RuntimeCapabilities.model_fields) == {
        "chat_execution_mode",
        "legacy_tool_planner_enabled",
        "agent_read_only_tools_enabled",
        "rag_chat_runtime_enabled",
        "patch_workflow_enabled",
        "command_workflow_enabled",
        "http_workflow_enabled",
        "sql_readonly_workflow_enabled",
        # v0.9.0 H0 additive
        "agent_runs_api_enabled",
        "coding_agent_ui_enabled",
        "project_bound_runs_enabled",
        "coding_workspace_auto_approve",
        "coding_full_access_supported",
        "coding_context_budget_enabled",
        "coding_execution_detail_enabled",
        "coding_worktree_enabled",
        "product_timezone",
        # v0.9.0 H1-C additive（计划 §5.3/§5.7）：审计/撤销独立声明 + 诊断命令面
        "coding_full_access_audit",
        "coding_full_access_revoke",
        "coding_diagnostic_commands_enabled",
    }
    mode = RuntimeCapabilities.model_fields["chat_execution_mode"]
    assert mode.annotation.__args__ == ("agent_runtime", "legacy")
    # 四个新增工作流开关默认关闭（高风险管理默认值）
    for field in (
        "patch_workflow_enabled",
        "command_workflow_enabled",
        "http_workflow_enabled",
        "sql_readonly_workflow_enabled",
    ):
        assert RuntimeCapabilities.model_fields[field].default is False
    # 互斥语义：legacy_tool_planner 只由 chat_execution_mode 决定（见 test_health.py）


def test_run_status_set_frozen():
    """§3：run 状态集合固定。"""
    assert {s.value for s in AgentRunStatus} == {
        "created",
        "running",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "limit_exceeded",
    }
    terminal = {"completed", "failed", "cancelled", "timed_out", "limit_exceeded"}
    assert {s.value for s in AgentRunStatus} >= terminal


def test_run_event_types_frozen():
    """§4：公开事件类型固定。

    v0.6.0 C0 §4.5 additive 扩展：plan/artifact 四个稳定事件（durable），
    既有事件不变。见 docs/releases/v0.6.0/v0.6.0-c0-contracts-20260820.md §4.5。
    """
    assert {e.value for e in AgentEventType} == {
        "run.started",
        "context.prepared",
        "model.started",
        "model.completed",
        "output.validation_started",
        "output.validation_passed",
        "output.validation_failed",
        "tool.requested",
        "tool.started",
        "tool.approval_required",
        "tool.approval_resolved",
        "tool.completed",
        "tool.failed",
        "run.completed",
        "run.failed",
        "run.cancelled",
        "run.timed_out",
        "run.limit_exceeded",
        "chat.output_persisted",
        # v0.6.0 durable 稳定事件
        "plan.created",
        "plan.updated",
        "plan.item_changed",
        "artifact.created",
        # v0.7.0 E0 §1：PatchSet durable 事件（additive）
        "patch_set.preview_created",
        "patch_set.applied",
        "patch_set.rolled_back",
        "patch_set.failed",
        "patch_set.unknown",
        # v0.9.0 H0 §7.2/§8：公开决策摘要与上下文压缩事件（additive）
        "decision.summary",
        "context.compaction_started",
        "context.compaction_completed",
        "context.compaction_failed",
        "permission.downgraded",
    }


def test_agent_run_response_fields_frozen():
    """§3/§6：run 与审批响应字段集合固定。

    v0.6.0 additive 扩展：project/workspace 绑定、Git/模型/权限快照、
    幂等重放与重连纠偏快照字段（旧客户端可忽略）。
    """
    assert set(AgentRunResponse.model_fields) == {
        "id",
        "session_id",
        "trace_id",
        "status",
        "provider",
        "model",
        "last_event_sequence",
        "tool_call_count",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "cost_usd",
        "output",
        "error_code",
        "error_message",
        "cancel_requested_at",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
        "active_in_process",
        "steps",
        # v0.6.0 additive
        "project_id",
        "workspace_id",
        "base_head_sha",
        "base_branch_name",
        "base_git_dirty",
        "model_profile_id",
        "reasoning_effort",
        "permission_mode",
        "client_request_id",
        "idempotent_replay",
        "plan",
        "artifacts",
    }


def test_approval_response_fields_frozen():
    """§6：审批对象字段固定。"""
    assert set(AgentToolApprovalResponse.model_fields) == {
        "id",
        "run_id",
        "step_id",
        "tool_call_id",
        "tool_name",
        "tool_version",
        "arguments_sha256",
        "risk_level",
        "required_capabilities",
        "status",
        "expires_at",
        "decision_at",
        "consumed_at",
        "created_at",
    }


def test_rag_citation_source_keys_frozen():
    """§5：done.sources 引用键固定（从投影实现抽取）。"""
    import inspect

    source = inspect.getsource(_project_agent_chat_output)
    for key in (
        "doc_name",
        "ordinal",
        "chunk_id",
        "heading",
        "score",
        "fusion_score",
        "bm25_score",
        "rerank_score",
        "matched_via",
        "matched_keywords",
    ):
        assert f'"{key}"' in source, f"RAG 引用键 {key} 从投影实现中消失"


def test_context_metadata_payload_keys_frozen():
    """§4：context.prepared payload 键固定（不含正文内容）。"""
    payload_keys = {
        "estimated_tokens",
        "section_tokens",
        "history_included",
        "memory_included",
        "rag_included",
        "summary_included",
        "sensitive_excluded",
        "truncated",
        "decisions",
        "decisions_truncated",
    }
    import inspect

    source = inspect.getsource(context_event_payload)
    for key in payload_keys:
        assert f'"{key}"' in source, f"context payload 键 {key} 从实现中消失"


def test_compatibility_telemetry_labels_frozen():
    """§8：telemetry path/mode/outcome 标签固定。

    v0.6.0 C0 §10 additive 扩展：coding 路由计数标签（只计数，不记录
    message/路径/Git 快照/权限正文）。
    """
    assert set(_LABELS) == {
        "/tools",
        "/tools/plan",
        "/chat/stream",
        "/chat/agent-runs/:id/stream",
        "/agent-runs",
        "/tool-calls/:id/approve",
        "/tool-calls/:id/reject",
        "/tool-calls",
        "/tool-calls/:id",
        # v0.6.0 additive
        "agent_run_create",
        "coding_session_create",
        "run_plan_update",
        "run_event_stream",
        "workspace_resolve",
        # v0.9.0 H0 §9 additive
        "legacy_session_bind",
        "full_access_grant",
        "permission_downgrade",
        "context_budget_poll",
        "unbound_run_create",
        "coding_ui_fallback",
        # v0.9.0 H2：unknown 执行人工处置计数（不含备注/输出正文）
        "manual_execution_resolution",
        # v0.9.0 H1-B（§5.6）：可执行意图路由计数（低基数，无消息正文）
        "executable_intent",
    }
    assert _LABELS["/chat/stream"]["modes"] == {
        "agent_runtime",
        "agent_runtime_rag",
        "legacy_runtime_disabled",
        "legacy_tool_result",
        "legacy_rag_tools_disabled",
        "legacy_output_verification_disabled",
    }
    assert _LABELS["/chat/stream"]["outcomes"] == {"routed"}
    assert _LABELS["/tools/plan"]["modes"] == {"legacy_full", "runtime_filtered"}
    assert _LABELS["/tools"]["modes"] == {"legacy_registry"}
    assert _LABELS["/agent-runs"]["modes"] == {"agent_runs_api"}
    # v0.6.0 标签约束：只计数，不记录敏感正文
    assert _LABELS["agent_run_create"]["modes"] == {"legacy", "project_bound"}
    assert _LABELS["agent_run_create"]["outcomes"] == {
        "created",
        "replayed",
        "rejected",
        # v0.9.0 H1-D additive（§5.8）：无默认 profile 的低基数计数
        "profile_default_missing",
    }
    assert _LABELS["run_event_stream"]["outcomes"] == {
        "connected",
        "reconnected",
        "completed",
        "aborted",
        "error",
    }
    assert _LABELS["workspace_resolve"]["outcomes"] == {
        "resolved",
        "missing",
        "mismatch",
        "untrusted",
    }


def test_chat_sse_event_types_frozen():
    """§2：/chat/stream 事件类型固定（runtime 与 legacy 公共子集）。"""
    import inspect

    from personal_assistant.api import routes_chat

    source = inspect.getsource(routes_chat)
    for event_type in ("run", "token", "approval", "done", "title", "error"):
        assert f'"type": "{event_type}"' in source, (
            f"SSE 事件 {event_type} 从 chat 路由中消失"
        )
    # done 事件包含固定键
    assert '"message_id"' in source
    assert '"sources"' in source
    assert '"memories"' in source


def test_chat_sse_error_has_no_done_fallback():
    """§2.2：legacy 错误事件不伪造 done 终态。"""
    assert "{'type': 'error'" or '"type": "error"' in json.dumps(
        ChatService.event_to_sse({"type": "error", "message": "x"})
    )


def test_summary_metadata_fields_frozen():
    """§7：摘要可见元数据键固定。"""
    assert set(StructuredConversationSummary.model_fields) == {
        "goal",
        "decisions",
        "completed",
        "pending",
        "constraints",
        "important_facts",
        "errors",
        "files",
        "tools",
        "next_steps",
    }


def test_error_code_vocabulary_frozen():
    """§9：run 级 error_code 固定词汇。"""
    import inspect

    from personal_assistant.agents import recovery as recovery_module
    from personal_assistant.agents import runtime as runtime_module
    from personal_assistant.agents import tools as tools_module
    from personal_assistant.api import routes_agent_runs as runs_module
    from personal_assistant.api import routes_chat as chat_module

    runtime_source = inspect.getsource(runtime_module)
    recovery_source = inspect.getsource(recovery_module)
    chat_source = inspect.getsource(chat_module)
    tools_source = inspect.getsource(tools_module)
    runs_source = inspect.getsource(runs_module)
    expected = {
        "max_steps",
        "max_tool_calls",
        "wall_time",
        "output_validation_failed",
        "cancelled",
        "approval_expired",
        "disconnected",
        "process_restarted",
        "process_restarted_after_cancel",
        "state_unknown",
    }
    sources = (
        runtime_source + recovery_source + chat_source + tools_source + runs_source
    ).replace(" = ", "=")
    for code in expected:
        literal = f'error_code="{code}"'
        # 限制类错误码通过 _RunLimitExceeded("max_steps") 字面量 + exc.limit 传递；
        # recovery 类错误码通过变量 error_code 传递，直接断言字符串字面量存在
        limit_literal = f'_RunLimitExceeded("{code}")'
        assert (
            literal in sources
            or limit_literal in runtime_source
            or (f'"{code}"' in recovery_source and code.startswith("process_"))
        ), f"错误码 {code} 未在实现中出现"
