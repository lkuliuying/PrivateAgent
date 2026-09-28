import { mount } from "@vue/test-utils";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { nextTick } from "vue";
import CommandPalette from "./CommandPalette.vue";
import { searchWorkspace } from "../features/coding/api/workspaceSearch";
vi.mock("../features/coding/api/workspaceSearch", () => ({ searchWorkspace: vi.fn() }));
beforeEach(() => vi.mocked(searchWorkspace).mockResolvedValue({ items: [], next_cursor: null, examined: 0 }));

async function mountPalette() {
  const w = mount(CommandPalette);
  await nextTick();
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "导航命令")!.click();
  await nextTick();
  return w;
}

describe("CommandPalette", () => {
  it("渲染命令列表", async () => {
    const w = await mountPalette();
    expect(document.body.textContent).not.toContain("全局搜索");
    expect(document.body.textContent).not.toContain("新建提醒");
    expect(document.body.textContent).toContain("打开设置");
    expect(document.body.textContent).not.toContain("打开诊断");
    expect(document.querySelectorAll(".cp-item").length).toBe(3);
    w.unmount();
  });

  it("按查询过滤命令", async () => {
    const w = await mountPalette();
    const input = document.querySelector(".cp-input") as HTMLInputElement;
    input.value = "设置";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    const items = document.querySelectorAll(".cp-item");
    expect(items.length).toBe(1);
    expect(document.body.textContent).toContain("打开设置");
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
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await nextTick();
    expect(w.emitted("close")).toBeTruthy();
    w.unmount();
  });

  it("点击设置发出本机导航事件", async () => {
    const w = await mountPalette();
    const items = Array.from(document.querySelectorAll<HTMLElement>(".cp-item"));
    const searchItem = items.find((item) => item.textContent?.includes("打开设置"));
    expect(searchItem).toBeTruthy();
    searchItem!.click();
    await nextTick();
    expect(w.emitted("navigate")).toEqual([["settings"]]);
    w.unmount();
  });

  it("只显示 Coding Agent 相关目的地", async () => {
    const w = await mountPalette();
    expect(document.body.textContent).not.toContain("打开诊断");
    expect(document.body.textContent).toContain("打开Coding");
    expect(document.body.textContent).toContain("打开设置");
    expect(document.body.textContent).not.toContain("打开提醒");
    expect(document.body.textContent).not.toContain("新建收件箱项");
    expect(document.body.textContent).not.toContain("生成今日简报");
    w.unmount();
  });
});
