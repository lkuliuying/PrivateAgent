import { apiFetch, ensureApiBase } from "./http";
import type { ApplyResult, PatchSet, PatchSetCreate } from "../types";

// ---- Patch set（第四阶段 M4）----
export async function listPatchSets(projectId: number): Promise<PatchSet[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/patch-sets`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createPatchSet(
  projectId: number,
  data: PatchSetCreate
): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/patch-sets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getPatchSet(patchSetId: number): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/patch-sets/${patchSetId}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function submitPatchSet(patchSetId: number): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/patch-sets/${patchSetId}/submit`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function applyPatchSet(patchSetId: number): Promise<ApplyResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/patch-sets/${patchSetId}/apply`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function rejectPatchSet(patchSetId: number): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/patch-sets/${patchSetId}/reject`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function rollbackPatchSet(patchSetId: number): Promise<ApplyResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/patch-sets/${patchSetId}/rollback`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
