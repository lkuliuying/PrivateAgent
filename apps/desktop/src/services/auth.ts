import { apiFetch, ensureApiBase } from "../api/http";
import type { AuthResponse, AuthUser } from "../types/auth";

async function responseJson<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => null);
  throw new Error(
    typeof body?.detail === "string" ? body.detail : `请求失败（${response.status}）`
  );
}

/** 使用邮箱和密码登录，密码只通过 HTTPS 请求发送给服务端。 */
export async function loginAccount(payload: {
  email: string;
  password: string;
}): Promise<AuthResponse> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return responseJson<AuthResponse>(response);
}

/** 注册新账号；服务端负责密码哈希和首个管理员判定。 */
export async function registerAccount(payload: {
  email: string;
  password: string;
  display_name: string;
}): Promise<AuthResponse> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return responseJson<AuthResponse>(response);
}

export async function getCurrentAccount(): Promise<AuthUser> {
  const base = await ensureApiBase();
  return responseJson<AuthUser>(await apiFetch(`${base}/auth/me`));
}

export async function logoutAccount(): Promise<void> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}/auth/logout`, { method: "POST" });
  if (!response.ok && response.status !== 401) {
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string" ? body.detail : "退出登录失败"
    );
  }
}
