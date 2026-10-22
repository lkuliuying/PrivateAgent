import { codingFetchJson, codingJsonInit } from "./codingHttp";
import type { ManagedExecution } from "./executions";
import type { PatchSummary } from "./patches";
import type { AgentRunStatus } from "../model/runContracts";

export interface ControlRequest {
  request_id: string;
  expected_state_version: number;
  checkpoint_id?: string | null;
  message?: string;
}
export type RunControlKind = "pause" | "resume" | "steer" | "cancel";
/** 恢复控制种类：核对提交与续跑共用幂等请求标识，避免重复写。 */
export type RecoveryControlKind = RunControlKind | "reconcile";
export type ReconcileKind = "file_operation" | "mcp_write" | "command" | "operation" | "abandon_task";
export type ReconcileDecision = "record_observation" | "externally_confirmed" | "externally_failed" | "abandon";
export interface ReconcileRequest extends ControlRequest {
  item_id: string;
  kind: ReconcileKind;
  decision: ReconcileDecision;
  note?: string;
}
export interface ResumeRequest extends ControlRequest {
  model_profile_id?: string;
  preview_sha256?: string;
  accept_model_change?: boolean;
  accept_unconfirmed_timing?: boolean;
}
export type ControlPayload = ControlRequest & Partial<Omit<ReconcileRequest, "request_id" | "expected_state_version">> & Partial<Omit<ResumeRequest, "request_id" | "expected_state_version">>;
export interface ControlRecord {
  request_id: string;
  kind: RecoveryControlKind | "answer" | "implement";
  status: "received" | "applied" | "interrupted";
  result_run_id: string;
  message?: string;
  cleanup_complete?: boolean;
  item_id?: string;
  item_kind?: ReconcileKind;
  decision?: ReconcileDecision;
  source?: "machine_observation" | "user_statement";
  verified?: boolean;
  note?: string;
  model_profile_id?: string;
  model_switched?: boolean;
}
/** 结构化待核对项：界面不解析中文错误字符串，按 kind 与 actions 决定入口。 */
export interface BlockerDetail {
  item_id: string;
  kind: ReconcileKind | "history" | "budget" | "session";
  label?: string;
  reason?: string;
  status: "open" | "resolved";
  source?: "machine" | "user_statement" | "machine_observation";
  actions: ReconcileDecision[];
  resolvable: boolean;
  target?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  observation?: string | null;
  resolution?: { decision: ReconcileDecision; source: string; verified: boolean; note: string | null; created_at: string } | null;
}
export interface ResolutionRecord {
  format_version: string;
  resolution_id: string;
  item_id: string;
  kind: ReconcileKind;
  target?: Record<string, unknown>;
  decision: ReconcileDecision;
  source: "machine_observation" | "user_statement";
  verified: boolean;
  observation?: string | null;
  note?: string | null;
  created_at: string;
  request_id: string;
  state_version: number;
}
export interface TimingReceipt {
  format_version?: string;
  clock_id?: string | null;
  monotonic_seconds?: number | null;
  confirmed_active_seconds?: number | null;
  last_receipt_at?: string | null;
  source?: string;
  unconfirmed_tail?: boolean;
}
export interface ModelFacts {
  model_profile_id: string;
  model_name: string | null;
  provider: string | null;
  api_format: string | null;
  endpoint: string | null;
  context_tokens: number | null;
  native_tool_calls: boolean | null;
  supports_vision: boolean | null;
  supports_structured_output: boolean | null;
  configuration_version: string | null;
  capability_version: string;
}
export interface ResumePreview {
  format_version: string;
  run_id: string;
  checkpoint_id: string | null;
  state_version: number;
  source: ModelFacts | null;
  target: ModelFacts;
  switched: boolean;
  capability_gaps: string[];
  blockers: string[];
  preview_sha256: string;
  eligible: boolean;
  can_resume: boolean;
  recovery_class: string;
  requires_model_change_acceptance: boolean;
  requires_timing_acceptance: boolean;
  budget_note: string;
  limitations: string[];
}
export interface RecoveryReport {
  run_id: string;
  supported?: boolean;
  status: AgentRunStatus;
  state_version: number;
  checkpoint_id: string | null;
  logical_task_id: string | null;
  resumed_from_run_id: string | null;
  model_profile_id?: string | null;
  can_resume: boolean;
  blockers: string[];
  blocker_details?: BlockerDetail[];
  open_items?: string[];
  resolutions?: ResolutionRecord[];
  recovery_class?: string;
  resumable_error?: string | null;
  controls: ControlRecord[];
  executions: ManagedExecution[];
  budget: {
    model_requests?: number; max_model_requests?: number;
    tool_calls?: number; max_tool_calls?: number;
    active_seconds?: number; max_active_seconds?: number;
    cost_usd?: number | null; max_cost_usd?: number | null;
  };
  timing?: TimingReceipt | null;
  time_policy?: string | null;
  queue_reason?: string | null;
  queue_position?: number | null;
  expired_approvals: string[];
  limitations: string[];
}
export interface ChangeSummary {
  rel_path: string;
  operation: string;
  before_sha256?: string | null;
  after_sha256?: string | null;
}
export interface RunReview {
  task_changes: PatchSummary[];
  preexisting_changes: { rel_path: string; status: string }[];
  external_or_unattributed: ChangeSummary[];
  command_candidates: { run_id: string; execution_id: string; complete: boolean; items: ChangeSummary[] }[];
  snapshot_complete: boolean;
  limitations: string[];
}
const path = (run: string) => `/agent-runs/${encodeURIComponent(run)}`;
export const fetchRecovery = (run: string, signal?: AbortSignal): Promise<RecoveryReport> => codingFetchJson(`${path(run)}/recovery`, { signal });
export const fetchRunReview = (run: string, signal?: AbortSignal): Promise<RunReview> => codingFetchJson(`${path(run)}/review`, { signal });
export const controlRun = (run: string, kind: RecoveryControlKind, data: ControlPayload): Promise<ControlRecord> => codingFetchJson(`${path(run)}/${kind}`, codingJsonInit("POST", data));
export const reconcileRun = (run: string, data: ReconcileRequest): Promise<ControlRecord> => codingFetchJson(`${path(run)}/recovery/reconcile`, codingJsonInit("POST", data));
/** 只读预览：不发起真实模型调用，也不改默认模型或原运行。 */
export const fetchResumePreview = (run: string, modelProfileId: string | null | undefined, checkpointId: string | null | undefined, signal?: AbortSignal): Promise<ResumePreview> =>
  codingFetchJson(`${path(run)}/resume/preview`, { ...codingJsonInit("POST", { model_profile_id: modelProfileId ?? null, checkpoint_id: checkpointId ?? null }), signal });

