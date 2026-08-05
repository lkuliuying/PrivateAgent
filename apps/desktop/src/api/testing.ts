import { apiFetch as fetch, ensureApiBase } from "./http";

export async function listTestRuns(
  kind?: string
): Promise<Array<Record<string, unknown>>> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const r = await fetch(`${base}/testing/runs${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listUpgradeSmokeRuns(): Promise<
  Array<Record<string, unknown>>
> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/testing/upgrade-smoke-runs`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
