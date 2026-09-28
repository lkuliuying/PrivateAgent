import { codingFetchJson } from "./codingHttp";

export interface WorkspaceFile {
  rel_path: string;
  name: string;
  kind: "directory" | "file";
  size_bytes: number | null;
}
export interface DirectoryPage { entries: WorkspaceFile[]; next_cursor: string | null; total: number }
export interface FilePage { rel_path: string; content: string; sha256: string; offset: number; next_offset: number | null; total_chars: number }

export function listWorkspaceFiles(project: number, workspace: number, path: string, cursor: string | null, signal: AbortSignal): Promise<DirectoryPage> {
  const query = new URLSearchParams({ path });
  if (cursor) query.set("cursor", cursor);
  return codingFetchJson(`/projects/${project}/workspaces/${workspace}/files?${query}`, { signal });
}
export function readWorkspaceFile(project: number, workspace: number, path: string, offset: number, version: string | null, signal: AbortSignal): Promise<FilePage> {
  const query = new URLSearchParams({ path, offset: String(offset) });
  if (version) query.set("version", version);
  return codingFetchJson(`/projects/${project}/workspaces/${workspace}/file?${query}`, { signal });
}
