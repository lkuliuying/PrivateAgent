import { describe, expect, it, vi } from "vitest";
import { flushPromises } from "@vue/test-utils";
import {
  createCodingWorkspaceStore,
} from "./codingWorkspaceStore";
import type {
  CodingProjectSummary,
  CodingThreadSummary,
  CodingWorkspaceFetchers,
  CodingWorkspaceSummary,
} from "./contracts";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";

function project(id: number, name = `项目 ${id}`): CodingProjectSummary {
  return { id, name, status: "active", updatedAt: "2026-08-22T00:00:00Z" };
}

function workspace(
  id: number,
  projectId: number,
  overrides: Partial<CodingWorkspaceSummary> = {}
): CodingWorkspaceSummary {
  return {
    id,
    projectId,
    kind: "root",
    branchName: null,
    headSha: null,
    status: "active",
    lastUsedAt: null,
    ...overrides,
  };
}

function thread(
  id: number,
  projectId: number,
  workspaceId: number | null,
  title = `任务 ${id}`
): CodingThreadSummary {
  return {
    id,
    title,
    projectId,
    workspaceId,
    updatedAt: `2026-08-22T00:0${id}:00Z`,
    lastRunId: null,
  };
}

const OK_PROFILES: CodingWorkspaceFetchers["modelProfiles"] = async () => ({
  status: "ok",
  profiles: [
    {
      id: "local-coder",
      provider: "ollama",
      displayName: "Local Coder",
      isLocal: true,
      reasoningEfforts: ["low", "medium", "high"],
    },
  ],
});

function baseFetchers(
  overrides: Partial<CodingWorkspaceFetchers> = {}
): CodingWorkspaceFetchers {
  return {
    projects: async () => [project(1), project(2)],
    workspaces: async (projectId) => [
      workspace(projectId * 100 + 1, projectId),
      workspace(projectId * 100 + 2, projectId, {
        kind: "git_worktree",
        branchName: "feature/x",
      }),
    ],
    threads: async (projectId) =>
      projectId === 1
        ? [thread(11, 1, 101), thread(12, 1, 102), thread(13, 1, 999)]
        : [],
    modelProfiles: OK_PROFILES,
    health: async () => true,
    createThread: async (input) => thread(99, input.projectId, input.workspaceId, input.title),
    ensureRootWorkspace: async (projectId) => workspace(projectId * 100 + 1, projectId),
    branches: async () => ({
      isGit: false,
      currentBranch: null,
      headSha: null,
      dirty: false,
      branches: [],
    }),
    ...overrides,
  };
}

describe("codingWorkspaceStore", () => {
  it("bootstrap 组树：线程按 workspace 分组，未知 workspace 落入 orphan", async () => {
    const store = createCodingWorkspaceStore(baseFetchers());
    await store.bootstrap();
    const tree = store.tree.value;
    expect(tree).toHaveLength(2);
    expect(tree[0].workspaces).toHaveLength(2);
    expect(tree[0].workspaces[0].threads.map((item) => item.id)).toEqual([11]);
    expect(tree[0].workspaces[1].threads.map((item) => item.id)).toEqual([12]);
    expect(tree[0].orphanThreads.map((item) => item.id)).toEqual([13]);
    // 默认选择：首个项目的首个可用工作区
    expect(store.selectedProjectId.value).toBe(1);
    expect(store.selectedWorkspaceId.value).toBe(101);
    expect(store.homeState.value).toBe("ready");
  });

  it.each([
    ["no-projects", "no-projects"],
    ["no-workspace", "no-workspace"],
    ["provider-unconfigured", "provider-unconfigured"],
    ["sidecar-unavailable", "sidecar-unavailable"],
    ["workspace-invalid", "workspace-invalid"],
    ["ready", "ready"],
  ] as const)("预览夹具 %s 派生 homeState=%s", async (key, expected) => {
    const store = createCodingWorkspacePreviewStore(key);
    await flushPromises();
    expect(store.homeState.value).toBe(expected);
  });

  it("bootstrap 失败收敛为 load-error 并保留错误码", async () => {
    const store = createCodingWorkspaceStore(
      baseFetchers({
        projects: async () => {
          throw { status: 409, code: "coding_mode_disabled", message: "flag 关闭" };
        },
      })
    );
    await store.bootstrap();
    expect(store.homeState.value).toBe("load-error");
    expect(store.loadError.value?.code).toBe("coding_mode_disabled");
  });

  it("sidecar 不可达时优先于其他状态（不闪现空项目）", async () => {
    const store = createCodingWorkspaceStore(
      baseFetchers({
        health: async () => {
          throw new Error("connection refused");
        },
        projects: async () => {
          throw new Error("不应被调用");
        },
      })
    );
    await store.bootstrap();
    expect(store.homeState.value).toBe("sidecar-unavailable");
  });

  it("selectThread 级联设置项目/工作区；startNewTask 只清线程", async () => {
    const store = createCodingWorkspaceStore(baseFetchers());
    await store.bootstrap();
    store.selectThread(12);
    expect(store.selectedThreadId.value).toBe(12);
    expect(store.selectedProjectId.value).toBe(1);
    expect(store.selectedWorkspaceId.value).toBe(102);
    store.startNewTask();
    expect(store.selectedThreadId.value).toBeNull();
    expect(store.selectedWorkspaceId.value).toBe(102);
  });

  it("读取本地分支并在切换成功后同步根工作区", async () => {
    const switchBranch = vi.fn(async (_projectId: number, branchName: string) => ({
      isGit: true,
      currentBranch: branchName,
      headSha: branchName === "main" ? "main-sha" : "dev-sha",
      dirty: false,
      branches: [
        { name: "dev", headSha: "dev-sha", current: branchName === "dev" },
        { name: "main", headSha: "main-sha", current: branchName === "main" },
      ],
    }));
    const store = createCodingWorkspaceStore(baseFetchers({
      branches: async () => ({
        isGit: true,
        currentBranch: "dev",
        headSha: "dev-sha",
        dirty: false,
        branches: [
          { name: "dev", headSha: "dev-sha", current: true },
          { name: "main", headSha: "main-sha", current: false },
        ],
      }),
      switchBranch,
    }));
    await store.bootstrap();
    expect(store.selectedBranchName.value).toBe("dev");
    await store.selectBranch("main");
    expect(switchBranch).toHaveBeenCalledWith(1, "main");
    expect(store.selectedBranchName.value).toBe("main");
    expect(store.workspacesByProject.value[1][0]).toMatchObject({
      branchName: "main",
      headSha: "main-sha",
      status: "active",
    });
  });

  it("recordThreadRun 立即记录最近 run，切走再返回可直接恢复", async () => {
    const store = createCodingWorkspaceStore(baseFetchers());
    await store.bootstrap();
    const previousUpdatedAt = store.threadsByProject.value[1][0].updatedAt;
    store.recordThreadRun(11, "run-durable");
    expect(store.threadsByProject.value[1][0].lastRunId).toBe("run-durable");
    expect(store.threadsByProject.value[1][0].updatedAt).toBe(previousUpdatedAt);
    store.recordThreadRun(11, "run-new", "2026-08-24T03:00:00Z");
    expect(store.threadsByProject.value[1][0]).toMatchObject({
      lastRunId: "run-new",
      updatedAt: "2026-08-24T03:00:00Z",
    });
  });

  it("createThreadFromInput 追加线程并选中；空输入/无工作区抛契约错误", async () => {
    const createThread = vi.fn(baseFetchers().createThread);
    const store = createCodingWorkspaceStore(baseFetchers({ createThread }));
    await store.bootstrap();
    const created = await store.createThreadFromInput("  修复窄屏遮挡  ");
    expect(createThread).toHaveBeenCalledWith({
      projectId: 1,
      workspaceId: 101,
      title: "修复窄屏遮挡",
    });
    expect(store.selectedThreadId.value).toBe(created.id);
    expect(store.threadsByProject.value[1]).toHaveLength(4);

    await expect(store.createThreadFromInput("   ")).rejects.toMatchObject({
      code: "coding_context_incomplete",
    });

    const noWorkspaceStore = createCodingWorkspaceStore(
      baseFetchers({
        workspaces: async () => [],
        threads: async () => [],
      })
    );
    await noWorkspaceStore.bootstrap();
    await expect(noWorkspaceStore.createThreadFromInput("任务")).rejects.toMatchObject({
      code: "coding_context_incomplete",
    });
  });

  it("createThreadFromFirstTurn 从首句生成短标题，并让首轮指令只消费一次", async () => {
    const createThread = vi.fn(baseFetchers().createThread);
    const store = createCodingWorkspaceStore(baseFetchers({ createThread }));
    await store.bootstrap();
    const payload = {
      message: "  修复登录页窄屏遮挡问题。随后补充回归测试  ",
      permissionMode: "confirm",
      modelProfileId: "local-coder",
      reasoningEffort: "high",
    };
    const created = await store.createThreadFromFirstTurn(payload);
    expect(createThread).toHaveBeenCalledWith({
      projectId: 1,
      workspaceId: 101,
      title: "修复登录页窄屏遮挡问题",
    });
    expect(store.takePendingFirstTurn(created.id)).toEqual(payload);
    expect(store.takePendingFirstTurn(created.id)).toBeNull();
  });

  it("createThread 后端拒绝（workspace_outside_trust）原样透传错误码", async () => {
    const store = createCodingWorkspaceStore(
      baseFetchers({
        createThread: async () => {
          throw { status: 403, code: "workspace_outside_trust", message: "工作区不在授权路径内" };
        },
      })
    );
    await store.bootstrap();
    await expect(store.createThreadFromInput("任务")).rejects.toMatchObject({
      status: 403,
      code: "workspace_outside_trust",
    });
  });

  it("ensureWorkspaceForProject 追加根工作区并选中", async () => {
    const store = createCodingWorkspaceStore(
      baseFetchers({ workspaces: async () => [], threads: async () => [] })
    );
    await store.bootstrap();
    expect(store.homeState.value).toBe("no-workspace");
    await store.ensureWorkspaceForProject(1);
    expect(store.workspacesByProject.value[1]).toHaveLength(1);
    expect(store.selectedWorkspaceId.value).toBe(101);
    expect(store.homeState.value).toBe("ready");
  });

  it("重复 bootstrap 时迟到响应不回写（竞态防护）", async () => {
    let resolveFirst: (value: CodingProjectSummary[]) => void = () => {};
    const first = new Promise<CodingProjectSummary[]>((resolve) => {
      resolveFirst = resolve;
    });
    let call = 0;
    const store = createCodingWorkspaceStore(
      baseFetchers({
        projects: () => {
          call += 1;
          return call === 1 ? first : Promise.resolve([project(2)]);
        },
        workspaces: async (projectId) => [workspace(projectId * 100 + 1, projectId)],
        threads: async () => [],
      })
    );
    const firstLoad = store.bootstrap();
    // 先让第一次 load 通过 health 并挂起在 projects(first) 上（此时 call=1 已被消费）
    await flushPromises();
    const secondLoad = store.bootstrap();
    await secondLoad;
    resolveFirst([project(1)]);
    await firstLoad;
    await flushPromises();
    // 第二次加载（项目 2）胜出；第一次的迟到结果被丢弃
    expect(store.projects.value.map((item) => item.id)).toEqual([2]);
  });

  it("树序列化不包含 root_path 等敏感字段（红线结构性保证）", async () => {
    const store = createCodingWorkspaceStore(baseFetchers());
    await store.bootstrap();
    const serialized = JSON.stringify(store.tree.value);
    expect(serialized).not.toContain("root_path");
    expect(serialized).not.toContain("C:");
  });

  it("项目置顶优先，刷新保留所选项目，取消置顶恢复来源顺序", async () => {
    const list: CodingProjectSummary[] = [project(1), { ...project(2), pinnedAt: "2026-09-19T00:00:00Z" }];
    const store = createCodingWorkspaceStore(baseFetchers({ projects: async () => list }));
    await store.bootstrap();
    expect(store.tree.value.map((node) => node.project.id)).toEqual([2, 1]);
    store.selectProject(1);
    await store.refresh();
    expect(store.selectedProjectId.value).toBe(1);
    list[1].pinnedAt = null;
    await store.refresh();
    expect(store.projects.value.map((item) => item.id)).toEqual([1, 2]);
  });

  it("删除当前对话立即清理选择和首轮输入，保留同项目其他对话", async () => {
    const store = createCodingWorkspaceStore(baseFetchers());
    await store.bootstrap();
    store.selectThread(11);
    store.pendingFirstTurn.value = { threadId: 11 } as NonNullable<typeof store.pendingFirstTurn.value>;
    store.removeDeletedThread(11);
    expect(store.selectedThreadId.value).toBeNull();
    expect(store.pendingFirstTurn.value).toBeNull();
    expect(store.selectedProjectId.value).toBe(1);
    expect(store.threadsByProject.value[1].map((item) => item.id)).toEqual([12, 13]);
  });

  it("删除其他项目保留当前会话，删除最后一个项目清理全部选择", async () => {
    const store = createCodingWorkspaceStore(baseFetchers());
    await store.bootstrap();
    store.selectThread(11);
    store.removeDeletedProject(2);
    expect(store.selectedThreadId.value).toBe(11);
    store.selectedBranchName.value = "main";
    store.removeDeletedProject(1);
    expect(store.projects.value).toEqual([]);
    expect(store.workspacesByProject.value).toEqual({});
    expect(store.threadsByProject.value).toEqual({});
    expect(store.selectedProjectId.value).toBeNull();
    expect(store.selectedWorkspaceId.value).toBeNull();
    expect(store.selectedBranchName.value).toBeNull();
    expect(store.selectedThreadId.value).toBeNull();
  });

  it("刷新发现会话已删除时清理选择，删除后迟到的刷新不能复活记录", async () => {
    let list = [thread(11, 1, 101)];
    const store = createCodingWorkspaceStore(baseFetchers({ threads: async () => list }));
    await store.bootstrap();
    store.selectThread(11);
    list = [];
    await store.refresh();
    expect(store.selectedThreadId.value).toBeNull();
    let resolve: (value: CodingProjectSummary[]) => void = () => {};
    const projects = vi.fn(async () => [project(1)]);
    const raced = createCodingWorkspaceStore(baseFetchers({ projects }));
    await raced.bootstrap();
    projects.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const refresh = raced.refresh();
    await flushPromises();
    raced.removeDeletedProject(1);
    resolve([project(1)]);
    await refresh;
    expect(raced.projects.value).toEqual([]);
    expect(raced.loadPhase.value).toBe("ready");
  });
});
