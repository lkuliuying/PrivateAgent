import { mount } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";
import { nextTick } from "vue";
import CommandPalette from "./CommandPalette.vue";

// 第八阶段 M1：CommandPalette 组件测试（渲染 / 过滤 / 键盘 / 动作）。
vi.mock("../api", () => ({
  createInbox: vi.fn(),
  createReminder: vi.fn(),
  createTodayBriefing: vi.fn(),
  createSession: vi.fn(),
}));
vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    prompt: vi.fn().mockResolvedValue(null),
  }),
}));

async function mountPalette() {
  const w = mount(CommandPalette);
  await nextTick();
  return w;
}

describe("CommandPalette", () => {
  it("渲染命令列表", async () => {
    const w = await mountPalette();
    expect(document.body.textContent).toContain("全局搜索");
    expect(document.body.textContent).toContain("新建提醒");
    expect(document.body.textContent).toContain("打开设置");
    expect(document.querySelectorAll(".cp-item").length).toBeGreaterThan(5);
    w.unmount();
  });

  it("按查询过滤命令", async () => {
    const w = await mountPalette();
    const input = document.querySelector(".cp-input") as HTMLInputElement;
    input.value = "收件箱项";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    const items = document.querySelectorAll(".cp-item");
    expect(items.length).toBe(1);
    expect(document.body.textContent).toContain("新建收件箱项");
    w.unmount();
  });

  it("无匹配时显示空状态", async () => {
    const w = await mountPalette();
    const input = document.querySelector(".cp-input") as HTMLInputElement;
    input.value = "zzz不存在的命令zzz";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    expect(document.body.textContent).toContain("无匹配命令");
    w.unmount();
  });

  it("Escape 发出 close 事件", async () => {
    const w = await mountPalette();
    const input = document.querySelector(".cp-input") as HTMLInputElement;
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await nextTick();
    expect(w.emitted("close")).toBeTruthy();
    w.unmount();
  });

  it("点击「全局搜索」发出 open-search", async () => {
    const w = await mountPalette();
    const items = Array.from(document.querySelectorAll<HTMLElement>(".cp-item"));
    const searchItem = items.find((item) => item.textContent?.includes("全局搜索"));
    expect(searchItem).toBeTruthy();
    searchItem!.click();
    await nextTick();
    expect(w.emitted("open-search")).toBeTruthy();
    w.unmount();
  });
});
