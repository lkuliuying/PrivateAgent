import { codingFetchJson, codingJsonInit } from "./codingHttp";
export interface McpPermission { name: string; readonly: boolean; approval: "always" | "session" }
export interface McpIntegration {
  id: string; name: string; version: string; transport: "https" | "stdio"; url: string; command: string; args: string[]; oauth: boolean; enabled: boolean;
  tools: McpPermission[]; catalog: { tools: { name: string; description: string; input_schema: object }[] } | null;
  connection: { status: string | null; authorization_url: string | null; error: string | null };
}
export const listIntegrations = (projectId: number, signal?: AbortSignal) => codingFetchJson<{ items: McpIntegration[] }>(`/projects/${projectId}/integrations`, { signal });
export const createIntegration = (projectId: number, data: { name: string; transport: string; url: string; command: string; args: string[]; oauth: boolean; trust_process: boolean }) => codingFetchJson<McpIntegration>(`/projects/${projectId}/integrations`, codingJsonInit("POST", data));
export const connectIntegration = (projectId: number, id: string) => codingFetchJson(`/projects/${projectId}/integrations/${id}/connect`, codingJsonInit("POST", {}));
export const selectIntegrationTools = (projectId: number, source: McpIntegration, enabled: boolean, tools: McpPermission[]) => codingFetchJson(`/projects/${projectId}/integrations/${source.id}`, codingJsonInit("PUT", { expected_version: source.version, enabled, tools }));
export const removeIntegration = (projectId: number, id: string) => codingFetchJson(`/projects/${projectId}/integrations/${id}`, { method: "DELETE" });
