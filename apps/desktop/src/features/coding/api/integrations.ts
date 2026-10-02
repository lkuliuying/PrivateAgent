import { codingFetchJson, codingJsonInit } from "./codingHttp";
import { saveMcpCredential, type McpCredentialBinding } from "../../../api/mcpCredentials";
export interface McpPermission { name: string; readonly: boolean; approval: "always" | "session" }
export interface McpConfiguration {
  name: string; transport: "https" | "stdio"; url: string; command: string; args: string[]; oauth: boolean;
  auth_mode?: "none" | "oauth" | "bearer" | "custom_headers"; header_names?: string[]; env_names?: string[]; trust_process: boolean;
  oauth_persistence?: "persistent" | "session";
}
export interface McpService extends McpConfiguration {
  id: string; version: string; credential_revision: string; auth_revision: string;
  projects: { project_id: number; project_name: string; source_id: string }[]; required_fields: string[];
}
export interface McpIntegration extends McpConfiguration {
  id: string; service_id: string; version: string; service_version: string; enabled: boolean; needs_validation?: boolean;
  discovered_at?: string | null;
  tools: McpPermission[]; catalog: { tools: { name: string; description: string; input_schema: object }[];
    unavailable_tools?: { name: string; reason: string; error_code: string }[] } | null;
  connection: { status: string | null; authorization_url: string | null; error: string | null; error_code?: string | null; warning?: string | null };
}
export interface McpPrepareInput { request_id: string; service_id?: string; expected_version?: string; configuration: McpConfiguration; replace_credentials: boolean }
export interface McpChange {
  id: string; service_id: string; credential_revision: string; configuration: McpService; request: McpPrepareInput;
  status: "prepared" | "completed" | "discarded"; binding: McpCredentialBinding | null; required_fields: string[]; replace_credentials: boolean;
}
export const listIntegrations = (projectId: number, signal?: AbortSignal) => codingFetchJson<{ items: McpIntegration[] }>(`/projects/${projectId}/integrations`, { signal });
export const createIntegration = (projectId: number, data: McpConfiguration) => codingFetchJson<McpIntegration>(`/projects/${projectId}/integrations`, codingJsonInit("POST", data));
export const connectIntegration = (projectId: number, id: string) => codingFetchJson(`/projects/${projectId}/integrations/${id}/connect`, codingJsonInit("POST", {}));
export const selectIntegrationTools = (projectId: number, source: McpIntegration, enabled: boolean, tools: McpPermission[]) => codingFetchJson(`/projects/${projectId}/integrations/${source.id}`, codingJsonInit("PUT", { expected_version: source.version, enabled, tools }));
export const removeIntegration = (projectId: number, id: string) => codingFetchJson(`/projects/${projectId}/integrations/${id}`, { method: "DELETE" });
export interface McpCredentialCleanup { id: string; service_id: string; revision: string; slot: "static" | "oauth" }
export const listMcpServices = (signal?: AbortSignal) => codingFetchJson<{ items: McpService[]; pending_changes: McpChange[]; credential_cleanup_pending?: McpCredentialCleanup[] }>("/mcp-services", { signal });
export const retryMcpCredentialCleanup = () => codingFetchJson<{ credential_cleanup_pending: McpCredentialCleanup[] }>("/mcp-services/credential-cleanup", codingJsonInit("POST", {}));
export const preflightMcpService = (configuration: McpConfiguration) => codingFetchJson<{ valid: boolean; notice: string }>("/mcp-services/preflight", codingJsonInit("POST", configuration));
export const prepareMcpService = (data: McpPrepareInput) => codingFetchJson<McpChange>("/mcp-services/prepare", codingJsonInit("POST", data));
export const commitMcpService = (change: McpChange, reference?: string) => codingFetchJson<McpService>(`/mcp-services/changes/${change.id}/commit`, codingJsonInit("POST", { reference: reference ?? null }));
export const discardMcpChange = (id: string) => codingFetchJson(`/mcp-services/changes/${id}`, { method: "DELETE" });
export const bindMcpService = (projectId: number, serviceId: string) => codingFetchJson<McpIntegration>(`/projects/${projectId}/integrations/bind`, codingJsonInit("POST", { service_id: serviceId }));
export const removeMcpService = (service: McpService) => codingFetchJson(`/mcp-services/${service.id}?expected_version=${service.version}`, { method: "DELETE" });
export const logoutMcpService = (service: McpService) => codingFetchJson(`/mcp-services/${service.id}/logout`, codingJsonInit("POST", { expected_version: service.version }));
export async function persistMcpChange(change: McpChange, values?: Record<string, string>) {
  let reference: string | undefined;
  if (change.binding) {
    const binding = change.binding;
    reference = `secret://os-keyring/mcp/${binding.identity}/${binding.service_id}/${binding.version}/${binding.slot}`;
    if (values) reference = (await saveMcpCredential(binding, JSON.stringify(values))).reference;
  }
  return commitMcpService(change, reference);
}
