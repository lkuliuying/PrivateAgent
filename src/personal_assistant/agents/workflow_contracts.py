"""v0.5.0 可信工作流契约表（B0 冻结）。

五类工作流工具的名称、版本、input/output Schema、risk、capability、
幂等策略、必需结果验证器与独立 feature flag 在此单一模块冻结，作为
Patch / 命令 / HTTP / SQL 适配（B1–B4）与桌面 UI 消费的唯一事实源。

变更规则：
- 任何字段改动必须先更新 ``tests/test_workflow_contracts.py`` 与
  ``docs/v0.5.0-b0-contracts-20260809.md``；
- 不新增开启多类工作流的总开关，一类高风险能力只能借用自己类别的 flag；
- 高风险工具默认关闭（flag 默认 False，见 ``config.Settings``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Mapping

from .tools import (
    ToolCapability,
    ToolIdempotency,
    ToolRedactionPolicy,
    ToolRiskLevel,
)

__all__ = [
    "COMMAND_WORKFLOW_FLAG_ENV",
    "HTTP_WORKFLOW_FLAG_ENV",
    "NEW_WORKFLOW_FLAG_ENV_VARS",
    "PATCH_WORKFLOW_FLAG_ENV",
    "SQL_READONLY_WORKFLOW_FLAG_ENV",
    "WORKFLOW_CONTRACT_BY_NAME",
    "WORKFLOW_KIND_BY_FLAG_ENV",
    "WORKFLOW_TOOL_CONTRACTS",
    "ResultVerifierKind",
    "WorkflowKind",
    "WorkflowToolContract",
]


class WorkflowKind(StrEnum):
    """四类新增可信工作流；``propose_patch`` 归属 PATCH 但由既有只读开关控制。"""

    PATCH = "patch"
    COMMAND = "command"
    HTTP = "http"
    SQL = "sql"


ResultVerifierKind = Literal[
    "file_diff",
    "shell",
    "code_command",
    "api",
    "database",
    "workflow_completion",
]

# === 独立 feature flag 环境变量名（冻结） ===
PATCH_WORKFLOW_FLAG_ENV = "PA_AGENT_PATCH_WORKFLOW_ENABLED"
COMMAND_WORKFLOW_FLAG_ENV = "PA_AGENT_COMMAND_WORKFLOW_ENABLED"
HTTP_WORKFLOW_FLAG_ENV = "PA_AGENT_HTTP_WORKFLOW_ENABLED"
SQL_READONLY_WORKFLOW_FLAG_ENV = "PA_AGENT_SQL_READONLY_WORKFLOW_ENABLED"
# propose_patch 继续由既有只读工具开关控制（plan §5 既有开关）。
_READ_ONLY_TOOLS_FLAG_ENV = "PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED"

NEW_WORKFLOW_FLAG_ENV_VARS = frozenset(
    {
        PATCH_WORKFLOW_FLAG_ENV,
        COMMAND_WORKFLOW_FLAG_ENV,
        HTTP_WORKFLOW_FLAG_ENV,
        SQL_READONLY_WORKFLOW_FLAG_ENV,
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowToolContract:
    """一份冻结的 v0.5.0 工作流工具契约（纯数据，不含 executor）。"""

    name: str
    version: str
    kind: WorkflowKind
    flag_env: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    risk_level: ToolRiskLevel
    required_capabilities: frozenset[ToolCapability]
    timeout_ms: int
    max_input_bytes: int
    max_output_bytes: int
    idempotency: ToolIdempotency
    supports_cancellation: bool
    redaction_policy: ToolRedactionPolicy
    required_result_verifiers: tuple[ResultVerifierKind, ...]


_SHA256_PATTERN = {"type": "string", "pattern": "^[0-9a-f]{64}$"}

# === propose_patch（既有只读工具，B0 一并冻结） ===
_PROPOSE_PATCH_INPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {
            "type": "integer",
            "minimum": 1,
            "description": "已授权项目 ID",
        },
        "rel_path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2048,
            "description": "项目内相对路径",
        },
        "new_content": {
            "type": "string",
            "maxLength": 500000,
            "description": "拟写入的完整新文件内容",
        },
        "create": {"type": "boolean", "description": "文件不存在时是否按新文件预览"},
    },
    "required": ["project_id", "rel_path", "new_content"],
    "additionalProperties": False,
}

_PROPOSE_PATCH_OUTPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {"type": "integer", "minimum": 1},
        "rel_path": {"type": "string", "maxLength": 2048},
        "diff": {"type": "string", "maxLength": 200020},
        "old_sha256": _SHA256_PATTERN,
        "new_sha256": _SHA256_PATTERN,
        "creates_file": {"type": "boolean"},
        "changed": {"type": "boolean"},
        "truncated": {"type": "boolean"},
    },
    "required": [
        "project_id",
        "rel_path",
        "diff",
        "old_sha256",
        "new_sha256",
        "creates_file",
        "changed",
        "truncated",
    ],
    "additionalProperties": False,
}

# === apply_patch_to_workspace（B1 迁入 versioned registry） ===
# 相比 legacy 收紧：rel_path 限长、expected_old_sha256 必须为 64 位十六进制、
# new_content 上限与预览一致、输出强制回读验证标志 verified。
_APPLY_PATCH_INPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {
            "type": "integer",
            "minimum": 1,
            "description": "已授权项目 ID",
        },
        "rel_path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2048,
            "description": "项目内相对路径；拒绝绝对路径、.. 与符号链接/重解析点越界",
        },
        "new_content": {
            "type": "string",
            "maxLength": 500000,
            "description": "拟写入的完整新文件内容",
        },
        "expected_old_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "description": "预览返回的旧内容 SHA-256；不匹配时拒绝应用过期补丁",
        },
        "create": {"type": "boolean", "description": "是否允许创建新文件"},
    },
    "required": ["project_id", "rel_path", "new_content"],
    "additionalProperties": False,
}

_APPLY_PATCH_OUTPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {"type": "integer", "minimum": 1},
        "rel_path": {"type": "string", "maxLength": 2048},
        "old_sha256": _SHA256_PATTERN,
        "new_sha256": _SHA256_PATTERN,
        "size_bytes": {"type": "integer", "minimum": 0},
        "diff": {"type": "string", "maxLength": 200020},
        "truncated": {"type": "boolean"},
        "verified": {
            "type": "boolean",
            "description": "写入后回读磁盘并核对 new_sha256 的结果",
        },
    },
    "required": [
        "project_id",
        "rel_path",
        "old_sha256",
        "new_sha256",
        "size_bytes",
        "truncated",
        "verified",
    ],
    "additionalProperties": False,
}

# === run_whitelisted_command（B2 迁入 versioned registry） ===
# 相比 legacy 收紧：command 只接受参数数组（不经 shell），拒绝 shell 控制符。
_RUN_COMMAND_INPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {
            "type": "integer",
            "minimum": 1,
            "description": "已授权项目 ID",
        },
        "command": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
            "minItems": 1,
            "maxItems": 64,
            "description": "固定参数数组；不经 shell，拒绝管道/重定向/变量展开/命令替换",
        },
        "timeout": {
            "type": "number",
            "minimum": 1,
            "maximum": 120,
            "description": "超时秒数，上限 120 秒",
        },
    },
    "required": ["project_id", "command"],
    "additionalProperties": False,
}

_RUN_COMMAND_OUTPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {"type": "integer", "minimum": 1},
        "args": {"type": "array", "items": {"type": "string"}},
        "cwd": {"type": "string"},
        "returncode": {"type": "integer"},
        "stdout": {"type": "string", "maxLength": 524288},
        "stderr": {"type": "string", "maxLength": 524288},
        "output": {"type": "string", "maxLength": 524288},
        "truncated": {"type": "boolean"},
        "succeeded": {"type": "boolean"},
        "cancelled": {
            "type": "boolean",
            "description": "是否被用户取消或超时终止（进程树已清理）",
        },
        "processes_remaining": {
            "type": "integer",
            "minimum": 0,
            "description": "取消/超时后仍残留的子进程数（0 表示清理完成）",
        },
        "profile": {
            "type": "string",
            "description": "匹配的项目 command profile 名称（未匹配时省略；B2 additive）",
        },
    },
    "required": [
        "project_id",
        "args",
        "cwd",
        "returncode",
        "output",
        "truncated",
        "succeeded",
    ],
    "additionalProperties": False,
}

# === call_allowlisted_api（B3 接入；executor 与 profile 尚不存在） ===
_CALL_API_INPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "profile_id": {
            "type": "integer",
            "minimum": 1,
            "description": "已启用 endpoint profile ID；模型不能提供任意 URL",
        },
        "method": {
            "enum": ["GET", "HEAD", "POST"],
            "description": "v0.5.0 仅开放 GET/HEAD/POST；PUT/PATCH/DELETE 不开放",
        },
        "path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "description": "profile path 前缀下的相对路径",
        },
        "query_params": {
            "type": "object",
            "maxProperties": 64,
            "additionalProperties": {"type": "string", "maxLength": 4096},
            "description": "可选的查询参数",
        },
        "body": {
            "type": "object",
            "description": "POST 请求体，按 profile 固定 Schema 校验",
        },
        "idempotency_key": {
            "type": "string",
            "minLength": 8,
            "maxLength": 256,
            "description": "POST 必填（契约校验）；GET/HEAD 可省略",
        },
    },
    "required": ["profile_id", "method", "path"],
    "additionalProperties": False,
}

_CALL_API_OUTPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "profile_id": {"type": "integer", "minimum": 1},
        "method": {"type": "string"},
        "path": {"type": "string"},
        "status_code": {"type": "integer", "minimum": 100, "maximum": 599},
        "headers": {
            "type": "object",
            "description": "已脱敏的非敏感响应头子集",
        },
        "body": {
            "type": ["object", "array", "string", "number", "boolean", "null"],
            "description": "有界响应体",
        },
        "truncated": {"type": "boolean"},
        "schema_valid": {"type": "boolean"},
        "elapsed_ms": {"type": "integer", "minimum": 0},
        "attempts": {"type": "integer", "minimum": 1},
        "idempotency_replayed": {"type": "boolean"},
    },
    "required": [
        "profile_id",
        "method",
        "path",
        "status_code",
        "body",
        "truncated",
        "schema_valid",
        "elapsed_ms",
        "attempts",
    ],
    "additionalProperties": False,
}

# === query_readonly_sql（B4 接入；executor 与 profile 尚不存在） ===
_QUERY_SQL_INPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "profile_id": {
            "type": "integer",
            "minimum": 1,
            "description": "已启用只读连接 profile ID；模型不能提供 DSN/用户名/密码",
        },
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": 65536,
            "description": "单条只读 SQL（SELECT/EXPLAIN/SHOW）；拒绝多语句与写语句",
        },
        "params": {
            "type": "object",
            "maxProperties": 256,
            "additionalProperties": {
                "type": ["string", "number", "boolean", "null"]
            },
            "description": "可选绑定参数",
        },
        "max_rows": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10000,
            "description": "返回行数上限",
        },
        "timeout_ms": {
            "type": "integer",
            "minimum": 100,
            "maximum": 30000,
            "description": "查询超时（毫秒）",
        },
    },
    "required": ["profile_id", "query"],
    "additionalProperties": False,
}

_QUERY_SQL_OUTPUT: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "profile_id": {"type": "integer", "minimum": 1},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {
            "type": "array",
            "items": {
                "type": "array",
                "description": "行数据，已限长并隐藏疑似秘密列",
            },
        },
        "row_count": {"type": "integer", "minimum": 0},
        "truncated": {"type": "boolean"},
        "elapsed_ms": {"type": "integer", "minimum": 0},
        "read_only_confirmed": {
            "type": "boolean",
            "description": "执行路径确认为只读事务/单语句的结果",
        },
        "message": {"type": "string", "description": "EXPLAIN/SHOW 等文本结果"},
    },
    "required": [
        "profile_id",
        "columns",
        "rows",
        "row_count",
        "truncated",
        "elapsed_ms",
        "read_only_confirmed",
    ],
    "additionalProperties": False,
}

WORKFLOW_TOOL_CONTRACTS: tuple[WorkflowToolContract, ...] = (
    WorkflowToolContract(
        name="propose_patch",
        version="1.0.0",
        kind=WorkflowKind.PATCH,
        flag_env=_READ_ONLY_TOOLS_FLAG_ENV,
        description="为已授权项目中的单个文件生成替换式 unified diff 预览；只读，不写入文件。",
        input_schema=_PROPOSE_PATCH_INPUT,
        output_schema=_PROPOSE_PATCH_OUTPUT,
        risk_level=ToolRiskLevel.SAFE,
        required_capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
        timeout_ms=20_000,
        max_input_bytes=512 * 1024,
        max_output_bytes=512 * 1024,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=False,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        required_result_verifiers=("file_diff",),
    ),
    WorkflowToolContract(
        name="apply_patch_to_workspace",
        version="1.0.0",
        kind=WorkflowKind.PATCH,
        flag_env=PATCH_WORKFLOW_FLAG_ENV,
        description="审批后把已预览内容原子写入已授权项目文件，写入后回读核对新 SHA；冲突或回读不一致一律失败关闭。",
        input_schema=_APPLY_PATCH_INPUT,
        output_schema=_APPLY_PATCH_OUTPUT,
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset(
            {ToolCapability.FILESYSTEM_READ, ToolCapability.FILESYSTEM_WRITE}
        ),
        timeout_ms=30_000,
        max_input_bytes=600 * 1024,
        max_output_bytes=512 * 1024,
        idempotency=ToolIdempotency.NON_IDEMPOTENT,
        supports_cancellation=False,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        required_result_verifiers=("file_diff",),
    ),
    WorkflowToolContract(
        name="run_whitelisted_command",
        version="1.0.0",
        kind=WorkflowKind.COMMAND,
        flag_env=COMMAND_WORKFLOW_FLAG_ENV,
        description="审批后在已授权项目根目录运行固定白名单命令（参数数组，不经 shell），支持超时、取消与进程树清理。",
        input_schema=_RUN_COMMAND_INPUT,
        output_schema=_RUN_COMMAND_OUTPUT,
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset(
            {ToolCapability.PROCESS_EXECUTE, ToolCapability.FILESYSTEM_READ}
        ),
        timeout_ms=120_000,
        max_input_bytes=128 * 1024,
        max_output_bytes=512 * 1024,
        idempotency=ToolIdempotency.NON_IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        required_result_verifiers=("shell", "code_command"),
    ),
    WorkflowToolContract(
        name="call_allowlisted_api",
        version="1.0.0",
        kind=WorkflowKind.HTTP,
        flag_env=HTTP_WORKFLOW_FLAG_ENV,
        description="按已启用 endpoint profile 调用固定 HTTPS 目标（DNS 钉住、禁私网/重定向/代理），GET/HEAD 可重试，POST 必须携带幂等键。",
        input_schema=_CALL_API_INPUT,
        output_schema=_CALL_API_OUTPUT,
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset({ToolCapability.NETWORK_FETCH}),
        timeout_ms=60_000,
        max_input_bytes=256 * 1024,
        max_output_bytes=1024 * 1024,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        required_result_verifiers=("api",),
    ),
    WorkflowToolContract(
        name="query_readonly_sql",
        version="1.0.0",
        kind=WorkflowKind.SQL,
        flag_env=SQL_READONLY_WORKFLOW_FLAG_ENV,
        description="按已启用只读连接 profile 执行单条只读 SQL（SELECT/EXPLAIN/SHOW），只读事务 + 解析策略双重限制，超时/行数/字节均有上限。",
        input_schema=_QUERY_SQL_INPUT,
        output_schema=_QUERY_SQL_OUTPUT,
        risk_level=ToolRiskLevel.CONFIRM,
        required_capabilities=frozenset({ToolCapability.DATABASE_QUERY}),
        timeout_ms=30_000,
        max_input_bytes=128 * 1024,
        max_output_bytes=1024 * 1024,
        idempotency=ToolIdempotency.IDEMPOTENT,
        supports_cancellation=True,
        redaction_policy=ToolRedactionPolicy.SENSITIVE_KEYS,
        required_result_verifiers=("database",),
    ),
)

WORKFLOW_CONTRACT_BY_NAME: Mapping[str, WorkflowToolContract] = {
    contract.name: contract for contract in WORKFLOW_TOOL_CONTRACTS
}

WORKFLOW_KIND_BY_FLAG_ENV: Mapping[str, WorkflowKind] = {
    contract.flag_env: contract.kind
    for contract in WORKFLOW_TOOL_CONTRACTS
    if contract.flag_env in NEW_WORKFLOW_FLAG_ENV_VARS
}
