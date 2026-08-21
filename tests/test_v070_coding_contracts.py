"""v0.7.0 E0 契约测试：可信编码执行（冻结清单见 E0 契约 §9）。

这些测试定义 v0.7.0 新增的公开契约。基础设施部分（flags、事件、
错误码、权限模式集合、Artifact kinds、PatchSet schema）立即通过；
工具/行为部分（E1–E4 实现）以 ``xfail(strict=True)`` 形态进入，
实现完成后移除 ``xfail`` 标记并保持全绿。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md``。
"""
from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from personal_assistant.agents.contracts import AgentEventType
from personal_assistant.agents.patchset_contracts import (
    APPLY_PATCH_SET_INPUT,
    APPLY_PATCH_SET_OUTPUT,
    HIGH_RISK_OPERATIONS,
    MAX_OPERATION_COUNT,
    MAX_PATCHSET_FILES,
    MAX_REL_PATH_LEN,
    MAX_SINGLE_FILE_BYTES,
    MAX_TOTAL_DIFF_BYTES,
    MAX_TOTAL_INPUT_BYTES,
    PATCHSET_CONTRACT_BY_NAME,
    PATCHSET_EVENT_PAYLOADS,
    PATCHSET_FILE_STATUSES,
    PATCHSET_OPERATIONS,
    PATCHSET_STATUSES,
    PATCHSET_TOOL_CONTRACTS,
    PROPOSE_PATCH_SET_INPUT,
    PROPOSE_PATCH_SET_OUTPUT,
)
from personal_assistant.core.coding_errors import (
    ERROR_CODES,
    PERMISSION_MODES,
    STABLE_EVENTS,
)

# ===========================================================================
# §9.1 权限模式集合替换（E0 §4.1）
# ===========================================================================


def test_permission_modes_replaced():
    """v0.7.0 三模式替换 C0-D07 集合；read_only/full_access 不再是合法值。"""
    assert PERMISSION_MODES == {"readonly", "confirm", "workspace"}
    assert "read_only" not in PERMISSION_MODES
    assert "full_access" not in PERMISSION_MODES
    # confirm 是两版集合交集，保留
    assert "confirm" in PERMISSION_MODES


def test_permission_mode_error_codes_frozen():
    """权限相关错误码冻结。"""
    for code in ("permission_mode_invalid", "permission_denied"):
        assert code in ERROR_CODES


# ===========================================================================
# §9.2/§9.3 PatchSet 契约冻结
# ===========================================================================


def test_patchset_tool_contracts_frozen():
    """两个 PatchSet 工具契约固定（名称/版本/flag/risk/幂等）。"""
    assert [c.name for c in PATCHSET_TOOL_CONTRACTS] == [
        "propose_patch_set",
        "apply_patch_set",
    ]
    propose = PATCHSET_CONTRACT_BY_NAME["propose_patch_set"]
    apply = PATCHSET_CONTRACT_BY_NAME["apply_patch_set"]
    assert propose.flag_env == "PA_CODING_PATCHSET_ENABLED"
    assert apply.flag_env == "PA_CODING_PATCHSET_ENABLED"
    assert propose.risk_level == "safe"
    assert apply.risk_level == "confirm"
    assert propose.idempotency == "idempotent"
    assert apply.idempotency == "non_idempotent"
    assert apply.required_capabilities == frozenset(
        {"filesystem_read", "filesystem_write"}
    )


def test_patchset_limits_frozen():
    """硬上限冻结（E0 §2.2）。"""
    assert MAX_PATCHSET_FILES == 32
    assert MAX_OPERATION_COUNT == 32
    assert MAX_SINGLE_FILE_BYTES == 500 * 1024
    assert MAX_TOTAL_INPUT_BYTES == 5 * 1024 * 1024
    assert MAX_TOTAL_DIFF_BYTES == 2 * 1024 * 1024
    assert MAX_REL_PATH_LEN == 2048


def test_patchset_operation_set_frozen():
    """四类操作与高风险分类冻结。"""
    assert PATCHSET_OPERATIONS == {"create", "update", "delete", "rename"}
    assert HIGH_RISK_OPERATIONS == {"delete", "rename"}


def test_patchset_status_machines_frozen():
    """状态机集合冻结（E0 §2.4）。"""
    assert PATCHSET_STATUSES == {
        "previewed",
        "applied",
        "failed",
        "rolled_back",
        "partial_unknown",
        "rejected",
    }
    assert PATCHSET_FILE_STATUSES == {"pending", "applied", "rolled_back", "unknown"}


def test_patchset_schemas_are_valid_json_schema():
    """四份 schema 均为有效 JSON Schema（根 object）。"""
    for schema in (
        PROPOSE_PATCH_SET_INPUT,
        PROPOSE_PATCH_SET_OUTPUT,
        APPLY_PATCH_SET_INPUT,
        APPLY_PATCH_SET_OUTPUT,
    ):
        assert schema["type"] == "object"
        Draft202012Validator.check_schema(schema)


def test_patchset_schemas_enforce_operation_discriminator():
    """操作项必须带 operation 判别字段，且操作参数不可混用。"""
    validator = Draft202012Validator(PROPOSE_PATCH_SET_INPUT)
    # 合法：create + rename 混合
    assert validator.is_valid(
        {
            "operations": [
                {"operation": "create", "create": {"path": "a.py", "new_content": "x"}},
                {
                    "operation": "rename",
                    "rename": {
                        "old_path": "a.py",
                        "new_path": "b.py",
                        "expected_old_sha256": "a" * 64,
                    },
                },
            ]
        }
    )
    # 非法：update 缺 expected_old_sha256
    assert not validator.is_valid(
        {
            "operations": [
                {"operation": "update", "update": {"path": "a.py", "new_content": "x"}}
            ]
        }
    )
    # 非法：operation=create 但带了 update 参数
    assert not validator.is_valid(
        {
            "operations": [
                {
                    "operation": "create",
                    "update": {"path": "a.py", "new_content": "x"},
                }
            ]
        }
    )
    # 非法：超过 32 项
    assert not validator.is_valid(
        {
            "operations": [
                {"operation": "create", "create": {"path": f"f{i}.py", "new_content": "x"}}
                for i in range(33)
            ]
        }
    )


def test_patchset_schemas_reject_bad_paths():
    """路径约束：空路径、超长路径拒绝。"""
    validator = Draft202012Validator(PROPOSE_PATCH_SET_INPUT)
    assert not validator.is_valid(
        {
            "operations": [
                {"operation": "create", "create": {"path": "", "new_content": "x"}}
            ]
        }
    )
    assert not validator.is_valid(
        {
            "operations": [
                {
                    "operation": "create",
                    "create": {"path": "a" * (MAX_REL_PATH_LEN + 1), "new_content": "x"},
                }
            ]
        }
    )


def test_patchset_schemas_reject_oversized_content():
    validator = Draft202012Validator(PROPOSE_PATCH_SET_INPUT)
    assert not validator.is_valid(
        {
            "operations": [
                {
                    "operation": "create",
                    "create": {"path": "a.py", "new_content": "x" * (MAX_SINGLE_FILE_BYTES + 1)},
                }
            ]
        }
    )


def test_apply_input_requires_preview_identity():
    """apply 必须携带 patch_set_id + preview_version + expected_parameters_hash。"""
    validator = Draft202012Validator(APPLY_PATCH_SET_INPUT)
    assert validator.is_valid(
        {
            "patch_set_id": "ps-1",
            "preview_version": 1,
            "expected_parameters_hash": "b" * 64,
        }
    )
    assert not validator.is_valid({"patch_set_id": "ps-1", "preview_version": 1})
    assert not validator.is_valid(
        {
            "patch_set_id": "ps-1",
            "preview_version": 0,
            "expected_parameters_hash": "b" * 64,
        }
    )
    assert not validator.is_valid(
        {
            "patch_set_id": "ps-1",
            "preview_version": 1,
            "expected_parameters_hash": "not-a-sha",
        }
    )


def test_preview_output_schema_frozen():
    validator = Draft202012Validator(PROPOSE_PATCH_SET_OUTPUT)
    assert validator.is_valid(
        {
            "patch_set_id": "ps-1",
            "preview_version": 1,
            "base_head_sha": "c" * 64,
            "parameters_hash": "d" * 64,
            "truncated": False,
            "file_count": 1,
            "additions": 3,
            "deletions": 1,
            "diff_total_bytes": 120,
            "files": [
                {
                    "operation": "update",
                    "path": "a.py",
                    "old_sha256": "e" * 64,
                    "new_sha256": "f" * 64,
                    "diff_text": "--- a/a.py\n+++ b/a.py\n",
                    "truncated": False,
                }
            ],
        }
    )


# ===========================================================================
# §9.7 Artifact kinds 冻结（E0 §3）
# ===========================================================================


def test_artifact_kinds_extended():
    from personal_assistant.core.run_artifact import ARTIFACT_KINDS

    assert ARTIFACT_KINDS == {
        # v0.6.0
        "diff",
        "file",
        "command_output",
        "test_report",
        "summary",
        # v0.7.0 新增
        "patch_preview",
        "patch_applied",
        "command_result",
        "lint_report",
        "build_report",
        "final_report",
    }


# ===========================================================================
# §9.8 新增 durable 事件（E0 §1）
# ===========================================================================


def test_patchset_events_frozen():
    """五个 patch_set.* 事件在枚举与稳定事件集合中，payload 规格冻结。"""
    for event_name in (
        "patch_set.preview_created",
        "patch_set.applied",
        "patch_set.rolled_back",
        "patch_set.failed",
        "patch_set.unknown",
    ):
        assert event_name in {e.value for e in AgentEventType}
        assert event_name in STABLE_EVENTS
    assert PATCHSET_EVENT_PAYLOADS["patch_set.preview_created"] == frozenset(
        {"patch_set_id", "preview_version", "file_count", "truncated", "base_head_sha"}
    )
    assert PATCHSET_EVENT_PAYLOADS["patch_set.applied"] == frozenset(
        {"patch_set_id", "preview_version", "verified"}
    )
    assert PATCHSET_EVENT_PAYLOADS["patch_set.rolled_back"] == frozenset(
        {"patch_set_id", "reason"}
    )
    assert PATCHSET_EVENT_PAYLOADS["patch_set.failed"] == frozenset(
        {"patch_set_id", "error_code", "error_message"}
    )
    assert PATCHSET_EVENT_PAYLOADS["patch_set.unknown"] == frozenset(
        {"patch_set_id", "reason"}
    )


def test_patchset_error_codes_frozen():
    """v0.7.0 错误码全部冻结。"""
    for code in (
        "patchset_invalid",
        "patchset_conflict",
        "patchset_not_found",
        "patchset_preview_stale",
        "patchset_truncated",
        "patchset_partial_unknown",
        "command_profile_invalid",
        "command_profile_not_found",
        "command_profile_version_conflict",
        "model_profile_not_found",
        "model_profile_unsupported",
        "artifact_kind_invalid",
        "completion_conditions_unmet",
    ):
        assert code in ERROR_CODES


# ===========================================================================
# §9.10 flags 默认关闭 + 依赖校验
# ===========================================================================


def test_v070_flags_default_off():
    from personal_assistant.config import settings

    assert settings.coding_patchset_enabled is False
    assert settings.coding_command_profiles_enabled is False
    assert settings.coding_artifacts_enabled is False
    assert settings.coding_permission_models_enabled is False


def test_v070_flag_dependency_validation():
    """编码 flag 依赖 project-bound；单独开启必须失败。"""
    from personal_assistant.config import Settings

    with pytest.raises(ValueError, match="PA_CODING_PATCHSET_ENABLED"):
        Settings(_env_file=None, project_bound_runs_enabled=False, coding_patchset_enabled=True)
    with pytest.raises(ValueError, match="PA_CODING_COMMAND_PROFILES_ENABLED"):
        Settings(
            _env_file=None,
            project_bound_runs_enabled=False,
            coding_command_profiles_enabled=True,
        )
    with pytest.raises(ValueError, match="PA_CODING_ARTIFACTS_ENABLED"):
        Settings(
            _env_file=None,
            project_bound_runs_enabled=False,
            coding_artifacts_enabled=True,
        )
    # project-bound 开启时允许
    ok = Settings(
        _env_file=None,
        project_bound_runs_enabled=True,
        coding_patchset_enabled=True,
    )
    assert ok.coding_patchset_enabled is True


# ===========================================================================
# E2–E4 实现后移除 xfail（strict=True：实现后忘记移除会失败提醒）
# ===========================================================================

# E4 已实现：以下两个契约测试解除 xfail（实现细节见 tests/test_v070_permissions.py
# 的对应完整用例，此处保留 E0 契约级断言）。


async def test_no_native_tool_calls_model_rejected_for_coding(
    client, monkeypatch, tmp_path
):
    """不支持原生工具调用的模型 profile 不能进入 Coding 执行循环。

    E0 契约 §5：native_tool_calls=False → 422 model_profile_unsupported。
    """
    from test_v070_permissions import _create_coding_env, _post_coding_run

    from personal_assistant.api import routes_agent_runs
    from personal_assistant.config import settings as cfg

    monkeypatch.setattr(cfg, "coding_permission_models_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    await client.put(
        "/agent-model-profiles/qa-only",
        json={
            "provider": "ollama",
            "display_name": "QA only",
            "native_tool_calls": False,
        },
    )
    resp = await _post_coding_run(client, env, model_profile_id="qa-only")
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "model_profile_unsupported"


async def test_legacy_permission_modes_rejected(client, monkeypatch, tmp_path):
    """read_only / full_access 创建 coding run → 422 permission_mode_invalid。"""
    from test_v070_permissions import _create_coding_env, _post_coding_run

    from personal_assistant.api import routes_agent_runs

    monkeypatch.setattr(routes_agent_runs.cfg, "agent_runs_api_enabled", True)
    monkeypatch.setattr(routes_agent_runs.cfg, "project_bound_runs_enabled", True)
    env = await _create_coding_env(client, tmp_path)
    for legacy in ("read_only", "full_access"):
        resp = await _post_coding_run(client, env, permission_mode=legacy)
        assert resp.status_code == 422, resp.text
        assert resp.json()["error_code"] == "permission_mode_invalid"
