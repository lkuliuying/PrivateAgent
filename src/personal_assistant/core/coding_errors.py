"""v0.6.0 Coding Agent 错误码（冻结于 C0 契约 §9）。

所有错误响应不得包含本地绝对路径；详细路径仅可进入受控诊断包并脱敏。
"""

from __future__ import annotations

# HTTP 状态码与错误码映射（C0 §9）
ERROR_CODES: dict[str, int] = {
    "coding_context_incomplete": 422,
    "coding_mode_disabled": 409,
    "session_not_coding": 409,
    "session_workspace_mismatch": 409,
    "workspace_not_found": 404,
    "workspace_unavailable": 409,
    "workspace_outside_trust": 403,
    "workspace_path_changed": 409,
    "git_snapshot_failed": 409,
    "client_request_conflict": 409,
    "plan_version_conflict": 409,
    "plan_transition_invalid": 422,
    "event_sequence_conflict": 500,
}

# 运行状态限定集合（C0 §4.3 与 §4.1）
WORKSPACE_STATUSES = frozenset(
    {"active", "missing", "dirty", "archived", "conflict"}
)
# runnable 状态：创建 run 时允许的 workspace 状态
RUNNABLE_WORKSPACE_STATUSES = frozenset({"active", "dirty"})

PLAN_ITEM_STATUSES = frozenset(
    {"pending", "in_progress", "completed", "blocked", "failed", "cancelled"}
)

# 权限模式 allowlist（C0-D07）
PERMISSION_MODES = frozenset({"read_only", "confirm", "full_access"})

# 合法 item_key 模式（C0 §7.1）
ITEM_KEY_PATTERN = r"[a-z0-9][a-z0-9_-]{0,127}"

# 稳定事件（C0 §4.5）
STABLE_EVENTS = frozenset(
    {
        "plan.created",
        "plan.updated",
        "plan.item_changed",
        "artifact.created",
    }
)


def http_status_for(error_code: str) -> int:
    return ERROR_CODES.get(error_code, 409)
