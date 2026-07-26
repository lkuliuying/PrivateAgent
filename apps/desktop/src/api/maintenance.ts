import { apiFetch, ensureApiBase } from "./http";

export interface IntegrityFinding {
  id: number;
  check_name: string;
  severity: string;
  ref_type: string | null;
  ref_id: number | null;
  detail_json: Record<string, unknown> | null;
  suggested_action: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface RepairPlanItem {
  finding_id: number;
  check_name: string;
  severity: string;
  ref_type: string | null;
  ref_id: number | null;
  suggested_action: string | null;
  detail: Record<string, unknown> | null;
  impact: string;
  destructive: boolean;
}

export async function listIntegrity(status?: string): Promise<IntegrityFinding[]> {
  const base = await ensureApiBase();
  const qs = status ? `?status=${status}` : "";
  const r = await apiFetch(`${base}/maintenance/integrity${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function runIntegrity(): Promise<IntegrityFinding[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/maintenance/integrity/run`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function repairPlan(): Promise<RepairPlanItem[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/maintenance/repair-plan`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function applyRepair(
  findingId: number
): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/maintenance/repair-plan/${findingId}/apply`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
