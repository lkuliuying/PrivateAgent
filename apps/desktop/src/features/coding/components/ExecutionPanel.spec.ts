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
