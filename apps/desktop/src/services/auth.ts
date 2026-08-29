import { apiFetch, ensureApiBase } from "../api/http";
import type {
  AuthResponse,
  AuthUser,
  EmailVerificationSent,
} from "../types/auth";

async function responseJson<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => null);
  throw new Error(
    typeof body?.detail === "string" ? body.detail : `请求失败（${response.status}）`
  );
}

/** 使用邮箱或用户名登录；远程构建中凭据只通过 HTTPS 发送。 */
export async function loginAccount(payload: {
  identifier: string;
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
  username: string;
  verification_code: string;
}): Promise<AuthResponse> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return responseJson<AuthResponse>(response);
}

/** 请求注册验证码；SMTP 凭据仅存在于 sidecar 配置中。 */
export async function sendRegistrationVerificationCode(
  email: string
): Promise<EmailVerificationSent> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}/auth/email-verification/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return responseJson<EmailVerificationSent>(response);
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
