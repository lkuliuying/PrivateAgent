import { apiFetch, ensureApiBase } from "./http";
import type {
  CodeFileContent,
  ContentSearchResponse,
  GitDiff,
  GitStatus,
  NameSearchResponse,
  Project,
  ProjectFile,
  ProjectStats,
  ProjectTree,
} from "../types";

// ---- 项目工作区（第三阶段 M0 骨架 / M1 实现）----
export async function listProjects(): Promise<Project[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createProject(
  name: string,
  rootPath: string
): Promise<Project> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, root_path: rootPath }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function archiveProject(id: number): Promise<Project> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function scanProject(id: number): Promise<Project> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${id}/scan`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getProjectStats(id: number): Promise<ProjectStats> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${id}/stats`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getProjectTree(id: number): Promise<ProjectTree> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${id}/tree`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getProjectFiles(
  id: number,
  opts?: { ext?: string; language?: string }
): Promise<ProjectFile[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.ext) params.set("ext", opts.ext);
  if (opts?.language) params.set("language", opts.language);
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`${base}/projects/${id}/files${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function searchProject(
  id: number,
  query: string,
  kind: "name" | "content"
): Promise<NameSearchResponse | ContentSearchResponse> {
  const base = await ensureApiBase();
  const r = await apiFetch(
    `${base}/projects/${id}/search?query=${encodeURIComponent(query)}&kind=${kind}`
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function readProjectFile(
  id: number,
  relPath: string,
  opts?: { startLine?: number; maxLines?: number }
): Promise<CodeFileContent> {
  const base = await ensureApiBase();
  const params = new URLSearchParams({ rel_path: relPath });
  if (opts?.startLine) params.set("start_line", String(opts.startLine));
  if (opts?.maxLines) params.set("max_lines", String(opts.maxLines));
  const r = await apiFetch(`${base}/projects/${id}/read?${params}`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getProjectGitStatus(id: number): Promise<GitStatus> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/projects/${id}/git/status`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getProjectGitDiff(
  id: number,
  cached = false
): Promise<GitDiff> {
  const base = await ensureApiBase();
  const r = await apiFetch(
    `${base}/projects/${id}/git/diff?cached=${cached}`
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
