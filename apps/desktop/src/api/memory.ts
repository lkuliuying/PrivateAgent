import { apiFetch, ensureApiBase } from "./http";
import type {
  MemoryEvent,
  MemoryItem,
  MemoryKind,
  MemoryStatus,
} from "../types";

// ---- 长期记忆（第四阶段 M1）----
export async function listMemories(opts?: {
  kind?: string;
  status?: string;
  project_id?: number;
  topic_id?: number;
  search?: string;
  enabled?: boolean;
}): Promise<MemoryItem[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.kind) params.set("kind", opts.kind);
  if (opts?.status) params.set("status", opts.status);
  if (opts?.project_id !== undefined)
    params.set("project_id", String(opts.project_id));
  if (opts?.topic_id !== undefined)
    params.set("topic_id", String(opts.topic_id));
  if (opts?.search) params.set("search", opts.search);
  if (opts?.enabled !== undefined) params.set("enabled", String(opts.enabled));
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`${base}/memories${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMemory(id: number): Promise<MemoryItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createMemory(data: {
  kind: MemoryKind;
  title: string;
  content_md: string;
  summary?: string;
  source_type?: string;
  source_id?: number;
  project_id?: number;
  topic_id?: number;
  tags?: string[];
  confidence?: number;
  sensitive?: boolean;
}): Promise<MemoryItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories`, {
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

export async function updateMemory(
  id: number,
  data: {
    title?: string;
    content_md?: string;
    summary?: string;
    tags?: string[];
    confidence?: number;
    enabled?: boolean;
    sensitive?: boolean;
    status?: MemoryStatus;
  }
): Promise<MemoryItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories/${id}`, {
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

export async function deleteMemory(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
}

export async function searchMemories(req: {
  query?: string;
  kind?: string;
  status?: string;
  enabled?: boolean;
  project_id?: number;
  topic_id?: number;
}): Promise<MemoryItem[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function candidateMemories(req: {
  source_type: "agent_task" | "chat_session" | "learning_review";
  source_id: number;
}): Promise<MemoryItem[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories/candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function useMemory(
  id: number,
  ref?: { ref_type?: string; ref_id?: number }
): Promise<void> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories/${id}/use`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ref || {}),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function listMemoryEvents(id: number): Promise<MemoryEvent[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/memories/${id}/events`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
