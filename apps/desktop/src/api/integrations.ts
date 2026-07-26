import { apiFetch, ensureApiBase } from "./http";

export interface IntegrationSource {
  id: number;
  kind: string;
  title: string;
  config_json: Record<string, unknown> | null;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
}

export interface IntegrationImport {
  id: number;
  source_id: number | null;
  source_kind: string;
  summary_json: Record<string, unknown> | null;
  target_type: string | null;
  target_id: number | null;
  reversible: boolean;
  reversal_info_json: Record<string, unknown> | null;
  status: string;
  error_message: string | null;
  created_at: string;
  reverted_at: string | null;
}

export interface IntegrationPreview {
  file_path: string;
  event_count: number;
  sample_titles: string[];
  events: Array<Record<string, unknown>>;
  target: string;
}

export async function listIntegrationSources(): Promise<IntegrationSource[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/integrations/sources`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createIntegrationSource(data: {
  kind?: string;
  title: string;
  file_path: string;
  target?: string;
}): Promise<IntegrationSource> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/integrations/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function previewIntegration(
  sourceId: number
): Promise<IntegrationPreview> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/integrations/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function runIntegrationImport(
  sourceId: number,
  target?: string
): Promise<IntegrationImport> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/integrations/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, target }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listIntegrationImports(): Promise<IntegrationImport[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/integrations/imports`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function revertIntegrationImport(
  importId: number
): Promise<IntegrationImport> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/integrations/imports/${importId}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
