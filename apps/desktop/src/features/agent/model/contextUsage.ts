/**
 * v0.8.0 W6-R3 · 上下文用量与自动压缩事实（typed contract）
 *
 * 零容忍红线：数值必须来自公开 usage/capability（run 快照 token 数与
 * 公开配置上限），不得由前端按字符数、消息数或常量伪造。本模块只接受
 * 数值型公开事实；缺失即「不可用」，绝不估算。
 */

export type CompressionState =
  /** 后端尚未公开压缩状态（能力默认关闭/无公开 API）——如实呈现，不伪造 */
  | { kind: "unsupported" }
  | { kind: "idle" }
  | { kind: "compressing" }
  | { kind: "compressed"; detail: string }
  | { kind: "failed"; retryable: boolean };

export type ContextUsageThreshold = "normal" | "near" | "full";

export interface ContextUsageFacts {
  state: "loading" | "unavailable" | "ready";
  /** 本轮窗口已用 token（公开 usage：最近 run 快照 input_tokens） */
  usedTokens: number | null;
  /** 窗口上限 token（公开配置：模型上下文长度/设置） */
  limitTokens: number | null;
  /** 仅由 used/limit 两个公开数值推导；0–100，无负数、无伪估算 */
  percentage: number | null;
  threshold: ContextUsageThreshold;
  compression: CompressionState;
}

export const CONTEXT_USAGE_NEAR_THRESHOLD = 80;

export function contextUsageLoading(): ContextUsageFacts {
  return {
    state: "loading",
    usedTokens: null,
    limitTokens: null,
    percentage: null,
    threshold: "normal",
    compression: { kind: "unsupported" },
  };
}

export function contextUsageUnavailable(): ContextUsageFacts {
  return {
    state: "unavailable",
    usedTokens: null,
    limitTokens: null,
    percentage: null,
    threshold: "normal",
    compression: { kind: "unsupported" },
  };
}

function isValidTokenCount(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

/**
 * 由公开 usage 数值推导用量事实。
 * - used/limit 任一缺失或非有限负数 → 不可用（不呈现百分比）；
 * - 百分比钳制在 0–100：超过上限呈现 100% + full 阈值态（错误显示防护）；
 * - ≥80% 为接近阈值。
 */
export function deriveContextUsage(
  usedTokens: number | null | undefined,
  limitTokens: number | null | undefined,
  compression: CompressionState = { kind: "unsupported" }
): ContextUsageFacts {
  if (!isValidTokenCount(usedTokens) || !isValidTokenCount(limitTokens) || limitTokens === 0) {
    return contextUsageUnavailable();
  }
  const raw = (usedTokens / limitTokens) * 100;
  const percentage = Math.min(100, Math.max(0, Math.round(raw)));
  const threshold: ContextUsageThreshold =
    percentage >= 100 ? "full" : percentage >= CONTEXT_USAGE_NEAR_THRESHOLD ? "near" : "normal";
  return {
    state: "ready",
    usedTokens,
    limitTokens,
    percentage,
    threshold,
    compression,
  };
}

/** 用量呈现文案（固定文案，不含敏感内容）。 */
export function contextUsageLabel(facts: ContextUsageFacts): string {
  if (facts.state === "loading") return "用量读取中…";
  if (facts.state === "unavailable" || facts.percentage === null) {
    return "上下文用量不可用";
  }
  const used = (facts.usedTokens ?? 0).toLocaleString();
  const limit = (facts.limitTokens ?? 0).toLocaleString();
  return `${used} / ${limit} · ${facts.percentage}%`;
}
