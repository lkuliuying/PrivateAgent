import { apiFetch, ensureApiBase } from "./http";
import type {
  CommandProfileCreate,
  CommandProfileUpdate,
  DiagnoseRequest,
  DiagnoseResult,
  ProjectCommandProfile,
  RunResult,
} from "../types";

// ---- 命令配置 / 诊断（第四阶段 M4）----
export async function listProjectCommands(
  projectId: number
): Promise<ProjectCommandProfile[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/commands`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createProjectCommand(
  projectId: number,
  data: CommandProfileCreate
): Promise<ProjectCommandProfile> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/commands`, {
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

export async function updateProjectCommand(
  projectId: number,
  commandId: number,
  data: CommandProfileUpdate
): Promise<ProjectCommandProfile> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/commands/${commandId}`, {
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

export async function deleteProjectCommand(
  projectId: number,
  commandId: number
): Promise<ProjectCommandProfile> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/commands/${commandId}`, {
    method: "DELETE",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function runProjectCommand(
  projectId: number,
  commandId: number
): Promise<RunResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/commands/${commandId}/run`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function diagnoseCommandOutput(
  projectId: number,
  data: DiagnoseRequest
): Promise<DiagnoseResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${projectId}/diagnose-command-output`, {
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
