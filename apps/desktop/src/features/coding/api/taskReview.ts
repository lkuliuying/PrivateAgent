import { codingFetchJson } from "./codingHttp";
import type { RunOutcome } from "../model/generated/codingContracts";
export interface TaskReview { scope: string; runs: { id: string; status: string; created_at: string; workspace_id: number; outcome: RunOutcome | null; patch_count: number }[]; workspace: { is_git: boolean; entries: { rel_path: string; status: string }[]; next_cursor: string | null } | null }
export interface WorkspaceDiff { diff: string; version: string; next_offset: number | null; rel_path: string }
export const fetchTaskReview = (id: number, scope: string, cursor?: string, signal?: AbortSignal) => codingFetchJson<TaskReview>(`/sessions/${id}/review?scope=${scope}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, { signal });
export const fetchWorkspaceDiff = (id: number, path: string, staged: boolean, offset = 0, version?: string, signal?: AbortSignal) => codingFetchJson<WorkspaceDiff>(`/sessions/${id}/review/diff?${new URLSearchParams({ path, staged: String(staged), offset: String(offset), ...(version ? { version } : {}) })}`, { signal });
