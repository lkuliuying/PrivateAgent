import { codingFetchJson, codingJsonInit } from "./codingHttp";

export interface PatchChange {
  change_id: string;
  operation: string;
  rel_path: string;
  before_kind: string;
  after_kind: string;
  diff_chars: number;
}
export interface PatchSummary {
  patch_set_id: string | null;
  run_id: string;
  preview_sha256: string;
  status: string;
  kind: "patch" | "rollback";
  changes: PatchChange[];
  conflicts: { rel_path: string; reason: string }[];
  error?: string | null;
  journal: { change_id: string; rel_path: string; status: string }[];
}
export interface GitBaseline {
  is_git: boolean;
  head_sha: string | null;
  current_branch: string | null;
  dirty: boolean;
  dirty_entries?: { rel_path: string; status: string }[];
}
export interface PatchReview {
  patches: PatchSummary[];
  baseline: GitBaseline | null;
  current_git: GitBaseline;
  ownership_note: string;
}
export interface PatchPage {
  content: string;
  offset: number;
  next_offset: number | null;
  total_chars: number;
  preview_sha256: string;
}
const path = (runId: string, patchId?: string) => `/agent-runs/${encodeURIComponent(runId)}/patches${patchId ? `/${encodeURIComponent(patchId)}` : ""}`;

export function fetchPatches(runId: string, signal?: AbortSignal): Promise<PatchReview> {
  return codingFetchJson(path(runId), { signal });
}
export function fetchPatchPage(runId: string, patchId: string, changeId: string, offset: number, signal?: AbortSignal): Promise<PatchPage> {
  return codingFetchJson(`${path(runId, patchId)}/files/${encodeURIComponent(changeId)}?offset=${offset}&limit=8000`, { signal });
}
export function previewRollback(runId: string, patchId: string, operationId: string): Promise<PatchSummary> {
  return codingFetchJson(`${path(runId, patchId)}/rollback-preview`, codingJsonInit("POST", { operation_id: operationId }));
}
export function applyRollback(runId: string, patchId: string, previewSha: string): Promise<PatchSummary> {
  return codingFetchJson(`${path(runId, patchId)}/apply`, codingJsonInit("POST", { preview_sha256: previewSha }));
}

export const patchStatus = (status: string) => ({ validated: "待应用", applying: "正在应用", applied: "已应用", partially_applied: "部分应用",
  failed: "失败，需核对日志", interrupted: "执行中断，需核对日志", conflicted: "存在冲突", rejected: "已拒绝" }[status] ?? "状态未知");
export const patchOperation = (operation: string) => ({ create: "新增", update: "修改", delete: "删除", move: "移动", mkdir: "创建目录", rollback: "回滚" }[operation] ?? operation);
