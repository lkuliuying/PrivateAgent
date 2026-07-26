import { getSidecarApiInfo, isDesktopRuntime } from "./tauri";

let API_BASE: string | null = null;
let API_TOKEN = "";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly path: string
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/**
 * Resolve backend API base.
 * - Desktop package: use the port negotiated by the Rust sidecar.
 * - Browser/dev mode: fall back to the manually started backend.
 */
export async function ensureApiBase(): Promise<string> {
  if (API_BASE) return API_BASE;
  const desktop = isDesktopRuntime();
  try {
    const info = await getSidecarApiInfo();
    if (info) {
      setApiConnection(info.port, info.api_token);
      return `http://127.0.0.1:${info.port}`;
    }
  } catch {
    if (desktop) throw new Error("无法读取桌面后端安全连接信息");
  }
  // 只有纯浏览器开发模式可隐式回退；Tauri dev 由 App 启动流程显式设置默认端口。
  if (desktop) throw new Error("桌面后端尚未就绪");
  API_BASE = "http://127.0.0.1:8000";
  return API_BASE;
}

/** Atomically set the sidecar endpoint and its process-lifetime credential. */
export function setApiConnection(port: number, apiToken: string | null): void {
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error("无效的桌面后端端口");
  }
  const normalizedToken = apiToken?.trim() ?? "";
  if (normalizedToken && !/^[a-f0-9]{64}$/.test(normalizedToken)) {
    throw new Error("无效的桌面后端安全凭据");
  }
  API_BASE = `http://127.0.0.1:${port}`;
  API_TOKEN = normalizedToken;
}

/** Set a backend port without authentication (browser/manual development only). */
export function setApiBase(port: number): void {
  setApiConnection(port, null);
}

/** Fall back to the default manual backend used in dev mode. */
export function setApiBaseDefault(): void {
  API_BASE = "http://127.0.0.1:8000";
  API_TOKEN = "";
}

/** Clear cached base so the next request negotiates again. */
export function resetApiBase(): void {
  API_BASE = null;
  API_TOKEN = "";
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

/**
 * Single native-fetch boundary for local API traffic. The ephemeral token is
 * attached only to the negotiated loopback origin and never persisted.
 */
export function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const inheritedHeaders = input instanceof Request ? input.headers : undefined;
  const headers = new Headers(init?.headers ?? inheritedHeaders);
  if (API_TOKEN) {
    if (!API_BASE || new URL(requestUrl(input)).origin !== new URL(API_BASE).origin) {
      return Promise.reject(new Error("拒绝向非本地 API 发送桌面鉴权信息"));
    }
    headers.set("Authorization", `Bearer ${API_TOKEN}`);
  }
  return fetch(input, {
    ...init,
    credentials: "omit",
    headers,
  });
}

async function errorDetail(response: Response): Promise<string> {
  const fallback = `HTTP ${response.status}`;
  const body = await response.json().catch(() => null);
  if (!body || typeof body !== "object") return fallback;
  const detail = "detail" in body ? body.detail : null;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item ? String(item.msg) : ""
      )
      .filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  return fallback;
}

function requestHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");
  return headers;
}

/** Typed JSON request boundary shared by all API domains. */
export async function requestJson<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}${path}`, {
    ...init,
    headers: requestHeaders(init),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response), path);
  }
  return response.json() as Promise<T>;
}

/** Request boundary for 202/204 endpoints that intentionally return no body. */
export async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}${path}`, {
    ...init,
    headers: requestHeaders(init),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response), path);
  }
}
