/**
 * v0.8.0 W1 · Coding 工作台 store
 *
 * 模块级响应式单例，无 pinia：
 * 侧栏/首页/任务页共享项目树、模型能力与选择状态；API 只在 store 与
 * features/coding/api 内发生，组件经 props 注入本 store（默认单例）。
 *
 * 竞态防护：bootstrap/refresh 使用序号令牌，迟到响应不回写状态
 * （对齐 App.vue contextSeq 范式）；切换项目只改选择，不整页重置树。
 */
import { transferFirstTurnDraft } from "./composerDrafts";
import { computed, ref, watch, type ComputedRef, type Ref } from "vue";
import { checkLocalExecutorHealth, setLocalProjectContext } from "../../../services/localExecutor";
import { reconnectDesktopBackend } from "../../../services/backendStartup";
import { getRuntimeCapabilities } from "../../../api";
import {
  ensureCodingRootWorkspace,
  fetchCodingBranches,
  fetchCodingProjects,
  fetchCodingWorkspaces,
  switchCodingBranch,
} from "../api/projects";
import { createCodingThread, fetchCodingThreads } from "../api/threads";
import { fetchCodingModelProfiles } from "../api/modelProfiles";
import type {
  CodingApiError,
  CodingBranchState,
  CodingHomeState,
  CodingFirstTurnPayload,
  CodingModelProfilesResult,
  CodingPendingFirstTurn,
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
  branchesByProject: Ref<Record<number, CodingBranchState>>;
  threadsByProject: Ref<Record<number, CodingThreadSummary[]>>;
  modelProfiles: Ref<CodingModelProfilesResult | null>;
  /** v0.9.0 H1-A：/capabilities 能力位（权限选项可用性事实源） */
  capabilities: Ref<Record<string, unknown> | null>;
  loadPhase: Ref<CodingLoadPhase>;
  loadError: Ref<CodingApiError | null>;
  sidecarOk: Ref<boolean | null>;
  reconnecting: Ref<boolean>;
  selectedProjectId: Ref<number | null>;
  selectedWorkspaceId: Ref<number | null>;
  selectedBranchName: Ref<string | null>;
  selectedThreadId: Ref<number | null>;
  pendingFirstTurn: Ref<CodingPendingFirstTurn | null>;
  tree: ComputedRef<CodingProjectNode[]>;
  homeState: ComputedRef<CodingHomeState>;
  selectedProject: ComputedRef<CodingProjectSummary | null>;
  selectedWorkspace: ComputedRef<CodingWorkspaceSummary | null>;
  selectedThread: ComputedRef<CodingThreadSummary | null>;
  bootstrap: () => Promise<void>;
  refresh: () => Promise<void>;
  reconnect: () => Promise<void>;
  dispose: () => void;
  removeDeletedProject: (projectId: number) => void;
  removeDeletedThread: (threadId: number) => void;
  selectProject: (projectId: number) => void;
  selectWorkspace: (workspaceId: number) => void;
  selectBranch: (branchName: string) => Promise<void>;
  selectThread: (threadId: number) => void;
  recordThreadRun: (threadId: number, runId: string, updatedAt?: string) => void;
  startNewTask: () => void;
  createThreadFromInput: (title: string) => Promise<CodingThreadSummary>;
  createThreadFromFirstTurn: (payload: CodingFirstTurnPayload) => Promise<CodingThreadSummary>;
  takePendingFirstTurn: (threadId: number) => CodingFirstTurnPayload | null;
  ensureWorkspaceForProject: (projectId: number) => Promise<void>;
}

/** 生产数据源（测试/预览经 createCodingWorkspaceStore 注入替换） */
const defaultFetchers: CodingWorkspaceFetchers = {
  projects: fetchCodingProjects,
  workspaces: fetchCodingWorkspaces,
  threads: fetchCodingThreads,
  modelProfiles: fetchCodingModelProfiles,
  health: checkLocalExecutorHealth,
  reconnect: reconnectDesktopBackend,
  createThread: createCodingThread,
  ensureRootWorkspace: ensureCodingRootWorkspace,
  branches: fetchCodingBranches,
  switchBranch: switchCodingBranch,
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
  const customSource = Object.keys(fetchers).length > 0;
  if (customSource && !("branches" in fetchers)) source.branches = undefined;
  if (customSource && !("switchBranch" in fetchers)) source.switchBranch = undefined;
  if (customSource && !("reconnect" in fetchers)) source.reconnect = undefined;

  const projects = ref<CodingProjectSummary[]>([]);
  const workspacesByProject = ref<Record<number, CodingWorkspaceSummary[]>>({});
  const branchesByProject = ref<Record<number, CodingBranchState>>({});
  const threadsByProject = ref<Record<number, CodingThreadSummary[]>>({});
  const modelProfiles = ref<CodingModelProfilesResult | null>(null);
  const capabilities = ref<Record<string, unknown> | null>(null);
  const loadPhase = ref<CodingLoadPhase>("idle");
  const loadError = ref<CodingApiError | null>(null);
  const sidecarOk = ref<boolean | null>(null);
  const reconnecting = ref(false);
  let reconnectPromise: Promise<void> | null = null;
  let disposed = false;

  const selectedProjectId = ref<number | null>(null);
  const selectedWorkspaceId = ref<number | null>(null);
  const selectedBranchName = ref<string | null>(null);
  const selectedThreadId = ref<number | null>(null);
  const pendingFirstTurn = ref<CodingPendingFirstTurn | null>(null);

  let contextSequence = 0;
  function syncProjectContext(projectId: number | null): void {
    const mine = ++contextSequence;
    // 重连尚未绑定身份时先保留选择，由重连流程同步最后选中的项目。
    if (disposed || reconnecting.value) return;
    void setLocalProjectContext(projectId).then(() => {
      if (mine !== contextSequence) return;
      if (loadError.value?.code === "project_context_failed") loadError.value = null;
    }).catch(() => {
      if (mine !== contextSequence) return;
      loadError.value = { status: 0, code: "project_context_failed", message: "项目切换撤权失败，请重新选择项目或退出客户端；新操作已阻止" };
    });
  }
  const stopProjectContextSync = watch(selectedProjectId, syncProjectContext, { flush: "sync" });

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
    if (selectedThreadId.value !== null && !selectedThread.value) {
      selectedThreadId.value = null;
    }
    if (pendingFirstTurn.value && !Object.values(threadsByProject.value).some(
      (threads) => threads.some((thread) => thread.id === pendingFirstTurn.value?.threadId)
    )) pendingFirstTurn.value = null;
    if (selectedProjectId.value === null || !projectExists(selectedProjectId.value)) {
      selectedProjectId.value = projects.value[0]?.id ?? null;
      selectedWorkspaceId.value = null;
    }
    const projectId = selectedProjectId.value;
    if (projectId === null) {
      selectedThreadId.value = null;
      selectedBranchName.value = null;
      return;
    }
    const workspaces = workspacesByProject.value[projectId] ?? [];
    const current = workspaces.find((workspace) => workspace.id === selectedWorkspaceId.value);
    if (!current) {
      const preferred = workspaces.find(isWorkspaceUsable) ?? workspaces[0];
      selectedWorkspaceId.value = preferred?.id ?? null;
    }
    selectedBranchName.value = branchesByProject.value[projectId]?.currentBranch ?? current?.branchName ?? null;
  }

  function projectExists(projectId: number): boolean {
    return projects.value.some((project) => project.id === projectId);
  }

  async function load(): Promise<void> {
    if (disposed) return;
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
      projects.value = [...projectList].sort((left, right) =>
        (right.pinnedAt ?? "").localeCompare(left.pinnedAt ?? "")
      );
      modelProfiles.value = profiles;
      // v0.9.0 H1-A：能力位不阻塞首页状态机（真实网络请求），单独尽力获取；
      // 失败/未提供时保持 null，权限高级选项不可选（不在前端扩大授权）。
      void loadCapabilities(mine);

      const workspaceEntries = await Promise.all(
        projectList.map(async (project) => [project.id, await source.workspaces(project.id)] as const)
      );
      if (mine !== loadSeq) return;
      const workspaceMap: Record<number, CodingWorkspaceSummary[]> = {};
      for (const [projectId, list] of workspaceEntries) workspaceMap[projectId] = list;
      workspacesByProject.value = workspaceMap;

      if (source.branches) {
        const branchEntries = await Promise.all(
          projectList.map(async (project) => {
            try {
              return [project.id, await source.branches!(project.id)] as const;
            } catch {
              return [project.id, null] as const;
            }
          })
        );
        if (mine !== loadSeq) return;
        const branchMap: Record<number, CodingBranchState> = {};
        for (const [projectId, state] of branchEntries) {
          if (state) branchMap[projectId] = state;
        }
        branchesByProject.value = branchMap;
      } else {
        branchesByProject.value = {};
      }

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

  async function loadCapabilities(mine: number): Promise<void> {
    if (!source.capabilities) return;
    try {
      const loaded = await source.capabilities();
      if (mine === loadSeq) capabilities.value = loaded;
    } catch {
      if (mine === loadSeq) capabilities.value = null;
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
    // 普通加载延续由状态反馈错误的契约，只有显式重连向调用者报告失败。
    return reconnectPromise?.catch(() => undefined) ?? load();
  }

  async function refresh(): Promise<void> {
    return reconnectPromise?.catch(() => undefined) ?? load();
  }

  async function restoreProjectContext(): Promise<void> {
    while (true) {
      assertActive();
      const projectId = selectedProjectId.value;
      try { await setLocalProjectContext(projectId); }
      catch (cause) { if (projectId === selectedProjectId.value) throw cause; }
      assertActive();
      if (projectId === selectedProjectId.value) return;
    }
  }

  function reconnect(): Promise<void> {
    if (disposed) return Promise.reject(new Error("当前工作台会话已失效"));
    if (reconnectPromise) return reconnectPromise;
    reconnecting.value = true;
    ++loadSeq;
    ++contextSequence;
    loadError.value = null;
    const operation = async () => {
      try {
        assertActive();
        if (!source.reconnect) throw new Error("当前数据源不支持本机重连");
        await source.reconnect();
        await restoreProjectContext();
        await load();
        assertActive();
        if (sidecarOk.value !== true || loadError.value) {
          throw loadError.value ?? new Error("本机执行器仍不可用，请重试连接");
        }
        // 数据加载期间允许继续选择项目；结束前核对最终选择，不能恢复旧项目权限。
        await restoreProjectContext();
      } catch (cause) {
        if (disposed) throw cause;
        sidecarOk.value = false;
        loadPhase.value = "error";
        loadError.value = {
          status: 0, code: "local_reconnect_failed",
          message: cause instanceof Error ? cause.message : normalizeError(cause).message,
        };
        throw cause;
      } finally {
        reconnecting.value = false;
        reconnectPromise = null;
      }
    };
    reconnectPromise = Promise.resolve().then(operation);
    return reconnectPromise;
  }

  function assertActive(): void {
    if (disposed) throw new Error("当前工作台会话已失效");
  }

  /** 会话替换后停止旧实例的上下文同步，迟到响应不能恢复旧项目权限。 */
  function dispose(): void {
    disposed = true;
    ++loadSeq;
    ++contextSequence;
    stopProjectContextSync();
    reconnecting.value = false;
  }

  /** 删除成功后先清理本地状态，避免刷新失败或旧响应让记录重新出现。 */
  function removeDeletedThread(threadId: number): void {
    ++loadSeq;
    threadsByProject.value = Object.fromEntries(Object.entries(threadsByProject.value).map(
      ([id, threads]) => [id, threads.filter((thread) => thread.id !== threadId)]
    ));
    applyDefaultSelection();
    loadPhase.value = "ready";
  }

  function removeDeletedProject(projectId: number): void {
    ++loadSeq;
    projects.value = projects.value.filter((project) => project.id !== projectId);
    delete workspacesByProject.value[projectId];
    delete branchesByProject.value[projectId];
    delete threadsByProject.value[projectId];
    applyDefaultSelection();
    loadPhase.value = "ready";
  }

  function selectProject(projectId: number): void {
    if (!projectExists(projectId)) return;
    if (selectedProjectId.value === projectId) syncProjectContext(projectId);
    selectedProjectId.value = projectId;
    const workspaces = workspacesByProject.value[projectId] ?? [];
    const preferred = workspaces.find(isWorkspaceUsable) ?? workspaces[0];
    selectedWorkspaceId.value = preferred?.id ?? null;
    selectedBranchName.value = branchesByProject.value[projectId]?.currentBranch ?? preferred?.branchName ?? null;
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
    selectedBranchName.value = branchesByProject.value[projectId]?.currentBranch ?? workspace.branchName;
    selectedThreadId.value = null;
  }

  async function selectBranch(branchName: string): Promise<void> {
    const projectId = selectedProjectId.value;
    if (projectId === null || !source.switchBranch) {
      throw { status: 409, code: "git_branch_unavailable", message: "当前 Runtime 不支持本地分支切换" } satisfies CodingApiError;
    }
    const state = await source.switchBranch(projectId, branchName);
    branchesByProject.value = { ...branchesByProject.value, [projectId]: state };
    const workspaces = workspacesByProject.value[projectId] ?? [];
    const rootWorkspace = workspaces.find((workspace) => workspace.kind === "root");
    if (rootWorkspace) {
      workspacesByProject.value = {
        ...workspacesByProject.value,
        [projectId]: workspaces.map((workspace) =>
          workspace.id === rootWorkspace.id
            ? {
                ...workspace,
                branchName: state.currentBranch,
                headSha: state.headSha,
                status: state.dirty ? "dirty" : "active",
              }
            : workspace
        ),
      };
      selectedWorkspaceId.value = rootWorkspace.id;
    }
    selectedBranchName.value = state.currentBranch;
    selectedThreadId.value = null;
  }

  function selectThread(threadId: number): void {
    for (const [projectId, threads] of Object.entries(threadsByProject.value)) {
      const thread = threads.find((candidate) => candidate.id === threadId);
      if (thread) {
        selectedProjectId.value = thread.projectId ?? Number(projectId);
        selectedWorkspaceId.value = thread.workspaceId;
        const resolvedProjectId = thread.projectId ?? Number(projectId);
        const selected = (workspacesByProject.value[resolvedProjectId] ?? []).find(
          (workspace) => workspace.id === thread.workspaceId
        );
        selectedBranchName.value = branchesByProject.value[resolvedProjectId]?.currentBranch ?? selected?.branchName ?? null;
        selectedThreadId.value = threadId;
        return;
      }
    }
  }

  /** run 创建成功后立即更新内存线程摘要，切走再返回无需等待整棵树刷新。 */
  function recordThreadRun(
    threadId: number,
    runId: string,
    updatedAt?: string
  ): void {
    for (const [projectId, threads] of Object.entries(threadsByProject.value)) {
      if (!threads.some((thread) => thread.id === threadId)) continue;
      threadsByProject.value = {
        ...threadsByProject.value,
        [Number(projectId)]: threads.map((thread) =>
          thread.id === threadId
            ? {
                ...thread,
                lastRunId: runId,
                updatedAt: updatedAt ?? thread.updatedAt,
              }
            : thread
        ),
      };
      return;
    }
  }

  /** 侧栏「新建任务」：回到首页输入器，保留项目/工作区偏好 */
  function startNewTask(): void {
    selectedThreadId.value = null;
  }

  /** 从首条指令提取简短、稳定的对话标题，完整指令仍作为首轮消息执行。 */
  function titleFromFirstInstruction(message: string): string {
    const normalized = message.replace(/\s+/g, " ").trim();
    const firstSentence = normalized.split(/[。！？!?]/, 1)[0]?.trim() || normalized;
    const source = firstSentence.length >= 4 ? firstSentence : normalized;
    return source.length > 36 ? `${source.slice(0, 36).trimEnd()}…` : source;
  }

  async function createThreadFromInput(title: string, select = true, clientRequestId?: string): Promise<CodingThreadSummary> {
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
      ...(clientRequestId ? { clientRequestId } : {}),
    });
    const existing = threadsByProject.value[thread.projectId] ?? [];
    threadsByProject.value = {
      ...threadsByProject.value,
      [thread.projectId]: [thread, ...existing.filter((item) => item.id !== thread.id)],
    };
    if (select) selectedThreadId.value = thread.id;
    return thread;
  }

  async function createThreadFromFirstTurn(
    payload: CodingFirstTurnPayload
  ): Promise<CodingThreadSummary> {
    const thread = await createThreadFromInput(titleFromFirstInstruction(payload.message), false, capabilities.value?.coding_durable_drafts_enabled === true ? payload.clientRequestId : undefined);
    await transferFirstTurnDraft(payload, thread.projectId!, thread.workspaceId!, thread.id, capabilities.value?.coding_durable_drafts_enabled === true);
    // 创建期间离开原工作区时只保留该会话草稿，不在其他项目继续发送。
    if (selectedProjectId.value === thread.projectId && selectedWorkspaceId.value === thread.workspaceId && selectedThreadId.value === null) {
      pendingFirstTurn.value = { threadId: thread.id, ...payload };
      selectedThreadId.value = thread.id;
    }
    return thread;
  }

  function takePendingFirstTurn(threadId: number): CodingFirstTurnPayload | null {
    const pending = pendingFirstTurn.value;
    if (!pending || pending.threadId !== threadId) return null;
    pendingFirstTurn.value = null;
    const { threadId: _threadId, ...payload } = pending;
    return payload;
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
    if (source.branches) {
      try {
        const state = await source.branches(projectId);
        branchesByProject.value = { ...branchesByProject.value, [projectId]: state };
        if (selectedProjectId.value === projectId) selectedBranchName.value = state.currentBranch;
      } catch {
        // 旧 Runtime 无分支接口时仍保留根工作区，不阻断项目使用。
      }
    }
  }

  return {
    projects,
    workspacesByProject,
    branchesByProject,
    threadsByProject,
    modelProfiles,
    capabilities,
    loadPhase,
    loadError,
    sidecarOk,
    reconnecting,
    selectedProjectId,
    selectedWorkspaceId,
    selectedBranchName,
    selectedThreadId,
    pendingFirstTurn,
    tree,
    homeState,
    selectedProject,
    selectedWorkspace,
    selectedThread,
    bootstrap,
    refresh,
    reconnect,
    dispose,
    removeDeletedProject,
    removeDeletedThread,
    selectProject,
    selectWorkspace,
    selectBranch,
    selectThread,
    recordThreadRun,
    startNewTask,
    createThreadFromInput,
    createThreadFromFirstTurn,
    takePendingFirstTurn,
    ensureWorkspaceForProject,
  };
}

let codingWorkspaceStore = createCodingWorkspaceStore();

/** 新会话不能继承旧项目、首轮草稿或迟到响应。 */
export function resetCodingWorkspace(): void {
  codingWorkspaceStore.dispose();
  codingWorkspaceStore = createCodingWorkspaceStore();
}

export function useCodingWorkspace(): CodingWorkspaceStore {
  return codingWorkspaceStore;
}
