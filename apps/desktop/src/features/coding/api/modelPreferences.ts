import { codingFetchJson, codingJsonInit } from "./codingHttp";
export type ModelScope = "global" | "project" | "session";
export interface ModelPreference { profile_id: string | null; source: ModelScope; overrides: Record<ModelScope, string | null>; available: boolean }
export function getModelPreference(projectId: number | null, sessionId: number | null): Promise<ModelPreference> {
  const query = new URLSearchParams();
  if (projectId) query.set("project_id", String(projectId));
  if (sessionId) query.set("session_id", String(sessionId));
  return codingFetchJson(`/model-preferences?${query}`);
}
export function setModelPreference(scope: ModelScope, profileId: string | null, projectId: number | null, sessionId: number | null): Promise<ModelPreference> {
  return codingFetchJson("/model-preferences", codingJsonInit("PUT", { scope, profile_id: profileId, project_id: projectId, session_id: sessionId }));
}
