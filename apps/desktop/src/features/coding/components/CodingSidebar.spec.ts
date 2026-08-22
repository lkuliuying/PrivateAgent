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
  return { wrapper, store };
}

/** tsconfig lib 未含 Array.at：以长度索引取最后一次事件 */
function lastEmitted(
  wrapper: { emitted: (event: string) => unknown[] | undefined },
  event: string
): unknown {
  const events = wrapper.emitted(event);
  return events?.[events.length - 1];
}

describe("CodingSidebar", () => {
  it("渲染项目树：项目 → 工作区/分支 → 任务，含状态标记", async () => {
    const { wrapper } = await mountSidebar();
    await wrapper.find('[data-testid="coding-project-1"]').trigger("click");
    await wrapper.find('[data-testid="coding-workspace-101"]').trigger("click");
    expect(wrapper.text()).toContain("PrivateAgent");
    expect(wrapper.text()).toContain("根工作区");
    expect(wrapper.text()).toContain("feature/coding-workbench");
    expect(wrapper.find('[data-testid="coding-thread-11"]').exists()).toBe(true);
    // 工作区状态 dot 带 data-status（e2e/视觉锚点）
    expect(wrapper.find('[data-testid="coding-workspace-101"]').attributes("data-status")).toBe(
      "active"
    );
  });

  it("点击任务：选中线程并请求导航到 coding 视图", async () => {
    const { wrapper, store } = await mountSidebar();
    await wrapper.find('[data-testid="coding-project-1"]').trigger("click");
    await wrapper.find('[data-testid="coding-workspace-101"]').trigger("click");
    await wrapper.find('[data-testid="coding-thread-11"]').trigger("click");
    expect(store.selectedThreadId.value).toBe(11);
    expect(lastEmitted(wrapper, "navigate")).toEqual(["coding"]);
  });

  it("新建任务：清线程选择、离开任务态并导航首页", async () => {
    const { wrapper, store } = await mountSidebar();
    store.selectThread(11);
    await wrapper.find('[data-testid="coding-new-task"]').trigger("click");
    expect(store.selectedThreadId.value).toBeNull();
    expect(wrapper.emitted("new-task")).toBeTruthy();
    expect(lastEmitted(wrapper, "navigate")).toEqual(["coding"]);
  });

  it("一级动作与底部入口指向既有页面（自动化/扩展/设置/诊断）", async () => {
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

  // ============ v0.8.0 W6-R：个人工作区六入口（计划 §4.1/§6.1） ============
  const PERSONAL_VIEWS = ["reminders", "inbox", "goals", "briefings", "capture", "privacy"] as const;

  it("渲染六个个人工作入口，点击导航到各自独立主区", async () => {
    const { wrapper } = await mountSidebar();
    expect(wrapper.find('[data-testid="coding-personal"]').exists()).toBe(true);
    for (const view of PERSONAL_VIEWS) {
      const entry = wrapper.find(`[data-testid="coding-personal-${view}"]`);
      expect(entry.exists()).toBe(true);
      expect(entry.element.tagName.toLowerCase()).toBe("button"); // 键盘可达
      await entry.trigger("click");
      expect(lastEmitted(wrapper, "navigate")).toEqual([view]);
    }
  });

  it("当前个人页高亮（aria-current=page）", async () => {
    const { wrapper } = await mountSidebar({ activeView: "reminders" });
    expect(wrapper.find('[data-testid="coding-personal-reminders"]').attributes("aria-current")).toBe("page");
  });

  it("待处理徽标仅呈现正整数（只读数字，非完整模块）", async () => {
    const { wrapper } = await mountSidebar({
      personalCounts: { reminders: 3, inbox: 0, privacy: 1 },
    });
    const badge = wrapper.find('[data-testid="coding-personal-badge-reminders"]');
    expect(badge.exists()).toBe(true);
    expect(badge.text()).toBe("3");
    expect(wrapper.find('[data-testid="coding-personal-badge-inbox"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="coding-personal-badge-privacy"]').text()).toBe("1");
  });

  it("折叠态个人入口保留可辨识图标、tooltip 与键盘可达名称", async () => {
    const { wrapper } = await mountSidebar({ collapsed: true });
    for (const view of PERSONAL_VIEWS) {
      const entry = wrapper.find(`[data-testid="coding-personal-${view}"]`);
      expect(entry.attributes("aria-label")).toBeTruthy();
      expect(entry.attributes("title")).toBeTruthy();
    }
  });

  it("折叠态隐藏文字标签，icon-only 按钮保留可访问名称", async () => {
    const { wrapper } = await mountSidebar({ collapsed: true });
    const newTask = wrapper.find('[data-testid="coding-new-task"]');
    expect(newTask.attributes("aria-label")).toBe("新建任务");
    expect(wrapper.find('[data-testid="coding-open-search"]').attributes("aria-label")).toBe(
      "搜索"
    );
    expect(wrapper.find('[data-testid="coding-nav-settings"]').attributes("aria-label")).toBe(
      "设置"
    );
    // 折叠态不渲染项目树（仅图标动作）
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(false);
  });

  it("空项目树呈现引导文案；刷新按钮可触发 store.refresh", async () => {
    const store = createCodingWorkspacePreviewStore("no-projects");
    await flushPromises();
    const refreshSpy = vi.spyOn(store, "refresh");
    const wrapper = mount(CodingSidebar, { props: { store } });
    expect(wrapper.text()).toContain("暂无项目");
    await wrapper.find('[data-testid="coding-refresh"]').trigger("click");
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });
});
