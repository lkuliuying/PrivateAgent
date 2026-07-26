import { getApiPort } from "./tauri";

let API_BASE: string | null = null;

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
  try {
    const port = await getApiPort();
    if (port) {
      API_BASE = `http://127.0.0.1:${port}`;
      return API_BASE;
    }
  } catch {
    // Tauri command failures fall back to the dev backend so browser mode remains usable.
  }
  API_BASE = "http://127.0.0.1:8000";
  return API_BASE;
}

/** Set backend port returned by start_sidecar and bypass cached negotiation. */
export function setApiBase(port: number): void {
  API_BASE = `http://127.0.0.1:${port}`;
}

/** Fall back to the default manual backend used in dev mode. */
export function setApiBaseDefault(): void {
  API_BASE = "http://127.0.0.1:8000";
}

/** Clear cached base so the next request negotiates again. */
export function resetApiBase(): void {
  API_BASE = null;
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
  const response = await fetch(`${base}${path}`, {
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
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: requestHeaders(init),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response), path);
  }
}
