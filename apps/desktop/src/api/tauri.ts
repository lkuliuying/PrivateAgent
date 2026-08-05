import { invoke, isTauri } from "@tauri-apps/api/core";

/** True when the UI is running inside the Tauri desktop runtime. */
export function isDesktopRuntime(): boolean {
  return isTauri();
}

/** Read the API port negotiated by the Rust sidecar, if available. */
export async function getApiPort(): Promise<number | null> {
  if (!isTauri()) return null;
  return invoke<number | null>("get_api_port");
}

export interface ApiConnection {
  port: number;
  token: string;
}

/** Read the current in-memory sidecar port and startup token. */
export async function getApiConnection(): Promise<ApiConnection | null> {
  if (!isTauri()) return null;
  return invoke<ApiConnection | null>("get_api_connection");
}

/** Tauri directory picker; browser/dev mode returns null so callers can fall back to text input. */
export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ directory: true, multiple: false });
    return typeof selected === "string" ? selected : null;
  } catch {
    return null;
  }
}

/** Tauri file picker for a single file; browser/dev mode returns null. */
export async function pickFile(
  filters?: { name: string; extensions: string[] }[]
): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ multiple: false, filters });
    return typeof selected === "string" ? selected : null;
  } catch {
    return null;
  }
}

/** Connection config mirrored with Rust ConfigData and PA_* .env keys. */
export interface ConfigData {
  db_host: string;
  db_port: number;
  db_user: string;
  db_name: string;
  db_password_configured: boolean;
  ollama_base_url: string;
  llm_model: string;
  embed_model: string;
  mcp_enabled: boolean;
}

export interface DepResult {
  mysql_reachable: boolean;
  ollama_reachable: boolean;
}

export interface ConnResult {
  mysql_ok: boolean;
  mysql_error: string | null;
  ollama_ok: boolean;
  ollama_error: string | null;
  ollama_models: string[];
  llm_model_available: boolean;
  embed_model_available: boolean;
}

export interface SidecarStartResult {
  ok: boolean;
  dev_mode: boolean;
  port: number | null;
  token: string | null;
  error: string | null;
}

export type ProviderSecretName = "openai" | "claude";

export interface ProviderSecretStatus {
  openai_configured: boolean;
  claude_configured: boolean;
}

export interface DatabaseSecretPromptResult {
  configured: boolean;
  cancelled: boolean;
}

export interface ProviderSecretPromptResult extends ProviderSecretStatus {
  cancelled: boolean;
}

export interface McpSecretStatus {
  reference: string;
  configured: boolean;
}

export interface McpSecretPromptResult extends McpSecretStatus {
  cancelled: boolean;
}

export interface UpdateInfo {
  version: string;
  date: string | null;
  body: string | null;
}

/** Whether connection config exists in %APPDATA%/personal-assistant/.env. */
export async function cmdConfigExists(): Promise<boolean> {
  return invoke<boolean>("config_exists");
}

/** Read desktop config; Rust returns defaults when no config exists. */
export async function cmdReadConfig(): Promise<ConfigData> {
  return invoke<ConfigData>("read_config");
}

/** Write only non-secret desktop config. */
export async function cmdWriteConfig(cfg: ConfigData): Promise<void> {
  return invoke<void>("write_config", { cfg });
}

/** Ask Windows for the DB password; the renderer never receives the value. */
export async function cmdPromptDatabasePassword(): Promise<DatabaseSecretPromptResult> {
  return invoke<DatabaseSecretPromptResult>("prompt_database_password");
}

/** Return only configured flags; secret values never leave the Rust process. */
export async function cmdProviderSecretStatus(): Promise<ProviderSecretStatus> {
  return invoke<ProviderSecretStatus>("provider_secret_status");
}

/** Ask Windows for a Provider secret; the renderer never receives the value. */
export async function cmdPromptProviderSecret(
  provider: ProviderSecretName
): Promise<ProviderSecretPromptResult> {
  return invoke<ProviderSecretPromptResult>("prompt_provider_secret", { provider });
}

/** Remove a Provider secret from the OS credential store. */
export async function cmdClearProviderSecret(
  provider: ProviderSecretName
): Promise<ProviderSecretStatus> {
  return invoke<ProviderSecretStatus>("clear_provider_secret", { provider });
}

/** Return only whether an MCP credential alias exists in the OS credential store. */
export async function cmdMcpSecretStatus(alias: string): Promise<McpSecretStatus> {
  return invoke<McpSecretStatus>("mcp_secret_status", { alias });
}

/** Ask the native shell for an MCP credential; plaintext never reaches the renderer. */
export async function cmdPromptMcpSecret(alias: string): Promise<McpSecretPromptResult> {
  return invoke<McpSecretPromptResult>("prompt_mcp_secret", { alias });
}

/** Remove an MCP credential and its non-secret startup index entry. */
export async function cmdClearMcpSecret(alias: string): Promise<McpSecretStatus> {
  return invoke<McpSecretStatus>("clear_mcp_secret", { alias });
}

/** Probe whether MySQL and Ollama are reachable on their default ports. */
export async function cmdCheckDependencies(): Promise<DepResult> {
  return invoke<DepResult>("check_dependencies");
}

/** Test MySQL and Ollama with the provided config, including model availability. */
export async function cmdTestConnections(cfg: ConfigData): Promise<ConnResult> {
  return invoke<ConnResult>("test_connections", { cfg });
}

/** Start the FastAPI sidecar; dev mode returns dev_mode=true. */
export async function cmdStartSidecar(): Promise<SidecarStartResult> {
  return invoke<SidecarStartResult>("start_sidecar");
}

/** Check for app updates; null means no update is available. */
export async function cmdCheckForUpdates(): Promise<UpdateInfo | null> {
  return invoke<UpdateInfo | null>("check_for_updates");
}

/** Download and install the available update; caller must relaunch afterwards. */
export async function cmdDownloadAndInstallUpdate(): Promise<void> {
  return invoke<void>("download_and_install_update");
}

/** Relaunch the desktop app after config or updater changes. */
export async function cmdRelaunchApp(): Promise<void> {
  return invoke<void>("relaunch_app");
}
