import { apiFetch as fetch, ensureApiBase } from "./http";

export interface DiagnosticsSnapshot {
  generated_at: string;
  version: string;
  migration_head: string | null;
  health: Record<string, unknown>;
  backup: { last_backup_at: string | null; count: number };
  failed_activities: Array<Record<string, unknown>>;
  provider_failures: Array<Record<string, unknown>>;
  reminder_tick: Record<string, unknown>;
  import_queue: Record<string, number>;
  integrity_summary: Record<string, number>;
  recent_errors: string[];
  settings_redacted: Record<string, string>;
  db_url_redacted: string;
}

export async function getDiagnostics(): Promise<DiagnosticsSnapshot> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/diagnostics`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function exportDiagnostics(
  outputDir?: string
): Promise<{ path: string; run_id: number; size_bytes: number }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/diagnostics/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ output_dir: outputDir ?? null }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
