import { requestJson } from "./modelProviders";
export interface BackupPreview {
  sha256: string; kind: "configuration" | "application"; home_layout: "standard" | "compact";
  providers: { id: string; name: string; base_url: string; conflict: boolean }[];
  projects: { id: number; name: string; root_path: string }[];
  workspaces: { id: number; project_id: number; root_path: string; kind: string }[];
  counts: Record<string, number>; warnings: string[];
}
export function exportBackup(kind: "configuration" | "application", homeLayout: "standard" | "compact"): Promise<unknown> {
  return requestJson("/local-backups/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, home_layout: homeLayout }) });
}
export function previewBackup(path: string): Promise<BackupPreview> {
  return requestJson("/local-backups/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }) });
}
export function importBackup(path: string, sha256: string, part: "configuration" | "data", mappings: Record<string, string>, workspaceMappings: Record<string, string>): Promise<{ imported?: string[]; skipped?: string[]; home_layout?: "standard" | "compact" }> {
  return requestJson("/local-backups/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path, sha256, part, mappings, workspace_mappings: workspaceMappings }) });
}
