"""§7.7 公开错误码冻结注册表（专项计划 v1.0.0 Codex 工具体系融合）。

所有"缺失工具、模型不支持、策略拒绝、健康失败、执行未知或证据不足"
的公开失败都必须命中本表中的稳定码；不得以自由文本或堆栈替代。

错误信封要求（§7.7）：稳定 code + 可读 message + 是否可重试 + 建议操作
+ 关联 ID；不得向用户返回堆栈、secret 或内部绝对敏感路径。
"""

from __future__ import annotations

from enum import StrEnum


class ToolErrorCode(StrEnum):
    """§7.7 P0 新增/统一的公开错误码（冻结集合，新增须走协议评审）。"""

    #: 本轮没有任何可提供必需 effect 的已暴露工具（F-002）。
    TOOL_CAPABILITY_UNAVAILABLE = "tool_capability_unavailable"
    #: 当前模型不支持本轮工具协议（能力探测/评测未通过，§8.3）。
    TOOL_MODEL_UNSUPPORTED = "tool_model_unsupported"
    #: 工具被策略隐藏/拒绝：调用不可达（不暴露、不授权、不执行）。
    TOOL_HIDDEN_BY_POLICY = "tool_hidden_by_policy"
    #: 工具健康检查/目录新鲜度失败（§12.1 失败关闭）。
    TOOL_HEALTH_FAILED = "tool_health_failed"
    #: Provider 可见名/注册键冲突，模型调用前拒绝（§7.1/§9.1）。
    TOOL_NAME_COLLISION = "tool_name_collision"
    #: Turn 运行中工具面变化（MCP 断开/健康变化）——显式失效，不静默换工具（§7.2）。
    TOOL_PLAN_INVALIDATED = "tool_plan_invalidated"
    #: 零执行证据却宣称完成（F-003）。
    REQUIRED_EFFECT_MISSING = "required_effect_missing"
    #: 完成契约未满足（或契约自定义 failure_message_code）。
    COMPLETION_NOT_MET = "completion_not_met"
    #: 必需副作用已执行但回读证据不成立（F-007）。
    SIDE_EFFECT_UNVERIFIED = "side_effect_unverified"
    #: 执行器离线/不可用（Exec Host 失败关闭）。
    EXECUTOR_UNAVAILABLE = "executor_unavailable"
    #: 沙箱策略不可用（§11.5 失败关闭，零降级）。
    SANDBOX_POLICY_UNAVAILABLE = "sandbox_policy_unavailable"
    #: 非幂等执行状态无法确定（§13.3：不自动重试、不伪装完成）。
    EXECUTION_STATE_UNKNOWN = "execution_state_unknown"
    #: Deferred Tool Search 无匹配（§9.3）。
    TOOL_SEARCH_NO_MATCH = "tool_search_no_match"


#: §7.7 冻结集合完整性（测试锚定）。
FROZEN_ERROR_CODES: frozenset[str] = frozenset(code.value for code in ToolErrorCode)
