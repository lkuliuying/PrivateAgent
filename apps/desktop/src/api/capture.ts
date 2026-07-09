import { ensureApiBase } from "./http";

export interface CaptureItem {
  id: number;
  title: string | null;
  content_md: string;
  source: string;
  candidate_type: string | null;
  status: string;
  target_type: string | null;
  target_id: number | null;
  created_at: string;
  handled_at: string | null;
}

export async function listCapture(opts?: { status?: string }): Promise<CaptureItem[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (opts?.status) qs.set("status", opts.status);
  const q = qs.toString();
  const r = await fetch(`${base}/capture${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createCapture(body: {
  content_md: string;
  source?: string;
  title?: string;
  candidate_type?: string;
}): Promise<CaptureItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function captureToInbox(id: number, itemType = "note"): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture/${id}/to-inbox`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_type: itemType }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function captureToReminder(id: number, dueAt?: string): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture/${id}/to-reminder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ due_at: dueAt }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function captureToMemory(id: number, kind = "note"): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture/${id}/to-memory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}
