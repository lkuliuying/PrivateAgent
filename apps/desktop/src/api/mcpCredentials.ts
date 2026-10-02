import { invoke, isTauri } from "@tauri-apps/api/core";

export interface McpCredentialBinding {
  identity: string;
  service_id: string;
  version: string;
  slot: "static" | "oauth";
}

export interface McpCredentialStatus {
  reference: string;
  configured: boolean;
}

export async function saveMcpCredential(binding: McpCredentialBinding, value: string): Promise<McpCredentialStatus> {
  if (!isTauri()) throw new Error("静态 MCP 凭据需要桌面系统凭据库，请使用桌面客户端");
  if (binding.slot !== "static") throw new Error("OAuth 凭据只能由本机连接流程保存");
  return invoke<McpCredentialStatus>("set_mcp_credential", { binding, value });
}
