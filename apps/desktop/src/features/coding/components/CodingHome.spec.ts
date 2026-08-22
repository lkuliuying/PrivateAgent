import { describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import CodingHome from "./CodingHome.vue";
import { createCodingWorkspaceStore } from "../model/codingWorkspaceStore";
import type {
  CodingThreadSummary,
  CodingWorkspaceFetchers,
} from "../model/contracts";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";

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
  it("就绪态：选择器 + 主输入 + 推荐模板齐备", async () => {
    const { wrapper } = await mountHome(readyFetchers());
    expect(wrapper.find('[data-testid="coding-home-project-select"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-home-workspace-select"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-home-input"]').exists()).toBe(true);
    expect(wrapper.findAll(".template-chip").length).toBe(4);
  });

  it("输入任务并提交：创建线程、清空输入、发出 thread-created", async () => {
    const createThread = vi.fn(readyFetchers().createThread);
    const { wrapper, store } = await mountHome(readyFetchers({ createThread }));
    const input = wrapper.find('[data-testid="coding-home-input"]');
    await input.setValue("修复窄屏侧栏遮挡问题");
    await wrapper.find('[data-testid="coding-home-submit"]').trigger("click");
    await flushPromises();
    expect(createThread).toHaveBeenCalledWith({
      projectId: 1,
      workspaceId: 101,
      title: "修复窄屏侧栏遮挡问题",
    });
    expect((input.element as HTMLTextAreaElement).value).toBe("");
    expect(store.selectedThreadId.value).toBe(99);
    expect(wrapper.emitted("thread-created")?.[0]?.[0]).toMatchObject({ id: 99 });
  });

  it("Enter 提交、Shift+Enter 换行不提交", async () => {
    const createThread = vi.fn(readyFetchers().createThread);
    const { wrapper } = await mountHome(readyFetchers({ createThread }));
    const input = wrapper.find('[data-testid="coding-home-input"]');
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
    await wrapper.find('[data-testid="coding-home-input"]').setValue("任务 A");
    await wrapper.find('[data-testid="coding-home-submit"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("任务创建失败");
    expect(wrapper.text()).toContain("工作区不在授权路径内");
  });

  it("推荐模板点击预填输入", async () => {
    const { wrapper } = await mountHome(readyFetchers());
    await wrapper.find('[data-testid="coding-home-template-1"]').trigger("click");
    expect((wrapper.find('[data-testid="coding-home-input"]').element as HTMLTextAreaElement).value).toContain(
      "失败的测试"
    );
  });

  it("无项目：空态 + 打开项目页导航", async () => {
    const { wrapper } = await mountPreview("no-projects");
    expect(wrapper.text()).toContain("还没有项目");
    await wrapper.find("button.pa-button").trigger("click");
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
    expect(wrapper.text()).toContain("开始一个新任务");
  });

  it("Provider 未配置：引导前往设置", async () => {
    const { wrapper } = await mountPreview("provider-unconfigured");
    expect(wrapper.text()).toContain("模型 Provider 未配置");
    await wrapper.find("button.pa-button").trigger("click");
    expect(wrapper.emitted("navigate")?.[0]).toEqual(["settings"]);
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
