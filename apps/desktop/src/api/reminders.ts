import { apiFetch, ensureApiBase } from "./http";
import type { Reminder, ReminderCreate, ReminderUpdate } from "../types";

// ---- 提醒（第六阶段 M3）----
export async function listReminders(status?: string): Promise<Reminder[]> {
  const base = await ensureApiBase();
  const qs = status ? `?status=${status}` : "";
  const r = await apiFetch(`${base}/reminders${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createReminder(data: ReminderCreate): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/reminders`, {
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

export async function updateReminder(
  id: number,
  data: ReminderUpdate
): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/reminders/${id}`, {
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

export async function snoozeReminder(
  id: number,
  data: { next_fire_at?: string; minutes?: number }
): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/reminders/${id}/snooze`, {
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

export async function doneReminder(id: number): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/reminders/${id}/done`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function tickReminders(): Promise<{ fired: number }> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/reminders/tick`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteReminder(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/reminders/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}
