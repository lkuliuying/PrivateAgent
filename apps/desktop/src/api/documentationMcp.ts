import { apiFetch, ensureApiBase } from "./http";

export interface DocumentationTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown> | null;
}

export interface DocumentationSource {
  id: string;
  name: string;
  url: string;
  version: string;
  enabled: boolean;
  tools: string[];
  catalog: { tools: DocumentationTool[]; sha256: string } | null;
  discovered_at: string | null;
}

async function request<T>(path: string, signal: AbortSignal, method = "GET", data?: unknown): Promise<T> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}${path}`, {
    signal, method,
    ...(data === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : "文档服务操作失败，请重试");
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

const path = (projectId: number, sourceId?: string) =>
  `/projects/${projectId}/documentation-sources${sourceId ? `/${encodeURIComponent(sourceId)}` : ""}`;

export const documentationProjects = (signal: AbortSignal) =>
  request<Array<{ id: number; name: string }>>("/projects", signal);
export const documentationSources = (projectId: number, signal: AbortSignal) =>
  request<DocumentationSource[]>(path(projectId), signal);
export const createDocumentationSource = (projectId: number, data: { name: string; url: string }, signal: AbortSignal) =>
  request<DocumentationSource>(path(projectId), signal, "POST", data);
export const discoverDocumentationSource = (projectId: number, source: DocumentationSource, signal: AbortSignal) =>
  request<DocumentationSource>(`${path(projectId, source.id)}/discover`, signal, "POST", { expected_version: source.version });
export const selectDocumentationTools = (projectId: number, source: DocumentationSource, tools: string[], enabled: boolean, signal: AbortSignal) =>
  request<DocumentationSource>(`${path(projectId, source.id)}/selection`, signal, "PUT", { expected_version: source.version, tools, enabled });
export const deleteDocumentationSource = (projectId: number, source: DocumentationSource, signal: AbortSignal) =>
  request<void>(`${path(projectId, source.id)}?expected_version=${encodeURIComponent(source.version)}`, signal, "DELETE");
