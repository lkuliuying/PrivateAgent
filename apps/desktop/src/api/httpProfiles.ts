import type { HttpEndpointProfile, HttpProfileDeleteResult } from "../types";
import { apiFetch as fetch, ensureApiBase } from "./http";

async function requireOk(response: Response): Promise<void> {
  if (response.ok) return;
  const body = await response.json().catch(() => null);
  throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
}

export async function listHttpProfiles(enabledOnly = false): Promise<HttpEndpointProfile[]> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/http-profiles${enabledOnly ? "?enabled_only=true" : ""}`
  );
  await requireOk(response);
  return response.json();
}

export async function createHttpProfile(
  payload: Record<string, unknown>
): Promise<HttpEndpointProfile> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/http-profiles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await requireOk(response);
  return response.json();
}

export async function updateHttpProfile(
  profileId: number,
  payload: Record<string, unknown>
): Promise<HttpEndpointProfile> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/http-profiles/${profileId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await requireOk(response);
  return response.json();
}

export async function deleteHttpProfile(
  profileId: number
): Promise<HttpProfileDeleteResult> {
  const base = await ensureApiBase();
  const response = await fetch(`${base}/http-profiles/${profileId}`, {
    method: "DELETE",
  });
  await requireOk(response);
  return response.json();
}
