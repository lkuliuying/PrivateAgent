import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ExecutionPanel from "./ExecutionPanel.vue";
import { cancelExecution, listExecutions, readExecution, writeExecution, type ManagedExecution } from "../api/executions";

const confirm = vi.hoisted(() => vi.fn());
vi.mock("../../../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));
vi.mock("../api/executions", async original => ({ ...await original<typeof import("../api/executions")>(),
  listExecutions: vi.fn(), readExecution: vi.fn(), cancelExecution: vi.fn(), writeExecution: vi.fn(), closeExecutions: vi.fn() }));
const item: ManagedExecution = { execution_id: "exec", run_id: "run", argv: ["python", "server.py"], cwd: "中文 目录", status: "running",
  retention: "session", state_version: 2, stdin_open: true, stopped: false, exit_code: null, error: null, dropped_bytes: 0, last_output_sequence: 1 };
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  vi.mocked(listExecutions).mockResolvedValue({ items: [item] });
  vi.mocked(readExecution).mockResolvedValue({ ...item, chunks: [{ sequence: 1, stream: "stdout", data: "<img src=x onerror=alert(1)>\u001b[31m中文🙂" }], next_cursor: 1, gap: false, has_more: false });
  vi.mocked(cancelExecution).mockResolvedValue({ ...item, status: "cancelled", stopped: true });
});
afterEach(() => { vi.useRealTimers(); });

it("完成记录默认收起，失败与仍在运行的进程自动展开", async () => {
  vi.mocked(listExecutions).mockResolvedValue({ items: [{ ...item, status: "exited", stopped: true, exit_code: 0 }] });
  const wrapper = mount(ExecutionPanel, { props: { sessionId: 1 } });
  await flushPromises();
  expect(wrapper.get("details").attributes("open")).toBeUndefined();
  vi.mocked(listExecutions).mockResolvedValue({ items: [{ ...item, status: "failed", error: "沙箱检查超时" }] });
  await vi.advanceTimersByTimeAsync(2000);
  await flushPromises();
  expect(wrapper.get("details").attributes("open")).toBeDefined();
  expect(wrapper.text()).toContain("沙箱检查超时");
  wrapper.unmount();
});

it("输出按文本展示，重复块去重，卸载清理轮询", async () => {
  const wrapper = mount(ExecutionPanel, { props: { sessionId: 1 } });
  await flushPromises();
  expect(wrapper.find("img").exists()).toBe(false);
  expect(wrapper.find("pre").text()).toContain("中文🙂");
  await vi.advanceTimersByTimeAsync(300); await flushPromises();
  expect(wrapper.find("pre").text().match(/中文/g)?.length).toBe(1);
  wrapper.unmount();
  const count = vi.mocked(listExecutions).mock.calls.length;
  await vi.advanceTimersByTimeAsync(5000);
  expect(listExecutions).toHaveBeenCalledTimes(count);
});

it("确认期间切换会话不发送 stdin，停止以服务端结果为准", async () => {
  let resolve!: (answer: boolean) => void;
  confirm.mockReturnValue(new Promise(done => { resolve = done; }));
  const wrapper = mount(ExecutionPanel, { props: { sessionId: 1 } });
  await flushPromises();
  await wrapper.find("input").setValue("hello");
  await wrapper.findAll("button").find(button => button.text() === "发送")!.trigger("click");
  await wrapper.setProps({ sessionId: 2 });
  resolve(true); await flushPromises();
  expect(writeExecution).not.toHaveBeenCalled();
  await wrapper.findAll("button").find(button => button.text() === "停止")!.trigger("click");
  await flushPromises();
  expect(cancelExecution).toHaveBeenCalledWith(2, "exec");
  expect(wrapper.text()).toContain("运行中");
  wrapper.unmount();
});

it("游标缺口与磁盘丢弃明确展示", async () => {
  vi.mocked(listExecutions).mockResolvedValue({ items: [{ ...item, dropped_bytes: 5000 }] });
  vi.mocked(readExecution).mockResolvedValue({ ...item, chunks: [], next_cursor: 7, gap: true, has_more: false });
  const wrapper = mount(ExecutionPanel, { props: { sessionId: 1 } });
  await flushPromises();
  expect(wrapper.text()).toContain("已丢弃 5000 字节");
  expect(wrapper.text()).toContain("不代表完整日志");
  wrapper.unmount();
});

it("持续输出跟随尾部，但保留用户向上翻阅的位置", async () => {
  const wrapper = mount(ExecutionPanel, { props: { sessionId: 1 } });
  await flushPromises();
  const element = wrapper.find("pre").element;
  const panel = wrapper.element;
  // 无布局环境中以已提交的 DOM 文本模拟新增一行后的高度。
  Object.defineProperties(element, { scrollHeight: { get: () => element.textContent?.includes("下一行") ? 700 : 600 }, clientHeight: { value: 180 } });
  Object.defineProperties(panel, { scrollHeight: { get: () => element.textContent?.includes("下一行") ? 400 : 350 }, clientHeight: { value: 240 } });
  element.scrollTop = 420;
  panel.scrollTop = 110;
  vi.mocked(readExecution).mockImplementation(async () => {
    return { ...item, chunks: [{ sequence: 2, stream: "stdout", data: "下一行" }], next_cursor: 2, gap: false, has_more: false };
  });
  await vi.advanceTimersByTimeAsync(300); await flushPromises();
  expect(element.scrollTop).toBe(700);
  expect(panel.scrollTop).toBe(400);
  element.scrollTop = 40;
  panel.scrollTop = 20;
  await vi.advanceTimersByTimeAsync(300); await flushPromises();
  expect(element.scrollTop).toBe(40);
  expect(panel.scrollTop).toBe(20);
  element.scrollTop = 520;
  await vi.advanceTimersByTimeAsync(300); await flushPromises();
  expect(panel.scrollTop).toBe(20);
  wrapper.unmount();
});
