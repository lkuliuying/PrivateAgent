import { apiFetch, ensureApiBase } from "./http";

// ---- 设置 ----
export interface AppSettings {
  llm_model: string;
  embed_model: string;
  llm_temperature: number;
  llm_context_length: number;
  kb_enabled_by_default: boolean;
  provider_type: "ollama" | "openai" | "claude";
  remote_provider_enabled: boolean;
  openai_api_key: string;
  openai_base_url: string;
  openai_model: string;
  claude_api_key: string;
  claude_model: string;
  reminders_enabled: boolean;
  reminder_tick_seconds: number;
  desktop_notifications_enabled: boolean;
}

export async function getSettings(): Promise<AppSettings> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/settings`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateSettings(
  data: Partial<AppSettings>
): Promise<AppSettings> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
