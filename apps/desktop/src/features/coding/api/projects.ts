/**
 * v0.8.0 W1 · Coding 项目/工作区 API（GET /projects、/projects/{id}/workspaces）
 *
 * 映射层职责：把后端 DTO 收敛为 CodingProjectSummary/CodingWorkspaceSummary，
 * 从结构上剔除 root_path 等敏感字段（红线，contracts.ts 头注）。
 */
import type { Project, ProjectWorkspace } from "../../../types";
import type { CodingProjectSummary, CodingWorkspaceSummary } from "../model/contracts";
import type { CodingFileHint } from "../model/runContracts";
import { codingFetchJson, codingJsonInit } from "./codingHttp";

export function toProjectSummary(dto: Project): CodingProjectSummary {
  return {
    id: dto.id,
    name: dto.name,
    status: dto.status,
    updatedAt: dto.updated_at,
  };
}

export function toWorkspaceSummary(dto: ProjectWorkspace, projectId: number): CodingWorkspaceSummary {
  return {
    id: dto.id,
    projectId,
    kind: dto.kind,
    branchName: dto.branch_name,
    headSha: dto.head_sha,
    status: dto.status,
    lastUsedAt: dto.last_used_at,
  };
}

/** 活跃项目（归档项目软删除，不出现在 Coding 树） */
export async function fetchCodingProjects(): Promise<CodingProjectSummary[]> {
  const list = await codingFetchJson<Project[]>("/projects");
  return list.filter((dto) => dto.status === "active").map(toProjectSummary);
}

export async function fetchCodingWorkspaces(projectId: number): Promise<CodingWorkspaceSummary[]> {
  const list = await codingFetchJson<ProjectWorkspace[]>(`/projects/${projectId}/workspaces`);
  return list
    .filter((dto) => dto.status !== "archived")
    .map((dto) => toWorkspaceSummary(dto, projectId));
}

/** 幂等补建根工作区（POST /projects/{id}/workspaces/root/ensure，201） */
export async function ensureCodingRootWorkspace(projectId: number): Promise<CodingWorkspaceSummary> {
  const dto = await codingFetchJson<ProjectWorkspace>(
    `/projects/${projectId}/workspaces/root/ensure`,
    codingJsonInit("POST", {})
  );
  return toWorkspaceSummary(dto, projectId);
}

/** @ 上下文发现：按名称搜索项目文件（GET /projects/{id}/search?kind=name） */
export async function searchCodingProjectFiles(
  projectId: number,
  query: string
): Promise<CodingFileHint[]> {
  const result = await codingFetchJson<{
    results: Array<{ rel_path: string; name: string; language: string | null }>;
    count: number;
  }>(
    `/projects/${projectId}/search?query=${encodeURIComponent(query)}&kind=name`
  );
  return (result.results ?? []).slice(0, 8).map((item) => ({
    relPath: item.rel_path,
    name: item.name,
    language: item.language,
  }));
}
