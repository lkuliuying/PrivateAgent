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
export interface ContextState {
  project_id: number;
  trusted: boolean;
  sources: InstructionSource[];
  active_sources: InstructionSource[];
  checkpoint: { id: string; state: string; completed_at: string; through_ordinal: number;
    summary_strategy?: "model" | "extractive" | null; summary_fallback_reason?: string | null } | null;
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
