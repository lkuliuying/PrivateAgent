import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import RunObserverPanel from "./RunObserverPanel.vue";
import { fetchRunObserver, type RunObserverReport } from "../api/observer";

vi.mock("../api/observer", async importOriginal => ({ ...await importOriginal<typeof import("../api/observer")>(), fetchRunObserver: vi.fn() }));
const copy = vi.fn();
let wrapper: VueWrapper;

function report(runId = "run-1"): RunObserverReport {
  return {
    schema_version: "1.0", run_id: runId, status: "completed", goal_outcome: "unmet", last_event_sequence: 120,
    config_version: 3, counts: { events: 120, steps: 2, executions: 1 }, truncated: true,
    progress: { repeated_observations: 3, failure_repeats: 2, verification_retries: 1 }, error: { category: "verification", code: "completion_unmet" },
    steps: [{ id: "step-1", ordinal: 1, kind: "tool", status: "completed", name: "read_project_file", plan_item_key: null }],
    checks: [{ id: "tests", kind: "test", status: "failed", reason_code: "missing_evidence", evidence_ids: ["evidence-1"] }],
    events: [{ sequence: 120, type: "output.validation_failed", step_id: "step-1", execution_id: "execution-1", category: "verification" }],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchRunObserver).mockResolvedValue(report());
  copy.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: copy } });
});
afterEach(() => wrapper?.unmount());

describe("运行观察诊断", () => {
  it("显示真实核验结论、关联标识和截断边界，手动刷新才重新读取", async () => {
    wrapper = mount(RunObserverPanel, { props: { runId: "run-1" } });
    await flushPromises();
    expect(wrapper.text()).toContain("未满足");
    expect(wrapper.text()).toContain("错误分类：完成核验");
    expect(wrapper.text()).toContain("测试结果 · 未通过");
    expect(wrapper.text()).toContain("evidence-1");
    expect(wrapper.text()).toContain("execution-1");
    expect(wrapper.text()).toContain("并非完整历史");
    expect(wrapper.text()).toContain("检查结论取自上次核验");
    expect(fetchRunObserver).toHaveBeenCalledTimes(1);
    await wrapper.get('[data-testid="observer-refresh"]').trigger("click");
    await flushPromises();
    expect(fetchRunObserver).toHaveBeenCalledTimes(2);
  });

  it("复制白名单 JSON，不带后端新增正文和事件 payload", async () => {
    const value = { ...report(), output: "sensitive body" };
    Object.assign(value.events[0], { payload: { stdout: "sensitive log" } });
    vi.mocked(fetchRunObserver).mockResolvedValue(value);
    wrapper = mount(RunObserverPanel, { props: { runId: "run-1" } });
    await flushPromises();
    await wrapper.get('[data-testid="observer-copy"]').trigger("click");
    await flushPromises();
    expect(copy).toHaveBeenCalledOnce();
    expect(copy.mock.calls[0][0]).not.toContain("sensitive");
    expect(JSON.parse(copy.mock.calls[0][0]).run_id).toBe("run-1");
    expect(wrapper.text()).toContain("已复制诊断摘要");
  });

  it("切换运行取消旧请求并拒绝迟到回执，卸载取消当前读取", async () => {
    let resolveOld!: (value: RunObserverReport) => void;
    vi.mocked(fetchRunObserver).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    wrapper = mount(RunObserverPanel, { props: { runId: "run-1" } });
    const oldSignal = vi.mocked(fetchRunObserver).mock.calls[0][1];
    vi.mocked(fetchRunObserver).mockResolvedValueOnce({ ...report("run-2"), config_version: 8, checks: [] });
    await wrapper.setProps({ runId: "run-2" });
    await flushPromises();
    expect(oldSignal?.aborted).toBe(true);
    resolveOld(report());
    await flushPromises();
    expect(wrapper.text()).toContain("v8");
    expect(wrapper.find('[data-testid="observer-check"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("v3");
    const currentSignal = vi.mocked(fetchRunObserver).mock.calls[1][1];
    wrapper.unmount();
    expect(currentSignal?.aborted).toBe(true);
  });

  it("首次失败可重试，空检查和无错误不被当成验收通过", async () => {
    vi.mocked(fetchRunObserver).mockRejectedValueOnce(new Error("private backend body"));
    wrapper = mount(RunObserverPanel, { props: { runId: "run-1" } });
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("读取失败");
    expect(wrapper.text()).not.toContain("private backend body");
    expect(wrapper.get('[data-testid="observer-copy"]').attributes("disabled")).toBeDefined();
    vi.mocked(fetchRunObserver).mockResolvedValueOnce({ ...report(), error: null, checks: [], goal_outcome: null, config_version: null });
    await wrapper.get('[data-testid="observer-refresh"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("尚无结论");
    expect(wrapper.text()).toContain("不代表任务已经通过验收");
    expect(wrapper.text()).toContain("没有应用项目验收检查");
  });

  it("用户限制和过时证据分别显示跳过与待核验，未知步骤保留空态", async () => {
    vi.mocked(fetchRunObserver).mockResolvedValueOnce({ ...report(),
      steps: [{ ...report().steps[0], id: null, plan_item_key: "plan-reference" }],
      checks: [
        { id: "limited", kind: "test", status: "skipped", reason_code: "user_constraint", evidence_ids: [] },
        { id: "stale", kind: "artifact", status: "pending", reason_code: "evidence_stale", evidence_ids: [] },
      ],
    });
    wrapper = mount(RunObserverPanel, { props: { runId: "run-1" } });
    await flushPromises();
    expect(wrapper.text()).toContain("测试结果 · 已跳过");
    expect(wrapper.text()).toContain("遵循用户限制");
    expect(wrapper.text()).toContain("产物存在 · 待核验");
    expect(wrapper.text()).toContain("等待重新核验");
    expect(wrapper.text()).toContain("未关联步骤");
    expect(wrapper.text()).toContain("计划引用：plan-reference");
  });

  it("剪贴板失败显示可恢复错误", async () => {
    copy.mockRejectedValueOnce(new Error("denied"));
    wrapper = mount(RunObserverPanel, { props: { runId: "run-1" } });
    await flushPromises();
    await wrapper.get('[data-testid="observer-copy"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("剪贴板权限");
    expect(wrapper.text()).not.toContain("已复制诊断摘要");
    copy.mockResolvedValueOnce(undefined);
    await wrapper.get('[data-testid="observer-copy"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("已复制诊断摘要");
  });
});
