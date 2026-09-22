const LOCAL_ACCESS_TOKEN_KEY = "pa_local_access_token";

/** 升级时仅移除旧平台凭证和入口偏好，不迁移或删除历史数据。 */
export function discardLegacyAccountSession(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem("pa_access_token");
  window.localStorage.removeItem("privateagent.local-access.v1");
}

export function getLocalAccessToken(): string | null {
  return typeof window === "undefined" ? null : window.sessionStorage.getItem(LOCAL_ACCESS_TOKEN_KEY);
}

export function getWorkspaceAccessToken(): string | null {
  return getLocalAccessToken();
}

export function setLocalAccessToken(token: string): void {
  discardLegacyAccountSession();
  window.sessionStorage.setItem(LOCAL_ACCESS_TOKEN_KEY, token);
}

export function clearLocalSession(): void {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(LOCAL_ACCESS_TOKEN_KEY);
}
