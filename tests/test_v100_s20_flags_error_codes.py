"""专项计划 §20 Feature Flags 与 §7.7 稳定错误码合规测试。

覆盖：
- §7.7 十三个公开错误码的冻结注册表完整性；
- §20 九个 v2 flag 的默认值与阶段语义（enforce/灰度预留）；
- 引擎策略拒绝 → ``tool_hidden_by_policy``（替换旧 permission_denied）；
- 预检健康失败 → ``tool_health_failed``；
- Deferred Tool Search 会话失效 → ``tool_plan_invalidated``（§7.2：
  MCP 断开/目录变化不静默换工具）；
- MCP server status=error → 注册面剔除 + v2 投影 health_failed；
- 预检 flag 关闭 → 回落 v0.9 无预检形态（§20/§24 回退语义）。
"""

from __future__ import annotations

import pytest
from test_v100_ct4_tool_engine import _engine, _v09_spec

from personal_assistant.agent_v2.application.deferred_search import (
    DeferredToolIndex,
    ToolSearchError,
    TurnSearchSession,
)
from personal_assistant.agent_v2.application.preflight import (
    PreflightErrorCode,
    assess_required_effects,
)
from personal_assistant.agent_v2.domain.effects import EffectClass
from personal_assistant.agent_v2.domain.error_codes import (
    FROZEN_ERROR_CODES,
    ToolErrorCode,
)
from personal_assistant.agent_v2.domain.tool_catalog import (
    ToolExposure,
    ToolSpecV2,
)
from personal_assistant.agent_v2.domain.tool_search import ToolSearchErrorCode
from personal_assistant.config import Settings

_EXPECTED_SECTION_7_7 = {
    "tool_capability_unavailable",
    "tool_model_unsupported",
    "tool_hidden_by_policy",
    "tool_health_failed",
    "tool_name_collision",
    "tool_plan_invalidated",
    "required_effect_missing",
    "completion_not_met",
    "side_effect_unverified",
    "executor_unavailable",
    "sandbox_policy_unavailable",
    "execution_state_unknown",
    "tool_search_no_match",
}


def test_frozen_error_codes_match_plan_section_7_7() -> None:
    assert FROZEN_ERROR_CODES == _EXPECTED_SECTION_7_7
    assert ToolErrorCode.TOOL_HIDDEN_BY_POLICY.value == "tool_hidden_by_policy"


def test_feature_flag_defaults_match_plan_section_20() -> None:
    defaults = {
        name: Settings.model_fields[name].default
        for name in (
            "agent_v2_tool_engine_enabled",
            "agent_v2_tool_preflight_enabled",
            "agent_v2_completion_evidence_enabled",
            "agent_v2_tool_snapshot_enabled",
            "agent_v2_exec_host_enabled",
            "agent_v2_deferred_tool_search_enabled",
            "agent_v2_safe_parallel_tools_enabled",
            "agent_v2_native_apply_patch_enabled",
            "codex_app_server_spike_enabled",
        )
    }
    # 已处于 enforce 阶段的门禁默认开；其余能力面默认关（失败关闭/灰度预留）。
    assert defaults["agent_v2_tool_preflight_enabled"] is True
    assert defaults["agent_v2_completion_evidence_enabled"] is True
    for name, value in defaults.items():
        if name in (
            "agent_v2_tool_preflight_enabled",
            "agent_v2_completion_evidence_enabled",
        ):
            continue
        assert value is False, name


async def test_engine_policy_deny_returns_tool_hidden_by_policy() -> None:
    """§7.7：策略拒绝的稳定公开码（替换 v2 引擎旧 permission_denied）。"""
    from personal_assistant.agents import CancellationToken

    engine = _engine(_v09_spec(), granted=frozenset())  # 零授权 → DENY
    outcome = await engine.execute(
        _engine_call(), cancellation=CancellationToken()
    )
    assert outcome.success is False
    assert outcome.error_code == ToolErrorCode.TOOL_HIDDEN_BY_POLICY


def _engine_call():
    from test_v100_ct4_tool_engine import _Call

    return _Call(id="call-policy-deny", name="echo", arguments={"value": "x"})


def test_preflight_health_failed_when_all_providers_unhealthy() -> None:
    decision = assess_required_effects(
        [EffectClass.FILESYSTEM_WRITE],
        providers={"filesystem.write": ["mcp"]},
        unhealthy_executors=frozenset({"mcp"}),
    )
    assert decision.blocked
    assert decision.error_code == PreflightErrorCode.TOOL_HEALTH_FAILED


def test_preflight_capability_missing_beats_health() -> None:
    decision = assess_required_effects(
        [EffectClass.FILESYSTEM_WRITE],
        providers={},
        unhealthy_executors=frozenset({"mcp"}),
    )
    assert decision.blocked
    assert decision.error_code == PreflightErrorCode.TOOL_CAPABILITY_UNAVAILABLE


def _deferred_spec(name: str = "deep_tool") -> ToolSpecV2:
    return ToolSpecV2(
        namespace="builtin",
        canonical_name=name,
        version="1.0.0",
        description="deferred demo tool for invalidation tests",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        exposure=ToolExposure.DEFERRED,
    )


def test_search_session_invalidation_returns_tool_plan_invalidated() -> None:
    """§7.2：显式失效后搜索/激活一律结构化拒绝，不静默换工具。"""
    session = TurnSearchSession(
        DeferredToolIndex.build([_deferred_spec()]),
        visible_hash_before="vh-" + "0" * 61,
    )
    session.invalidate(reason="mcp disconnected")
    with pytest.raises(ToolSearchError) as search_exc:
        session.search("deep")
    assert search_exc.value.code == ToolSearchErrorCode.TOOL_PLAN_INVALIDATED
    with pytest.raises(ToolSearchError) as activate_exc:
        session.activate(["deep_tool"], plan=None)
    assert activate_exc.value.code == ToolSearchErrorCode.TOOL_PLAN_INVALIDATED


def test_search_session_catalog_hash_change_invalidates() -> None:
    session = TurnSearchSession(
        DeferredToolIndex.build([_deferred_spec()]),
        visible_hash_before="vh-" + "0" * 61,
        catalog_hash="a" * 64,
    )
    session.guard_catalog("a" * 64)  # 未变化 → 不触发
    session.guard_catalog("b" * 64)  # 目录重建 → 失效
    with pytest.raises(ToolSearchError) as excinfo:
        session.search("deep")
    assert excinfo.value.code == ToolSearchErrorCode.TOOL_PLAN_INVALIDATED


async def test_mcp_error_status_excluded_and_projected_health_failed(db) -> None:
    """§7.7 tool_health_failed：status=error 的 server 失败关闭。"""
    from uuid import uuid4

    from test_v100_ct7_mcp_policy import _FakeClient, _stdio_config

    from personal_assistant.agent_v2.application.mcp_catalog import (
        build_mcp_catalog_specs,
    )
    from personal_assistant.mcp import (
        McpManager,
        McpRepository,
        build_mcp_tool_registry,
    )

    config = _stdio_config(name=f"ct20-{uuid4().hex[:8]}")
    repository = McpRepository(db)
    record = await repository.create(config)
    try:
        await McpManager(db, client=_FakeClient()).discover(record)
        assert build_mcp_tool_registry(db, [record], client=_FakeClient()).list()

        record.status = "error"  # 健康/发现失败 → 失败关闭
        assert not build_mcp_tool_registry(
            db, [record], client=_FakeClient()
        ).list()
        specs, health_failed = build_mcp_catalog_specs([record])
        assert specs, "投影仍解释该工具（隐藏原因可见）"
        assert health_failed == frozenset({f"mcp.{config.id.lower()}"})
    finally:
        await repository.delete(record)


async def test_preflight_flag_off_falls_back_to_legacy_creation(
    client, monkeypatch, tmp_path
) -> None:
    """§20/§24：预检 flag 关闭 → 回落 v0.9 无预检形态（非 409 结构化阻断）。"""
    from test_v100_ct1_fake_success_gate import (
        _create_coding_env,
        _post_coding_run,
    )

    from personal_assistant.api import routes_agent_runs

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    monkeypatch.setattr(
        routes_agent_runs.cfg, "agent_v2_tool_preflight_enabled", False
    )
    env = await _create_coding_env(client, tmp_path)
    resp = await _post_coding_run(
        client,
        env,
        message="在根目录创建 hello.py 文件，写入打印 hello world 的代码",
    )
    assert resp.status_code != 409, resp.text
