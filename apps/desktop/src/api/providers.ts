import { apiFetch, ensureApiBase } from "./http";
import type { ProviderStatus } from "../types";

// ---- Provider（第四阶段 M6）----
export async function listProviders(): Promise<ProviderStatus> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/providers`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateProviders(data: {
  provider_type?: "ollama" | "openai" | "claude";
  remote_provider_enabled?: boolean;
  openai_api_key?: string;
  openai_base_url?: string;
  openai_model?: string;
  claude_api_key?: string;
  claude_model?: string;
}): Promise<ProviderStatus> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/providers`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function testProvider(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/providers/test`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
