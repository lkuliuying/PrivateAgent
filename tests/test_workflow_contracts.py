"""v0.5.0 B0 可信工作流契约冻结测试。

固定 ``docs/releases/v0.5.0/v0.5.0-b0-contracts-20260809.md`` 声明的五类工作流工具契约：
名称、版本、input/output Schema、risk、capability、幂等策略、验证器
与独立 feature flag。同时固化：

- 四个新 flag 默认关闭、不存在开启多类工作流的总开关；
- 契约数据可无损构造 ToolSpec（与 versioned registry 兼容）；
- Schema 必须为有效 Draft 2020-12 且无远程 ``$ref``。

任何字段改动必须先更新冻结文档与本文件。
"""

from __future__ import annotations

import hashlib
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from personal_assistant.agents.tools import (
    ToolCapability,
    ToolIdempotency,
    ToolRiskLevel,
    ToolSpec,
)
from personal_assistant.agents.workflow_contracts import (
    NEW_WORKFLOW_FLAG_ENV_VARS,
    WORKFLOW_CONTRACT_BY_NAME,
    WORKFLOW_KIND_BY_FLAG_ENV,
    WORKFLOW_TOOL_CONTRACTS,
    WorkflowKind,
    WorkflowToolContract,
)

FROZEN_TOOL_NAMES = {
    "propose_patch",
    "apply_patch_to_workspace",
    "run_whitelisted_command",
    "call_allowlisted_api",
    "query_readonly_sql",
}

FROZEN_NEW_FLAG_ENV_VARS = {
    "PA_AGENT_PATCH_WORKFLOW_ENABLED",
    "PA_AGENT_COMMAND_WORKFLOW_ENABLED",
    "PA_AGENT_HTTP_WORKFLOW_ENABLED",
    "PA_AGENT_SQL_READONLY_WORKFLOW_ENABLED",
}


def _contract(name: str) -> WorkflowToolContract:
    return WORKFLOW_CONTRACT_BY_NAME[name]


def _walk_refs(value, refs):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"}:
                refs.append(child)
            _walk_refs(child, refs)
    elif isinstance(value, list):
        for child in value:
            _walk_refs(child, refs)


def test_workflow_contract_table_has_exactly_five_frozen_tools():
    assert len(WORKFLOW_TOOL_CONTRACTS) == 5
    assert {c.name for c in WORKFLOW_TOOL_CONTRACTS} == FROZEN_TOOL_NAMES
    assert set(WORKFLOW_CONTRACT_BY_NAME) == FROZEN_TOOL_NAMES
    for contract in WORKFLOW_TOOL_CONTRACTS:
        assert WORKFLOW_CONTRACT_BY_NAME[contract.name] is contract


def test_all_contracts_use_frozen_versions():
    assert all(c.version == "1.0.0" for c in WORKFLOW_TOOL_CONTRACTS)


def test_risk_levels_and_capabilities_frozen():
    assert _contract("propose_patch").risk_level == ToolRiskLevel.SAFE
    assert _contract("propose_patch").required_capabilities == frozenset(
        {ToolCapability.FILESYSTEM_READ}
    )
    assert _contract("apply_patch_to_workspace").risk_level == ToolRiskLevel.CONFIRM
    assert _contract("apply_patch_to_workspace").required_capabilities == frozenset(
        {ToolCapability.FILESYSTEM_READ, ToolCapability.FILESYSTEM_WRITE}
    )
    assert _contract("run_whitelisted_command").risk_level == ToolRiskLevel.CONFIRM
    assert _contract("run_whitelisted_command").required_capabilities == frozenset(
        {ToolCapability.PROCESS_EXECUTE, ToolCapability.FILESYSTEM_READ}
    )
    assert _contract("call_allowlisted_api").risk_level == ToolRiskLevel.CONFIRM
    assert _contract("call_allowlisted_api").required_capabilities == frozenset(
        {ToolCapability.NETWORK_FETCH}
    )
    assert _contract("query_readonly_sql").risk_level == ToolRiskLevel.CONFIRM
    assert _contract("query_readonly_sql").required_capabilities == frozenset(
        {ToolCapability.DATABASE_QUERY}
    )


def test_idempotency_policy_frozen():
    assert _contract("propose_patch").idempotency == ToolIdempotency.IDEMPOTENT
    assert _contract("apply_patch_to_workspace").idempotency == (
        ToolIdempotency.NON_IDEMPOTENT
    )
    assert _contract("run_whitelisted_command").idempotency == (
        ToolIdempotency.NON_IDEMPOTENT
    )
    assert _contract("call_allowlisted_api").idempotency == ToolIdempotency.IDEMPOTENT
    assert _contract("query_readonly_sql").idempotency == ToolIdempotency.IDEMPOTENT


def test_required_result_verifiers_frozen():
    assert _contract("propose_patch").required_result_verifiers == ("file_diff",)
    assert _contract("apply_patch_to_workspace").required_result_verifiers == (
        "file_diff",
    )
    assert _contract("run_whitelisted_command").required_result_verifiers == (
        "shell",
        "code_command",
    )
    assert _contract("call_allowlisted_api").required_result_verifiers == ("api",)
    assert _contract("query_readonly_sql").required_result_verifiers == ("database",)


def test_flag_binding_frozen_and_no_master_switch():
    assert _contract("propose_patch").flag_env == "PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED"
    assert _contract("apply_patch_to_workspace").flag_env == (
        "PA_AGENT_PATCH_WORKFLOW_ENABLED"
    )
    assert _contract("run_whitelisted_command").flag_env == (
        "PA_AGENT_COMMAND_WORKFLOW_ENABLED"
    )
    assert _contract("call_allowlisted_api").flag_env == (
        "PA_AGENT_HTTP_WORKFLOW_ENABLED"
    )
    assert _contract("query_readonly_sql").flag_env == (
        "PA_AGENT_SQL_READONLY_WORKFLOW_ENABLED"
    )
    # 四个新 flag 集合固定，且每个 flag 只映射一种工作流（不存在总开关）。
    assert NEW_WORKFLOW_FLAG_ENV_VARS == FROZEN_NEW_FLAG_ENV_VARS
    assert len(WORKFLOW_KIND_BY_FLAG_ENV) == len(FROZEN_NEW_FLAG_ENV_VARS)
    for flag in FROZEN_NEW_FLAG_ENV_VARS:
        assert flag in WORKFLOW_KIND_BY_FLAG_ENV


def test_kinds_assigned_by_flag():
    assert WORKFLOW_KIND_BY_FLAG_ENV["PA_AGENT_PATCH_WORKFLOW_ENABLED"] == (
        WorkflowKind.PATCH
    )
    assert WORKFLOW_KIND_BY_FLAG_ENV["PA_AGENT_COMMAND_WORKFLOW_ENABLED"] == (
        WorkflowKind.COMMAND
    )
    assert WORKFLOW_KIND_BY_FLAG_ENV["PA_AGENT_HTTP_WORKFLOW_ENABLED"] == (
        WorkflowKind.HTTP
    )
    assert WORKFLOW_KIND_BY_FLAG_ENV["PA_AGENT_SQL_READONLY_WORKFLOW_ENABLED"] == (
        WorkflowKind.SQL
    )


def test_contract_tool_names_are_valid_spec_names():
    for contract in WORKFLOW_TOOL_CONTRACTS:
        spec = _build_spec(contract)
        assert spec.name == contract.name
        assert spec.version == contract.version


def test_command_contract_accepts_only_argument_arrays():
    schema = _contract("run_whitelisted_command").input_schema
    items = schema["properties"]["command"]
    assert items["type"] == "array"
    assert items["minItems"] == 1
    assert "oneOf" not in schema["properties"]["command"]


def test_command_contract_explicitly_excludes_file_writes():
    description = _contract("run_whitelisted_command").description
    assert "不得用于" in description
    assert "文件" in description
    assert "Patch" in description


def test_patch_preview_contract_requires_follow_up_apply_for_writes():
    description = _contract("propose_patch").description
    assert "不写入" in description
    assert "apply_patch_to_workspace" in description


def test_http_contract_allows_only_frozen_methods():
    method = _contract("call_allowlisted_api").input_schema["properties"]["method"]
    assert method == {
        "enum": ["GET", "HEAD", "POST"],
        "description": "v0.5.0 仅开放 GET/HEAD/POST；PUT/PATCH/DELETE 不开放",
    }


def test_all_schemas_are_valid_draft202012_without_remote_refs():
    for contract in WORKFLOW_TOOL_CONTRACTS:
        for label, schema in (
            ("input", contract.input_schema),
            ("output", contract.output_schema),
        ):
            refs: list[str] = []
            _walk_refs(schema, refs)
            assert all(ref.startswith("#") for ref in refs), f"{contract.name} {label} 含远程引用"
            assert schema.get("type") == "object", f"{contract.name} {label} 根类型必须为 object"
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:  # pragma: no cover - 失败信息辅助
                raise AssertionError(f"{contract.name} {label} 不是有效 JSON Schema") from exc


def test_all_contracts_can_build_tool_spec():
    for contract in WORKFLOW_TOOL_CONTRACTS:
        spec = _build_spec(contract)
        assert 1 <= spec.timeout_ms <= 600_000
        assert 128 <= spec.max_output_bytes <= 10 * 1024 * 1024
        assert 128 <= spec.max_input_bytes <= 1024 * 1024


def test_frozen_schema_hashes_are_stable():
    """Schema 摘要固定：任何意外改动会在此失败，提示更新冻结文档。"""
    expected = {
        "propose_patch": {
            "input": "7b18d79197c5d525e70e17d1dc4639151c880c0f20e139127878289d5841b98e",
            "output": "662c4cfd8ab97327c7e25e093bd5f14a81c2d9728b4647130bf63d76b0fcb795",
        },
        "apply_patch_to_workspace": {
            "input": "3e3f9b85b40bc0f412629afce089a5d5ad55caa974974e08db4f6c4953679d95",
            "output": "3978ef02b7f4358ebf90b3828ff005d6d7724161f313e53a20534548061f55e4",
        },
        "run_whitelisted_command": {
            "input": "e4c81cf7903b5f19162ac45215ad922150c17a0e07711953604a79f6ae7b5fa1",
            "output": "5e32c2546bae581539b6abebaa626166e6b046409475cff6dbe67b415938d5bb",
        },
        "call_allowlisted_api": {
            "input": "6e17911a602f2eeb070bd98b3f14d66c2eca5f4ae201ccdf17194af8abd3752b",
            "output": "d1d31a62b7791af93bc498b9154837a598acb3cf123c0b904f7a41d9dff09269",
        },
        "query_readonly_sql": {
            "input": "2d1713442fb72f62c4998f5b2a0628ff860ad0a097a5fb37a6e7559a30906d39",
            "output": "1971c20b124d92c649382cedc22feed123418bd2d208a531e33a44f942d712f9",
        },
    }
    for name, parts in expected.items():
        contract = _contract(name)
        for part, digest in parts.items():
            schema = contract.input_schema if part == "input" else contract.output_schema
            raw = json.dumps(
                schema, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            actual = hashlib.sha256(raw).hexdigest()
            assert actual == digest, f"{name}.{part} schema 摘要漂移（{actual}）"


def test_workflow_flags_are_present_and_off_by_default_in_settings():
    from personal_assistant.config import Settings

    expected_fields = {
        "agent_patch_workflow_enabled",
        "agent_command_workflow_enabled",
        "agent_http_workflow_enabled",
        "agent_sql_readonly_workflow_enabled",
    }
    assert expected_fields <= set(Settings.model_fields)
    for field in expected_fields:
        assert Settings.model_fields[field].default is False, (
            f"{field} 必须默认关闭"
        )


def test_capabilities_response_exposes_workflow_flags():
    from personal_assistant.api.routes_health import RuntimeCapabilities

    expected = {
        "patch_workflow_enabled",
        "command_workflow_enabled",
        "http_workflow_enabled",
        "sql_readonly_workflow_enabled",
    }
    assert expected <= set(RuntimeCapabilities.model_fields)
    for field in expected:
        assert RuntimeCapabilities.model_fields[field].default is False


def _build_spec(contract: WorkflowToolContract) -> ToolSpec:
    async def _stub_executor(arguments, cancellation):
        return None

    return ToolSpec(
        name=contract.name,
        version=contract.version,
        description=contract.description,
        input_schema=contract.input_schema,
        output_schema=contract.output_schema,
        risk_level=contract.risk_level,
        required_capabilities=contract.required_capabilities,
        timeout_ms=contract.timeout_ms,
        max_input_bytes=contract.max_input_bytes,
        max_output_bytes=contract.max_output_bytes,
        idempotency=contract.idempotency,
        supports_cancellation=contract.supports_cancellation,
        redaction_policy=contract.redaction_policy,
        executor=_stub_executor,
    )
