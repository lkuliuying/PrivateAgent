/**
 * v0.8.0 W1 · Coding 首页开发预览夹具
 *
 * 机制与 ?workspace-preview 相同：仅 import.meta.env.DEV 且显式
 * ?coding-preview=<key> 时由 App.vue 动态 import（生产构建不进入）。
 * 夹具直接实现 CodingWorkspaceFetchers，返回与后端 DTO 映射后一致的
 * 摘要（「禁止虚构后端状态」——状态语义对齐 W0 冻结矩阵 §3 第 1–6 项）。
 */
import type {
  CodingProjectSummary,
  CodingThreadSummary,
  CodingWorkspaceFetchers,
  CodingWorkspaceSummary,
} from "../model/contracts";
import { createCodingWorkspaceStore, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";

export const CODING_HOME_PREVIEW_KEYS = [
  "no-projects",
  "no-workspace",
  "provider-unconfigured",
  "sidecar-unavailable",
  "workspace-invalid",
  "ready",
] as const;

export type CodingHomePreviewKey = (typeof CODING_HOME_PREVIEW_KEYS)[number];

function iso(minutesAgo: number): string {
  return new Date(Date.now() - minutesAgo * 60_000).toISOString();
}

function project(id: number, name: string): CodingProjectSummary {
  return { id, name, status: "active", updatedAt: iso(5) };
}

function workspace(
  id: number,
  projectId: number,
  overrides: Partial<CodingWorkspaceSummary> = {}
): CodingWorkspaceSummary {
  return {
    id,
    projectId,
    kind: id === projectId * 100 + 1 ? "root" : "git_worktree",
    branchName: id === projectId * 100 + 1 ? null : "feature/ui",
    headSha: "ab" + "0".repeat(38),
    status: "active",
    lastUsedAt: iso(30),
    ...overrides,
  };
}

function thread(
  id: number,
  projectId: number,
  workspaceId: number,
  title: string,
  minutesAgo: number
): CodingThreadSummary {
  return {
    id,
    title,
    projectId,
    workspaceId,
    updatedAt: iso(minutesAgo),
    lastRunId: null,
  };
}

const READY_PROJECTS = [project(1, "PrivateAgent"), project(2, "网站重构")];
const READY_WORKSPACES: Record<number, CodingWorkspaceSummary[]> = {
  1: [
    workspace(101, 1, { kind: "root", branchName: null }),
    workspace(102, 1, { kind: "git_worktree", branchName: "feature/coding-workbench" }),
  ],
  2: [workspace(201, 2, { kind: "root", branchName: null })],
};
const READY_THREADS: Record<number, CodingThreadSummary[]> = {
  1: [
    thread(11, 1, 101, "修复窄屏侧栏遮挡问题", 12),
    thread(12, 1, 102, "梳理 coding 模块依赖", 90),
    thread(13, 1, 102, "为 store 补充竞态测试", 26 * 60),
  ],
  2: [thread(21, 2, 201, "首页视觉走查", 3 * 24 * 60)],
};

const OK_PROFILES = {
  status: "ok" as const,
  profiles: [
    {
      id: "local-coder",
      provider: "ollama" as const,
      displayName: "Qwen3 Coder 30B",
      isLocal: true,
      reasoningEfforts: ["low", "medium", "high"],
    },
  ],
};

function previewFetchers(key: CodingHomePreviewKey): Partial<CodingWorkspaceFetchers> {
  // 预览默认 sidecar 可达（除显式 sidecar-unavailable 场景），不发真实请求
  const base: Partial<CodingWorkspaceFetchers> = { health: async () => true };
  const withBase = (extra: Partial<CodingWorkspaceFetchers>): Partial<CodingWorkspaceFetchers> => ({
    ...base,
    ...extra,
  });
  switch (key) {
    case "no-projects":
      return withBase({
        projects: async () => [],
        workspaces: async () => [],
        threads: async () => [],
        modelProfiles: async () => OK_PROFILES,
      });
    case "no-workspace":
      return withBase({
        projects: async () => [READY_PROJECTS[0]],
        workspaces: async () => [],
        threads: async () => [],
        modelProfiles: async () => OK_PROFILES,
      });
    case "provider-unconfigured":
      return withBase({
        projects: async () => READY_PROJECTS,
        workspaces: async (projectId) => READY_WORKSPACES[projectId] ?? [],
        threads: async (projectId) => READY_THREADS[projectId] ?? [],
        modelProfiles: async () => ({ status: "disabled" as const }),
      });
    case "sidecar-unavailable":
      return withBase({
        health: async () => false,
        projects: async () => READY_PROJECTS,
        workspaces: async (projectId) => READY_WORKSPACES[projectId] ?? [],
        threads: async (projectId) => READY_THREADS[projectId] ?? [],
        modelProfiles: async () => OK_PROFILES,
      });
    case "workspace-invalid":
      return withBase({
        projects: async () => [READY_PROJECTS[0]],
        workspaces: async (projectId) => {
          if (projectId !== 1) return [];
          // 唯一工作区路径缺失：默认选择落到它，首页派生 workspace-invalid
          const [root] = READY_WORKSPACES[1];
          return [{ ...root, status: "missing" as const }];
        },
        threads: async (projectId) => READY_THREADS[projectId] ?? [],
        modelProfiles: async () => OK_PROFILES,
      });
    case "ready":
      return withBase({
        projects: async () => READY_PROJECTS,
        workspaces: async (projectId) => READY_WORKSPACES[projectId] ?? [],
        threads: async (projectId) => READY_THREADS[projectId] ?? [],
        modelProfiles: async () => OK_PROFILES,
      });
  }
}

export function createCodingWorkspacePreviewStore(key: CodingHomePreviewKey): CodingWorkspaceStore {
  const store = createCodingWorkspaceStore(previewFetchers(key));
  void store.bootstrap();
  return store;
}
