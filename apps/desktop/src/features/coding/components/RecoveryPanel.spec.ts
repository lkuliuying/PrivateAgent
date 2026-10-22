import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import RecoveryPanel from "./RecoveryPanel.vue";
import { controlRun, fetchRecovery, fetchResumePreview, fetchRunReview, reconcileRun, type RecoveryReport } from "../api/recovery";
import { listCodingModelProfiles } from "../api/modelProfiles";
import { savePendingControl } from "../model/pendingControls";

vi.mock("../api/recovery", () => ({ controlRun: vi.fn(), fetchRecovery: vi.fn(), fetchRunReview: vi.fn(), fetchResumePreview: vi.fn(), reconcileRun: vi.fn() }));
vi.mock("../api/modelProfiles", () => ({ listCodingModelProfiles: vi.fn() }));
vi.mock("./PatchReviewPanel.vue", () => ({ default: { template: "<div />" } }));
const report: RecoveryReport = { run_id: "run", status: "running", state_version: 5, checkpoint_id: "checkpoint", logical_task_id: "run",
  resumed_from_run_id: null, can_resume: false, blockers: [], controls: [], executions: [], budget: { model_requests: 3 }, expired_approvals: [], limitations: [] };
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); sessionStorage.clear(); savePendingControl("run", null); savePendingControl("other", null);
  vi.mocked(fetchRecovery).mockResolvedValue(report);
  vi.mocked(listCodingModelProfiles).mockResolvedValue([]);
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
  expect(wrapper.findAll("button").find(b => b.text() === "保留当前代码并继续")!.attributes("disabled")).toBeDefined();
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
  await wrapper.findAll("button").find(b => b.text() === "保留当前代码并继续")!.trigger("click");
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

it("结构化待核对项提交核对依据，人工说明标注系统未验证", async () => {
  vi.mocked(fetchRecovery).mockResolvedValue({ ...report, status: "interrupted", can_resume: false,
    blocker_details: [{ item_id: "mcp-item", kind: "mcp_write", label: "MCP 写入结果未知", status: "open", source: "machine",
      actions: ["externally_confirmed", "externally_failed"], resolvable: true, reason: "系统无法验证远端结果" }] });
  vi.mocked(reconcileRun).mockResolvedValue({ request_id: "reconcile-request", kind: "reconcile", status: "applied", result_run_id: "run",
    item_id: "mcp-item", source: "user_statement", verified: false, note: "远端已出现目标文件" });
  const wrapper = mount(RecoveryPanel, { props: { runId: "run", reconcileEnabled: true } });
  await flushPromises();
  expect(wrapper.text()).toContain("系统无法验证远端结果");
  await wrapper.find("textarea").setValue("远端已出现目标文件");
  await wrapper.findAll("button").find(b => b.text() === "已核对完成")!.trigger("click");
  await flushPromises();
  const sent = vi.mocked(reconcileRun).mock.calls[0][1];
  expect(sent.item_id).toBe("mcp-item");
  expect(sent.decision).toBe("externally_confirmed");
  expect(sent.note).toBe("远端已出现目标文件");
  expect(sent.checkpoint_id).toBe("checkpoint");
  expect(typeof sent.request_id).toBe("string");
  wrapper.unmount();
});

it("核对入口按能力位隐藏，旧后端不出现新提交按钮", async () => {
  vi.mocked(fetchRecovery).mockResolvedValue({ ...report, status: "interrupted",
    blocker_details: [{ item_id: "mcp-item", kind: "mcp_write", label: "MCP 写入结果未知", status: "open", actions: ["externally_confirmed"], resolvable: true }] });
  const wrapper = mount(RecoveryPanel, { props: { runId: "run" } });
  await flushPromises();
  expect(wrapper.text()).toContain("MCP 写入结果未知");
  expect(wrapper.findAll("button").some(b => b.text() === "已核对完成")).toBe(false);
  wrapper.unmount();
});

it("选择模型后继续要求先预览差异再提交摘要", async () => {
  vi.mocked(fetchRecovery).mockResolvedValue({ ...report, status: "interrupted", can_resume: true, model_profile_id: "source-profile" });
  vi.mocked(listCodingModelProfiles).mockResolvedValue([
    { id: "source-profile", provider: "openai", displayName: "原模型", modelName: "gpt-a", isDefault: true, isLocal: false, nativeToolCalls: true, supportsStreaming: true, supportsStructuredOutput: true, supportsVision: true, contextTokens: 64000, reasoningEfforts: null, usageReporting: true, enabled: true },
    { id: "target-profile", provider: "openai", displayName: "目标模型", modelName: "gpt-b", isDefault: false, isLocal: false, nativeToolCalls: true, supportsStreaming: true, supportsStructuredOutput: true, supportsVision: true, contextTokens: 64000, reasoningEfforts: null, usageReporting: true, enabled: true },
  ]);
  vi.mocked(fetchResumePreview).mockResolvedValue({ format_version: "1.0", run_id: "run", checkpoint_id: "checkpoint", state_version: 5, source: null,
    target: { model_profile_id: "target-profile", model_name: "gpt-b", provider: "openai", api_format: "responses", endpoint: "https://example.test", context_tokens: 64000, native_tool_calls: true, supports_vision: true, supports_structured_output: true, configuration_version: "c2", capability_version: "k2" },
    switched: true, capability_gaps: [], blockers: [], preview_sha256: "sha-1", eligible: true, can_resume: true, recovery_class: "manual_resume",
    requires_model_change_acceptance: true, requires_timing_acceptance: false, budget_note: "沿用原逻辑任务的累计用量、失败记录与上限；切换模型不清零、不扩额", limitations: [] });
  vi.mocked(controlRun).mockResolvedValue({ request_id: "resume-1", kind: "resume", status: "applied", result_run_id: "child", model_switched: true });
  const wrapper = mount(RecoveryPanel, { props: { runId: "run", handoffEnabled: true } });
  await flushPromises();
  await wrapper.find("select").setValue("target-profile");
  await wrapper.findAll("button").find(b => b.text() === "预览差异")!.trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("gpt-b");
  expect(wrapper.text()).toContain("沿用原逻辑任务");
  await wrapper.findAll("button").find(b => b.text() === "用目标模型继续")!.trigger("click");
  await flushPromises();
  const sent = vi.mocked(controlRun).mock.calls[0][2];
  expect(sent.model_profile_id).toBe("target-profile");
  expect(sent.preview_sha256).toBe("sha-1");
  expect(sent.accept_model_change).toBe(true);
  expect(sent.checkpoint_id).toBe("checkpoint");
  wrapper.unmount();
});

it("未确认计时尾段需要显式勾选后才允许继续", async () => {
  vi.mocked(fetchRecovery).mockResolvedValue({ ...report, status: "interrupted", can_resume: true,
    timing: { unconfirmed_tail: true, confirmed_active_seconds: 30 } });
  vi.mocked(controlRun).mockResolvedValue({ request_id: "resume-2", kind: "resume", status: "applied", result_run_id: "child" });
  const wrapper = mount(RecoveryPanel, { props: { runId: "run" } });
  await flushPromises();
  expect(wrapper.text()).toContain("末段耗时未确认");
  const resume = () => wrapper.findAll("button").find(b => b.text() === "保留当前代码并继续")!;
  expect(resume().attributes("disabled")).toBeDefined();
  await wrapper.find('input[type="checkbox"]').setValue(true);
  await resume().trigger("click");
  await flushPromises();
  expect(vi.mocked(controlRun).mock.calls[0][2].accept_unconfirmed_timing).toBe(true);
  wrapper.unmount();
});

