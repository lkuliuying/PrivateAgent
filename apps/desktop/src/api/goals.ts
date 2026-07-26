import { apiFetch, ensureApiBase } from "./http";
import type {
  GoalCheckin,
  GoalCreate,
  GoalDetail,
  GoalLink,
  GoalUpdate,
  PersonalGoal,
} from "../types";

// ---- 目标 / 简报 / 隐私维护（第六阶段 M4/M5/M6）----
export async function listGoals(opts?: {
  status?: string;
  domain?: string;
}): Promise<PersonalGoal[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.domain) params.set("domain", opts.domain);
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`${base}/goals${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createGoal(data: GoalCreate): Promise<PersonalGoal> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getGoal(id: number): Promise<GoalDetail> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/goals/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateGoal(
  id: number,
  data: GoalUpdate
): Promise<PersonalGoal> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/goals/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function addGoalLink(
  goalId: number,
  data: { target_type: string; target_id: number; relation?: string }
): Promise<GoalLink> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/goals/${goalId}/links`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function addGoalCheckin(
  goalId: number,
  data: {
    checkin_date?: string;
    progress_note_md?: string;
    confidence?: number;
    blockers_json?: string[];
    next_actions_json?: string[];
  }
): Promise<GoalCheckin> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/goals/${goalId}/checkins`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function createGoalTaskDraft(
  goalId: number
): Promise<{ task_id: number }> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/goals/${goalId}/task-draft`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
