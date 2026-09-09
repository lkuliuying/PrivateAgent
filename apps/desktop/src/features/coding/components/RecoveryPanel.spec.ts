import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import RecoveryPanel from "./RecoveryPanel.vue";
import { controlRun, fetchRecovery, fetchRunReview, type RecoveryReport } from "../api/recovery";

vi.mock("../api/recovery", () => ({ controlRun: vi.fn(), fetchRecovery: vi.fn(), fetchRunReview: vi.fn() }));
vi.mock("./PatchReviewPanel.vue", () => ({ default: { template: "<div />" } }));
const report: RecoveryReport = { run_id: "run", status: "running", state_version: 5, checkpoint_id: "checkpoint", logical_task_id: "run",
  resumed_from_run_id: null, can_resume: false, blockers: [], controls: [], executions: [], budget: { model_requests: 3 }, expired_approvals: [], limitations: [] };
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  vi.mocked(fetchRecovery).mockResolvedValue(report);
  vi.mocked(fetchRunReview).mockResolvedValue({ task_changes: [], preexisting_changes: [], external_or_unattributed: [], command_candidates: [], snapshot_complete: true, limitations: [] });
});
afterEach(() => vi.useRealTimers());

it("追加约束显示等待应用，同一网络失败重试保留请求标识", async () => {
  vi.mocked(controlRun).mockRejectedValueOnce(new Error("network"));
  const wrapper = mount(RecoveryPanel, { props: { runId: "run" } });
  await flushPromises();
  await wrapper.find("textarea").setValue("只解释");
  await wrapper.find("form").trigger("submit");
  await flushPromises();
  const sent = vi.mocked(controlRun).mock.calls[0][2];
  vi.mocked(controlRun).mockResolvedValue({ request_id: sent.request_id, kind: "steer", status: "received", result_run_id: "run" });
  vi.mocked(fetchRecovery).mockResolvedValue({ ...report, controls: [{ request_id: sent.request_id, kind: "steer", status: "received", result_run_id: "run" }] });
  await wrapper.findAll("button").find(b => b.text() === "重试上次控制")!.trigger("click");
  await flushPromises();
  expect(vi.mocked(controlRun).mock.calls[1][2]).toEqual(sent);
  expect(wrapper.text()).toContain("等待应用");
  expect(wrapper.text()).not.toContain("已应用");
  wrapper.unmount();
});

it("未知副作用阻止继续，取消接受不伪装为清理完成", async () => {
  vi.mocked(fetchRecovery).mockResolvedValue({ ...report, status: "interrupted", blockers: ["命令身份未知"], controls: [
    { request_id: "cancel", kind: "cancel", status: "applied", result_run_id: "run", cleanup_complete: false } ] });
  const wrapper = mount(RecoveryPanel, { props: { runId: "run" } });
  await flushPromises();
  expect(wrapper.findAll("button").find(b => b.text() === "核对并继续")!.attributes("disabled")).toBeDefined();
  expect(wrapper.text()).toContain("命令身份未知");
  expect(wrapper.text()).toContain("进程清理未确认");
  expect(wrapper.find("textarea").exists()).toBe(false);
  wrapper.unmount();
});

it("切换任务丢弃旧恢复回执，卸载关闭轮询", async () => {
  vi.mocked(fetchRecovery).mockResolvedValue({ ...report, status: "paused", can_resume: true });
  let resolve!: (value: Awaited<ReturnType<typeof controlRun>>) => void;
  vi.mocked(controlRun).mockReturnValue(new Promise(done => { resolve = done; }));
  const wrapper = mount(RecoveryPanel, { props: { runId: "run" } });
  await flushPromises();
  await wrapper.findAll("button").find(b => b.text() === "核对并继续")!.trigger("click");
  await wrapper.setProps({ runId: "other" });
  resolve({ request_id: "resume", kind: "resume", status: "applied", result_run_id: "child" });
  await flushPromises();
  expect(wrapper.emitted("resumed")).toBeUndefined();
  wrapper.unmount();
  const count = vi.mocked(fetchRecovery).mock.calls.length;
  await vi.advanceTimersByTimeAsync(5000);
  expect(fetchRecovery).toHaveBeenCalledTimes(count);
});

it("版本冲突后刷新并要求新操作，不自动覆盖控制状态", async () => {
  vi.mocked(controlRun).mockRejectedValue({ status: 409, message: "任务状态已变化" });
  const wrapper = mount(RecoveryPanel, { props: { runId: "run" } });
  await flushPromises();
  await wrapper.findAll("button").find(b => b.text() === "暂停")!.trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("任务状态已变化");
  expect(wrapper.text()).not.toContain("重试上次控制");
  expect(controlRun).toHaveBeenCalledTimes(1);
  wrapper.unmount();
});
