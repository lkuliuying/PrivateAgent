import { apiFetch as fetch, ensureApiBase } from "./http";

export async function restoreDrillBackup(
  path: string
): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/backup/restore/drill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMigrationRunbook(): Promise<Record<string, string>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/backup/migration-runbook`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const d = await r.json();
  return d.runbook as Record<string, string>;
}
