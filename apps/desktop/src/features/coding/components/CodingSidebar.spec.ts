import { describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import CodingSidebar from "./CodingSidebar.vue";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";

async function mountSidebar(props: Record<string, unknown> = {}) {
  const store = createCodingWorkspacePreviewStore("ready");
  await flushPromises();
  const wrapper = mount(CodingSidebar, {
    props: { store, ...props },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, store };
}

function lastEmitted(
  wrapper: { emitted: (event: string) => unknown[] | undefined },
  event: string
): unknown {
  const events = wrapper.emitted(event);
  return events?.[events.length - 1];
}

describe("CodingSidebar", () => {
  it("使用紧凑导航与最近对话，个人工作区和更多工作区不再呈现", async () => {
    const { wrapper } = await mountSidebar();

    expect(wrapper.text()).toContain("PrivateAgent");
    expect(wrapper.find('[data-testid="coding-thread-11"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-personal"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="coding-legacy-section"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("个人工作区");
    expect(wrapper.text()).not.toContain("更多工作区");
  });

  it("项目树按需展开，并保留项目 → 工作区/分支 → 对话层级", async () => {
    const { wrapper } = await mountSidebar();
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(false);

    await wrapper.find('[data-testid="coding-toggle-projects"]').trigger("click");
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-workspace-101"]').attributes("data-status")).toBe(
      "active"
    );

    await wrapper.find('[data-testid="coding-workspace-101"]').trigger("click");
    expect(wrapper.text()).toContain("根工作区");
    expect(wrapper.find('[data-testid="coding-tree-thread-11"]').exists()).toBe(true);
  });

  it("最近对话和项目树对话都能选择线程并返回 Coding 工作台", async () => {
    const { wrapper, store } = await mountSidebar();
    await wrapper.find('[data-testid="coding-thread-11"]').trigger("click");
    expect(store.selectedThreadId.value).toBe(11);
    expect(lastEmitted(wrapper, "navigate")).toEqual(["coding"]);

    store.startNewTask();
    await wrapper.find('[data-testid="coding-toggle-projects"]').trigger("click");
    await wrapper.find('[data-testid="coding-workspace-101"]').trigger("click");
    await wrapper.find('[data-testid="coding-tree-thread-11"]').trigger("click");
    expect(store.selectedThreadId.value).toBe(11);
  });

  it("新对话清除线程选择并导航首页", async () => {
    const { wrapper, store } = await mountSidebar();
    store.selectThread(11);
    await wrapper.find('[data-testid="coding-new-task"]').trigger("click");
    expect(store.selectedThreadId.value).toBeNull();
    expect(wrapper.emitted("new-task")).toBeTruthy();
    expect(lastEmitted(wrapper, "navigate")).toEqual(["coding"]);
  });

  it("保留 Coding Agent 相关入口：自动化、插件、设置和诊断", async () => {
    const { wrapper } = await mountSidebar();
    await wrapper.find('[data-testid="coding-nav-tasks"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["tasks"]);
    await wrapper.find('[data-testid="coding-nav-extensions"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["extensions"]);
    await wrapper.find('[data-testid="coding-nav-settings"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["settings"]);
    await wrapper.find('[data-testid="coding-nav-diagnostics"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["diagnostics"]);
  });

  it("中部独立滚动，底部用户与系统入口保持固定", async () => {
    const { wrapper } = await mountSidebar();
    const scrollRegion = wrapper.find(".sidebar-scroll-region");
    expect(scrollRegion.exists()).toBe(true);
    expect(scrollRegion.find(".sidebar-actions").exists()).toBe(true);
    expect(scrollRegion.find('[data-testid="coding-recent"]').exists()).toBe(true);
    expect(scrollRegion.find(".sidebar-footer").exists()).toBe(false);
    expect(wrapper.find(".sidebar-footer").exists()).toBe(true);
  });

  it("折叠态隐藏文字并为图标入口保留可访问名称", async () => {
    const { wrapper } = await mountSidebar({ collapsed: true });
    expect(wrapper.find('[data-testid="coding-new-task"]').attributes("aria-label")).toBe("新对话");
    expect(wrapper.find('[data-testid="coding-toggle-projects"]').attributes("aria-label")).toBe("项目");
    expect(wrapper.find('[data-testid="coding-nav-settings"]').attributes("aria-label")).toBe("打开设置");
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(false);
  });

  it("空项目在展开项目区后呈现引导，刷新按钮调用 store.refresh", async () => {
    const store = createCodingWorkspacePreviewStore("no-projects");
    await flushPromises();
    const refreshSpy = vi.spyOn(store, "refresh");
    const wrapper = mount(CodingSidebar, { props: { store } });
    await wrapper.find('[data-testid="coding-toggle-projects"]').trigger("click");
    expect(wrapper.text()).toContain("暂无项目");
    await wrapper.find('[data-testid="coding-refresh"]').trigger("click");
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });
});
