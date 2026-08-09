/**
 * v0.5.0 rc.3：桌面凭据 API 统一边界。
 *
 * HTTP/SQL profile 的 OS keyring 凭据操作全部经此封装；组件不直接
 * 动态导入 Tauri invoke。明文只经原生系统凭据对话框（CredUI）交互，
 * 不进入 Vue 状态。
 */

export type SecretPromptResult = {
  reference: string;
  configured: boolean;
  cancelled: boolean;
};

export type SecretStatus = {
  reference: string;
  configured: boolean;
};

async function isDesktop(): Promise<boolean> {
  try {
    const { isTauri } = await import("@tauri-apps/api/core");
    return Boolean(isTauri());
  } catch {
    return false;
  }
}

async function invoke(name: string, args: Record<string, unknown>): Promise<unknown> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  return tauriInvoke(name, args);
}

export const desktopCapable = isDesktop;

export async function promptHttpProfileSecret(
  name: string,
  slot: string
): Promise<SecretPromptResult> {
  return (await invoke("prompt_http_profile_secret", { name, slot })) as SecretPromptResult;
}

export async function httpProfileSecretStatus(
  name: string,
  slot: string
): Promise<SecretStatus> {
  return (await invoke("http_profile_secret_status", { name, slot })) as SecretStatus;
}

/** 删除单个 http 凭据槽位；返回是否成功（供残留清理重试）。 */
export async function clearHttpProfileSecret(
  name: string,
  slot: string
): Promise<SecretStatus> {
  return (await invoke("clear_http_profile_secret", { name, slot })) as SecretStatus;
}

export async function promptSqlProfileSecret(name: string): Promise<SecretPromptResult> {
  return (await invoke("prompt_sql_profile_secret", { name })) as SecretPromptResult;
}

export async function sqlProfileSecretStatus(name: string): Promise<SecretStatus> {
  return (await invoke("sql_profile_secret_status", { name })) as SecretStatus;
}

export async function clearSqlProfileSecret(name: string): Promise<SecretStatus> {
  return (await invoke("clear_sql_profile_secret", { name })) as SecretStatus;
}

/** 从 keyring 引用解析 slot（secret://os-keyring/http/<name>/<slot>）。 */
export function slotFromHttpReference(reference: string): string | null {
  const match = /^secret:\/\/os-keyring\/http\/[^/]+\/([^/]+)$/.exec(reference);
  return match ? match[1] : null;
}
