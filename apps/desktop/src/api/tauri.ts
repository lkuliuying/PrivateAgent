import { invoke, isTauri } from "@tauri-apps/api/core";

export interface ModelProviderSecretStatus {
  reference: string;
  configured: boolean;
}

export interface UpdateInfo {
  version: string;
  date: string | null;
  body: string | null;
}

export interface UpdateConfiguration {
  version: string;
  endpoint: string | null;
  target: string;
}

export async function cmdGetUpdateConfiguration(): Promise<UpdateConfiguration> {
  return invoke<UpdateConfiguration>("get_update_configuration");
}

export function isDesktopRuntime(): boolean {
  return isTauri();
}

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

export async function cmdModelProviderSecretStatus(
  alias: string
): Promise<ModelProviderSecretStatus> {
  return invoke<ModelProviderSecretStatus>("model_provider_secret_status", { alias });
}

export async function cmdSetModelProviderSecret(
  alias: string,
  secret: string
): Promise<ModelProviderSecretStatus> {
  return invoke<ModelProviderSecretStatus>("set_model_provider_secret", {
    alias,
    secret,
  });
}

export async function cmdClearModelProviderSecret(
  alias: string
): Promise<ModelProviderSecretStatus> {
  return invoke<ModelProviderSecretStatus>("clear_model_provider_secret", { alias });
}

export async function cmdCheckForUpdates(endpoint?: string): Promise<UpdateInfo | null> {
  return invoke<UpdateInfo | null>("check_for_updates", { endpoint });
}

export async function cmdDownloadAndInstallUpdate(expectedVersion?: string, endpoint?: string): Promise<void> {
  return invoke<void>("download_and_install_update", { expectedVersion, endpoint });
}

export async function cmdRelaunchApp(): Promise<void> {
  return invoke<void>("relaunch_app");
}

export async function listenForMainWindowClose(
  handler: () => void | Promise<void>
): Promise<() => void> {
  if (!isTauri()) return () => undefined;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow().onCloseRequested((event) => {
    event.preventDefault();
    return handler();
  });
}

export async function cmdHideMainWindow(): Promise<void> {
  return invoke<void>("hide_main_window");
}

export async function cmdExitApp(): Promise<void> {
  return invoke<void>("exit_app");
}
