"""v1.0.0 CT2 单元测试：ToolSpec v2 / Catalog / ToolPlan / ToolSnapshot。

覆盖专项计划 §17 CT2-01～03 退出条件：

- ToolSpecV2 字段与不变式（effects↔副作用大类、auto 审批仅限无副作用、
  别名可逆、disabled/deny 必须 hidden、AD-T07 并发资格）；
- Catalog 唯一性与 Provider 可见名冲突（tool_name_collision）与规范化 hash；
- Planner §9.2 暴露决策链：每层隐藏原因稳定可测试；预算确定性；
  ToolPlan/ToolPlan ID 确定性；快照脱敏。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from personal_assistant.agent_v2.application.catalog import (
    ToolCatalog,
    ToolCatalogError,
)
from personal_assistant.agent_v2.application.planner import (
    HiddenReason,
    ModelCapabilitySnapshot,
    PolicySnapshot,
    SnapshotEntry,
    build_tool_plan,
    build_tool_snapshot,
)
from personal_assistant.agent_v2.domain.effects import EffectClass
from personal_assistant.agent_v2.domain.intents import IntentTag
from personal_assistant.agent_v2.domain.tool_catalog import (
    ApprovalMode,
    ExecutorKind,
    ModelRequirements,
    SideEffectClass,
    ToolExposure,
    ToolIdempotency,
    ToolMaturity,
    ToolRiskLevel,
    ToolSpecV2,
)

_MIN_SCHEMA = {"type": "object", "properties": {}}


def _spec(**overrides) -> ToolSpecV2:
    payload: dict = {
        "namespace": "builtin",
        "canonical_name": "read_file",
        "version": "1.0.0",
        "description": "读取已授权文件内容",
        "input_schema": _MIN_SCHEMA,
        "output_schema": _MIN_SCHEMA,
    }
    payload.update(overrides)
    return ToolSpecV2(**payload)


# ===========================================================================
# A. ToolSpecV2 不变式（CT2-01）
# ===========================================================================


def test_minimal_builtin_spec_is_valid_and_parallel_ineligible_by_default():
    spec = _spec()
    assert spec.catalog_key == ("builtin", "read_file", "1.0.0")
    assert spec.is_parallel_eligible() is False  # parallel_safe 默认 False


def test_effects_must_match_side_effect_class():
    with pytest.raises(ValidationError):
        _spec(
            side_effect_class=SideEffectClass.NETWORK,
            effects=frozenset({EffectClass.FILESYSTEM_WRITE}),
        )
    ok = _spec(
        side_effect_class=SideEffectClass.FILESYSTEM,
        effects=frozenset({EffectClass.FILESYSTEM_WRITE}),
        approval_mode=ApprovalMode.PROMPT,
    )
    assert EffectClass.FILESYSTEM_WRITE in ok.effects


def test_auto_approval_requires_no_side_effects():
    """§12.2：approval_mode=auto 仅允许无副作用工具。"""
    with pytest.raises(ValidationError):
        _spec(
            side_effect_class=SideEffectClass.FILESYSTEM,
            effects=frozenset({EffectClass.FILESYSTEM_WRITE}),
        )


def test_aliases_must_be_reversible_within_spec():
    with pytest.raises(ValidationError):
        _spec(model_aliases={"qwen": "read_file", "openai": "READ_FILE"})


def test_disabled_maturity_and_deny_mode_force_hidden_exposure():
    with pytest.raises(ValidationError):
        _spec(maturity=ToolMaturity.DISABLED, exposure=ToolExposure.DIRECT)
    with pytest.raises(ValidationError):
        _spec(approval_mode=ApprovalMode.DENY, exposure=ToolExposure.DIRECT)


def test_adt07_parallel_eligibility_matrix():
    """AD-T07：只读 + 幂等 + auto 审批 + parallel_safe 才允许并发。"""
    eligible = _spec(
        parallel_safe=True,
        side_effect_class=SideEffectClass.NONE,
        idempotency=ToolIdempotency.IDEMPOTENT,
        approval_mode=ApprovalMode.AUTO,
    )
    assert eligible.is_parallel_eligible() is True
    not_idempotent = _spec(
        parallel_safe=True,
        side_effect_class=SideEffectClass.NONE,
        idempotency=ToolIdempotency.NON_IDEMPOTENT,
        approval_mode=ApprovalMode.AUTO,
    )
    assert not_idempotent.is_parallel_eligible() is False
    streaming = _spec(
        parallel_safe=True,
        side_effect_class=SideEffectClass.NONE,
        idempotency=ToolIdempotency.IDEMPOTENT,
        approval_mode=ApprovalMode.AUTO,
        streaming_output=True,
    )
    assert streaming.is_parallel_eligible() is False


def test_namespace_pattern_rejects_unknown_prefixes():
    with pytest.raises(ValidationError):
        _spec(namespace="internal.read_file")


def test_model_requirements_default_fails_closed_for_freeform():
    req = ModelRequirements()
    assert req.function_calling is True
    assert req.freeform_patch is False


def test_source_records_provenance_without_secrets():
    source = _spec(
        source={
            "component": "codex/apply-patch",
            "upstream_commit": "465eafacbc2db4ff828cd6d18ed8f25d22e48f53",
            "license_id": "Apache-2.0",
        }
    ).source
    assert source.upstream_commit == "465eafacbc2db4ff828cd6d18ed8f25d22e48f53"
    assert source.model_dump() == {
        "component": "codex/apply-patch",
        "version": None,
        "upstream_commit": "465eafacbc2db4ff828cd6d18ed8f25d22e48f53",
        "license_id": "Apache-2.0",
    }


# ===========================================================================
# B. Catalog 唯一性/冲突/规范化 hash（CT2-02）
# ===========================================================================


def test_duplicate_catalog_key_is_rejected_as_collision():
    with pytest.raises(ToolCatalogError) as excinfo:
        ToolCatalog.build([_spec(), _spec()])
    assert excinfo.value.code == "tool_name_collision"


def test_provider_alias_collision_across_tools_is_rejected_before_model_call():
    a = _spec(canonical_name="alpha", model_aliases={"qwen": "reader"})
    b = _spec(canonical_name="beta", model_aliases={"qwen": "Reader"})
    with pytest.raises(ToolCatalogError) as excinfo:
        ToolCatalog.build([a, b])
    assert excinfo.value.code == "tool_name_collision"


def test_catalog_hash_is_order_stable_and_sensitive_to_content():
    specs = [_spec(canonical_name="alpha"), _spec(canonical_name="beta")]
    h1 = ToolCatalog.build(specs).catalog_hash()
    h2 = ToolCatalog.build(list(reversed(specs))).catalog_hash()
    assert h1 == h2
    changed = ToolCatalog.build(
        [_spec(canonical_name="alpha", description="changed"), specs[1]]
    ).catalog_hash()
    assert changed != h1


def test_catalog_find_roundtrip():
    catalog = ToolCatalog.build([_spec(version="1.0.0"), _spec(version="1.1.0")])
    found = catalog.find(
        namespace="builtin", canonical_name="read_file", version="1.1.0"
    )
    assert found is not None and found.version == "1.1.0"


# ===========================================================================
# C. Planner 暴露决策链（CT2-03，§9.2）
# ===========================================================================


_MODEL = ModelCapabilitySnapshot(profile_hash="model-hash-0001")
_POLICY = PolicySnapshot(
    policy_hash="policy-hash-001",
    granted_capabilities=frozenset({"filesystem.read"}),
    enabled_features=frozenset({"read_only_tools"}),
)


def _healthy_spec(name: str = "read_file") -> ToolSpecV2:
    return _spec(
        canonical_name=name,
        feature_flag="read_only_tools",
        required_capabilities=frozenset({"filesystem.read"}),
    )


def test_healthy_tool_is_direct():
    plan = build_tool_plan(
        ToolCatalog.build([_healthy_spec()]),
        frozenset({IntentTag.CODE_INSPECT}),
        model=_MODEL,
        policy=_POLICY,
    )
    assert [item.canonical_name for item in plan.direct_tools] == ["read_file"]
    assert plan.hidden_tools == ()
    assert plan.visible_hash
    assert plan.tool_plan_id.startswith("tp-")


def test_every_hidden_reason_is_stable_and_testable():
    cases = [
        (
            _spec(
                maturity=ToolMaturity.DISABLED,
                exposure=ToolExposure.HIDDEN,
            ),
            HiddenReason.MATURITY_DISABLED,
        ),
        (
            _spec(
                model_requirements=ModelRequirements(freeform_patch=True),
            ),
            HiddenReason.MODEL_UNSUPPORTED,
        ),
        (
            _spec(required_capabilities=frozenset({"filesystem.write"})),
            HiddenReason.POLICY_DENIED,
        ),
        (
            _spec(feature_flag="patch_workflow"),
            HiddenReason.FEATURE_DISABLED,
        ),
        (
            _spec(health_check_id="mcp-alpha"),
            HiddenReason.HEALTH_FAILED,
        ),
        (
            _spec(intent_tags=frozenset({"database.read"})),
            HiddenReason.NOT_RELEVANT,
        ),
    ]
    for index, (spec, reason) in enumerate(cases):
        policy = _POLICY
        if reason is HiddenReason.HEALTH_FAILED:
            policy = PolicySnapshot(
                policy_hash=_POLICY.policy_hash,
                granted_capabilities=_POLICY.granted_capabilities,
                enabled_features=_POLICY.enabled_features,
                health_failed=frozenset({"mcp-alpha"}),
            )
        plan = build_tool_plan(
            ToolCatalog.build([spec]),
            frozenset({IntentTag.CODE_INSPECT}),
            model=_MODEL,
            policy=policy,
        )
        assert plan.direct_tools == (), f"case {index} should be hidden"
        assert [item.reason for item in plan.hidden_tools] == [reason]


def test_context_budget_hides_overflow_deterministically():
    specs = [_healthy_spec("a_tool"), _healthy_spec("b_tool")]
    tiny_model = ModelCapabilitySnapshot(
        profile_hash="model-hash-0001",
        max_direct_tools=1,
        max_schema_bytes=1024,
    )
    plan = build_tool_plan(
        ToolCatalog.build(specs),
        frozenset({IntentTag.ANSWER_ONLY}),
        model=tiny_model,
        policy=_POLICY,
    )
    assert [item.canonical_name for item in plan.direct_tools] == ["a_tool"]
    assert [
        (item.canonical_name, item.reason) for item in plan.hidden_tools
    ] == [("b_tool", HiddenReason.CONTEXT_BUDGET)]


def test_deferred_tools_do_not_consume_schema_budget():
    deferred_spec = _spec(
        canonical_name="z_searchable",
        exposure=ToolExposure.DEFERRED,
        feature_flag="read_only_tools",
        required_capabilities=frozenset({"filesystem.read"}),
    )
    direct_spec = _healthy_spec("a_tool")
    plan = build_tool_plan(
        ToolCatalog.build([deferred_spec, direct_spec]),
        frozenset({IntentTag.ANSWER_ONLY}),
        model=ModelCapabilitySnapshot(
            profile_hash="model-hash-0001", max_direct_tools=1
        ),
        policy=_POLICY,
    )
    assert [item.canonical_name for item in plan.deferred_tools] == ["z_searchable"]
    # direct 预算未被 deferred 占用。
    assert [item.canonical_name for item in plan.direct_tools] == ["a_tool"]


def test_tool_plan_is_deterministic_and_policy_sensitive():
    def build(policy: PolicySnapshot):
        return build_tool_plan(
            ToolCatalog.build([_healthy_spec()]),
            frozenset({IntentTag.CODE_INSPECT}),
            model=_MODEL,
            policy=policy,
        )

    p1 = build(_POLICY)
    p2 = build(_POLICY)
    assert p1.tool_plan_id == p2.tool_plan_id
    assert p1.visible_hash == p2.visible_hash
    other_policy = PolicySnapshot(
        policy_hash="policy-hash-002",
        granted_capabilities=_POLICY.granted_capabilities,
        enabled_features=_POLICY.enabled_features,
    )
    assert build(other_policy).tool_plan_id != p1.tool_plan_id


def test_required_effects_flow_into_plan_from_intent_tags():
    plan = build_tool_plan(
        ToolCatalog.build([_healthy_spec()]),
        frozenset({IntentTag.FILE_MUTATE, IntentTag.CODE_INSPECT}),
        model=_MODEL,
        policy=_POLICY,
    )
    assert plan.required_effects == frozenset({EffectClass.FILESYSTEM_WRITE})


def test_snapshot_is_redacted_and_explains_every_tool():
    """§7.3/迭代退出证据：快照能解释每个工具的 direct/deferred/hidden 原因。"""
    catalog = ToolCatalog.build(
        [
            _healthy_spec(),
            _spec(
                canonical_name="z_disabled_tool",
                maturity=ToolMaturity.DISABLED,
                exposure=ToolExposure.HIDDEN,
            ),
        ]
    )
    plan = build_tool_plan(
        catalog,
        frozenset({IntentTag.CODE_INSPECT}),
        model=_MODEL,
        policy=_POLICY,
    )
    snapshot = build_tool_snapshot(plan, catalog)
    assert snapshot.direct_total == 1
    assert snapshot.hidden_total == 1
    by_name = {entry.canonical_name: entry for entry in snapshot.entries}
    assert by_name["read_file"].exposure == "direct"
    assert by_name["read_file"].executor_kind == ExecutorKind.PYTHON.value
    assert by_name["read_file"].risk_level == ToolRiskLevel.SAFE.value
    assert by_name["read_file"].side_effect_class == SideEffectClass.NONE.value
    second = snapshot.entries[1]
    assert isinstance(second, SnapshotEntry)
    assert second.exposure == f"hidden:{HiddenReason.MATURITY_DISABLED.value}"
    # 脱敏红线：快照条目不含 schema/描述全文/参数。
    entry_fields = set(SnapshotEntry.model_fields)
    assert "input_schema" not in entry_fields
    assert "description" not in entry_fields


def test_applicability_override_hides_workspace_irrelevant_tool():
    plan = build_tool_plan(
        ToolCatalog.build([_healthy_spec()]),
        frozenset({IntentTag.CODE_INSPECT}),
        model=_MODEL,
        policy=_POLICY,
        applicable={"read_file": False},
    )
    assert [item.reason for item in plan.hidden_tools] == [
        HiddenReason.NOT_APPLICABLE
    ]
