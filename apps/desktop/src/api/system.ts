import { apiFetch, ensureApiBase } from "./http";

export async function getHealth(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getApiInfo(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
