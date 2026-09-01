import { describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import CodingHome from "./CodingHome.vue";
import NewProjectDialog from "./NewProjectDialog.vue";
import { createCodingWorkspaceStore } from "../model/codingWorkspaceStore";
import type {
  CodingThreadSummary,
  CodingWorkspaceFetchers,
} from "../model/contracts";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";

// v0.9.0 H1-D：导入状态/导入动作的确定性 mock（部分 mock，其余导出保留）
vi.mock("../api/modelProfiles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/modelProfiles")>();
  return {
    ...actual,
    fetchCodingProfileImportStatus: vi.fn(async () => ({
      importState: "pending",
      reasonCode: null,
      provider: "ollama",
      modelAvailable: true,
    })),
    importCodingModelProfile: vi.fn(async () => ({
      imported: true,
      alreadyExists: false,
      profileId: "ollama-default",
    })),
  };
});
import { importCodingModelProfile } from "../api/modelProfiles";

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

function readyFetchers(
  overrides: Partial<CodingWorkspaceFetchers> = {}
): CodingWorkspaceFetchers {
  return {
    projects: async () => [{ id: 1, name: "PrivateAgent", status: "active", updatedAt: "2026-08-22T00:00:00Z" }],
    workspaces: async () => [
      {
        id: 101,
        projectId: 1,
        kind: "root",
        branchName: null,
        headSha: null,
        status: "active",
        lastUsedAt: null,
      },
    ],
    threads: async () => [],
    modelProfiles: OK_PROFILES,
    health: async () => true,
    createThread: async (input) =>
      ({
        id: 99,
        title: input.title,
        projectId: input.projectId,
        workspaceId: input.workspaceId,
        updatedAt: "2026-08-22T03:00:00Z",
        lastRunId: null,
      }) satisfies CodingThreadSummary,
    ensureRootWorkspace: async (projectId) => ({
      id: 101,
      projectId,
      kind: "root",
      branchName: null,
      headSha: null,
      status: "active",
      lastUsedAt: null,
    }),
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
    switchBranch: async (_projectId, branchName) => ({
      isGit: true,
      currentBranch: branchName,
      headSha: `${branchName}-sha`,
      dirty: false,
      branches: [
        { name: "dev", headSha: "dev-sha", current: branchName === "dev" },
        { name: "main", headSha: "main-sha", current: branchName === "main" },
      ],
    }),
    ...overrides,
  };
}

async function mountHome(fetchers: CodingWorkspaceFetchers) {
  const store = createCodingWorkspaceStore(fetchers);
  await store.bootstrap();
  const wrapper = mount(CodingHome, { props: { store }, attachTo: document.body });
  return { wrapper, store };
}

async function mountPreview(key: Parameters<typeof createCodingWorkspacePreviewStore>[0]) {
  const store = createCodingWorkspacePreviewStore(key);
  await flushPromises();
  const wrapper = mount(CodingHome, { props: { store }, attachTo: document.body });
  return { wrapper, store };
}

describe("CodingHome", () => {
  it("就绪态：直接进入空白对话，项目与分支选择器位于输入区", async () => {
    const { wrapper } = await mountHome(readyFetchers());
    expect(wrapper.find('[data-testid="coding-home-empty-chat"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-home-project-select"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-home-workspace-select"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("dev");
    expect(wrapper.text()).toContain("main");
    expect(wrapper.find('[data-testid="coding-composer-input"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain("推荐任务");
  });

  it("首次发送：提取标题创建线程，并暂存完整首轮指令等待任务页执行", async () => {
    const createThread = vi.fn(readyFetchers().createThread);
    const { wrapper, store } = await mountHome(readyFetchers({ createThread }));
    const input = wrapper.find('[data-testid="coding-composer-input"]');
    await input.setValue("修复窄屏侧栏遮挡问题。并补充对应的回归测试与说明");
    await wrapper.find('[data-testid="coding-composer-send"]').trigger("click");
    await flushPromises();
    expect(createThread).toHaveBeenCalledWith({
      projectId: 1,
      workspaceId: 101,
      title: "修复窄屏侧栏遮挡问题",
    });
    expect((input.element as HTMLTextAreaElement).value).toBe("");
    expect(store.selectedThreadId.value).toBe(99);
    expect(store.pendingFirstTurn.value).toMatchObject({
      threadId: 99,
      message: "修复窄屏侧栏遮挡问题。并补充对应的回归测试与说明",
      permissionMode: "confirm",
      modelProfileId: "local-coder",
    });
    expect(wrapper.emitted("thread-created")?.[0]?.[0]).toMatchObject({ id: 99 });
  });

  it("Enter 提交、Shift+Enter 换行不提交", async () => {
    const createThread = vi.fn(readyFetchers().createThread);
    const { wrapper } = await mountHome(readyFetchers({ createThread }));
    const input = wrapper.find('[data-testid="coding-composer-input"]');
    await input.setValue("任务 A");
    await input.trigger("keydown", { key: "Enter", shiftKey: true });
    expect(createThread).not.toHaveBeenCalled();
    await input.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(createThread).toHaveBeenCalledTimes(1);
  });

  it("创建失败（workspace_outside_trust）呈现脱敏错误说明", async () => {
    const { wrapper } = await mountHome(
      readyFetchers({
        createThread: async () => {
          throw { status: 403, code: "workspace_outside_trust", message: "工作区不在授权路径内" };
        },
      })
    );
    await wrapper.find('[data-testid="coding-composer-input"]').setValue("任务 A");
    await wrapper.find('[data-testid="coding-composer-send"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("对话创建失败");
    expect(wrapper.text()).toContain("工作区不在授权路径内");
    expect((wrapper.find('[data-testid="coding-composer-input"]').element as HTMLTextAreaElement).value).toBe("任务 A");
  });

  it("无项目：空态提供新建项目与项目页两个动作（v0.9.0 H1 拆分）", async () => {
    const { wrapper } = await mountPreview("no-projects");
    expect(wrapper.text()).toContain("还没有项目");
    // 主动作：新建项目（打开选目录+授权对话框）
    await wrapper.find('[data-testid="home-new-project"]').trigger("click");
    expect(wrapper.find('[data-testid="new-project-dialog"]').exists()).toBe(true);
    const dialog = wrapper.findComponent(NewProjectDialog);
    dialog.vm.$emit("close");
    await flushPromises();
    expect(wrapper.find('[data-testid="new-project-dialog"]').exists()).toBe(false);
    // 次动作：打开项目页（旧入口保留）
    const buttons = wrapper.findAll("button.pa-button");
    const projectsBtn = buttons.find((btn) => btn.text().includes("打开项目页"));
    await projectsBtn?.trigger("click");
    expect(wrapper.emitted("navigate")?.[0]).toEqual(["projects"]);
  });

  it("无工作区：CTA 幂等补建根工作区后转入就绪", async () => {
    const ensureRootWorkspace = vi.fn(readyFetchers().ensureRootWorkspace);
    const fetchers = readyFetchers({
      workspaces: async () => [],
      ensureRootWorkspace,
    });
    const { wrapper } = await mountHome(fetchers);
    expect(wrapper.text()).toContain("项目还没有可用工作区");
    await wrapper.find("button.pa-button").trigger("click");
    await flushPromises();
    expect(ensureRootWorkspace).toHaveBeenCalledWith(1);
    expect(wrapper.text()).toContain("你想在");
  });

  it("能力位关闭（feature_disabled）：呈现更新/重试语义（H1-D 拆分）", async () => {
    const { wrapper } = await mountPreview("provider-unconfigured");
    expect(wrapper.text()).toContain("模型能力未开启");
    expect(wrapper.find('[data-testid="home-provider-retry"]').exists()).toBe(true);
    // 前往设置入口进入同一模型管理区（configure-provider）
    const buttons = wrapper.findAll("button.pa-button");
    const settingsBtn = buttons.find((btn) => btn.text().includes("前往设置"));
    await settingsBtn?.trigger("click");
    expect(wrapper.emitted("configure-provider")).toBeTruthy();
  });

  it("profile 缺失（profile_missing）：一键导入与创建入口（H1-D）", async () => {
    const { wrapper } = await mountHome(
      readyFetchers({
        modelProfiles: async () => ({ status: "ok", profiles: [] }),
      })
    );
    expect(wrapper.text()).toContain("尚无 Coding 模型");
    // 全局配置可导入 → 一键验证并导入按钮可见并调用 typed API
    const importBtn = wrapper.find('[data-testid="home-provider-import"]');
    expect(importBtn.exists()).toBe(true);
    await importBtn.trigger("click");
    await flushPromises();
    expect(importCodingModelProfile).toHaveBeenCalled();
    // 创建入口进入同一模型管理区（不丢失项目/草稿）
    await wrapper.find('[data-testid="home-provider-create"]').trigger("click");
    expect(wrapper.emitted("configure-provider")).toBeTruthy();
  });

  it("sidecar 不可达：错误态与重试入口", async () => {
    const health = vi.fn(async () => false);
    const { wrapper } = await mountHome(readyFetchers({ health }));
    expect(wrapper.text()).toContain("本地后端未就绪");
    await wrapper.find("button.pa-button").trigger("click");
    await flushPromises();
    expect(health).toHaveBeenCalledTimes(2);
  });

  it("工作区异常（路径缺失）：呈现状态语义与项目页入口", async () => {
    const { wrapper } = await mountPreview("workspace-invalid");
    expect(wrapper.text()).toContain("当前工作区状态异常");
    expect(wrapper.text()).toContain("路径缺失");
    await wrapper.find("button.pa-button").trigger("click");
    expect(wrapper.emitted("navigate")?.[0]).toEqual(["projects"]);
  });
});
