"""v0.6.0 Coding Agent 错误码（冻结于 C0 契约 §9）。

v0.7.0 E0 §2/§6 与 v0.9.0 H0 §6.4 additive 扩展。
所有错误响应不得包含本地绝对路径；详细路径仅可进入受控诊断包并脱敏。
"""

from __future__ import annotations

# HTTP 状态码与错误码映射（C0 §9；v0.7.0 E0 §2/§6 扩展）
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
    # v0.7.0 E0：PatchSet / 命令 profile / 模型 profile / 权限 / Artifact / 完成条件
    "patchset_invalid": 422,
    "patchset_conflict": 409,
    "patchset_not_found": 404,
    "patchset_preview_stale": 409,
    "patchset_truncated": 422,
    "patchset_partial_unknown": 409,
    "command_profile_invalid": 422,
    "command_profile_not_found": 404,
    "command_profile_version_conflict": 409,
    "model_profile_not_found": 404,
    "model_profile_unsupported": 422,
    "permission_mode_invalid": 422,
    "permission_denied": 403,
    "artifact_kind_invalid": 422,
    "completion_conditions_unmet": 409,
    # v0.9.0 H0 §6.4：full_access 独立 capability / 上下文预算 / 会话绑定（additive）
    "full_access_unsupported": 409,
    "full_access_grant_expired": 409,
    "full_access_revoked": 409,
    "budget_exceeded": 409,
    "session_bind_conflict": 409,
    # v0.9.0 H3：worktree 生命周期（计划 §4）
    "worktree_branch_invalid": 422,
    "worktree_path_invalid": 422,
    "worktree_ref_invalid": 422,
    "worktree_create_failed": 409,
    "worktree_remove_failed": 409,
    "worktree_dirty": 409,
    "worktree_not_git": 409,
}

# 运行状态限定集合（C0 §4.3 与 §4.1；v0.9.0 H3 扩展 worktree 生命周期态）
WORKSPACE_STATUSES = frozenset(
    {
        "active",
        "missing",
        "dirty",
        "archived",
        "conflict",
        "creating",
        "cleanup_pending",
    }
)
# runnable 状态：创建 run 时允许的 workspace 状态
RUNNABLE_WORKSPACE_STATUSES = frozenset({"active", "dirty"})

PLAN_ITEM_STATUSES = frozenset(
    {"pending", "in_progress", "completed", "blocked", "failed", "cancelled"}
)

# 权限模式 allowlist（v0.9.0 H0 §6.1：full_access 作为独立能力重新引入，
# 具备授予/撤销/到期/审计真实语义，不是 workspace 别名；
# readonly/confirm/workspace 语义保持 v0.7.0 冻结）
PERMISSION_MODES = frozenset({"readonly", "confirm", "workspace", "full_access"})

# 合法 item_key 模式（C0 §7.1）
ITEM_KEY_PATTERN = r"[a-z0-9][a-z0-9_-]{0,127}"

# 稳定事件（C0 §4.5；v0.7.0 E0 §1 patch_set.*；v0.9.0 H0 §7.2/§8 新增）
STABLE_EVENTS = frozenset(
    {
        "plan.created",
        "plan.updated",
        "plan.item_changed",
        "artifact.created",
        "patch_set.preview_created",
        "patch_set.applied",
        "patch_set.rolled_back",
        "patch_set.failed",
        "patch_set.unknown",
        # v0.9.0 H0：公开决策摘要（不含隐藏 chain-of-thought）与上下文压缩事件；
        # permission.downgraded 记录能力异常时降级到 confirm 的低基数原因。
        "decision.summary",
        "context.compaction_started",
        "context.compaction_completed",
        "context.compaction_failed",
        "permission.downgraded",
    }
)


def http_status_for(error_code: str) -> int:
    return ERROR_CODES.get(error_code, 409)
