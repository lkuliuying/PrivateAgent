"""按需目录的实际模型定义、配置隔离和有界加载回归。"""
import copy

import pytest
from pydantic import ValidationError

from private_agent_core.tool_specs import ToolFailure
from private_agent_local import tool_catalog
from private_agent_local.tool_catalog import DEFERRED_TOOLS, SEARCH_SPEC, ToolCatalog
from private_agent_local.tool_registry import REGISTRY


def run_state(**changes):
    return {"permission_mode": "confirm", "execution_contract_version": "1.0", **changes}


def eligible():
    return tuple(spec for spec in REGISTRY if spec.name not in {"request_user_input", "update_run_plan", "tool_search"})


def documentation():
    return {"sources": [{"id": "a" * 32, "name": "SDK reference", "version": "b" * 32,
                         "catalog_expired": False, "tools": [{"name": "search_sdk", "description": "检索 SDK 技术文档",
                         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                                          "required": ["query"], "additionalProperties": False}}]}], "untrusted": True}


def names(definitions):
    return {definition.name for definition in definitions}


def test_search_activates_actual_definitions_without_mutating_registry_or_saving_schemas():
    catalog, run = ToolCatalog(REGISTRY), run_state()
    before = tuple(REGISTRY)
    initial = catalog.definitions(run, eligible(), {})
    assert {"exec_command", "get_execution_capabilities", "write_stdin", "cancel_execution", "tool_search"} <= names(initial)
    assert not DEFERRED_TOOLS.intersection(names(initial))
    assert "tool_catalog" not in run
    result = catalog.search(run, eligible(), {}, {"query": "request_execution", "limit": 1})
    assert [match["name"] for match in result["matches"]] == ["request_execution"]
    assert result["loaded_tools"] == ["request_execution"]
    assert "request_execution" in names(catalog.definitions(run, eligible(), {}))
    assert run["tool_catalog"] == {"loaded_names": ["request_execution"]}
    assert tuple(REGISTRY) == before


def test_legacy_protocol_preserves_existing_catalog_and_empty_deferred_catalog_adds_nothing():
    catalog = ToolCatalog(REGISTRY)
    run = run_state(execution_contract_version=None)
    visible = names(catalog.definitions(run, eligible(), {}))
    assert {"run_project_command", "call_documentation_tool"} <= visible
    assert "tool_search" not in visible
    assert not {"exec_command", "request_execution"}.intersection(visible)
    with pytest.raises(ToolFailure, match="执行协议"):
        catalog.search(run, eligible(), {}, {"query": "文档"})
    basics = tuple(spec for spec in eligible() if spec.name not in DEFERRED_TOOLS)
    assert "tool_search" not in names(catalog.definitions(run_state(), basics, {}))


@pytest.mark.parametrize("arguments", [{"query": ""}, {"query": "   "}, {"query": None}, {"query": 123},
                                        {"query": "docs", "limit": 0}, {"query": "docs", "limit": 6},
                                        {"query": "docs", "limit": "1"}, {"query": "docs", "extra": True}])
def test_invalid_search_inputs_never_load_tools(arguments):
    run = run_state()
    with pytest.raises(ValidationError):
        ToolCatalog(REGISTRY).search(run, eligible(), documentation(), arguments)
    assert "tool_catalog" not in run


def test_documentation_search_returns_bound_versions_and_original_schema_without_network():
    catalog, run, sources = ToolCatalog(REGISTRY), run_state(), documentation()
    result = catalog.search(run, eligible(), sources, {"query": "search_sdk", "limit": 1})
    match = result["matches"][0]
    assert match["kind"] == "documentation" and match["untrusted"] is True
    assert match["source_id"] == "a" * 32 and match["source_version"] == "b" * 32
    assert match["tool_name"] == "search_sdk"
    assert match["input_schema"] == sources["sources"][0]["tools"][0]["input_schema"]
    assert set(result["loaded_tools"]) == {"list_documentation_sources", "call_documentation_tool"}
    match["input_schema"]["properties"].clear()
    assert sources["sources"][0]["tools"][0]["input_schema"]["properties"]
    other_run = run_state()
    assert "call_documentation_tool" not in names(catalog.definitions(other_run, eligible(), sources))
    assert catalog.search(other_run, eligible(), {}, {"query": "search_sdk"})["matches"] == []


def test_latest_permissions_and_eligible_snapshot_override_persisted_loads():
    catalog, run = ToolCatalog(REGISTRY), run_state()
    catalog.search(run, eligible(), documentation(), {"query": "request_execution", "limit": 1})
    catalog.search(run, eligible(), documentation(), {"query": "search_sdk", "limit": 1})
    run["permission_mode"] = "readonly"
    assert "request_execution" not in names(catalog.definitions(run, eligible(), documentation()))
    run["completion_policy"] = {"network_forbidden": True}
    assert "call_documentation_tool" not in names(catalog.definitions(run, eligible(), documentation()))
    assert catalog.search(run, eligible(), documentation(), {"query": "search_sdk"})["matches"] == []
    reduced = tuple(spec for spec in eligible() if spec.name not in tool_catalog.DOCUMENTATION_TOOLS)
    assert not tool_catalog.DOCUMENTATION_TOOLS.intersection(names(catalog.definitions(run, reduced, {})))
    run["collaboration_mode"] = "plan"
    assert "request_execution" not in names(catalog.definitions(run, eligible(), {}))


def test_stale_catalog_is_not_loaded_and_source_version_is_refreshed_on_search():
    catalog, run, sources = ToolCatalog(REGISTRY), run_state(), documentation()
    sources["sources"][0]["catalog_expired"] = True
    assert catalog.search(run, eligible(), sources, {"query": "search_sdk"})["matches"] == []
    sources["sources"][0].update(catalog_expired=False, version="c" * 32)
    result = catalog.search(run, eligible(), sources, {"query": "search_sdk", "limit": 1})
    assert result["matches"][0]["source_version"] == "c" * 32


def test_documentation_wrapper_search_loads_catalog_dependency_together():
    run = run_state()
    result = ToolCatalog(REGISTRY).search(run, eligible(), documentation(), {"query": "call_documentation_tool", "limit": 1})
    assert result["matches"][0]["name"] == "call_documentation_tool"
    assert set(result["loaded_tools"]) == tool_catalog.DOCUMENTATION_TOOLS


@pytest.mark.parametrize("query", ["request_execution", "  REQUEST_EXECUTION  "])
def test_exact_builtin_name_takes_priority_over_colliding_documentation_name(query):
    catalog, run, sources = ToolCatalog(REGISTRY), run_state(), documentation()
    sources["sources"][0]["tools"][0]["name"] = "request_execution"
    exact = catalog.search(run, eligible(), sources, {"query": query, "limit": 1})
    assert exact["matches"][0]["kind"] == "builtin"
    assert exact["matches"][0]["name"] == "request_execution"
    assert exact["loaded_tools"] == ["request_execution"]
    assert not tool_catalog.DOCUMENTATION_TOOLS.intersection(names(catalog.definitions(run, eligible(), sources)))
    document_query = catalog.search(run_state(), eligible(), sources, {"query": "文档", "limit": 1})
    assert document_query["matches"][0]["kind"] == "documentation"
    assert document_query["matches"][0]["tool_name"] == "request_execution"
    assert set(document_query["loaded_tools"]) == tool_catalog.DOCUMENTATION_TOOLS


def test_chinese_search_deterministic_ranking_and_no_irrelevant_fallback():
    catalog, run = ToolCatalog(REGISTRY), run_state()
    assert catalog.search(run, eligible(), {}, {"query": "需要高级命令的交互终端", "limit": 1})["matches"][0]["name"] == "request_execution"
    first = catalog.search(run, eligible(), documentation(), {"query": "文档", "limit": 5})
    second = catalog.search(run, tuple(reversed(eligible())), documentation(), {"query": "文档", "limit": 5})
    assert first == second
    assert len(first["matches"]) <= 5
    prior = copy.deepcopy(run)
    assert catalog.search(run, eligible(), {}, {"query": "zqx987nonexistent"})["matches"] == []
    assert run == prior


def test_discovery_output_and_loaded_count_fail_before_state_change(monkeypatch):
    catalog, run, sources = ToolCatalog(REGISTRY), run_state(), documentation()
    sources["sources"][0]["tools"][0]["input_schema"]["description"] = "x" * tool_catalog.MAX_RESULT_BYTES
    with pytest.raises(ToolFailure) as error:
        catalog.search(run, eligible(), sources, {"query": "search_sdk", "limit": 1})
    assert error.value.code == "tool_output_too_large"
    assert "tool_catalog" not in run
    monkeypatch.setattr(tool_catalog, "MAX_LOADED_TOOLS", 1)
    with pytest.raises(ToolFailure) as error:
        catalog.search(run, eligible(), documentation(), {"query": "search_sdk", "limit": 1})
    assert error.value.code == "tool_catalog_full"
    assert "tool_catalog" not in run


def test_restored_loaded_names_reach_definitions_but_invalid_state_fails_closed():
    run = run_state(tool_catalog={"loaded_names": ["list_executions"]})
    catalog = ToolCatalog(REGISTRY)
    assert "list_executions" in names(catalog.definitions(run, eligible(), {}))
    run["tool_catalog"]["loaded_names"].append("list_executions")
    with pytest.raises(ValidationError):
        catalog.definitions(run, eligible(), {})
    assert SEARCH_SPEC.parallel_safe is False and SEARCH_SPEC.effect == "control"
