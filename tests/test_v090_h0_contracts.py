"""v0.9.0 H0 契约冻结测试。

冻结依据：``docs/releases/v0.9.0/v0.9.0-h0-contracts-20260823.md``。
覆盖：默认值矩阵（不隐式扩大权限）、flag 依赖、/capabilities 扩展、
权限模式集合与快照、错误码词汇、稳定事件、产品时区与时间序列化、
遥测标签。任何破坏性变更必须先更新冻结文档与本文件。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from personal_assistant.config import Settings
from personal_assistant.core.coding_errors import (
    ERROR_CODES,
    PERMISSION_MODES,
    STABLE_EVENTS,
)
from personal_assistant.core.permission_modes import (
    PERMISSION_MODE_DEFAULT,
    build_permission_snapshot,
    permission_mode_capabilities,
)
from personal_assistant.core.timeutil import PRODUCT_TIMEZONE, format_rfc3339_utc

# ===========================================================================
# §1 默认值矩阵：新安装不隐式扩大权限
# ===========================================================================


def test_new_install_defaults_do_not_escalate():
    """H0 §1.1：全部 v0.9.0 新 flag 默认关闭（默认权限不因默认值扩大）。"""
    for name in (
        "coding_agent_ui_enabled",
        "coding_workspace_auto_approve_enabled",
        "coding_full_access_enabled",
        "coding_context_budget_enabled",
        "coding_execution_detail_enabled",
        "coding_worktree_enabled",
    ):
        field = Settings.model_fields[name]
        assert field.default is False, f"{name} 默认值必须是 False"


def test_full_access_ttl_bounds():
    """full_access 有效期有界（60..1440 分钟），超限拒绝。"""
    field = Settings.model_fields["coding_full_access_ttl_minutes"]
    assert field.default == 240
    with pytest.raises(ValidationError):
        Settings(coding_full_access_ttl_minutes=1)  # type: ignore[call-arg]


def test_flag_dependencies_fail_fast():
    """H0 §2.3：依赖不满足时启动即失败（不静默运行）。"""
    # 禁用 .env 干扰，只用显式字段值验证依赖链（字段名即 init 参数）
    with pytest.raises(ValidationError):
        Settings(_env_file=None, coding_full_access_enabled=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            project_bound_runs_enabled=True,
            coding_workspace_auto_approve_enabled=True,
        )
    # 依赖齐备时合法（auto_approve 额外要求命令 profile）
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        project_bound_runs_enabled=True,
        coding_command_profiles_enabled=True,
        coding_workspace_auto_approve_enabled=True,
    )
    assert settings.coding_workspace_auto_approve_enabled is True


# ===========================================================================
# §3 /capabilities 扩展（additive，默认 False，workspace≠full_access）
# ===========================================================================


def test_capabilities_v090_fields_frozen():
    from personal_assistant.api.routes_health import RuntimeCapabilities

    v090_fields = {
        "coding_agent_ui_enabled",
        "project_bound_runs_enabled",
        "coding_workspace_auto_approve",
        "coding_full_access_supported",
        "coding_context_budget_enabled",
        "coding_execution_detail_enabled",
        "coding_worktree_enabled",
        "product_timezone",
    }
    fields = set(RuntimeCapabilities.model_fields)
    assert v090_fields <= fields
    # 能力位默认关闭；产品时区常量声明
    for name in v090_fields - {"product_timezone"}:
        assert RuntimeCapabilities.model_fields[name].default is False
    assert RuntimeCapabilities.model_fields["product_timezone"].default == (
        "Asia/Shanghai"
    )
    # workspace 与 full_access 是两个独立字段，不是别名
    assert "coding_workspace_auto_approve" in fields
    assert "coding_full_access_supported" in fields


# ===========================================================================
# §6 权限模式集合与快照（full_access 独立能力，非 workspace 别名）
# ===========================================================================


def test_permission_modes_v090_set():
    """H0 §6.1：四模式集合；readonly/confirm/workspace 保持，新增 full_access。"""
    assert PERMISSION_MODES == frozenset(
        {"readonly", "confirm", "workspace", "full_access"}
    )
    # API 层默认仍是最小权限（计划 §3.1 的产品默认 confirm 由前端请求声明，
    # 后端不因缺省扩大权限）
    assert PERMISSION_MODE_DEFAULT == "readonly"


def test_full_access_capabilities_equal_workspace():
    """full_access 与 workspace 能力集相同——差异在审批策略与硬阻断，
    不在能力集本身（避免能力集差异造成提权假象，H0 §6.2）。"""
    assert permission_mode_capabilities(
        "full_access"
    ) == permission_mode_capabilities("workspace")


def test_permission_snapshot_granted_full_access_additive():
    """快照默认不含 granted_full_access（旧语义不变）；显式授予才出现。"""
    base = build_permission_snapshot(
        permission_mode="confirm",
        max_patchset_files=8,
        max_patchset_total_bytes=256 * 1024,
    )
    assert "granted_full_access" not in base

    granted = build_permission_snapshot(
        permission_mode="full_access",
        max_patchset_files=8,
        max_patchset_total_bytes=256 * 1024,
        granted_full_access=True,
    )
    assert granted["permission_mode"] == "full_access"
    assert granted["granted_full_access"] is True

    # full_access 无有效授予 → 快照如实记录 False（fail-closed 事实）
    ungranted = build_permission_snapshot(
        permission_mode="full_access",
        max_patchset_files=8,
        max_patchset_total_bytes=256 * 1024,
        granted_full_access=False,
    )
    assert ungranted["granted_full_access"] is False


def test_v090_error_codes_frozen():
    """H0 §6.4：错误码词汇与状态码（additive，不改动既有映射）。"""
    assert ERROR_CODES["full_access_unsupported"] == 409
    assert ERROR_CODES["full_access_grant_expired"] == 409
    assert ERROR_CODES["full_access_revoked"] == 409
    assert ERROR_CODES["budget_exceeded"] == 409
    assert ERROR_CODES["session_bind_conflict"] == 409
    # 既有冻结不受影响
    assert ERROR_CODES["permission_mode_invalid"] == 422
    assert ERROR_CODES["coding_mode_disabled"] == 409


# ===========================================================================
# §7/§8 稳定事件（决策摘要/压缩/降级，全部公开语义）
# ===========================================================================


def test_v090_stable_events_additive():
    v090_events = {
        "decision.summary",
        "context.compaction_started",
        "context.compaction_completed",
        "context.compaction_failed",
        "permission.downgraded",
    }
    assert v090_events <= STABLE_EVENTS
    # AgentEventType 同步扩展
    from personal_assistant.agents.contracts import AgentEventType

    assert {e.value for e in AgentEventType} >= v090_events


def test_decision_summary_payload_contract():
    """decision.summary 只含结构化公开摘要键（无隐藏 chain-of-thought）。"""
    from personal_assistant.core.execution_contracts import (
        DECISION_SUMMARY_PAYLOAD_KEYS,
        DecisionSummary,
    )

    assert DECISION_SUMMARY_PAYLOAD_KEYS == {
        "goal",
        "method",
        "key_judgments",
        "rationale",
        "next_steps",
        "risks",
        "verification",
    }
    summary = DecisionSummary(
        goal="修复测试失败",
        method="定位断言并修改",
        key_judgments=["断言期望值过时"],
        rationale="测试输出显示期望 3 实际 4",
        next_steps=["运行回归"],
        risks=["影响相邻用例"],
        verification="pytest 通过",
    )
    payload = summary.to_payload()
    assert set(payload) == DECISION_SUMMARY_PAYLOAD_KEYS
    # 有界：单字段超长拒绝
    with pytest.raises(ValidationError):
        DecisionSummary(goal="x" * 5000)


def test_context_budget_dto_contract():
    """H0 §7.1：budget DTO 字段集合与域约束（不伪造百分比）。"""
    from personal_assistant.core.context_budget import (
        COMPACTION_STATES,
        ContextBudget,
        UsageSource,
    )

    assert COMPACTION_STATES == frozenset(
        {"idle", "compacting", "compacted", "failed"}
    )
    budget = ContextBudget(
        used_tokens=100,
        max_context_tokens=1000,
        reserved_output_tokens=256,
        source=UsageSource.PROVIDER_USAGE,
        compaction_state="idle",
    )
    assert budget.usage_percent == 10
    # 超限时封顶 100 并要求错误码（禁止 >100 裸数值）
    over = ContextBudget(
        used_tokens=2000,
        max_context_tokens=1000,
        reserved_output_tokens=256,
        source=UsageSource.RUNTIME_COUNT,
        compaction_state="failed",
        error_code="budget_exceeded",
        error_reason="budget exceeded after compaction",
    )
    assert over.usage_percent == 100
    # 不可用：不显示百分比
    unavailable = ContextBudget(
        used_tokens=0,
        max_context_tokens=0,
        reserved_output_tokens=0,
        source=UsageSource.UNAVAILABLE,
        compaction_state="idle",
        error_reason="model profile does not report usage",
    )
    assert unavailable.usage_percent is None


# ===========================================================================
# §5 产品时区与时间序列化
# ===========================================================================


def test_product_timezone_frozen():
    assert PRODUCT_TIMEZONE == "Asia/Shanghai"
    import zoneinfo

    assert zoneinfo.ZoneInfo(PRODUCT_TIMEZONE) is not None


def test_format_rfc3339_utc_semantics():
    """naive 按 UTC 解释；aware 先转 UTC；毫秒精度；None 透传。"""
    naive = datetime(2026, 8, 23, 16, 0, 0, 123000)
    assert format_rfc3339_utc(naive) == "2026-08-23T16:00:00.123Z"

    aware = datetime(2026, 8, 24, 0, 0, 0, tzinfo=timezone.utc)
    assert format_rfc3339_utc(aware) == "2026-08-24T00:00:00.000Z"

    import zoneinfo

    shanghai = datetime(
        2026, 8, 24, 8, 0, 0, tzinfo=zoneinfo.ZoneInfo("Asia/Shanghai")
    )
    # 上海 08:00 == UTC 00:00（UTC+8，无 DST）：序列化统一为 UTC 事实
    assert format_rfc3339_utc(shanghai) == "2026-08-24T00:00:00.000Z"

    assert format_rfc3339_utc(None) is None


# ===========================================================================
# §9 遥测标签（低基数，不记录正文）
# ===========================================================================


def test_v090_telemetry_labels_frozen():
    from personal_assistant.core.compatibility import _LABELS

    v090_paths = {
        "legacy_session_bind",
        "full_access_grant",
        "permission_downgrade",
        "context_budget_poll",
        "unbound_run_create",
        "coding_ui_fallback",
    }
    assert v090_paths <= set(_LABELS)
    assert _LABELS["full_access_grant"]["outcomes"] == {
        "granted",
        "expired",
        "revoked",
        "denied",
        "downgraded",
    }
    assert _LABELS["legacy_session_bind"]["modes"] == {"explicit"}
