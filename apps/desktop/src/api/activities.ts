import { apiFetch, ensureApiBase } from "./http";
import type { Activity } from "../types";

// ---- 活动流（第二阶段 M4）----
export async function listActivities(
  sessionId?: number,
  kind?: string,
  status?: string
): Promise<Activity[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", String(sessionId));
  if (kind) params.set("kind", kind);
  if (status) params.set("status", status);
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`${base}/activities${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function retryActivity(id: number): Promise<Activity> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/activities/${id}/retry`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
