import { apiFetch, ensureApiBase } from "./http";
import type { ScanResponse, SummarizeResult } from "../types";

// ---- 文件处理（第二阶段 M2）----
export async function summarizeFile(path: string): Promise<SummarizeResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/files/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function scanDirectory(path: string): Promise<ScanResponse> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/files/scan?path=${encodeURIComponent(path)}`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
