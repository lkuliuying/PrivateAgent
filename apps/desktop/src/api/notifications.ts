import { ensureApiBase } from "./http";
import type { AppNotification, AppNotificationCreate } from "../types";

export async function listNotifications(
  opts?: { status?: string; kind?: string; limit?: number }
): Promise<AppNotification[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (opts?.status) qs.set("status", opts.status);
  if (opts?.kind) qs.set("kind", opts.kind);
  if (opts?.limit) qs.set("limit", String(opts.limit));
  const q = qs.toString();
  const r = await fetch(`${base}/notifications${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createNotification(
  body: AppNotificationCreate
): Promise<AppNotification> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/notifications`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function patchNotification(
  id: number,
  status: "read" | "archived"
): Promise<AppNotification> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/notifications/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function readAllNotifications(): Promise<{ marked: number }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/notifications/read-all`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
