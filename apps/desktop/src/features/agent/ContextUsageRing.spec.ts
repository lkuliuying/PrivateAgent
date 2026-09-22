import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import ContextUsageRing from "./ContextUsageRing.vue";
import type { ContextBudgetResponse } from "../../api";

const mocks = vi.hoisted(() => ({ getContextBudget: vi.fn() }));
vi.mock("../../api", () => ({ getContextBudget: mocks.getContextBudget }));
let wrapper: VueWrapper;
const usage: ContextBudgetResponse = {
  used_tokens: 142_000, max_context_tokens: 258_000, reserved_output_tokens: 1_024,
  cache_hit_percent: 97.9, usage_percent: 55, source: "provider_usage",
  compaction_state: "idle", last_compacted_at: null, error_code: null, error_reason: null,
};
function create(props = {}) {
  wrapper = mount(ContextUsageRing, { props: { sessionId: 7, enabled: true, ...props }, global: { stubs: { Teleport: true } }, attachTo: document.body });
}
afterEach(() => { wrapper?.unmount(); vi.resetAllMocks(); });

describe("ContextUsageRing", () => {
  it("容量已知但尚无用量时不伪造百分比，切换模型重新读取", async () => {
    mocks.getContextBudget.mockResolvedValue({ ...usage, used_tokens: 0, max_context_tokens: 32_000, usage_percent: null, source: "unavailable", error_reason: "等待供应商用量" });
    create({ modelProfileId: "first" });
    await flushPromises();
    await wrapper.get("button").trigger("mouseenter");
    expect(wrapper.get('[data-testid="context-capacity-pending"]').text()).toBe("总容量 32k 标记");
    expect(wrapper.find('[data-testid="context-usage-percent"]').exists()).toBe(false);
    await wrapper.setProps({ modelProfileId: "second" });
    await flushPromises();
    expect(mocks.getContextBudget).toHaveBeenLastCalledWith(7, "second");
  });

  it("悬浮或键盘焦点显示已用比例、标记数和总容量，Escape 关闭", async () => {
    mocks.getContextBudget.mockResolvedValue(usage);
    create();
    await flushPromises();
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
    await wrapper.get("button").trigger("focus");
    expect(wrapper.get('[data-testid="context-usage-percent"]').text()).toBe("55% 已用");
    expect(wrapper.get('[data-testid="context-capacity-value"]').text()).toBe("已用 142k 标记，共 258k");
    expect(wrapper.get('[role="tooltip"]').text()).not.toContain("缓存命中率");
    expect(wrapper.get("button").attributes("aria-describedby")).toBe(wrapper.get('[role="tooltip"]').attributes("id"));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
  });

  it("新会话只显示已知总容量，不请求用量；估算明确标注", async () => {
    create({ sessionId: null, contextTokens: 258_000 });
    await wrapper.get("button").trigger("mouseenter");
    expect(wrapper.text()).toContain("开始对话后显示用量");
    expect(wrapper.text()).toContain("总容量 258k 标记");
    expect(mocks.getContextBudget).not.toHaveBeenCalled();
    mocks.getContextBudget.mockResolvedValue({ ...usage, source: "estimated" });
    await wrapper.setProps({ sessionId: 7 });
    await flushPromises();
    expect(wrapper.get('[data-testid="context-usage-percent"]').text()).toBe("估算 55% 已用");
  });

  it("旧会话迟到的回执不会覆盖新会话，卸载后不再因窗口焦点请求", async () => {
    let resolveFirst!: (value: ContextBudgetResponse) => void;
    mocks.getContextBudget.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; })).mockResolvedValue({ ...usage, used_tokens: 1000, max_context_tokens: 100_000, usage_percent: 1 });
    create();
    await wrapper.setProps({ sessionId: 8 });
    await flushPromises();
    resolveFirst(usage);
    await flushPromises();
    await wrapper.get("button").trigger("mouseenter");
    expect(wrapper.get('[data-testid="context-capacity-value"]').text()).toBe("已用 1k 标记，共 100k");
    wrapper.unmount();
    window.dispatchEvent(new Event("focus"));
    expect(mocks.getContextBudget).toHaveBeenCalledTimes(2);
  });
});
