import { apiFetch, ensureApiBase } from "./http";

export type ChatExecutionMode = "agent_runtime" | "legacy";

export interface RuntimeCapabilities {
  chat_execution_mode: ChatExecutionMode;
  legacy_tool_planner_enabled: boolean;
  agent_read_only_tools_enabled: boolean;
  rag_chat_runtime_enabled: boolean;
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
