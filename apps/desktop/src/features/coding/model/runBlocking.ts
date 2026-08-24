/**
 * v0.9.0 H1-B（计划 §5.6）· run 创建阻塞项诊断
 *
 * 能力未就绪时不得创建假完成记录，也不得静默隐藏阻塞项：后端创建链的
 * 平铺 error_code（core/coding_errors.py）在这里映射为「阻塞项 + 原因 +
 * 可操作恢复入口」。纯函数，可单测；不含路径/命令正文等敏感内容。
 */

export type RunBlockerRecovery =
  | "configure-model"
  | "select-project"
  | "reauthorize"
  | "retry"
  | "none";

export interface RunBlockerFacts {
  /** 阻塞项（面向用户的简短标题） */
  title: string;
  /** 具体原因（与后端 detail 语义一致，不含敏感内容） */
  hint: string;
  /** 首选恢复动作（界面渲染按钮/入口） */
  recovery: RunBlockerRecovery;
  /** 恢复动作说明文案 */
  recoveryLabel: string;
}

const BLOCKERS: Record<string, RunBlockerFacts> = {
  coding_mode_disabled: {
    title: "Coding 执行能力未开启",
    hint: "Runtime 的 project-bound run 能力位未启用，无法创建执行。",
    recovery: "retry",
    recoveryLabel: "更新 Runtime 后重试",
  },
  coding_context_incomplete: {
    title: "项目/工作区信息不完整",
    hint: "project_id 与 workspace_id 必须同时提供；请重新选择项目后发起。",
    recovery: "select-project",
    recoveryLabel: "选择项目",
  },
  session_not_coding: {
    title: "会话类型不匹配",
    hint: "该会话不是 Coding 会话；请新建一个绑定项目的对话。",
    recovery: "select-project",
    recoveryLabel: "新建对话",
  },
  session_workspace_mismatch: {
    title: "会话绑定不一致",
    hint: "会话绑定的项目/工作区与请求不一致；请回到该会话所属项目。",
    recovery: "select-project",
    recoveryLabel: "选择项目",
  },
  permission_mode_invalid: {
    title: "权限模式无效",
    hint: "请求的权限模式不受支持；请重新选择总是询问/替我批准/完全访问。",
    recovery: "retry",
    recoveryLabel: "重新选择权限后重试",
  },
  full_access_unsupported: {
    title: "完全访问能力不可用",
    hint: "Runtime 未启用完全访问能力；请更新 Runtime 或改选其他权限模式。",
    recovery: "retry",
    recoveryLabel: "更新 Runtime 后重试",
  },
  full_access_revoked: {
    title: "完全访问已被撤销",
    hint: "当前会话的完全访问授予已撤销；重新发起并确认后可再次启用。",
    recovery: "retry",
    recoveryLabel: "重新发起",
  },
  full_access_grant_expired: {
    title: "完全访问已到期",
    hint: "完全访问授予已到期失效；重新发起并确认后可再次启用。",
    recovery: "retry",
    recoveryLabel: "重新发起",
  },
  model_profile_not_found: {
    title: "模型配置缺失",
    hint: "所选模型 profile 不存在；请配置 PrivateAgent 使用的模型。",
    recovery: "configure-model",
    recoveryLabel: "配置 PrivateAgent",
  },
  model_profile_unsupported: {
    title: "模型不满足执行要求",
    hint: "模型 profile 不支持原生工具调用或 Provider 未启用；请调整模型配置。",
    recovery: "configure-model",
    recoveryLabel: "配置 PrivateAgent",
  },
  workspace_not_found: {
    title: "工作区不存在",
    hint: "请求的工作区未找到；请重新选择项目与工作区。",
    recovery: "select-project",
    recoveryLabel: "选择项目",
  },
  workspace_outside_trust: {
    title: "工作区不在授权范围",
    hint: "工作区与所选项目不匹配或未经过授权；请重新授权目录。",
    recovery: "reauthorize",
    recoveryLabel: "重新授权",
  },
  workspace_unavailable: {
    title: "工作区不可用",
    hint: "工作区状态不可运行或目录路径缺失；请检查目录后重新授权。",
    recovery: "reauthorize",
    recoveryLabel: "重新授权",
  },
  git_snapshot_failed: {
    title: "Git 状态读取失败",
    hint: "工作区 Git 快照读取失败；请检查仓库状态后重试。",
    recovery: "retry",
    recoveryLabel: "重试",
  },
  budget_exceeded: {
    title: "上下文用量超限",
    hint: "上下文压缩后仍超过窗口上限；请新开会话恢复。",
    recovery: "select-project",
    recoveryLabel: "新开会话",
  },
};

const UNKNOWN_BLOCKER: RunBlockerFacts = {
  title: "执行创建失败",
  hint: "后端拒绝了本次执行创建；请检查后端连接与配置后重试。",
  recovery: "retry",
  recoveryLabel: "重试",
};

/** 按后端 error_code 派生阻塞项事实；未知码收敛为通用阻塞（不猜测）。 */
export function describeRunBlocker(code: string | null): RunBlockerFacts {
  if (code && code in BLOCKERS) return BLOCKERS[code];
  return UNKNOWN_BLOCKER;
}
