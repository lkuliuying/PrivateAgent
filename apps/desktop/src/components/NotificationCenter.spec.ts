import { mount } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ref, computed, nextTick } from "vue";
import NotificationCenter from "./NotificationCenter.vue";

// 第八阶段 M1：NotificationCenter 组件测试（开合 / 历史渲染 / 未读计数）。
const centerOpen = ref(false);
const history = ref<any[]>([]);
const unreadCount = computed(() => history.value.filter((h) => !h.read).length);

vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    centerOpen,
    history,
    unreadCount,
    closeCenter: vi.fn(() => {
      centerOpen.value = false;
    }),
    markAllRead: vi.fn(),
    clearHistory: vi.fn(() => {
      history.value = [];
    }),
    toasts: ref([]),
    confirmState: ref({ open: false, opts: { title: "" }, resolve: null }),
    promptState: ref({ open: false, opts: { title: "" }, resolve: null }),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  }),
}));

beforeEach(() => {
  centerOpen.value = false;
  history.value = [];
  document.body.innerHTML = "";
});

describe("NotificationCenter", () => {
  it("center 关闭时不渲染面板", () => {
    const w = mount(NotificationCenter);
    expect(document.querySelector(".nc-panel")).toBeNull();
    w.unmount();
  });

  it("打开后渲染历史条目", async () => {
    history.value = [
      {
        id: 1,
        level: "info",
        kind: "x",
        title: "通知A",
        message: "内容A",
        created_at: new Date().toISOString(),
        read: false,
      },
    ];
    centerOpen.value = true;
    const w = mount(NotificationCenter);
    await nextTick();
    expect(document.querySelector(".nc-panel")).not.toBeNull();
    expect(document.body.textContent).toContain("通知A");
    expect(document.body.textContent).toContain("内容A");
    w.unmount();
  });

  it("未读计数显示徽标", async () => {
    history.value = [
      {
        id: 1,
        level: "warning",
        kind: "x",
        title: "未读1",
        created_at: new Date().toISOString(),
        read: false,
      },
      {
        id: 2,
        level: "info",
        kind: "x",
        title: "已读1",
        created_at: new Date().toISOString(),
        read: true,
      },
    ];
    centerOpen.value = true;
    const w = mount(NotificationCenter);
    await nextTick();
    const badge = document.querySelector(".nc-badge");
    expect(badge).not.toBeNull();
    expect(badge?.textContent?.trim()).toBe("1");
    w.unmount();
  });

  it("无历史显示空状态", async () => {
    centerOpen.value = true;
    const w = mount(NotificationCenter);
    await nextTick();
    expect(document.body.textContent).toContain("暂无通知");
    w.unmount();
  });
});
