import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import CommandPalette from "./CommandPalette.vue";
import { searchWorkspace, type WorkspaceSearchPage } from "../features/coding/api/workspaceSearch";
vi.mock("../features/coding/api/workspaceSearch", () => ({ searchWorkspace: vi.fn() }));
const mounted: { unmount: () => void }[] = [];
const hit = { kind: "message" as const, project_id: 1, project_name: "项目", session_id: 3, message_id: 9, title: "找到的任务", excerpt: "正文匹配", updated_at: "", status: "completed", archived: false };
beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); vi.mocked(searchWorkspace).mockResolvedValue({ items: [hit], next_cursor: null, examined: 1 }); });
afterEach(() => { mounted.splice(0).forEach(w => w.unmount()); vi.useRealTimers(); });
describe("任务与消息检索", () => {
  it("默认展示任务并将消息定位目标传给工作台", async () => {
    const w = mount(CommandPalette, { global: { stubs: { Teleport: true } } }); mounted.push(w); await flushPromises();
    expect(w.get(".cp-result").text()).toContain("正文匹配");
    await w.get(".cp-input").trigger("keydown", { key: "Enter" });
    expect(w.emitted("open-result")).toEqual([[hit]]);
    expect(w.emitted("navigate")).toBeUndefined();
  });
  it("更改筛选会撤销旧搜索，旧响应不能覆盖新结果", async () => {
    let finish!: (value: WorkspaceSearchPage) => void;
    vi.mocked(searchWorkspace).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const w = mount(CommandPalette, { props: { projects: [{ id: 1, name: "项目" }] }, global: { stubs: { Teleport: true } } }); mounted.push(w);
    const signal = vi.mocked(searchWorkspace).mock.calls[0][1];
    await w.get('[aria-label="按项目筛选"]').setValue(1); await w.get('input[type="checkbox"]').setValue(true);
    await vi.advanceTimersByTimeAsync(181); await flushPromises();
    expect(signal?.aborted).toBe(true);
    expect(vi.mocked(searchWorkspace).mock.lastCall?.[0]).toMatchObject({ project_id: 1, archived: true });
    finish({ items: [{ ...hit, title: "旧响应" }], next_cursor: null, examined: 1 }); await flushPromises();
    expect(w.text()).not.toContain("旧响应");
  });
  it("继续检索保留当前结果并携带游标", async () => {
    vi.mocked(searchWorkspace).mockResolvedValueOnce({ items: [hit], next_cursor: 7, examined: 3 }).mockResolvedValueOnce({ items: [{ ...hit, message_id: 5, title: "更早的消息" }], next_cursor: null, examined: 1 });
    const w = mount(CommandPalette, { global: { stubs: { Teleport: true } } }); mounted.push(w); await flushPromises();
    await w.findAll("button").find(b => b.text() === "继续搜索更早记录")!.trigger("click"); await flushPromises();
    expect(vi.mocked(searchWorkspace).mock.lastCall?.[0].before).toBe(7);
    expect(w.findAll(".cp-result")).toHaveLength(2);
  });
});
