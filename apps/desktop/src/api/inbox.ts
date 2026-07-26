import { apiFetch, ensureApiBase } from "./http";
import type { InboxCreate, InboxItem, InboxUpdate } from "../types";

// ---- 收件箱 ----
export async function listInbox(opts?: {
  status?: string;
  item_type?: string;
  priority?: string;
  source_type?: string;
}): Promise<InboxItem[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.item_type) params.set("item_type", opts.item_type);
  if (opts?.priority) params.set("priority", opts.priority);
  if (opts?.source_type) params.set("source_type", opts.source_type);
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`${base}/inbox${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createInbox(data: InboxCreate): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/inbox`, {
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

export async function updateInbox(
  id: number,
  data: InboxUpdate
): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/inbox/${id}`, {
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

export async function deleteInbox(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/inbox/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function inboxToTask(id: number): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/inbox/${id}/to-task`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function inboxToReminder(
  id: number,
  data?: { due_at?: string; recurrence_rule?: Record<string, unknown> }
): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/inbox/${id}/to-reminder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data || {}),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
