import { apiFetch, ensureApiBase } from "./http";
import type { BackupExportResult, BackupRestorePreview } from "../types";

// ---- 备份（第四阶段 M6）----
export async function listBackups(): Promise<{ items: BackupExportResult[]; last_backup_at: string | null }> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/backup`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function exportBackup(): Promise<BackupExportResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/backup/export`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function previewRestoreBackup(path: string): Promise<BackupRestorePreview> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/backup/restore/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
