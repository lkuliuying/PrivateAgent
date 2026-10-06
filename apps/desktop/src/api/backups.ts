import { requestJson } from "./modelProviders";
import { apiFetch, ensureApiBase } from "./http";
export interface BackupModelIdentity {
  provider_id: string; protocol: string; api_format: string; base_url: string; model_id: string;
}
export interface BackupModelSelection {
  scope: "project" | "session"; id: number; profile_id: string | null; source_scope: "global" | "project" | "session";
  source_identity: BackupModelIdentity | null; requires_confirmation: boolean; reason: string | null;
  target_identity: BackupModelIdentity | null;
}
export interface BackupPreview {
  sha256: string; kind: "configuration" | "application"; home_layout: "standard" | "compact";
  format?: string; created_at?: string; size_bytes?: number; coverage?: string[]; model_selections?: BackupModelSelection[];
  providers: { id: string; name: string; base_url: string; conflict: boolean }[];
  projects: { id: number; name: string; root_path: string }[];
  workspaces: { id: number; project_id: number; root_path: string; kind: string }[];
  counts: Record<string, number>; warnings: string[];
}
export interface BackupImportResult {
  imported?: string[]; skipped?: string[]; home_layout?: "standard" | "compact";
  id?: string; source_kind?: string; backup_format?: string; already_imported?: boolean; imported_counts?: Record<string, number>; skipped_counts?: Record<string, number>;
}
async function archiveBlob(path: string, init?: RequestInit): Promise<Blob> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `备份导出失败（HTTP ${response.status}），请检查本机连接后重试`);
  }
  // 直接保存服务端字节，避免再次序列化改变浮点数表示并破坏备份摘要。
  return response.blob();
}
export function exportBackup(kind: "configuration" | "application", homeLayout: "standard" | "compact"): Promise<Blob> {
  return archiveBlob("/local-backups/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, home_layout: homeLayout }) });
}
export function exportHistoryArchive(importId?: string): Promise<Blob> {
  return archiveBlob(importId ? `/local-history/imports/${encodeURIComponent(importId)}/export` : "/local-history/export");
}
export function previewBackup(path: string): Promise<BackupPreview> {
  return requestJson("/local-backups/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }) });
}
export function importBackup(path: string, sha256: string, part: "configuration" | "data", mappings: Record<string, string>, workspaceMappings: Record<string, string>): Promise<BackupImportResult> {
  return requestJson("/local-backups/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path, sha256, part, mappings, workspace_mappings: workspaceMappings }) });
}
