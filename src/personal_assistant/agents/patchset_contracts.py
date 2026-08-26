"""v0.7.0 E0：PatchSet 契约冻结（纯数据，不含 executor）。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §2。

本模块是 PatchSet 工具（``propose_patch_set`` / ``apply_patch_set``）
input/output Schema、硬上限、状态集合与事件 payload 的唯一事实源；
实现（E1）与测试都引用本模块，任何字段改动必须先更新契约文档与
``tests/test_v070_coding_contracts.py`` 再改实现。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# === feature flag 环境变量名（E0 §8） ===
PATCHSET_FLAG_ENV = "PA_CODING_PATCHSET_ENABLED"
COMMAND_PROFILES_FLAG_ENV = "PA_CODING_COMMAND_PROFILES_ENABLED"
ARTIFACTS_FLAG_ENV = "PA_CODING_ARTIFACTS_ENABLED"
PERMISSION_MODELS_FLAG_ENV = "PA_CODING_PERMISSION_MODELS_ENABLED"

# === 硬上限（E0 §2.2） ===
MAX_PATCHSET_FILES = 32
MAX_SINGLE_FILE_BYTES = 500 * 1024
MAX_TOTAL_INPUT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_DIFF_BYTES = 2 * 1024 * 1024
MAX_OPERATION_COUNT = 32
MAX_REL_PATH_LEN = 2048

# === 状态集合（E0 §2.4） ===
PATCHSET_STATUSES = frozenset(
    {"previewed", "applied", "failed", "rolled_back", "partial_unknown", "rejected"}
)
PATCHSET_FILE_STATUSES = frozenset({"pending", "applied", "rolled_back", "unknown"})
PATCHSET_OPERATIONS = frozenset({"create", "update", "delete", "rename"})
# 风险高于普通 update：workspace 模式仍需要确认（E0 §4.1）
HIGH_RISK_OPERATIONS = frozenset({"delete", "rename"})

_SHA256_PATTERN = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
# Git HEAD 快照：SHA-1（40 位）或未来 SHA-256（64 位）十六进制（T4 漂移检测用）
_GIT_HEAD_PATTERN = {"type": "string", "pattern": "^[0-9a-f]{40,64}$"}
_PATH_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_REL_PATH_LEN,
    "description": "workspace 内规范化相对路径；拒绝绝对路径、..、设备路径与链接逃逸",
}
_RAW_FILE_CONTENT_DESCRIPTION = (
    "原始完整文件内容；不要使用 Markdown 代码围栏或二次 JSON 转义"
)

# === 操作项（create/update/delete/rename 共用基础字段） ===
_OPERATION_BASE = {
    "type": "object",
    "properties": {
        "path": _PATH_SCHEMA,
        "old_path": _PATH_SCHEMA,
        "new_path": _PATH_SCHEMA,
        "expected_old_sha256": _SHA256_PATTERN,
        "new_content": {
            "type": "string",
            "maxLength": MAX_SINGLE_FILE_BYTES,
            "description": _RAW_FILE_CONTENT_DESCRIPTION,
        },
    },
    "additionalProperties": False,
}

_CREATE_OP = {
    **_OPERATION_BASE,
    "required": ["path", "new_content"],
    "properties": {
        "path": _PATH_SCHEMA,
        "new_content": {
            "type": "string",
            "maxLength": MAX_SINGLE_FILE_BYTES,
            "description": _RAW_FILE_CONTENT_DESCRIPTION,
        },
    },
}
_UPDATE_OP = {
    **_OPERATION_BASE,
    "required": ["path", "expected_old_sha256", "new_content"],
    "properties": {
        "path": _PATH_SCHEMA,
        "expected_old_sha256": _SHA256_PATTERN,
        "new_content": {
            "type": "string",
            "maxLength": MAX_SINGLE_FILE_BYTES,
            "description": _RAW_FILE_CONTENT_DESCRIPTION,
        },
    },
}
_DELETE_OP = {
    **_OPERATION_BASE,
    "required": ["path", "expected_old_sha256"],
    "properties": {
        "path": _PATH_SCHEMA,
        "expected_old_sha256": _SHA256_PATTERN,
    },
}
_RENAME_OP = {
    **_OPERATION_BASE,
    "required": ["old_path", "new_path", "expected_old_sha256"],
    "properties": {
        "old_path": _PATH_SCHEMA,
        "new_path": _PATH_SCHEMA,
        "expected_old_sha256": _SHA256_PATTERN,
        "new_content": {
            "type": "string",
            "maxLength": MAX_SINGLE_FILE_BYTES,
            "description": f"可选：rename 同时改写内容；{_RAW_FILE_CONTENT_DESCRIPTION}",
        },
    },
}

_OPERATIONS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_OPERATION_COUNT,
    "items": {
        "type": "object",
        "properties": {
            "operation": {"enum": sorted(PATCHSET_OPERATIONS)},
            "create": _CREATE_OP,
            "update": _UPDATE_OP,
            "delete": _DELETE_OP,
            "rename": _RENAME_OP,
        },
        "required": ["operation"],
        "additionalProperties": False,
        "oneOf": [
            {
                "properties": {"operation": {"const": "create"}, "create": _CREATE_OP},
                "required": ["create"],
            },
            {
                "properties": {"operation": {"const": "update"}, "update": _UPDATE_OP},
                "required": ["update"],
            },
            {
                "properties": {"operation": {"const": "delete"}, "delete": _DELETE_OP},
                "required": ["delete"],
            },
            {
                "properties": {"operation": {"const": "rename"}, "rename": _RENAME_OP},
                "required": ["rename"],
            },
        ],
    },
}

# === propose_patch_set 输入（模型可见字段） ===
PROPOSE_PATCH_SET_INPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "operations": _OPERATIONS_SCHEMA,
    },
    "required": ["operations"],
    "additionalProperties": False,
}

# === apply_patch_set 输入 ===
APPLY_PATCH_SET_INPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "patch_set_id": {"type": "string", "minLength": 1, "maxLength": 36},
        "preview_version": {"type": "integer", "minimum": 1},
        "expected_parameters_hash": _SHA256_PATTERN,
    },
    "required": ["patch_set_id", "preview_version", "expected_parameters_hash"],
    "additionalProperties": False,
}

# === 预览输出 ===
PATCH_SET_FILE_PREVIEW = {
    "type": "object",
    "properties": {
        "operation": {"enum": sorted(PATCHSET_OPERATIONS)},
        "path": {"type": "string"},
        "new_path": {"type": "string"},
        "old_sha256": _SHA256_PATTERN,
        "new_sha256": _SHA256_PATTERN,
        "diff_text": {"type": "string"},
        "truncated": {"type": "boolean"},
    },
    "required": ["operation", "path", "diff_text", "truncated"],
    "additionalProperties": False,
}

PROPOSE_PATCH_SET_OUTPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "patch_set_id": {"type": "string", "minLength": 1, "maxLength": 36},
        "preview_version": {"type": "integer", "minimum": 1},
        "base_head_sha": _GIT_HEAD_PATTERN,
        "parameters_hash": _SHA256_PATTERN,
        "truncated": {"type": "boolean"},
        "file_count": {"type": "integer", "minimum": 0},
        "additions": {"type": "integer", "minimum": 0},
        "deletions": {"type": "integer", "minimum": 0},
        "diff_total_bytes": {"type": "integer", "minimum": 0},
        "files": {
            "type": "array",
            "items": PATCH_SET_FILE_PREVIEW,
        },
    },
    "required": [
        "patch_set_id",
        "preview_version",
        "parameters_hash",
        "truncated",
        "file_count",
        "additions",
        "deletions",
        "diff_total_bytes",
        "files",
    ],
    "additionalProperties": False,
}

# === apply_patch_set 输出 ===
APPLY_PATCH_SET_OUTPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "patch_set_id": {"type": "string", "minLength": 1, "maxLength": 36},
        "preview_version": {"type": "integer", "minimum": 1},
        "status": {"enum": sorted(PATCHSET_STATUSES)},
        "verified": {"type": "boolean"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "operation": {"enum": sorted(PATCHSET_OPERATIONS)},
                    "old_sha256": _SHA256_PATTERN,
                    "new_sha256": _SHA256_PATTERN,
                    "status": {"enum": sorted(PATCHSET_FILE_STATUSES)},
                },
                "required": ["path", "operation", "status"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["patch_set_id", "preview_version", "status", "verified", "files"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class PatchSetToolContract:
    """一份冻结的 v0.7.0 PatchSet 工具契约（纯数据，不含 executor）。"""

    name: str
    version: str
    flag_env: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    risk_level: str
    required_capabilities: frozenset[str]
    timeout_ms: int
    max_input_bytes: int
    max_output_bytes: int
    idempotency: str
    supports_cancellation: bool


PATCHSET_TOOL_CONTRACTS: tuple[PatchSetToolContract, ...] = (
    PatchSetToolContract(
        name="propose_patch_set",
        version="1.0.0",
        flag_env=PATCHSET_FLAG_ENV,
        description=(
            "为当前 coding run 的 workspace 生成多文件 PatchSet 预览；"
            "只读零写入，返回参数哈希与预览版本供 apply 时强校验；需要落盘时，"
            "预览成功后必须继续调用 apply_patch_set。"
        ),
        input_schema=PROPOSE_PATCH_SET_INPUT,
        output_schema=PROPOSE_PATCH_SET_OUTPUT,
        risk_level="safe",
        required_capabilities=frozenset({"filesystem_read"}),
        timeout_ms=30_000,
        max_input_bytes=5 * 1024 * 1024,
        max_output_bytes=2 * 1024 * 1024,
        idempotency="idempotent",
        supports_cancellation=False,
    ),
    PatchSetToolContract(
        name="apply_patch_set",
        version="1.0.0",
        flag_env=PATCHSET_FLAG_ENV,
        description=(
            "审批后原子应用已预览的多文件 PatchSet；冲突或回读不一致一律"
            "回滚失败关闭，无法完整回滚时标记 partial_unknown 并阻止自动续跑。"
        ),
        input_schema=APPLY_PATCH_SET_INPUT,
        output_schema=APPLY_PATCH_SET_OUTPUT,
        risk_level="confirm",
        required_capabilities=frozenset({"filesystem_read", "filesystem_write"}),
        timeout_ms=60_000,
        max_input_bytes=1 * 1024 * 1024,
        max_output_bytes=512 * 1024,
        idempotency="non_idempotent",
        supports_cancellation=False,
    ),
)

PATCHSET_CONTRACT_BY_NAME: Mapping[str, PatchSetToolContract] = {
    contract.name: contract for contract in PATCHSET_TOOL_CONTRACTS
}

# === 新增 durable 事件 payload 规格（E0 §1） ===
PATCHSET_EVENT_PAYLOADS: Mapping[str, frozenset[str]] = {
    "patch_set.preview_created": frozenset(
        {"patch_set_id", "preview_version", "file_count", "truncated", "base_head_sha"}
    ),
    "patch_set.applied": frozenset({"patch_set_id", "preview_version", "verified"}),
    "patch_set.rolled_back": frozenset({"patch_set_id", "reason"}),
    "patch_set.failed": frozenset({"patch_set_id", "error_code", "error_message"}),
    "patch_set.unknown": frozenset({"patch_set_id", "reason"}),
}
