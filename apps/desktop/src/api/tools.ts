import { apiFetch, ensureApiBase } from "./http";
import type { ToolDefinition, TrustedPath } from "../types";

// ---- 工具调用（第二阶段 M1）----
export async function listTools(): Promise<ToolDefinition[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/tools`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 文件授权（M1 文本式，M2 替换为 Tauri 选择器）----
export async function authorizeFile(
  path: string,
  kind: "file" | "directory" = "file"
): Promise<TrustedPath> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/files/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, kind }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listTrustedPaths(): Promise<TrustedPath[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/files/trusted`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
