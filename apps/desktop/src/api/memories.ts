import { apiFetch, ensureApiBase } from "./http";

export interface MemoryConfig {
  enabled: boolean;
  use_memories: boolean;
  generate_memories: boolean;
  exclude_external_context: boolean;
  model_profile_id: string | null;
  idle_seconds: number;
  max_calls_per_day: number;
}
export interface MemorySettings extends MemoryConfig { version: number; generation_since: string }
export interface MemoryInput {
  scope: "user" | "project";
  kind: "preference" | "project" | "workflow" | "reference";
  title: string;
  content: string;
}
export interface MemoryItem extends MemoryInput {
  id: string;
  project_id: number | null;
  version: number;
  origin: "user" | "generated";
  updated_at: string;
  source_session_id: number | null;
  source_item_ids: string[];
  status?: "active" | "pending_review" | "stale";
  review_reason?: string | null;
  supersedes_id?: string | null;
  legacy?: boolean;
}
export interface MemoryRecallEntry {
  memory_id: string; current_memory_id?: string; version: number; title?: string; scope: "project" | "user";
  project_id?: number | null; updated_at?: string; available?: boolean;
  matched_terms: string[]; source_session_id: number | null; source_item_ids: string[];
  decision: "included" | "omitted" | "excluded"; reason: string;
}
export interface MemorySource {
  item_id: string; content: string; offset: number; next_offset: number | null; total_chars: number;
  session_id: number; project_id: number; message_id: number | null; run_id: string;
}
export interface MemorySourceTarget { projectId: number; sessionId: number; messageId: number | null }
export interface MemoryRevision extends MemoryItem { revision_reason: string }
export interface MemoryStatus {
  calls_today: number;
  worker_running: boolean;
  error: string | null;
  last_attempt: { created_at: string; state: "running" | "completed" | "cancelled" | "failed"; saved?: number; error?: string } | null;
}
export interface SessionMemorySettings {
  version: number;
  use_memories: boolean;
  generate_memories: boolean;
  effective_use: boolean;
  effective_generate: boolean;
  last_recall: { recalled_ids: string[]; omitted_ids: string[]; run_id?: string; entries?: MemoryRecallEntry[] } | null;
}

async function request<T>(path: string, signal: AbortSignal, method = "GET", data?: unknown): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = setTimeout(abort, 15000);
  try {
    const base = await ensureApiBase();
    if (controller.signal.aborted) throw new DOMException("请求已取消或超时", "AbortError");
    const response = await apiFetch(`${base}${path}`, {
      signal: controller.signal, method,
      ...(data === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(typeof body?.detail === "string" ? body.detail : "记忆操作失败，请刷新后重试");
    }
    return response.status === 204 ? undefined as T : await response.json() as T;
  } catch (cause) {
    if (controller.signal.aborted) throw new Error("请求已取消或超时，请刷新后重试");
    throw cause;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}

function path(project: number | null, id?: string, version?: number) {
  const query = new URLSearchParams();
  if (project !== null) query.set("project_id", String(project));
  if (version !== undefined) query.set("expected_version", String(version));
  return `/local-memories/items${id ? `/${encodeURIComponent(id)}` : ""}?${query}`;
}

export const memoryProjects = (signal: AbortSignal) => request<Array<{ id: number; name: string }>>("/projects", signal);
export const memorySettings = (signal: AbortSignal) => request<MemorySettings>("/local-memories/settings", signal);
export const memoryStatus = (signal: AbortSignal) => request<MemoryStatus>("/local-memories/status", signal);
export const saveMemorySettings = (data: MemoryConfig, version: number, signal: AbortSignal) =>
  request<MemorySettings>("/local-memories/settings", signal, "PUT", { ...data, expected_version: version });
export const memoryItems = (project: number | null, signal: AbortSignal) => request<MemoryItem[]>(path(project), signal);
export const memoryItem = (project: number | null, id: string, signal: AbortSignal) => request<MemoryItem>(path(project, id), signal);
export const createMemory = (project: number | null, data: MemoryInput, signal: AbortSignal) => request<MemoryItem>(path(project), signal, "POST", data);
export const editMemory = (project: number | null, item: MemoryItem, data: MemoryInput, signal: AbortSignal) =>
  request<MemoryItem>(path(project, item.id), signal, "PUT", { ...data, expected_version: item.version });
export const forgetMemory = (project: number | null, item: MemoryItem, signal: AbortSignal) =>
  request<void>(path(project, item.id, item.version), signal, "DELETE");
const detailPath = (project: number | null, id: string, suffix: string) =>
  `/local-memories/items/${encodeURIComponent(id)}/${suffix}${project === null ? "" : `?project_id=${project}`}`;
export const reviewMemory = (project: number | null, item: MemoryItem, decision: "accept" | "reject" | "stale", signal: AbortSignal) =>
  request<MemoryItem>(detailPath(project, item.id, "review"), signal, "POST", { expected_version: item.version, decision });
export const memoryRevisions = (project: number | null, id: string, signal: AbortSignal) =>
  request<MemoryRevision[]>(detailPath(project, id, "revisions"), signal);
export const memorySource = (project: number | null, id: string, sourceId: string, offset: number, signal: AbortSignal) => {
  const base = detailPath(project, id, `sources/${encodeURIComponent(sourceId)}`);
  return request<MemorySource>(`${base}${base.includes("?") ? "&" : "?"}offset=${offset}&limit=2000`, signal);
};
export const searchMemories = (project: number | null, query: string, signal: AbortSignal) =>
  request<MemoryItem[]>(`/local-memories/search?query=${encodeURIComponent(query)}${project === null ? "" : `&project_id=${project}`}`, signal);
export const sessionMemorySettings = (session: number, signal: AbortSignal) =>
  request<SessionMemorySettings>(`/sessions/${session}/memory-settings`, signal);
export const saveSessionMemorySettings = (session: number, data: SessionMemorySettings, signal: AbortSignal) =>
  request<SessionMemorySettings>(`/sessions/${session}/memory-settings`, signal, "PUT", {
    use_memories: data.use_memories, generate_memories: data.generate_memories, expected_version: data.version,
  });
