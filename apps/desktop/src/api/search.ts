import { ensureApiBase } from "./http";

export interface SearchResult {
  type: string;
  id: number;
  title: string;
  snippet: string | null;
  source: string;
  updated_at: string | null;
  action: string;
  meta: Record<string, unknown> | null;
}

export async function search(
  q: string,
  opts?: { types?: string[]; limit?: number }
): Promise<SearchResult[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams({ q });
  if (opts?.types?.length) qs.set("types", opts.types.join(","));
  if (opts?.limit) qs.set("limit", String(opts.limit));
  const r = await fetch(`${base}/search?${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function recordRecentOpen(
  objectType: string,
  objectId: number,
  title?: string
): Promise<void> {
  const base = await ensureApiBase();
  await fetch(`${base}/search/recent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_type: objectType, object_id: objectId, title }),
  });
}
