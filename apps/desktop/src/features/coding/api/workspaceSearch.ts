import { codingFetchJson } from "./codingHttp";

export interface WorkspaceSearchHit {
  kind: "project" | "session" | "message";
  project_id: number;
  project_name: string;
  session_id: number | null;
  message_id: number | null;
  title: string;
  excerpt: string;
  updated_at: string;
  status: string;
  archived: boolean;
}
export interface SearchFilters {
  q: string;
  project_id?: number;
  status?: string;
  archived?: boolean;
  since?: string;
  before?: number;
}
export interface WorkspaceSearchPage { items: WorkspaceSearchHit[]; next_cursor: number | null; examined: number }
export function searchWorkspace(filters: SearchFilters, signal?: AbortSignal) {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== "") query.set(key, String(value)); });
  return codingFetchJson<WorkspaceSearchPage>(`/workspace-search?${query}`, { signal });
}
