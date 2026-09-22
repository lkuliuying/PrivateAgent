import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import RunControlBar from "./RunControlBar.vue";
import CodingComposer from "./CodingComposer.vue";
import DiffFeedback from "./DiffFeedback.vue";
import { controlRun, fetchRecovery, type RecoveryReport } from "../api/recovery";
import { enqueueTurn, fetchTurnQueue } from "../api/turnQueue";
import { savePendingControl } from "../model/pendingControls";

vi.mock("../api/recovery", () => ({ controlRun: vi.fn(), fetchRecovery: vi.fn() }));
vi.mock("../api/turnQueue", () => ({ enqueueTurn: vi.fn(), fetchTurnQueue: vi.fn(), removeQueuedTurn: vi.fn() }));
const mounted: { unmount: () => void }[] = [];
const report: RecoveryReport = { run_id: "run", status: "running", state_version: 2, checkpoint_id: "cp", logical_task_id: "run", resumed_from_run_id: null, can_resume: false, blockers: [], controls: [], executions: [], budget: {}, expired_approvals: [], limitations: [] };
beforeEach(() => {
  vi.resetAllMocks(); savePendingControl("run", null);
  vi.mocked(fetchRecovery).mockResolvedValue(report);
  vi.mocked(fetchTurnQueue).mockResolvedValue({ item: null });
});
afterEach(() => { mounted.splice(0).forEach(w => w.unmount()); savePendingControl("run", null); });

describe("工作台核心交互", () => {
  it("运行中只保留草稿，不再提供补充和排队；结束后可正常发送", async () => {
    const wrapper = mount(CodingComposer, { props: { running: true, busy: true } }); mounted.push(wrapper);
    const input = wrapper.get("textarea");
    expect(input.attributes("disabled")).toBeUndefined();
    expect(wrapper.find('[aria-label="运行中发送方式"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="coding-composer-send"]').exists()).toBe(false);
    await input.setValue("保留兼容性");
    await input.trigger("keydown", { key: "Enter" }); await flushPromises();
    expect(wrapper.emitted("send")).toBeUndefined();
    expect((input.element as HTMLTextAreaElement).value).toBe("保留兼容性");
    await wrapper.setProps({ paused: true });
    await input.trigger("keydown", { key: "Enter" }); await flushPromises();
    expect(wrapper.emitted("send")).toBeUndefined();
    await wrapper.setProps({ running: false, busy: false, paused: false });
    await input.trigger("keydown", { key: "Enter" }); await flushPromises();
    expect(wrapper.emitted("send")?.[0]?.[0]).toMatchObject({ message: "保留兼容性" });
    expect((input.element as HTMLTextAreaElement).value).toBe("");
  });

  it("发送前异步确认期间重复点击只发送一次，并保留后来补写的草稿", async () => {
    let resolve!: (value: boolean) => void;
    const before = vi.fn(() => new Promise<boolean>(done => { resolve = done; }));
    const wrapper = mount(CodingComposer, { props: { beforeSend: before } }); mounted.push(wrapper);
    const input = wrapper.get("textarea"); await input.setValue("第一条");
    await input.trigger("keydown", { key: "Enter" }); await input.trigger("keydown", { key: "Enter" });
    expect(before).toHaveBeenCalledOnce();
    await input.setValue("后来编辑的文字"); resolve(true); await flushPromises();
    expect(wrapper.emitted("send")).toHaveLength(1);
    expect((input.element as HTMLTextAreaElement).value).toBe("后来编辑的文字");
  });

  it("审阅反馈追加到现有草稿，移除预算与子任务参数后正常发送", async () => {
    const wrapper = mount(CodingComposer); mounted.push(wrapper);
    await wrapper.get("textarea").setValue("原有草稿");
    await wrapper.setProps({ restoreRequest: { message: "反馈内容", append: true, seq: 1 } }); await nextTick();
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("原有草稿\n\n反馈内容");
    expect(wrapper.find('input[type="number"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("任务预算与协作");
    await wrapper.get("textarea").trigger("keydown", { key: "Enter" });
    const payload = wrapper.emitted("send")![0][0];
    expect(payload).toMatchObject({ message: "原有草稿\n\n反馈内容" });
    expect(payload).not.toHaveProperty("contextLimits");
    expect(payload).not.toHaveProperty("allowSubagents");
  });

  it("状态读取失败后手动刷新成功会清除旧提示", async () => {
    vi.mocked(fetchRecovery).mockRejectedValueOnce(new Error("状态连接暂时中断"));
    const wrapper = mount(RunControlBar, { props: { runId: "run", sessionId: 3 } }); mounted.push(wrapper);
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("状态连接暂时中断");
    await wrapper.findAll("button").find(b => b.text() === "刷新状态")!.trigger("click"); await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("任务执行中");
    expect(wrapper.vm.canPause).toBe(true);
    expect(controlRun).not.toHaveBeenCalled();
  });

  it("控制请求结果未知时，重新挂载仍沿用原幂等标识", async () => {
    vi.mocked(controlRun).mockRejectedValueOnce(new Error("连接中断"));
    const wrapper = mount(RunControlBar, { props: { runId: "run", sessionId: 3 } });
    await flushPromises();
    expect(await wrapper.vm.pause()).toBe(false);
    expect(wrapper.text()).toContain("连接中断");
    const original = vi.mocked(controlRun).mock.calls[0][2]; wrapper.unmount();
    vi.mocked(controlRun).mockResolvedValueOnce({ request_id: original.request_id, kind: "pause", status: "applied", result_run_id: "run" });
    const restored = mount(RunControlBar, { props: { runId: "run", sessionId: 3 } }); mounted.push(restored); await flushPromises();
    await restored.findAll("button").find(b => b.text() === "重试上次请求")!.trigger("click"); await flushPromises();
    expect(vi.mocked(controlRun).mock.calls[1][2]).toEqual(original);
    expect(enqueueTurn).not.toHaveBeenCalled();
    expect(restored.text()).not.toContain("重试上次请求");
  });

  it("暂停请求未到达执行边界时不重复提交；暂停完成后保留继续入口", async () => {
    let finish!: (value: Awaited<ReturnType<typeof controlRun>>) => void;
    vi.mocked(controlRun).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(RunControlBar, { props: { runId: "run", sessionId: 3 } }); mounted.push(wrapper);
    await flushPromises();
    expect(wrapper.find("section").exists()).toBe(false);
    const pendingPause = wrapper.vm.pause();
    expect(await wrapper.vm.pause()).toBe(false);
    expect(controlRun).toHaveBeenCalledOnce();
    const control = { request_id: vi.mocked(controlRun).mock.calls[0][2].request_id, kind: "pause" as const, status: "received" as const, result_run_id: "run" };
    vi.mocked(fetchRecovery).mockResolvedValueOnce({ ...report, controls: [control] });
    finish(control);
    expect(await pendingPause).toBe(true);
    expect(wrapper.vm.pausePending).toBe(true);
    expect(wrapper.vm.canPause).toBe(false);
    expect(await wrapper.vm.pause()).toBe(false);
    expect(controlRun).toHaveBeenCalledOnce();

    vi.mocked(fetchRecovery).mockResolvedValue({ ...report, status: "paused", can_resume: true });
    await wrapper.setProps({ runId: "paused-run" }); await flushPromises();
    expect(wrapper.vm.paused).toBe(true);
    expect(wrapper.findAll("button").some(button => button.text() === "继续任务")).toBe(true);
    expect(wrapper.findAll("button").some(button => button.text() === "暂停")).toBe(false);
  });

  it("行内反馈绑定差异侧、真实行号和版本，不自动提交任务", async () => {
    const wrapper = mount(DiffFeedback, { props: { content: "@@ -10,1 +10,1 @@\n-before\n+after\n", path: "src/app.ts", version: "abc" } }); mounted.push(wrapper);
    await wrapper.get('[aria-label="反馈修改后第 10 行"]').trigger("click");
    await wrapper.get("textarea").setValue("边界为空时仍须返回数组");
    await wrapper.get("form").trigger("submit");
    const feedback = wrapper.emitted("feedback")![0][0] as string;
    expect(feedback).toContain("src/app.ts"); expect(feedback).toContain("修改后第 10 行"); expect(feedback).toContain("审阅版本：abc");
  });
});
