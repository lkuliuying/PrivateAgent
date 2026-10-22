import type { ContextBudgetResponse } from "../../../api";
import { codingFetchJson, codingJsonInit } from "./codingHttp";

export interface InstructionSource {
  path: string;
  scope: string;
  sha256: string;
  trusted: boolean;
  priority: number;
  content?: string;
}
/** 压缩前后指标：旧检查点没有该字段，界面显示“未记录”。 */
export interface CompactionMetrics {
  version?: string;
  measured?: boolean;
  estimated_before_tokens?: number | null;
  estimated_after_tokens?: number | null;
  archived_items?: number;
  retained_messages?: number;
  retained_user_messages?: number | null;
  archived_bytes?: number | null;
  recorded_at?: string | null;
}
export interface HandoffEntry {
  category: string;
  kind: "observation" | "user_requirement" | "model_report" | "unknown";
  text: string;
  source_item_ids: string[];
  source?: string | null;
  version?: string | null;
  stale?: boolean;
}
export interface HandoffSection {
  status: "known" | "unknown" | "recheck_required";
  note?: string;
  items?: HandoffEntry[];
  /** 目标区段由后端以 requirements 返回；界面统一按 items 渲染。 */
  requirements?: HandoffEntry[];
  next_step?: string | null;
  goal_version?: number | null;
  [key: string]: unknown;
}
export interface Handoff {
  version: string;
  goal: HandoffSection;
  constraints: HandoffSection;
  plan: HandoffSection;
  findings: HandoffSection;
  changes: HandoffSection;
  unresolved: HandoffSection;
}
export interface ContextState {
  project_id: number;
  trusted: boolean;
  sources: InstructionSource[];
  active_sources: InstructionSource[];
  checkpoint: { id: string; state: string; completed_at: string; through_ordinal: number;
    summary_strategy?: "model" | "extractive" | null; summary_fallback_reason?: string | null;
    compaction_metrics?: CompactionMetrics | null } | null;
  handoff?: Handoff | null;
  pending: { id: string; state: string } | null;
  compaction_error: string | null;
  loop_budget: { model_requests: number; max_model_requests: number; tool_calls: number; max_tool_calls: number;
    active_seconds: number; approval_wait_seconds: number; cost_usd: number | null } | null;
}
export function fetchSessionContext(sessionId: number): Promise<ContextState> {
  return codingFetchJson(`/sessions/${sessionId}/context`);
}
export function fetchSessionBudget(sessionId: number): Promise<ContextBudgetResponse> {
  return codingFetchJson(`/sessions/${sessionId}/context-budget`);
}
export function compactSessionContext(sessionId: number, requestId: string): Promise<{ id: string; state: string; error: string | null }> {
  return codingFetchJson(`/sessions/${sessionId}/context/compact`, codingJsonInit("POST", { client_request_id: requestId }));
}
export function setInstructionTrust(projectId: number, trusted: boolean): Promise<{ trusted: boolean }> {
  return codingFetchJson(`/projects/${projectId}/instruction-trust`, codingJsonInit("POST", { trusted }));
}
