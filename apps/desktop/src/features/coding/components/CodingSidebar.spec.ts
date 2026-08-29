import { describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import CodingSidebar from "./CodingSidebar.vue";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";

vi.mock("../../../components/UserMenu.vue", () => ({
  default: {
    emits: ["settings"],
    template: `
      <div>
        <button data-testid="user-menu-trigger" aria-label="账号菜单：liuying">liuying</button>
        <button data-testid="user-menu-settings" @click="$emit('settings')">设置</button>
      </div>
    `,
  },
}));

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
  it("使用紧凑导航，并把对话直接归入所属项目", async () => {
    const { wrapper } = await mountSidebar();

    expect(wrapper.text()).toContain("PrivateAgent");
    expect(wrapper.find('[data-testid="coding-thread-11"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-thread-11"]').attributes("data-project-id")).toBe("1");
    expect(wrapper.find('[data-testid="coding-thread-12"]').attributes("data-workspace-id")).toBe("102");
    expect(wrapper.find('[data-testid="coding-thread-21"]').attributes("data-project-id")).toBe("2");
    expect(wrapper.find('[data-testid="coding-recent"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="coding-personal"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="coding-legacy-section"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("个人工作区");
    expect(wrapper.text()).not.toContain("更多工作区");
  });

  it("项目分组默认展开，也可以单独折叠", async () => {
    const { wrapper } = await mountSidebar();
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coding-project-1"]').attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('[data-testid="coding-thread-11"]').exists()).toBe(true);

    await wrapper.find('[data-testid="coding-project-1"]').trigger("click");
    expect(wrapper.find('[data-testid="coding-project-1"]').attributes("aria-expanded")).toBe("false");
    expect(wrapper.find('[data-testid="coding-thread-11"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="coding-thread-21"]').exists()).toBe(true);
  });

  it("项目内对话能选择对应线程、项目与工作区并返回 Coding 工作台", async () => {
    const { wrapper, store } = await mountSidebar();
    await wrapper.find('[data-testid="coding-thread-12"]').trigger("click");
    expect(store.selectedThreadId.value).toBe(12);
    expect(store.selectedProjectId.value).toBe(1);
    expect(store.selectedWorkspaceId.value).toBe(102);
    expect(lastEmitted(wrapper, "navigate")).toEqual(["coding"]);
  });

  it("鼠标悬浮或键盘聚焦对话时显示项目、分支、状态和更新时间", async () => {
    const { wrapper } = await mountSidebar();
    const thread = wrapper.find('[data-testid="coding-thread-12"]');

    await thread.trigger("mouseenter");
    const details = wrapper.find('[data-testid="coding-thread-details-12"]');
    expect(details.attributes("role")).toBe("tooltip");
    expect(details.text()).toContain("梳理 coding 模块依赖");
    expect(details.text()).toContain("PrivateAgent");
    expect(details.text()).toContain("feature/coding-workbench");
    expect(details.text()).toContain("正常");

    await thread.trigger("mouseleave");
    expect(wrapper.find('[data-testid="coding-thread-details-12"]').exists()).toBe(false);

    await thread.trigger("focusin");
    expect(wrapper.find('[data-testid="coding-thread-details-12"]').exists()).toBe(true);
    expect(thread.attributes("aria-describedby")).toBe("coding-thread-details-12");
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
    await wrapper.find('[data-testid="user-menu-trigger"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["extensions"]);
    await wrapper.find('[data-testid="user-menu-settings"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["settings"]);
    await wrapper.find('[data-testid="coding-nav-diagnostics"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["diagnostics"]);
  });

  it("中部独立滚动，底部用户与系统入口保持固定", async () => {
    const { wrapper } = await mountSidebar();
    const scrollRegion = wrapper.find(".sidebar-scroll-region");
    expect(scrollRegion.exists()).toBe(true);
    expect(scrollRegion.find(".sidebar-actions").exists()).toBe(true);
    expect(scrollRegion.find('[data-testid="coding-tree"]').exists()).toBe(true);
    expect(scrollRegion.find(".sidebar-footer").exists()).toBe(false);
    expect(wrapper.find(".sidebar-footer").exists()).toBe(true);
  });

  it("折叠态隐藏文字并为图标入口保留可访问名称", async () => {
    const { wrapper } = await mountSidebar({ collapsed: true });
    expect(wrapper.find('[data-testid="coding-new-task"]').attributes("aria-label")).toBe("新对话");
    expect(wrapper.find('[data-testid="coding-toggle-projects"]').attributes("aria-label")).toBe("项目");
    expect(wrapper.find('[data-testid="user-menu-trigger"]').attributes("aria-label")).toBe("账号菜单：liuying");
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(false);
  });

  it("空项目直接呈现引导，刷新按钮调用 store.refresh", async () => {
    const store = createCodingWorkspacePreviewStore("no-projects");
    await flushPromises();
    const refreshSpy = vi.spyOn(store, "refresh");
    const wrapper = mount(CodingSidebar, { props: { store } });
    expect(wrapper.text()).toContain("暂无项目");
    await wrapper.find('[data-testid="coding-refresh"]').trigger("click");
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });
});
