import { apiFetch as fetch, ensureApiBase } from "./http";

export type McpTransport = "stdio" | "streamable_http";

export interface McpDiscoveredTool {
  name: string;
  title?: string | null;
  description?: string | null;
  input_schema: Record<string, unknown>;
  output_schema?: Record<string, unknown> | null;
}

export interface McpServer {
  id: string;
  name: string;
  transport: McpTransport;
  command: string | null;
  args: string[];
  working_directory: string | null;
  url: string | null;
  env_names: string[];
  secret_ref_names: string[];
  allow_insecure_local: boolean;
  allow_private_network: boolean;
  trusted: boolean;
  enabled: boolean;
  allowed_tools: string[];
  timeout_ms: number;
  max_output_bytes: number;
  status: string;
  last_error_code: string | null;
  tools: McpDiscoveredTool[];
  resources: Array<Record<string, unknown>>;
  prompts: Array<Record<string, unknown>>;
  discovery_sha256: string | null;
  last_checked_at: string | null;
  discovered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpServerCreate {
  name: string;
  transport: McpTransport;
  command?: string | null;
  args?: string[];
  working_directory?: string | null;
  url?: string | null;
  env?: Record<string, string>;
  secret_refs?: Record<string, string>;
  allow_insecure_local?: boolean;
  allow_private_network?: boolean;
  trusted?: boolean;
  enabled?: boolean;
  allowed_tools?: string[];
  timeout_ms?: number;
  max_output_bytes?: number;
}

export interface McpCallLog {
  id: number;
  run_id: string | null;
  tool_name: string;
  request_sha256: string;
  status: string;
  error_code: string | null;
  duration_ms: number;
  output_bytes: number;
  created_at: string;
}

async function detail(response: Response): Promise<string> {
  const body = await response.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`;
}

export async function listMcpServers(): Promise<McpServer[]> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/mcp/servers`);
  if (!response.ok) throw new Error(await detail(response));
  return response.json();
}

export async function createMcpServer(body: McpServerCreate): Promise<McpServer> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/mcp/servers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await detail(response));
  return response.json();
}

export async function updateMcpServerState(
  server: Pick<McpServer, "id" | "trusted" | "enabled" | "allowed_tools">
): Promise<McpServer> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/mcp/servers/${encodeURIComponent(server.id)}/state`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trusted: server.trusted,
      enabled: server.enabled,
      allowed_tools: server.allowed_tools,
    }),
  });
  if (!response.ok) throw new Error(await detail(response));
  return response.json();
}

export async function discoverMcpServer(serverId: string): Promise<McpServer> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/mcp/servers/${encodeURIComponent(serverId)}/discover`,
    { method: "POST" }
  );
  if (!response.ok) throw new Error(await detail(response));
  return response.json();
}

export async function deleteMcpServer(serverId: string): Promise<void> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/mcp/servers/${encodeURIComponent(serverId)}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 204) throw new Error(await detail(response));
}

export async function listMcpCalls(serverId: string): Promise<McpCallLog[]> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/mcp/servers/${encodeURIComponent(serverId)}/calls?limit=50`
  );
  if (!response.ok) throw new Error(await detail(response));
  return response.json();
}
