import type { SqlProfileDeleteResult, SqlReadonlyProfile } from "../types";
import { apiFetch as fetch, ensureApiBase } from "./http";

async function requireOk(response: Response): Promise<void> {
  if (response.ok) return;
  const body = await response.json().catch(() => null);
  throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
}

export async function listSqlProfiles(enabledOnly = false): Promise<SqlReadonlyProfile[]> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/sql-profiles${enabledOnly ? "?enabled_only=true" : ""}`
  );
  await requireOk(response);
  return response.json();
}

export async function createSqlProfile(
  payload: Record<string, unknown>
): Promise<SqlReadonlyProfile> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/sql-profiles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await requireOk(response);
  return response.json();
}

export async function updateSqlProfile(
  profileId: number,
  payload: Record<string, unknown>
): Promise<SqlReadonlyProfile> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/sql-profiles/${profileId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await requireOk(response);
  return response.json();
}

export async function deleteSqlProfile(
  profileId: number
): Promise<SqlProfileDeleteResult> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/sql-profiles/${profileId}`, {
    method: "DELETE",
  });
  await requireOk(response);
  return response.json();
}
