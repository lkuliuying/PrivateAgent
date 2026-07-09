import { ensureApiBase } from "./http";

export interface ExtensionDescriptor {
  id: string;
  title: string;
  kind: string;
  description: string;
  risk_level: string;
  permissions: string[];
  input_schema: Record<string, unknown> | null;
  output_summary: string | null;
  ui_entry: Record<string, unknown> | null;
  enabled: boolean;
  configurable: boolean;
}

export async function listExtensions(
  kind?: string
): Promise<ExtensionDescriptor[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const r = await fetch(`${base}/extensions${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function patchExtension(
  extId: string,
  enabled: boolean
): Promise<ExtensionDescriptor> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/extensions/${encodeURIComponent(extId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
