import { apiFetch, ensureApiBase } from "./http";
import type { TodayFilters, TodaySnapshot } from "../types";

// ---- 今日中枢 / 收件箱（第六阶段 M2）----
export async function getToday(filters?: TodayFilters): Promise<TodaySnapshot> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (filters?.type) qs.set("type", filters.type);
  if (filters?.priority) qs.set("priority", filters.priority);
  if (filters?.time) qs.set("time", filters.time);
  if (filters?.status) qs.set("status", filters.status);
  const q = qs.toString();
  const r = await apiFetch(`${base}/today${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
