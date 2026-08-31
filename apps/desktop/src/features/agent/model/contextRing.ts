/**
 * v0.9.0 H1-A · 上下文用量圆环契约（计划 §5.4 / H0 §7）
 *
 * 红线（零容忍）：圆环数值只来自后端 typed budget（provider usage /
 * 受验证 tokenizer / Runtime 统一计数），不按字符数/消息数伪造；
 * 不可用时呈现「不可用 + 原因」；百分比域 0..100（后端封顶）；
 * 不显示上一会话旧值（按 sessionId 拉取，切换即重新读取）。
 */
import type { ContextBudgetResponse } from "../../../api";

export type ContextRingState =
  | "loading"
  | "unavailable"
  | "ok"
  | "near"
  | "full"
  | "compacting"
  | "failed";

export interface ContextRingFacts {
  state: ContextRingState;
  /** 0..100；不可用/读取中为 null（不渲染虚假进度） */
  percent: number | null;
  usedTokens: number;
  limitTokens: number;
  reservedTokens: number;
  /** 缓存命中率与统计范围由后端一起声明。 */
  cacheHitPercent: number | null;
  cacheHitScope?: "latest_request" | "session";
  /** 不可用/失败原因（公开文案，不含敏感内容） */
  reason: string | null;
  compactionState: ContextBudgetResponse["compaction_state"];
  lastCompactedAt: string | null;
  /** v0.9.0 H1-C（§5.7）：数据来源（冻结词汇）与最近成功读取时间 */
  source: ContextBudgetResponse["source"] | null;
  updatedAt: number | null;
}

export const CONTEXT_RING_NEAR_THRESHOLD = 80;

export function contextRingLoading(): ContextRingFacts {
  return {
    state: "loading",
    percent: null,
    usedTokens: 0,
    limitTokens: 0,
    reservedTokens: 0,
    cacheHitPercent: null,
    reason: null,
    compactionState: "idle",
    lastCompactedAt: null,
    source: null,
    updatedAt: null,
  };
}

export function contextRingUnavailable(reason: string | null): ContextRingFacts {
  return {
    state: "unavailable",
    percent: null,
    usedTokens: 0,
    limitTokens: 0,
    reservedTokens: 0,
    cacheHitPercent: null,
    reason,
    compactionState: "idle",
    lastCompactedAt: null,
    source: null,
    updatedAt: null,
  };
}

/** 数据来源词汇 → 面向用户的说明（§5.7：详情显示数据来源）。 */
export function contextRingSourceLabel(
  source: ContextRingFacts["source"]
): string {
  switch (source) {
    case "provider_usage":
      return "Provider usage 上报";
    case "tokenizer":
      return "经校验 tokenizer";
    case "runtime_count":
      return "Runtime 统一计数";
    case "unavailable":
      return "无可用计量来源";
    default:
      return "未知";
  }
}

/** 从后端 typed budget 派生圆环事实（纯函数，可单测）。 */
export function deriveContextRing(
  body: ContextBudgetResponse | null
): ContextRingFacts {
  if (!body) return contextRingUnavailable("用量读取失败");
  const base = {
    usedTokens: body.used_tokens,
    limitTokens: body.max_context_tokens,
    reservedTokens: body.reserved_output_tokens,
    cacheHitScope: body.cache_hit_scope ?? "session",
    cacheHitPercent:
      body.cache_hit_percent === null
        ? null
        : Math.min(100, Math.max(0, body.cache_hit_percent)),
    compactionState: body.compaction_state,
    lastCompactedAt: body.last_compacted_at,
    source: body.source,
    updatedAt: Date.now(),
  };
  if (body.source === "unavailable" || body.usage_percent === null) {
    return {
      ...base,
      state: "unavailable",
      percent: null,
      reason: body.error_reason ?? "该模型无法准确计量上下文用量",
    };
  }
  const percent = Math.min(100, Math.max(0, Math.round(body.usage_percent)));
  let state: ContextRingState;
  if (body.compaction_state === "failed") state = "failed";
  else if (body.error_code === "budget_exceeded" || percent >= 100) state = "full";
  else if (body.compaction_state === "compacting") state = "compacting";
  else if (percent >= CONTEXT_RING_NEAR_THRESHOLD) state = "near";
  else state = "ok";
  return {
    ...base,
    state,
    percent,
    reason:
      state === "full"
        ? body.error_reason ?? "上下文用量已达窗口上限"
        : state === "failed"
          ? body.error_reason ?? "自动压缩失败，可新开会话恢复"
          : body.error_reason,
  };
}

/** 面向上下文容量卡片的中文紧凑 token 数字。 */
export function formatCompactTokens(tokens: number): string {
  const safe = Math.max(0, Math.round(tokens));
  if (safe < 10_000) return safe.toLocaleString("zh-CN");
  const value = safe / 10_000;
  const compact = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `${compact}万`;
}

/** 圆环文本替代（aria/读屏；固定文案，不含敏感内容）。 */
export function contextRingAriaLabel(facts: ContextRingFacts): string {
  switch (facts.state) {
    case "loading":
      return "上下文用量读取中";
    case "unavailable":
      return `上下文用量不可用：${facts.reason ?? "无法准确计量"}`;
    case "compacting":
      return `上下文用量 ${facts.percent}%，正在自动压缩`;
    case "failed":
      return `上下文压缩失败：${facts.reason ?? "请新开会话恢复"}`;
    case "full":
      return `上下文用量已达上限（${facts.percent}%）`;
    case "near":
      return `上下文用量 ${facts.percent}%，接近压缩阈值`;
    default:
      return `上下文用量 ${facts.percent}%`;
  }
}
