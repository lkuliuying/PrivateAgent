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
}
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
  last_recall: { recalled_ids: string[]; omitted_ids: string[] } | null;
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
export const createMemory = (project: number | null, data: MemoryInput, signal: AbortSignal) => request<MemoryItem>(path(project), signal, "POST", data);
export const editMemory = (project: number | null, item: MemoryItem, data: MemoryInput, signal: AbortSignal) =>
  request<MemoryItem>(path(project, item.id), signal, "PUT", { ...data, expected_version: item.version });
export const forgetMemory = (project: number | null, item: MemoryItem, signal: AbortSignal) =>
  request<void>(path(project, item.id, item.version), signal, "DELETE");
export const sessionMemorySettings = (session: number, signal: AbortSignal) =>
  request<SessionMemorySettings>(`/sessions/${session}/memory-settings`, signal);
export const saveSessionMemorySettings = (session: number, data: SessionMemorySettings, signal: AbortSignal) =>
  request<SessionMemorySettings>(`/sessions/${session}/memory-settings`, signal, "PUT", {
    use_memories: data.use_memories, generate_memories: data.generate_memories, expected_version: data.version,
  });
