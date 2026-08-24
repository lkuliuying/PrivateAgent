import { describe, expect, it } from "vitest";
import type { ContextBudgetResponse } from "../../../api";
import {
  CONTEXT_RING_NEAR_THRESHOLD,
  contextRingAriaLabel,
  contextRingLoading,
  contextRingSourceLabel,
  contextRingUnavailable,
  deriveContextRing,
} from "./contextRing";

function budget(overrides: Partial<ContextBudgetResponse> = {}): ContextBudgetResponse {
  return {
    used_tokens: 100,
    max_context_tokens: 1000,
    reserved_output_tokens: 256,
    usage_percent: 10,
    source: "provider_usage",
    compaction_state: "idle",
    last_compacted_at: null,
    error_code: null,
    error_reason: null,
    ...overrides,
  };
}

describe("contextRing（v0.9.0 H0 §7：真实计量，不伪造）", () => {
  it("正常用量派生 ok 态与百分比", () => {
    const facts = deriveContextRing(budget());
    expect(facts.state).toBe("ok");
    expect(facts.percent).toBe(10);
    expect(facts.usedTokens).toBe(100);
    expect(facts.limitTokens).toBe(1000);
    expect(facts.reservedTokens).toBe(256);
  });

  it("source=unavailable → 不可用 + 原因，无百分比", () => {
    const facts = deriveContextRing(
      budget({
        source: "unavailable",
        usage_percent: null,
        error_reason: "模型未报告 token 用量",
      })
    );
    expect(facts.state).toBe("unavailable");
    expect(facts.percent).toBeNull();
    expect(facts.reason).toContain("未报告");
  });

  it("≥80% 为 near 态；100%/超限为 full 态（封顶，无 >100）", () => {
    expect(deriveContextRing(budget({ usage_percent: 85 })).state).toBe("near");
    const full = deriveContextRing(
      budget({
        usage_percent: 100,
        error_code: "budget_exceeded",
        error_reason: "已达窗口上限",
      })
    );
    expect(full.state).toBe("full");
    expect(full.percent).toBe(100);
    // 后端超限值不得呈现 >100
    const capped = deriveContextRing(budget({ usage_percent: 140 }));
    expect(capped.percent).toBe(100);
  });

  it("压缩状态如实呈现：压缩中/失败优先于常规阈值", () => {
    expect(
      deriveContextRing(budget({ compaction_state: "compacting" })).state
    ).toBe("compacting");
    const failed = deriveContextRing(
      budget({ compaction_state: "failed", error_reason: "摘要生成失败" })
    );
    expect(failed.state).toBe("failed");
    expect(failed.reason).toContain("摘要生成失败");
  });

  it("null 响应 → 不可用（读取失败），不渲染旧值", () => {
    expect(deriveContextRing(null).state).toBe("unavailable");
  });

  it("加载/不可用构造器与 aria 文案（文本替代）", () => {
    expect(contextRingLoading().state).toBe("loading");
    expect(contextRingUnavailable("无会话").reason).toBe("无会话");
    expect(contextRingAriaLabel(contextRingLoading())).toContain("读取中");
    expect(contextRingAriaLabel(contextRingUnavailable("x"))).toContain("不可用");
    const ok = deriveContextRing(budget());
    expect(contextRingAriaLabel(ok)).toContain("10%");
    const near = deriveContextRing(
      budget({ usage_percent: CONTEXT_RING_NEAR_THRESHOLD })
    );
    expect(contextRingAriaLabel(near)).toContain("接近压缩阈值");
  });

  // v0.9.0 H1-C（§5.7）：详情显示数据来源与最近更新时间（可对账）
  it("派生事实携带数据来源与最近更新时间；词汇表固定", () => {
    const before = Date.now();
    const facts = deriveContextRing(budget({ source: "provider_usage" }));
    expect(facts.source).toBe("provider_usage");
    expect(facts.updatedAt).not.toBeNull();
    expect(facts.updatedAt!).toBeGreaterThanOrEqual(before);
    expect(contextRingSourceLabel("provider_usage")).toContain("Provider usage");
    expect(contextRingSourceLabel("tokenizer")).toContain("tokenizer");
    expect(contextRingSourceLabel("runtime_count")).toContain("Runtime");
    expect(contextRingSourceLabel("unavailable")).toContain("无可用");
    expect(contextRingSourceLabel(null)).toBe("未知");
    // 加载/不可用态不携带来源与时间（不闪现上一会话数据）
    expect(contextRingLoading().source).toBeNull();
    expect(contextRingUnavailable("x").updatedAt).toBeNull();
  });
});
