/**
 * v0.8.0 W1 · Coding 工作台 store
 *
 * 模块级响应式单例（延续 stores/health.ts 惯例，无 pinia）：
 * 侧栏/首页/任务页共享项目树、模型能力与选择状态；API 只在 store 与
 * features/coding/api 内发生，组件经 props 注入本 store（默认单例）。
 *
 * 竞态防护：bootstrap/refresh 使用序号令牌，迟到响应不回写状态
 * （对齐 App.vue contextSeq 范式）；切换项目只改选择，不整页重置树。
 */
import { computed, ref, type ComputedRef, type Ref } from "vue";
import { getHealth, getRuntimeCapabilities } from "../../../api";
import {
  ensureCodingRootWorkspace,
  fetchCodingProjects,
  fetchCodingWorkspaces,
} from "../api/projects";
import { createCodingThread, fetchCodingThreads } from "../api/threads";
import { fetchCodingModelProfiles } from "../api/modelProfiles";
import type {
  CodingApiError,
  CodingHomeState,
  CodingModelProfilesResult,
  CodingProjectNode,
  CodingProjectSummary,
  CodingThreadSummary,
  CodingWorkspaceFetchers,
  CodingWorkspaceSummary,
} from "./contracts";
import { isWorkspaceUsable } from "./contracts";

export type CodingLoadPhase = "idle" | "loading" | "ready" | "error";

export interface CodingWorkspaceStore {
  projects: Ref<CodingProjectSummary[]>;
  workspacesByProject: Ref<Record<number, CodingWorkspaceSummary[]>>;
  threadsByProject: Ref<Record<number, CodingThreadSummary[]>>;
  modelProfiles: Ref<CodingModelProfilesResult | null>;
  /** v0.9.0 H1-A：/capabilities 能力位（权限选项可用性事实源） */
  capabilities: Ref<Record<string, unknown> | null>;
  loadPhase: Ref<CodingLoadPhase>;
  loadError: Ref<CodingApiError | null>;
  sidecarOk: Ref<boolean | null>;
  selectedProjectId: Ref<number | null>;
  selectedWorkspaceId: Ref<number | null>;
  selectedThreadId: Ref<number | null>;
  tree: ComputedRef<CodingProjectNode[]>;
  homeState: ComputedRef<CodingHomeState>;
  selectedProject: ComputedRef<CodingProjectSummary | null>;
  selectedWorkspace: ComputedRef<CodingWorkspaceSummary | null>;
  selectedThread: ComputedRef<CodingThreadSummary | null>;
  bootstrap: () => Promise<void>;
  refresh: () => Promise<void>;
  selectProject: (projectId: number) => void;
  selectWorkspace: (workspaceId: number) => void;
  selectThread: (threadId: number) => void;
  startNewTask: () => void;
  createThreadFromInput: (title: string) => Promise<CodingThreadSummary>;
  ensureWorkspaceForProject: (projectId: number) => Promise<void>;
}

/** 生产数据源（测试/预览经 createCodingWorkspaceStore 注入替换） */
const defaultFetchers: CodingWorkspaceFetchers = {
  projects: fetchCodingProjects,
  workspaces: fetchCodingWorkspaces,
  threads: fetchCodingThreads,
  modelProfiles: fetchCodingModelProfiles,
  health: async () => {
    await getHealth();
    return true;
  },
  createThread: createCodingThread,
  ensureRootWorkspace: ensureCodingRootWorkspace,
  // v0.9.0 H1-A：能力位获取失败按「未提供」处理（不在前端扩大授权）
  capabilities: async () => {
    try {
      return (await getRuntimeCapabilities()) as unknown as Record<
        string,
        unknown
      >;
    } catch {
      return null;
    }
  },
};

function sortByUpdatedAtDesc(a: CodingThreadSummary, b: CodingThreadSummary): number {
  return b.updatedAt.localeCompare(a.updatedAt);
}

export function createCodingWorkspaceStore(
  fetchers: Partial<CodingWorkspaceFetchers> = {}
): CodingWorkspaceStore {
  const source: CodingWorkspaceFetchers = { ...defaultFetchers, ...fetchers };

  const projects = ref<CodingProjectSummary[]>([]);
  const workspacesByProject = ref<Record<number, CodingWorkspaceSummary[]>>({});
  const threadsByProject = ref<Record<number, CodingThreadSummary[]>>({});
  const modelProfiles = ref<CodingModelProfilesResult | null>(null);
  const capabilities = ref<Record<string, unknown> | null>(null);
  const loadPhase = ref<CodingLoadPhase>("idle");
  const loadError = ref<CodingApiError | null>(null);
  const sidecarOk = ref<boolean | null>(null);

  const selectedProjectId = ref<number | null>(null);
  const selectedWorkspaceId = ref<number | null>(null);
  const selectedThreadId = ref<number | null>(null);

  // bootstrap/refresh 序号令牌：迟到响应放弃回写
  let loadSeq = 0;

  const tree = computed<CodingProjectNode[]>(() => {
    return projects.value.map((project) => {
      const workspaces = workspacesByProject.value[project.id] ?? [];
      const threads = threadsByProject.value[project.id] ?? [];
      const knownWorkspaceIds = new Set(workspaces.map((workspace) => workspace.id));
      const orphanThreads = threads.filter(
        (thread) => thread.workspaceId === null || !knownWorkspaceIds.has(thread.workspaceId)
      );
      return {
        project,
        workspaces: workspaces.map((workspace) => ({
          workspace,
          threads: threads
            .filter((thread) => thread.workspaceId === workspace.id)
            .sort(sortByUpdatedAtDesc),
        })),
        orphanThreads: orphanThreads.sort(sortByUpdatedAtDesc),
      };
    });
  });

  const selectedProject = computed(
    () => projects.value.find((project) => project.id === selectedProjectId.value) ?? null
  );

  const selectedWorkspace = computed(() => {
    const projectId = selectedProjectId.value;
    if (projectId === null) return null;
    return (
      (workspacesByProject.value[projectId] ?? []).find(
        (workspace) => workspace.id === selectedWorkspaceId.value
      ) ?? null
    );
  });

  const selectedThread = computed(() => {
    for (const threads of Object.values(threadsByProject.value)) {
      const hit = threads.find((thread) => thread.id === selectedThreadId.value);
      if (hit) return hit;
    }
    return null;
  });

  const homeState = computed<CodingHomeState>(() => {
    if (sidecarOk.value === false) return "sidecar-unavailable";
    if (loadPhase.value === "idle" || loadPhase.value === "loading") return "loading";
    if (loadPhase.value === "error") return "load-error";
    if (projects.value.length === 0) return "no-projects";
    const hasWorkspace = Object.values(workspacesByProject.value).some(
      (list) => list.length > 0
    );
    if (!hasWorkspace) return "no-workspace";
    const profiles = modelProfiles.value;
    if (profiles?.status === "disabled") return "provider-unconfigured";
    if (profiles?.status === "ok" && profiles.profiles.length === 0) {
      return "provider-unconfigured";
    }
    const workspace = selectedWorkspace.value;
    if (workspace && !isWorkspaceUsable(workspace)) return "workspace-invalid";
    return "ready";
  });

  /** 载入首个可用工作区作为默认选择（保持既有选择优先） */
  function applyDefaultSelection() {
    if (selectedProjectId.value === null || !projectExists(selectedProjectId.value)) {
      selectedProjectId.value = projects.value[0]?.id ?? null;
      selectedWorkspaceId.value = null;
    }
    const projectId = selectedProjectId.value;
    if (projectId === null) return;
    const workspaces = workspacesByProject.value[projectId] ?? [];
    const current = workspaces.find((workspace) => workspace.id === selectedWorkspaceId.value);
    if (!current) {
      const preferred = workspaces.find(isWorkspaceUsable) ?? workspaces[0];
      selectedWorkspaceId.value = preferred?.id ?? null;
    }
  }

  function projectExists(projectId: number): boolean {
    return projects.value.some((project) => project.id === projectId);
  }

  async function load(): Promise<void> {
    const mine = ++loadSeq;
    loadPhase.value = "loading";
    loadError.value = null;

    let healthy = true;
    try {
      healthy = await source.health();
    } catch {
      healthy = false;
    }
    if (mine !== loadSeq) return;
    sidecarOk.value = healthy;
    if (!healthy) {
      loadPhase.value = "ready";
      return;
    }

    try {
      const [projectList, profiles] = await Promise.all([
        source.projects(),
        source.modelProfiles(),
      ]);
      if (mine !== loadSeq) return;
      projects.value = projectList;
      modelProfiles.value = profiles;
      // v0.9.0 H1-A：能力位不阻塞首页状态机（真实网络请求），单独尽力获取；
      // 失败/未提供时保持 null，权限高级选项不可选（不在前端扩大授权）。
      void loadCapabilities();

      const workspaceEntries = await Promise.all(
        projectList.map(async (project) => [project.id, await source.workspaces(project.id)] as const)
      );
      if (mine !== loadSeq) return;
      const workspaceMap: Record<number, CodingWorkspaceSummary[]> = {};
      for (const [projectId, list] of workspaceEntries) workspaceMap[projectId] = list;
      workspacesByProject.value = workspaceMap;

      const threadEntries = await Promise.all(
        projectList.map(async (project) => [project.id, await source.threads(project.id)] as const)
      );
      if (mine !== loadSeq) return;
      const threadMap: Record<number, CodingThreadSummary[]> = {};
      for (const [projectId, list] of threadEntries) threadMap[projectId] = list;
      threadsByProject.value = threadMap;

      // 模型 profile 结果只影响 homeState（provider-unconfigured），不单独失败
      applyDefaultSelection();
      loadPhase.value = "ready";
    } catch (cause) {
      if (mine !== loadSeq) return;
      loadPhase.value = "error";
      loadError.value = normalizeError(cause);
    }
  }

  async function loadCapabilities(): Promise<void> {
    if (!source.capabilities) return;
    try {
      capabilities.value = await source.capabilities();
    } catch {
      capabilities.value = null;
    }
  }

  function normalizeError(cause: unknown): CodingApiError {
    const error = cause as CodingApiError;
    if (error && typeof error.status === "number" && typeof error.code === "string") {
      return error;
    }
    return {
      status: 0,
      code: "network_error",
      message: "本地服务连接失败，请稍后重试",
    };
  }

  async function bootstrap(): Promise<void> {
    return load();
  }

  async function refresh(): Promise<void> {
    return load();
  }

  function selectProject(projectId: number): void {
    if (!projectExists(projectId)) return;
    selectedProjectId.value = projectId;
    const workspaces = workspacesByProject.value[projectId] ?? [];
    const preferred = workspaces.find(isWorkspaceUsable) ?? workspaces[0];
    selectedWorkspaceId.value = preferred?.id ?? null;
    selectedThreadId.value = null;
  }

  function selectWorkspace(workspaceId: number): void {
    const projectId = selectedProjectId.value;
    if (projectId === null) return;
    const workspace = (workspacesByProject.value[projectId] ?? []).find(
      (candidate) => candidate.id === workspaceId
    );
    if (!workspace) return;
    selectedWorkspaceId.value = workspaceId;
    selectedThreadId.value = null;
  }

  function selectThread(threadId: number): void {
    for (const [projectId, threads] of Object.entries(threadsByProject.value)) {
      const thread = threads.find((candidate) => candidate.id === threadId);
      if (thread) {
        selectedProjectId.value = thread.projectId ?? Number(projectId);
        selectedWorkspaceId.value = thread.workspaceId;
        selectedThreadId.value = threadId;
        return;
      }
    }
  }

  /** 侧栏「新建任务」：回到首页输入器，保留项目/工作区偏好 */
  function startNewTask(): void {
    selectedThreadId.value = null;
  }

  async function createThreadFromInput(title: string): Promise<CodingThreadSummary> {
    const trimmed = title.trim();
    if (!trimmed) {
      throw { status: 422, code: "coding_context_incomplete", message: "请先描述要完成的任务" } satisfies CodingApiError;
    }
    const projectId = selectedProjectId.value;
    const workspaceId = selectedWorkspaceId.value;
    const workspace =
      projectId !== null && workspaceId !== null
        ? (workspacesByProject.value[projectId] ?? []).find(
            (candidate) => candidate.id === workspaceId
          )
        : undefined;
    if (!workspace || !isWorkspaceUsable(workspace)) {
      throw {
        status: 422,
        code: "coding_context_incomplete",
        message: "请选择一个可用的项目与工作区",
      } satisfies CodingApiError;
    }
    const thread = await source.createThread({
      projectId: workspace.projectId,
      workspaceId: workspace.id,
      title: trimmed,
    });
    const existing = threadsByProject.value[thread.projectId] ?? [];
    threadsByProject.value = {
      ...threadsByProject.value,
      [thread.projectId]: [thread, ...existing.filter((item) => item.id !== thread.id)],
    };
    selectedThreadId.value = thread.id;
    return thread;
  }

  async function ensureWorkspaceForProject(projectId: number): Promise<void> {
    const workspace = await source.ensureRootWorkspace(projectId);
    const existing = workspacesByProject.value[projectId] ?? [];
    workspacesByProject.value = {
      ...workspacesByProject.value,
      [projectId]: [
        workspace,
        ...existing.filter((candidate) => candidate.id !== workspace.id),
      ],
    };
    if (selectedProjectId.value === projectId) {
      selectedWorkspaceId.value = workspace.id;
    }
  }

  return {
    projects,
    workspacesByProject,
    threadsByProject,
    modelProfiles,
    capabilities,
    loadPhase,
    loadError,
    sidecarOk,
    selectedProjectId,
    selectedWorkspaceId,
    selectedThreadId,
    tree,
    homeState,
    selectedProject,
    selectedWorkspace,
    selectedThread,
    bootstrap,
    refresh,
    selectProject,
    selectWorkspace,
    selectThread,
    startNewTask,
    createThreadFromInput,
    ensureWorkspaceForProject,
  };
}

const codingWorkspaceStore = createCodingWorkspaceStore();

export function useCodingWorkspace(): CodingWorkspaceStore {
  return codingWorkspaceStore;
}
