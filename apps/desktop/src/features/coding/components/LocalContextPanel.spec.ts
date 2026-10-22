import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import LocalContextPanel from "./LocalContextPanel.vue";
import type { ContextState } from "../api/context";
vi.mock("./SessionMemoryPanel.vue", () => ({ default: { template: '<div />' } }));

const api = vi.hoisted(() => ({ context: vi.fn(), budget: vi.fn(), compact: vi.fn(), trust: vi.fn(), confirm: vi.fn() }));
vi.mock("../api/context", () => ({ fetchSessionContext: api.context, fetchSessionBudget: api.budget,
  compactSessionContext: api.compact, setInstructionTrust: api.trust }));
vi.mock("../../../stores/notifications", () => ({ useNotifications: () => ({ confirm: api.confirm }) }));
function state(): ContextState {
  return { project_id: 1, trusted: false, sources: [{ path: "AGENTS.md", scope: ".", sha256: "a".repeat(64), priority: 0, trusted: false, content: "仅中文注释" }],
    active_sources: [], checkpoint: null, pending: null, compaction_error: null,
    loop_budget: { model_requests: 30, max_model_requests: 64, tool_calls: 29, max_tool_calls: 128, active_seconds: 5, approval_wait_seconds: 9, cost_usd: null } };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  api.context.mockResolvedValue(state());
  api.budget.mockResolvedValue({ source: "estimated", estimated_input_tokens: 5000, used_tokens: 5000,
    input_budget_tokens: 28000, reserved_output_tokens: 2048, compaction_state: "idle" });
});
afterEach(() => vi.useRealTimers());

describe("本机上下文面板", () => {
  it("展示压缩阈值、摘要方式与回退状态", async () => {
    api.budget.mockResolvedValue({ estimated_input_tokens: 6000, input_budget_tokens: 7000,
      auto_compact_threshold_tokens: 6300, reserved_output_tokens: 1024, compaction_state: "compacted" });
    api.context.mockResolvedValue({ ...state(), checkpoint: { id: "cp", state: "completed", completed_at: "today",
      through_ordinal: 9, summary_strategy: "model", summary_fallback_reason: null } });
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await flushPromises();
    expect(wrapper.text()).toContain("6,300 tokens");
    expect(wrapper.text()).toContain("工作摘要与事实索引");
    api.context.mockResolvedValue({ ...state(), checkpoint: { id: "cp", state: "completed", completed_at: "today",
      through_ordinal: 9, summary_strategy: "extractive", summary_fallback_reason: "summary_unavailable" } });
    await vi.advanceTimersByTimeAsync(5000);
    expect(wrapper.text()).toContain("本次未采用工作摘要，已保留事实索引和原始历史");
    expect(wrapper.text()).not.toContain("工作摘要与事实索引");
    wrapper.unmount();
  });
  it("区分估算、供应商未知、未信任规则与执行预算", async () => {
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await flushPromises();
    expect(wrapper.text()).toContain("仅展示，未作为指令使用");
    expect(wrapper.text()).toContain("5,000 tokens");
    expect(wrapper.text()).toContain("最近供应商实测未知 tokens");
    expect(wrapper.text()).toContain("模型 30/64");
    expect(wrapper.text()).toContain("费用 未知");
    wrapper.unmount();
    const count = api.context.mock.calls.length;
    await vi.advanceTimersByTimeAsync(15000);
    expect(api.context).toHaveBeenCalledTimes(count);
  });
  it("压缩失败保留后端原因，重复点击互斥", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.compact.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await flushPromises();
    const button = wrapper.findAll("button").find(b => b.text() === "压缩历史")!;
    await button.trigger("click");
    await button.trigger("click");
    expect(api.compact).toHaveBeenCalledTimes(1);
    resolve({ id: "cp", state: "failed", error: "必需上下文无法缩小，原历史保留" });
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("原历史保留");
    wrapper.unmount();
  });
  it("信任变更经过已有确认机制，取消时不写入", async () => {
    api.confirm.mockResolvedValue(false);
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await flushPromises();
    await wrapper.findAll("button").find(b => b.text() === "信任此项目规则")!.trigger("click");
    await flushPromises();
    expect(api.confirm).toHaveBeenCalledOnce();
    expect(api.trust).not.toHaveBeenCalled();
    api.confirm.mockResolvedValue(true);
    await wrapper.findAll("button").find(b => b.text() === "信任此项目规则")!.trigger("click");
    await flushPromises();
    expect(api.trust).toHaveBeenCalledWith(1, true);
    wrapper.unmount();
  });
  it("切换会话后忽略迟到响应", async () => {
    let resolve: (value: ContextState) => void = () => {};
    api.context.mockImplementationOnce(() => new Promise<ContextState>(done => { resolve = done; }));
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await wrapper.setProps({ sessionId: 8 });
    await flushPromises();
    resolve({ ...state(), trusted: true, sources: [] });
    await flushPromises();
    expect(wrapper.text()).toContain("仅展示，未作为指令使用");
    expect(wrapper.text()).toContain("AGENTS.md");
    wrapper.unmount();
  });
  it("面板卸载后迟到的确认不会修改规则信任", async () => {
    let resolve: (value: boolean) => void = () => {};
    api.confirm.mockImplementation(() => new Promise<boolean>(done => { resolve = done; }));
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await flushPromises();
    await wrapper.findAll("button").find(b => b.text() === "信任此项目规则")!.trigger("click");
    wrapper.unmount();
    resolve(true);
    await flushPromises();
    expect(api.trust).not.toHaveBeenCalled();
  });
  it("展示分项明细与压缩前后估算，旧记录显示暂无明细", async () => {
    api.budget.mockResolvedValue({ estimated_input_tokens: 9000, input_budget_tokens: 28000,
      reserved_output_tokens: 2048, compaction_state: "compacted",
      breakdown: { schema: "context-breakdown/1", basis: "utf8_share_estimate",
        measurement_source: "utf8_conservative", estimate_ratio: 1, total_bytes: 6000, estimate_tokens: 9000,
        provider_usage_tokens: 8500,
        items: [{ category: "tool_definitions", label: "工具定义", bytes: 4000, estimated_tokens: 5000,
          measurement: "utf8_share_estimate", messages: 0 },
        { category: "user_messages", label: "用户消息", bytes: 2000, estimated_tokens: 4000,
          measurement: "utf8_share_estimate", messages: 2 }],
        notice: "分项按同一请求的 UTF-8 字节分摊估算；供应商只返回总输入用量时以该实测总值为准。" } });
    api.context.mockResolvedValue({ ...state(), checkpoint: { id: "cp", state: "completed", completed_at: "today",
      through_ordinal: 9, summary_strategy: "model", summary_fallback_reason: null,
      compaction_metrics: { measured: true, estimated_before_tokens: 21000, estimated_after_tokens: 12000,
        archived_items: 32, retained_messages: 9 } } });
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("上下文分项明细");
    expect(text).toContain("工具定义");
    expect(text).toContain("5,000");
    expect(text).toContain("21,000 tokens → 12,000 tokens");
    expect(text).toContain("归档 32 项 · 保留 9 条");
    expect(text).toContain("供应商实测前缀 8,500 tokens");
    // 手动压缩与旧检查点：只报告未记录，不显示成零。
    api.context.mockResolvedValue({ ...state(), checkpoint: { id: "cp", state: "completed", completed_at: "today",
      through_ordinal: 9, summary_strategy: "extractive", summary_fallback_reason: null,
      compaction_metrics: { measured: false, archived_items: 4, retained_messages: 6 } } });
    await vi.advanceTimersByTimeAsync(5000);
    expect(wrapper.text()).toContain("估算未记录");
    expect(wrapper.text()).toContain("归档 4 项 · 保留 6 条");
    // 旧记录没有分项字段：显示暂无明细，而不是零。
    api.budget.mockResolvedValue({ estimated_input_tokens: 6000, input_budget_tokens: 28000,
      reserved_output_tokens: 2048, compaction_state: "idle" });
    await vi.advanceTimersByTimeAsync(5000);
    expect(wrapper.text()).toContain("暂无分项明细");
    wrapper.unmount();
  });
  it("展示六类压缩交接，旧检查点提示待核对", async () => {
    const entry = (text: string, extra: Record<string, unknown> = {}) => ({ category: "finding", kind: "observation",
      text, source_item_ids: ["item-1"], version: null, stale: false, ...extra });
    // 目标区段按后端真实结构使用 requirements，不再使用虚构的 goal.items。
    api.context.mockResolvedValue({ ...state(), checkpoint: { id: "cp", state: "completed", completed_at: "today",
      through_ordinal: 9, summary_strategy: "model", summary_fallback_reason: null },
      handoff: { version: "1.0",
        goal: { status: "known", goal_version: 2, source_item_ids: ["item-1"],
          requirements: [{ ...entry("验收：只读取 src 并报告"), category: "requirement", kind: "user_requirement" }] },
        constraints: { status: "known", items: [entry("用户禁止修改文件")] },
        plan: { status: "known", next_step: "核对 src/app.py 接口", items: [entry("核对 src/app.py 接口")] },
        findings: { status: "known", items: [entry("早期读取失败", { stale: true })] },
        changes: { status: "recheck_required", items: [entry("修改 src/app.py")] },
        unresolved: { status: "known", items: [entry("未解决：文件缺失")] } } });
    const wrapper = mount(LocalContextPanel, { props: { sessionId: 7 } });
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("压缩交接（程序投影）");
    for (const title of ["当前目标与验收条件", "生效限制与规则", "当前计划与下一步", "关键发现与决定", "修改与验证", "未解决问题"]) {
      expect(text).toContain(title);
    }
    // 目标正文来自 requirements，必须真正渲染，不能只显示“有来源”。
    expect(text).toContain("验收：只读取 src 并报告");
    expect(text).toContain("下一步：核对 src/app.py 接口");
    expect(text).toContain("需复核");
    // 旧检查点没有交接明细：明确提示待核对，不伪造状态。
    api.context.mockResolvedValue({ ...state(), checkpoint: { id: "cp", state: "completed", completed_at: "today",
      through_ordinal: 9, summary_strategy: "extractive", summary_fallback_reason: null } });
    await vi.advanceTimersByTimeAsync(5000);
    expect(wrapper.text()).toContain("旧检查点未保存该明细");
    wrapper.unmount();
  });
});
