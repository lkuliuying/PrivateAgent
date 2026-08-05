import { getApiConnection } from "./tauri";

let API_BASE: string | null = null;
let API_TOKEN: string | null = null;

/**
 * Resolve backend API base.
 * - Desktop package: use the port negotiated by the Rust sidecar.
 * - Browser/dev mode: fall back to the manually started backend.
 */
export async function ensureApiBase(): Promise<string> {
  if (API_BASE) return API_BASE;
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
  API_BASE = "http://127.0.0.1:8000";
  API_TOKEN = import.meta.env.VITE_API_TOKEN || null;
}

/** Fetch through the local API boundary with this process's bearer token. */
export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {}
): Promise<Response> {
  if (!API_BASE) await ensureApiBase();
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  if (API_TOKEN && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${API_TOKEN}`);
  }
  return fetch(input, { ...init, headers });
}

/** Clear cached base so the next request negotiates again. */
export function resetApiBase(): void {
  API_BASE = null;
  API_TOKEN = null;
}
