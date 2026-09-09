import { codingFetchJson, codingJsonInit } from "./codingHttp";
import type { ManagedExecution } from "./executions";
import type { PatchSummary } from "./patches";
import type { AgentRunStatus } from "../model/runContracts";
import type { ProjectWorkspace } from "../../../types";

export interface ControlRequest {
  request_id: string;
  expected_state_version: number;
  checkpoint_id?: string | null;
  message?: string;
}
export interface ControlRecord {
  request_id: string;
  kind: "pause" | "resume" | "steer" | "cancel";
  status: "received" | "applied" | "interrupted";
  result_run_id: string;
  message?: string;
  cleanup_complete?: boolean;
}
export interface RecoveryReport {
  run_id: string;
  supported?: boolean;
  status: AgentRunStatus;
  state_version: number;
  checkpoint_id: string | null;
  logical_task_id: string | null;
  resumed_from_run_id: string | null;
  can_resume: boolean;
  blockers: string[];
  controls: ControlRecord[];
  executions: ManagedExecution[];
  budget: { model_requests?: number; tool_calls?: number; active_seconds?: number };
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
export const controlRun = (run: string, kind: ControlRecord["kind"], data: ControlRequest): Promise<ControlRecord> => codingFetchJson(`${path(run)}/${kind}`, codingJsonInit("POST", data));
export const createWorktree = (project: number, ref: string, requestId: string): Promise<ProjectWorkspace> => codingFetchJson(`/projects/${project}/workspaces/worktree`, codingJsonInit("POST", { ref, request_id: requestId }));
export const cleanupWorktree = (project: number, workspace: number): Promise<ProjectWorkspace> => codingFetchJson(`/projects/${project}/workspaces/${workspace}/cleanup`, codingJsonInit("POST", {}));
