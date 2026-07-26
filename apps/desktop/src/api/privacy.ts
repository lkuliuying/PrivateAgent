import { apiFetch, ensureApiBase } from "./http";
import type { MaintenanceHealthReport, PrivacyPreview, ProviderCallAudit } from "../types";

// ---- 隐私维护 ----
export async function privacyPreview(data: {
  purpose?: string;
  provider_type?: string;
  include_kb?: boolean;
  include_memories?: boolean;
  include_messages?: boolean;
  estimated_message_chars?: number;
}): Promise<PrivacyPreview> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/privacy/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listPrivacyAudits(
  remote?: boolean
): Promise<ProviderCallAudit[]> {
  const base = await ensureApiBase();
  const qs = remote === undefined ? "" : `?remote=${String(remote)}`;
  const r = await apiFetch(`${base}/privacy/audits${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMaintenanceHealthReport(): Promise<MaintenanceHealthReport> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/maintenance/health-report`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
