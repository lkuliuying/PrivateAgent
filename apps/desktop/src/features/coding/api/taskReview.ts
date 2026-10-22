import { codingFetchJson } from "./codingHttp";
import type { RunOutcome } from "../model/generated/codingContracts";
/** 按运行轮次展示续跑链：只读已提交事实，旧结论不被改写。 */
export interface TaskReviewRun {
  id: string;
  status: string;
  created_at: string;
  workspace_id: number;
  outcome: RunOutcome | null;
  patch_count: number;
  resumed_from_run_id?: string | null;
  logical_task_id?: string | null;
  ancestor_count?: number;
  error_code?: string | null;
  error_message?: string | null;
  recovery_class?: string;
  resolution_count?: number;
  model_switch?: boolean;
  model_switch_from?: string | null;
  model_switch_to?: string | null;
  patch_status?: string[];
  rollback_available?: boolean;
}
export interface TaskReview { scope: string; runs: TaskReviewRun[]; workspace: { is_git: boolean; entries: { rel_path: string; status: string }[]; next_cursor: string | null } | null }
export interface WorkspaceDiff { diff: string; version: string; next_offset: number | null; rel_path: string }
export const fetchTaskReview = (id: number, scope: string, cursor?: string, signal?: AbortSignal) => codingFetchJson<TaskReview>(`/sessions/${id}/review?scope=${scope}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, { signal });
export const fetchWorkspaceDiff = (id: number, path: string, staged: boolean, offset = 0, version?: string, signal?: AbortSignal) => codingFetchJson<WorkspaceDiff>(`/sessions/${id}/review/diff?${new URLSearchParams({ path, staged: String(staged), offset: String(offset), ...(version ? { version } : {}) })}`, { signal });
