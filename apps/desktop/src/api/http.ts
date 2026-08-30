import { getApiConnection } from "./tauri";
import { clearAccessToken, getAccessToken } from "../auth/session";
import { fetchLocalProject, isLocalProjectPath, usesLocalExecutor } from "../services/localExecutor";

let API_BASE: string | null = null;
let API_TOKEN: string | null = null;

function normalizeRemoteApi(value: string): string {
  if (!value) throw new Error("服务器地址不能为空");
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("服务器地址必须是完整的 HTTP(S) 地址");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("远程 API 仅支持 HTTP(S)");
  }
  if (url.username || url.password) {
    throw new Error("服务器地址不能包含用户名或密码");
  }
  if (url.search || url.hash) {
    throw new Error("服务器地址不能包含查询参数或片段");
  }
  const loopback = ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  if (import.meta.env.PROD && url.protocol !== "https:" && !loopback) {
    throw new Error("生产环境远程 API 必须使用 HTTPS");
  }
  return value.replace(/\/+$/, "");
}

function configuredRemoteApi(): string | null {
  const value = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  return value ? normalizeRemoteApi(value) : null;
}

/** 构建时配置的账号和模型服务器；本机项目执行器使用独立连接。 */
export function hasConfiguredRemoteApi(): boolean {
  return configuredRemoteApi() !== null;
}

/**
 * Resolve backend API base.
 * - Desktop package: use the port negotiated by the Rust sidecar.
 * - Browser/dev mode: fall back to the manually started backend.
 */
export async function ensureApiBase(): Promise<string> {
  if (API_BASE) return API_BASE;
  const remote = configuredRemoteApi();
  if (remote) {
    API_BASE = remote;
    API_TOKEN = null;
    return API_BASE;
  }
  try {
    const connection = await getApiConnection();
    if (connection) {
      API_BASE = `http://127.0.0.1:${connection.port}`;
      API_TOKEN = connection.token;
      return API_BASE;
    }
  } catch {
    // Tauri command failures fall back to the dev backend so browser mode remains usable.
  }
  API_BASE = "http://127.0.0.1:8000";
  API_TOKEN = import.meta.env.VITE_API_TOKEN || null;
  return API_BASE;
}

/** Set backend port returned by start_sidecar and bypass cached negotiation. */
export function setApiBase(port: number, token: string): void {
  API_BASE = `http://127.0.0.1:${port}`;
  API_TOKEN = token;
}

/** Fall back to the default manual backend used in dev mode. */
export function setApiBaseDefault(): void {
  API_BASE = configuredRemoteApi() || "http://127.0.0.1:8000";
  API_TOKEN = API_BASE.startsWith("http://127.0.0.1:")
    ? import.meta.env.VITE_API_TOKEN || null
    : null;
}

function targetsConfiguredApi(input: RequestInfo | URL): boolean {
  if (!API_BASE) return false;
  try {
    const base = new URL(`${API_BASE}/`);
    const raw = input instanceof Request ? input.url : input.toString();
    const target = new URL(raw, base);
    const basePath = base.pathname.endsWith("/") ? base.pathname : `${base.pathname}/`;
    return (
      target.origin === base.origin &&
      (target.pathname === base.pathname.replace(/\/$/, "") ||
        target.pathname.startsWith(basePath))
    );
  } catch {
    return false;
  }
}

/** Fetch through the local API boundary with this process's bearer token. */
export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {}
): Promise<Response> {
  if (!API_BASE) await ensureApiBase();
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  const accessToken = getAccessToken();
  const authorizationToken = accessToken || API_TOKEN;
  const isApiRequest = targetsConfiguredApi(input);
  if (authorizationToken && isApiRequest && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${authorizationToken}`);
  }
  const url = new URL(input instanceof Request ? input.url : input.toString(), `${API_BASE}/`);
  let response: Response;
  if (usesLocalExecutor() && isApiRequest && isLocalProjectPath(url.pathname)) {
    const requestInit = input instanceof Request
      ? { method: input.method, body: input.body && init.body === undefined ? await input.clone().arrayBuffer() : undefined, signal: input.signal, ...init, headers }
      : { ...init, headers };
    response = await fetchLocalProject(url.pathname + url.search, requestInit);
  } else {
    response = await fetch(input, { ...init, headers });
  }
  if (response.status === 401 && accessToken && accessToken === getAccessToken() && isApiRequest) {
    clearAccessToken();
    window.dispatchEvent(new CustomEvent("pa:session-expired"));
  }
  return response;
}

/** Clear cached base so the next request negotiates again. */
export function resetApiBase(): void {
  API_BASE = null;
  API_TOKEN = null;
}
