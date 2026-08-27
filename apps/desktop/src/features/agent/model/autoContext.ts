/**
 * v0.8.0 W6-R3 · 自动知识检索 / 短期摘要 / 长期记忆候选能力契约
 *
 * 原则：按钮移除不等于能力删除；自动化状态只消费公开能力/事件，
 * 能力未就绪时如实呈现「未就绪/不可用」，不制造成功记录或伪记忆。
 *
 * 当前后端公开事实（审计于 2026-08-22）：
 * - 知识检索：agent_runtime + rag_chat_runtime_enabled 时，RAG 由 Runtime
 *   随每轮对话自动执行（助手消息 sources 为公开检索证据）；无需手动按钮。
 * - 短期摘要/上下文压缩：后端存在可追溯压缩组件（conversation_summarizer，
 *   默认关闭、跨进程去重锁、隐私/远程 Provider 边界、会话隔离），但尚无
 *   公开状态端点/能力位 → UI 呈现「未就绪」，不伪造压缩事件。
 * - 长期记忆候选：现有候选流为手动触发（/memories/candidates）；自动
 *   生成未公开 → UI 呈现「未就绪」，候选确认流保持不变。
 */

export type AutoKnowledgeState = "auto" | "disabled" | "unavailable";
export type AutoSummaryState = "ready" | "not-ready";
export type AutoMemoryState = "ready" | "not-ready";

export interface AutoContextCapabilities {
  /** 自动知识检索（按项目/session 随轮执行） */
  knowledge: AutoKnowledgeState;
  /** 短期摘要（随上下文压缩自动维护） */
  shortTermSummary: AutoSummaryState;
  /** 长期记忆候选（自动生成 + 既有隐私/确认策略） */
  longTermMemory: AutoMemoryState;
}

/**
 * 从公开 /capabilities 推导自动化能力（不猜测后端内部状态）。
 * `capabilities` 缺省字段一律按「未提供」处理。
 */
export function deriveAutoContextCapabilities(
  capabilities: Record<string, unknown> | null,
  settings: { kbEnabledByDefault?: boolean | null } | null
): AutoContextCapabilities {
  const ragRuntime = capabilities?.rag_chat_runtime_enabled === true;
  const agentRuntime = capabilities?.chat_execution_mode === "agent_runtime";
  const knowledge: AutoKnowledgeState =
    ragRuntime && agentRuntime
      ? "auto"
      : settings?.kbEnabledByDefault === true
        ? "auto"
        : agentRuntime
          ? "disabled"
          : "unavailable";
  return {
    knowledge,
    // 压缩组件默认关闭且无公开状态端点：如实「未就绪」（见文件头审计）
    shortTermSummary: "not-ready",
    // 候选自动生成未公开：如实「未就绪」；手动候选确认流不变
    longTermMemory: "not-ready",
  };
}

/** 自动化状态呈现文案（固定文案，不含敏感内容）。 */
export function autoCapabilityLabel(state: AutoKnowledgeState | AutoSummaryState | AutoMemoryState): string {
  switch (state) {
    case "auto":
      return "自动执行";
    case "disabled":
      return "未启用";
    case "not-ready":
      return "未就绪";
    default:
      return "不可用";
  }
}
