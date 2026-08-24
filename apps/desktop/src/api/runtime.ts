import { apiFetch, ensureApiBase } from "./http";

export type ChatExecutionMode = "agent_runtime" | "legacy";

export interface RuntimeCapabilities {
  chat_execution_mode: ChatExecutionMode;
  legacy_tool_planner_enabled: boolean;
  agent_read_only_tools_enabled: boolean;
  rag_chat_runtime_enabled: boolean;
  /** v0.5.0 B0 additive extension: trusted workflow gates, off by default. */
  patch_workflow_enabled: boolean;
  command_workflow_enabled: boolean;
  http_workflow_enabled: boolean;
  sql_readonly_workflow_enabled: boolean;
  /**
   * v0.9.0 H0 additive extension（旧后端不提供时一律按「未提供」处理）：
   * coding 默认切换、三档权限能力位、上下文预算、执行详情与 worktree。
   * workspace 与 full_access 独立声明，不是别名。
   */
  coding_agent_ui_enabled?: boolean;
  project_bound_runs_enabled?: boolean;
  coding_workspace_auto_approve?: boolean;
  coding_full_access_supported?: boolean;
  coding_context_budget_enabled?: boolean;
  coding_execution_detail_enabled?: boolean;
  coding_worktree_enabled?: boolean;
  product_timezone?: string;
  /**
   * v0.9.0 H1-C additive（计划 §5.3/§5.7）：full_access 的审计与撤销独立声明；
   * 显式为 false 时前端必须失败关闭。内置只读诊断命令面（H1-B 动手主链）。
   */
  coding_full_access_audit?: boolean;
  coding_full_access_revoke?: boolean;
  coding_diagnostic_commands_enabled?: boolean;
}

/**
 * Older backends do not expose /capabilities. Keep their legacy planner usable,
 * while a positive Agent Runtime signal is authoritative and prevents a second
 * planning framework from running for the same new message.
 */
export function shouldUseLegacyToolPlanner(
  capabilities: RuntimeCapabilities | null
): boolean {
  return capabilities?.chat_execution_mode !== "agent_runtime";
}

export async function getRuntimeCapabilities(): Promise<RuntimeCapabilities> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}/capabilities`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
