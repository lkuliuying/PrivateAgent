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
  db_password: string;
  db_name: string;
  ollama_base_url: string;
  llm_model: string;
  embed_model: string;
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
  error: string | null;
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

/** Write desktop config to .env. */
export async function cmdWriteConfig(cfg: ConfigData): Promise<void> {
  return invoke<void>("write_config", { cfg });
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
