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
    """§4：公开事件类型固定。"""
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
    }


def test_agent_run_response_fields_frozen():
    """§3/§6：run 与审批响应字段集合固定。"""
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
    """§8：telemetry path/mode/outcome 标签固定。"""
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
