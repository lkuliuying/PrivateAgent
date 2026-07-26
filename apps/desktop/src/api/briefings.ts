import { apiFetch, ensureApiBase } from "./http";
import type { Briefing } from "../types";

// ---- 简报 ----
export async function createGoalBriefing(goalId: number): Promise<Briefing> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/goals/${goalId}/briefing`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createTodayBriefing(): Promise<Briefing> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/today/briefing`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createWeeklyBriefing(): Promise<Briefing> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/briefings/weekly`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listBriefings(kind?: string): Promise<Briefing[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const r = await apiFetch(`${base}/briefings${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function briefingToTask(id: number): Promise<{ task_id: number }> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/briefings/${id}/to-task`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
