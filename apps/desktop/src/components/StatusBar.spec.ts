import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import StatusBar from "./StatusBar.vue";

vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    unreadCount: { value: 0 },
    loadPersisted: vi.fn().mockResolvedValue(undefined),
    openCenter: vi.fn(),
  }),
}));

describe("StatusBar", () => {
  it("只显示任务与通知，不再展示服务端拓扑状态", () => {
    const wrapper = mount(StatusBar, { props: { taskLabel: "空闲" } });

    expect(wrapper.text()).toContain("空闲");
    expect(wrapper.text()).not.toContain("API");
    expect(wrapper.text()).not.toContain("MySQL");
    expect(wrapper.text()).not.toContain("Chroma");
    expect(wrapper.attributes("aria-label")).toBe("任务与通知状态");

    wrapper.unmount();
  });
});
