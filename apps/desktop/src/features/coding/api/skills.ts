import { codingFetchJson, codingJsonInit } from "./codingHttp";
export interface LocalSkill { id: string; scope: "user" | "project"; name: string; description: string; version: string | null; enabled: boolean; dependencies?: string[]; missing_dependencies: string[]; error: string | null }
export const listSkills = (projectId: number, signal?: AbortSignal) => codingFetchJson<{ items: LocalSkill[] }>(`/projects/${projectId}/skills`, { signal });
export const readSkill = (projectId: number, skill: LocalSkill, signal?: AbortSignal) => codingFetchJson<{ content: string }>(`/projects/${projectId}/skills/${encodeURIComponent(skill.id)}?version=${skill.version}`, { signal });
export const enableSkill = (projectId: number, skill: LocalSkill, enabled: boolean) => codingFetchJson(`/projects/${projectId}/skills/${encodeURIComponent(skill.id)}`, codingJsonInit("PUT", { expected_version: skill.version, enabled }));
export const createSkill = (projectId: number, data: { name: string; scope: string; content: string }) => codingFetchJson(`/projects/${projectId}/skills`, codingJsonInit("POST", data));
