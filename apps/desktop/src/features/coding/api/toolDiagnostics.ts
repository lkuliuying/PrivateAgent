/**
 * CT-9 · 工具快照诊断 API（GET /agent-runs/tool-diagnostics）。
 *
 * 端点由 PA_AGENT_V2_TOOL_SNAPSHOT_ENABLED 门控（默认关闭 → 404）；
 * 视图脱敏：不含 schema 全文/描述正文/参数/secret。
 */

export interface ToolDiagnosticEntry {
  namespace: string;
  canonical_name: string;
  version: string;
  /** direct | deferred | hidden:<reason> */
  exposure: string;
  risk_level: string;
  approval_mode: string;
  executor_kind: string;
  side_effect_class: string;
  health_check_id: string | null;
}

export interface ToolDiagnosticsSnapshot {
  generated_at: string;
  tool_plan_id: string;
  intent_tags: string[];
  direct_total: number;
  deferred_total: number;
  hidden_total: number;
  catalog_hash: string;
  visible_hash: string;
  model_profile_hash: string;
  policy_hash: string;
  tools: ToolDiagnosticEntry[];
}

/** 解析 exposure 字符串为状态与原因（hidden:<reason> 口径）。 */
export function parseExposure(
  exposure: string
): { state: "direct" | "deferred" | "hidden"; reason: string | null } {
  if (exposure.startsWith("hidden:")) {
    return { state: "hidden", reason: exposure.slice("hidden:".length) };
  }
  if (exposure === "direct" || exposure === "deferred") {
    return { state: exposure, reason: null };
  }
  return { state: "hidden", reason: exposure };
}

const HIDDEN_REASON_LABELS: Record<string, string> = {
  maturity_disabled: "能力已停用",
  model_unsupported: "当前模型不支持",
  not_applicable: "不适用当前工作区",
  policy_denied: "权限策略未授予",
  feature_disabled: "功能开关未启用",
  health_failed: "健康检查失败",
  not_relevant: "与本轮意图无关",
  context_budget: "超出上下文预算",
};

export function hiddenReasonLabel(reason: string | null): string {
  if (!reason) return "";
  return HIDDEN_REASON_LABELS[reason] ?? reason;
}

export async function fetchToolDiagnostics(
  intentTags?: string[]
): Promise<ToolDiagnosticsSnapshot> {
  const { codingFetchJson } = await import("./codingHttp");
  const query = intentTags?.length
    ? `?intent_tags=${encodeURIComponent(intentTags.join(","))}`
    : "";
  return codingFetchJson<ToolDiagnosticsSnapshot>(
    `/agent-runs/tool-diagnostics${query}`
  );
}
