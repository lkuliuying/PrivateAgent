import { describe, expect, it } from "vitest";
import {
  contextUsageLabel,
  contextUsageLoading,
  contextUsageUnavailable,
  deriveContextUsage,
} from "./contextUsage";

describe("deriveContextUsage（W6-R3 上下文用量：只用公开数值，不估算）", () => {
  it("公开 used/limit → 真实百分比与阈值分级", () => {
    expect(deriveContextUsage(1600, 8192).percentage).toBe(20);
    expect(deriveContextUsage(1600, 8192).threshold).toBe("normal");
    expect(deriveContextUsage(7000, 8192).threshold).toBe("near");
    expect(deriveContextUsage(8192, 8192).percentage).toBe(100);
    expect(deriveContextUsage(8192, 8192).threshold).toBe("full");
  });

  it("边界：0% 与超限时钳制为 100%（无负数、无超过 100% 的错误显示）", () => {
    expect(deriveContextUsage(0, 8192).percentage).toBe(0);
    expect(deriveContextUsage(99999, 8192).percentage).toBe(100);
    expect(deriveContextUsage(99999, 8192).threshold).toBe("full");
    expect(deriveContextUsage(-5, 8192).state).toBe("unavailable");
  });

  it("缺少任一公开数值 → 不可用（绝不按字符数/消息数伪造）", () => {
    expect(deriveContextUsage(null, 8192).state).toBe("unavailable");
    expect(deriveContextUsage(1000, null).state).toBe("unavailable");
    expect(deriveContextUsage(Number.NaN, 8192).state).toBe("unavailable");
    expect(deriveContextUsage(1000, 0).state).toBe("unavailable");
    expect(contextUsageUnavailable().percentage).toBeNull();
  });

  it("loading 态不呈现数值；文案固定且不含敏感内容", () => {
    expect(contextUsageLoading().state).toBe("loading");
    expect(contextUsageLabel(contextUsageLoading())).toBe("用量读取中…");
    expect(contextUsageLabel(contextUsageUnavailable())).toBe("上下文用量不可用");
    expect(contextUsageLabel(deriveContextUsage(1600, 8192))).toContain("1,600");
    expect(contextUsageLabel(deriveContextUsage(1600, 8192))).toContain("20%");
  });

  it("压缩状态缺省为未就绪（后端未公开压缩状态时不伪造事件）", () => {
    expect(deriveContextUsage(1600, 8192).compression.kind).toBe("unsupported");
  });
});
