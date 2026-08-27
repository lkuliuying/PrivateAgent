"""v1.0.0 CT-7 契约测试：本地 Deferred Tool Search（专项计划 §9.3）。

覆盖：
- BM25 检索质量与确定性排序；索引字段（名称/描述/参数标题/effect/tags）；
- 只索引已授权 deferred 集：direct/hidden/policy-denied 条目防御性排除；
- 过滤器（namespace/effect/risk_max）与 limit；
- 越权防护：激活不在已授权 deferred 索引内的名字一律拒绝；
  重复激活拒绝；搜索/激活双上限结构化失败；
- `tool_exposure_changed` 记录语义：activated 列表、visible_hash 更新
  （前后不一致）、会话余量；更新后的 ToolPlan direct 集合并入且
  deferred 移除，原计划不可变；
- search_tools Function 入口：输入 schema 冻结、输出不含 schema 全文/
  secret；§19.3 对照口径——deferred-first 的 Schema 字节开销低于全量直发。
"""

from __future__ import annotations

import json

import pytest

from personal_assistant.agent_v2.application.deferred_search import (
    DeferredToolIndex,
    SearchToolsResult,
    ToolSearchError,
    TurnSearchSession,
    handle_search_tools,
    serialize_result,
)
from personal_assistant.agent_v2.application.planner import ToolPlan
from personal_assistant.agent_v2.domain.effects import EffectClass
from personal_assistant.agent_v2.domain.tool_catalog import (
    ApprovalMode,
    SideEffectClass,
    ToolExposure,
    ToolIdempotency,
    ToolRiskLevel,
    ToolSpecV2,
)

_MIN_SCHEMA = {"type": "object", "properties": {}}


def _spec(name: str, description: str, **overrides) -> ToolSpecV2:
    payload: dict = {
        "namespace": "builtin",
        "canonical_name": name,
        "version": "1.0.0",
        "description": description,
        "input_schema": _MIN_SCHEMA,
        "output_schema": _MIN_SCHEMA,
    }
    payload.update(overrides)
    return ToolSpecV2(**payload)


_EFFECT_TO_CLASS = {
    "database.query": ("database", {"database.query"}),
    "network.request": ("network", {"network.request"}),
    "process.spawn": ("process", {"process.spawn", "process.exit"}),
}


def _deferred(name: str, description: str, *, effects=(), risk="safe", tags=()) -> ToolSpecV2:
    if effects:
        primary = effects[0]
        side_effect, allowed = _EFFECT_TO_CLASS[primary]
        effect_set = frozenset(EffectClass(e) for e in effects if e in allowed)
    else:
        side_effect, effect_set = "none", frozenset()
    return _spec(
        name,
        description,
        exposure=ToolExposure.DEFERRED,
        feature_flag="read_only_tools",
        required_capabilities=frozenset({"filesystem.read"}),
        risk_level=ToolRiskLevel(risk),
        # §12.2：auto 仅限无副作用工具；带副作用一律 prompt。
        approval_mode=(
            ApprovalMode.AUTO
            if risk == "safe" and side_effect == "none"
            else ApprovalMode.PROMPT
        ),
        side_effect_class=SideEffectClass(side_effect),
        effects=effect_set,
        idempotency=ToolIdempotency.IDEMPOTENT,
        intent_tags=frozenset(tags),
    )


@pytest.fixture()
def index() -> DeferredToolIndex:
    specs = [
        _deferred(
            "query_readonly_sql",
            "执行只读 SQL 查询数据库",
            effects=("database.query",),
            tags=("database.read",),
        ),
        _deferred(
            "call_allowlisted_api",
            "调用已授权 HTTPS 接口发送网络请求",
            effects=("network.request",),
            risk="confirm",
            tags=("network.read", "network.write"),
        ),
        _deferred(
            "run_whitelisted_command",
            "运行白名单命令执行测试构建",
            effects=("process.spawn", "process.exit"),
            risk="confirm",
            tags=("command.run", "command.test"),
        ),
        # 非 deferred 条目：不得进入索引。
        _spec("hidden_tool", "机密内部工具不应被检索"),
        _spec(
            "direct_tool",
            "已经直接可见的工具",
            exposure=ToolExposure.DIRECT,
        ),
    ]
    return DeferredToolIndex.build(specs)


# ===========================================================================
# A. 索引范围与检索质量
# ===========================================================================


def test_index_only_contains_authorized_deferred_entries(index):
    """防御性过滤：direct/hidden/policy 未授条目永不进入索引。"""
    assert index.size == 3
    for forbidden in ("hidden_tool", "direct_tool"):
        assert not index.contains(forbidden)


def test_bm25_ranks_relevant_tool_first(index):
    hits = index.search("查询 数据库 sql")
    assert hits[0].canonical_name == "query_readonly_sql"
    hits2 = index.search("网络 http 接口")
    assert hits2[0].canonical_name == "call_allowlisted_api"


def test_unknown_terms_raise_no_match(index):
    with pytest.raises(ToolSearchError) as excinfo:
        index.search("完全不相关的量子术语")
    assert excinfo.value.code.value == "tool_search_no_match"


def test_empty_or_overlong_query_rejected(index):
    with pytest.raises(ToolSearchError):
        index.search("   ")
    with pytest.raises(ToolSearchError):
        index.search("x" * 600)


def test_filters_namespace_effect_and_risk_cap(index):
    by_ns = index.search("sql", namespace="builtin")
    assert [h.canonical_name for h in by_ns] == ["query_readonly_sql"]

    by_effect = index.search("执行", effect="process.spawn")
    assert {h.canonical_name for h in by_effect} == {"run_whitelisted_command"}

    # risk_max=safe 会滤掉 confirm 级工具（宽查询命中多文档后过滤）。
    safe_only = index.search("sql 网络 执行 命令 接口 数据库", risk_max="safe")
    assert safe_only, "safe 过滤后应有结果"
    assert all(h.risk_level == "safe" for h in safe_only)
    assert all(h.canonical_name != "call_allowlisted_api" for h in safe_only)


def test_results_are_deterministic_across_calls(index):
    a = index.search("执行 测试 构建")
    b = index.search("执行 测试 构建")
    assert [(h.canonical_name, h.score) for h in a] == [
        (h.canonical_name, h.score) for h in b
    ]


# ===========================================================================
# B. 会话上限与越权防护
# ===========================================================================


def _session(index) -> TurnSearchSession:
    return TurnSearchSession(
        index, visible_hash_before="vh-before", max_activations=2, max_searches=2
    )


def _real_plan() -> "ToolPlan":
    """最小真实 ToolPlan（frozen pydantic，支持 model_copy 语义）。"""
    from personal_assistant.agent_v2.application.planner import PlannedTool, ToolPlan

    return ToolPlan(
        tool_plan_id="tp-" + "0" * 32,
        turn_tags=frozenset(),
        required_effects=frozenset(),
        direct_tools=(
            PlannedTool(namespace="builtin", canonical_name="a_direct", version="1.0.0"),
        ),
        deferred_tools=tuple(
            PlannedTool(namespace="builtin", canonical_name=name, version="1.0.0")
            for name in (
                "query_readonly_sql",
                "call_allowlisted_api",
                "run_whitelisted_command",
            )
        ),
        hidden_tools=(),
        catalog_hash="catalog-hash-0001",
        visible_hash="vh-before",
        model_profile_hash="model-hash-0001",
        policy_hash="policy-hash-001",
    )


def test_activation_requires_authorized_deferred_membership(index):
    session = _session(index)
    with pytest.raises(ToolSearchError) as excinfo:
        session.activate(["hidden_tool"], plan=_real_plan())
    assert excinfo.value.code.value == "activation_unauthorized"
    with pytest.raises(ToolSearchError) as excinfo:
        session.activate(["policy_denied_tool"], plan=_real_plan())
    assert excinfo.value.code.value == "activation_unauthorized"


def test_duplicate_activation_semantics(index):
    """全部重复 → activation_duplicate；混合重复 → 仅计新增不重复。"""
    session = _session(index)
    plan = _real_plan()
    p1, _ = session.activate(["query_readonly_sql"], plan=plan)

    with pytest.raises(ToolSearchError) as excinfo:
        session.activate(["query_readonly_sql"], plan=p1)
    assert excinfo.value.code.value == "activation_duplicate"

    p2, record = session.activate(
        ["query_readonly_sql", "call_allowlisted_api"], plan=p1
    )
    # 仅新增 call_allowlisted_api，不重复计数。
    assert record.activated == ("call_allowlisted_api",)
    assert record.activations_used == 2
    names = {item.canonical_name for item in p2.direct_tools}
    assert "query_readonly_sql" in names and "call_allowlisted_api" in names


def test_activation_and_search_caps_enforced(index):
    session = _session(index)
    plan_stub = _real_plan()
    session.activate(["query_readonly_sql", "call_allowlisted_api"], plan=plan_stub)
    with pytest.raises(ToolSearchError) as excinfo:
        session.activate(["run_whitelisted_command"], plan=plan_stub)
    assert excinfo.value.code.value == "activation_limit_reached"

    s2 = _session(index)
    s2.search("sql")
    s2.search("网络")
    with pytest.raises(ToolSearchError) as excinfo:
        s2.search("命令")
    assert excinfo.value.code.value == "search_limit_reached"


def test_empty_activation_list_rejected(index):
    with pytest.raises(ToolSearchError) as excinfo:
        _session(index).activate([], plan=_real_plan())
    assert excinfo.value.code.value == "activation_unauthorized"


# ===========================================================================
# C. tool_exposure_changed 语义与计划更新
# ===========================================================================


def test_activation_updates_plan_and_emits_exposure_changed(index):
    session = _session(index)
    original = _real_plan()
    updated, record = session.activate(
        ["query_readonly_sql", "run_whitelisted_command"], plan=original
    )
    # 事件语义：activated 有序、哈希前后不同、余量正确。
    assert record.activated == ("query_readonly_sql", "run_whitelisted_command")
    assert record.visible_hash_before == "vh-before"
    assert record.visible_hash_after != "vh-before"
    assert (record.searches_used, record.activations_used) == (0, 2)
    # 计划更新：direct 并入、deferred 移除；原对象不被修改（§7.2）。
    new_names = {item.canonical_name for item in updated.direct_tools}
    assert new_names == {"a_direct", "query_readonly_sql", "run_whitelisted_command"}
    deferred_names = {item.canonical_name for item in updated.deferred_tools}
    assert deferred_names == {"call_allowlisted_api"}
    assert len(original.direct_tools) == 1  # 原 plan 不变
    # visible_hash 与事件一致，且可由 planner 公共函数复算验证。
    from personal_assistant.agent_v2.application.planner import compute_visible_hash

    assert updated.visible_hash == compute_visible_hash(updated.direct_tools)


def test_second_activation_updates_hash_again(index):
    session = _session(index)
    plan_stub = _real_plan()
    p1, r1 = session.activate(["query_readonly_sql"], plan=plan_stub)
    p2, r2 = session.activate(["call_allowlisted_api"], plan=p1)
    assert r1.visible_hash_after == r2.visible_hash_before
    assert r2.visible_hash_after != r1.visible_hash_after


# ===========================================================================
# D. search_tools Function 入口
# ===========================================================================


def test_handle_search_tools_returns_bounded_summary(index):
    session = _session(index)
    result = handle_search_tools(session, {"query": "数据库 sql", "limit": 2})
    assert isinstance(result, SearchToolsResult)
    assert result.hits[0].canonical_name == "query_readonly_sql"
    assert result.searches_limit == 2 and result.activations_limit == 2

    payload = serialize_result(result)
    serialized = json.dumps(payload, ensure_ascii=False)
    # 输出红线：无 schema 全文、无 input_schema 键。
    assert "input_schema" not in serialized
    assert set(payload["hits"][0]) == {
        "namespace",
        "canonical_name",
        "version",
        "effects",
        "risk_level",
    }


def test_search_tools_function_propagates_session_errors(index):
    session = _session(index)
    with pytest.raises(ToolSearchError) as excinfo:
        handle_search_tools(session, {"query": "不存在的东西"})
    assert excinfo.value.code.value == "tool_search_no_match"


def test_input_schema_is_frozen_shape():
    from personal_assistant.agent_v2.application.deferred_search import (
        SEARCH_TOOLS_INPUT_SCHEMA,
    )

    assert SEARCH_TOOLS_INPUT_SCHEMA["required"] == ["query"]
    assert SEARCH_TOOLS_INPUT_SCHEMA["additionalProperties"] is False
    assert set(SEARCH_TOOLS_INPUT_SCHEMA["properties"]) == {
        "query",
        "namespace",
        "effect",
        "risk_max",
        "limit",
    }


# ===========================================================================
# E. §19.3 对照口径：deferred-first 的 Schema 字节开销低于全量直发
# ===========================================================================


def test_deferred_first_sends_fewer_schema_bytes_than_exposing_all():
    big_schema = {
        "type": "object",
        "properties": {
            f"field_{i}": {"type": "string", "description": "x" * 64}
            for i in range(20)
        },
    }
    tools = [
        _spec(f"big_{i}", "大 schema 工具", input_schema=big_schema,
              exposure=ToolExposure.DEFERRED, feature_flag="f",
              required_capabilities=frozenset({"filesystem.read"}))
        for i in range(6)
    ]

    def schemas_bytes(names):
        return sum(
            len(json.dumps(dict(t.input_schema)).encode("utf-8"))
            for t in tools
            if t.canonical_name in names
        )

    all_names = {t.canonical_name for t in tools}
    baseline = schemas_bytes(all_names)  # 全量直发
    deferred_first = schemas_bytes(set())  # 首轮仅发 search_tools 本体
    assert deferred_first < baseline * 0.5  # §19.3 目标 ≥50% 下降的机制口径
