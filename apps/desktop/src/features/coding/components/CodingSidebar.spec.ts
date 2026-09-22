import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import CodingSidebar from "./CodingSidebar.vue";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";

const actions = vi.hoisted(() => ({ pin: vi.fn(), deleteProject: vi.fn(), deleteThread: vi.fn(), prompt: vi.fn(), confirm: vi.fn(), error: vi.fn() }));
vi.mock("../api/projects", async (original) => ({
  ...await original<typeof import("../api/projects")>(),
  setCodingProjectPinned: actions.pin, deleteCodingProject: actions.deleteProject,
}));
vi.mock("../api/threads", async (original) => ({ ...await original<typeof import("../api/threads")>(), deleteThread: actions.deleteThread }));
vi.mock("../../../stores/notifications", () => ({ useNotifications: () => ({ prompt: actions.prompt, confirm: actions.confirm, error: actions.error, openCenter: vi.fn(), unreadCount: { value: 0 } }) }));
vi.mock("./EditProjectDialog.vue", () => ({ default: { props: ["projectId"], emits: ["saved", "close"], template: '<button data-testid="edit-project-stub" @click="$emit(\'saved\')">保存项目 {{ projectId }}</button>' } }));
beforeEach(() => vi.resetAllMocks());

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

  it("移除自动化并保留插件和设置入口", async () => {
    const { wrapper } = await mountSidebar();
    expect(wrapper.find('[data-testid="coding-nav-tasks"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("自动化");
    await wrapper.find('[data-testid="coding-nav-extensions"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["extensions"]);
    await wrapper.find('[data-testid="user-menu-trigger"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["extensions"]);
    await wrapper.find('[data-testid="user-menu-settings"]').trigger("click");
    expect(lastEmitted(wrapper, "navigate")).toEqual(["settings"]);
    expect(wrapper.find('[data-testid="coding-nav-diagnostics"]').exists()).toBe(false);
    expect(wrapper.find('[aria-label="帮助与诊断"]').exists()).toBe(false);
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

  it("折叠态保留图标名称与展开入口，切换后能再次折叠", async () => {
    const { wrapper } = await mountSidebar({ collapsed: true });
    expect(wrapper.find('[data-testid="coding-new-task"]').attributes("aria-label")).toBe("新对话");
    expect(wrapper.find('[data-testid="coding-toggle-projects"]').attributes("aria-label")).toBe("项目");
    expect(wrapper.find('[data-testid="user-menu-trigger"]').attributes("aria-label")).toBe("账号菜单：liuying");
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(false);
    const toggle = wrapper.get('[data-testid="coding-toggle-collapse"]');
    expect(toggle.attributes("aria-label")).toBe("展开侧栏");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    await toggle.trigger("click");
    expect(wrapper.emitted("toggle-collapse")).toHaveLength(1);
    await wrapper.setProps({ collapsed: false });
    expect(toggle.attributes("aria-label")).toBe("折叠侧栏");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('[data-testid="coding-tree"]').exists()).toBe(true);
    await toggle.trigger("click");
    expect(wrapper.emitted("toggle-collapse")).toHaveLength(2);
    wrapper.unmount();
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

  it("编辑和置顶不会折叠项目，保存后刷新", async () => {
    const { wrapper, store } = await mountSidebar();
    const refresh = vi.spyOn(store, "refresh").mockResolvedValue();
    await wrapper.get('[data-testid="coding-project-edit-1"]').trigger("click");
    expect(wrapper.get('[data-testid="edit-project-stub"]').text()).toContain("1");
    await wrapper.get('[data-testid="edit-project-stub"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="coding-project-1"]').attributes("aria-expanded")).toBe("true");
    await wrapper.get('[data-testid="coding-project-pin-1"]').trigger("click");
    await flushPromises();
    expect(actions.pin).toHaveBeenCalledWith(1, true);
    expect(refresh).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).not.toContain("归档");
    wrapper.unmount();
  });

  it("删除需确认，确认等待中阻止重复点击，成功后清理当前项目", async () => {
    const { wrapper, store } = await mountSidebar();
    vi.spyOn(store, "refresh").mockResolvedValue();
    store.selectThread(11);
    let confirm: (accepted: boolean) => void = () => {};
    actions.confirm.mockImplementation(() => new Promise((resolve) => { confirm = resolve; }));
    const button = wrapper.get('[data-testid="coding-project-delete-1"]');
    await button.trigger("click");
    await button.trigger("click");
    expect(actions.confirm).toHaveBeenCalledOnce();
    expect(actions.confirm).toHaveBeenCalledWith(expect.objectContaining({ danger: true, impact: expect.stringContaining("文件保持不变") }));
    expect(actions.deleteProject).not.toHaveBeenCalled();
    confirm(true);
    await flushPromises();
    expect(actions.deleteProject).toHaveBeenCalledWith(1);
    expect(store.selectedThreadId.value).toBeNull();
    expect(wrapper.find('[data-testid="coding-project-1"]').exists()).toBe(false);
    expect(store.selectedProjectId.value).toBe(2);
    wrapper.unmount();
  });

  it("取消删除不提交，后端拒绝时保留会话并显示错误", async () => {
    const { wrapper, store } = await mountSidebar();
    store.selectThread(11);
    actions.confirm.mockResolvedValueOnce(false);
    const button = wrapper.get('[data-testid="coding-thread-delete-11"]');
    await button.trigger("click");
    await flushPromises();
    expect(actions.deleteThread).not.toHaveBeenCalled();
    actions.confirm.mockResolvedValueOnce(true);
    actions.deleteThread.mockRejectedValueOnce({ message: "请先停止任务" });
    await button.trigger("click");
    await flushPromises();
    expect(actions.error).toHaveBeenCalledWith("操作失败", "请先停止任务");
    expect(store.selectedThreadId.value).toBe(11);
    expect(button.attributes("disabled")).toBeUndefined();
    wrapper.unmount();
  });

  it("删除当前会话回到首页，保留项目和其他会话", async () => {
    const { wrapper, store } = await mountSidebar();
    vi.spyOn(store, "refresh").mockResolvedValue();
    store.selectThread(11);
    actions.confirm.mockResolvedValue(true);
    await wrapper.get('[data-testid="coding-thread-delete-11"]').trigger("click");
    await flushPromises();
    expect(actions.deleteThread).toHaveBeenCalledWith(11);
    expect(store.selectedThreadId.value).toBeNull();
    expect(wrapper.find('[data-testid="coding-thread-11"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="coding-thread-12"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
