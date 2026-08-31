import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import ContextUsageRing from "./ContextUsageRing.vue";

const mocks = vi.hoisted(() => ({
  getContextBudget: vi.fn(),
}));

vi.mock("../../api", () => ({
  getContextBudget: mocks.getContextBudget,
}));

describe("ContextUsageRing", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("容量已知但尚无用量时展示容量，不伪造百分比；切换模型重新读取", async () => {
    mocks.getContextBudget.mockResolvedValue({
      used_tokens: 0, max_context_tokens: 32000, reserved_output_tokens: 0,
      cache_hit_percent: null, usage_percent: null, source: "unavailable",
      compaction_state: "idle", last_compacted_at: null,
      error_code: "context_usage_unavailable", error_reason: "等待供应商用量",
    });
    const wrapper = mount(ContextUsageRing, { props: { sessionId: 7, modelProfileId: "first", enabled: true } });
    await flushPromises();
    expect(wrapper.get('[data-testid="context-capacity-pending"]').text()).toContain("3.2万");
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false);
    await wrapper.setProps({ modelProfileId: "second" });
    await flushPromises();
    expect(mocks.getContextBudget).toHaveBeenLastCalledWith(7, "second");
    wrapper.unmount();
  });

  it("悬浮详情只呈现容量进度与平均缓存命中率", async () => {
    mocks.getContextBudget.mockResolvedValue({
      used_tokens: 195_000,
      max_context_tokens: 1_000_000,
      reserved_output_tokens: 1_024,
      cache_hit_percent: 97.9,
      cache_hit_scope: "session",
      usage_percent: 20,
      source: "provider_usage",
      compaction_state: "idle",
      last_compacted_at: null,
      error_code: null,
      error_reason: null,
    });
    const wrapper = mount(ContextUsageRing, {
      props: { sessionId: 7, enabled: true },
    });
    await flushPromises();

    expect(wrapper.get('[data-testid="context-capacity-value"]').text()).toBe(
      "19.5万/100万（19.5%）"
    );
    expect(wrapper.get('[data-testid="context-cache-hit"]').text()).toBe("97.9%");
    const popover = wrapper.get('[data-testid="context-ring-popover"]').text();
    expect(popover).toContain("平均缓存命中率");
    expect(popover).not.toContain("最近请求缓存命中率");
    expect(popover).not.toContain("保留输出预算");
    expect(popover).not.toContain("压缩阈值");
    expect(popover).not.toContain("数据来源");
    expect(popover).not.toContain("最近更新");
    wrapper.unmount();
  });
});
