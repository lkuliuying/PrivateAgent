import { getApiPort } from "./tauri";

let API_BASE: string | null = null;

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
