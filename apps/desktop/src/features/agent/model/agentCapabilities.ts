/**
 * v0.8.0 W6-R2 · Agent 输入器的模型/推理/权限呈现契约（纯数据）
 *
 * 计划 §6.7：选择必须绑定真实公开契约，不得用前端标签伪造权限。
 * - 当前模型与推理强度：对话路径（/chat/stream，ChatRequest 冻结字段
 *   session_id/message/knowledge_base/tool_result）不接受模型或推理强度
 *   入参 → 选择器禁用并说明，不静默改用默认值（零容忍）。
 * - 三档权限：
 *   · 总是询问 → 对话运行时现行事实语义（写入/命令前进入审批流），唯一可选；
 *   · 替我批准 → 需要工作区 + 安全命令档案（/agent-runs permission_mode=
 *     workspace 契约），对话路径未开放 → 禁用说明；
 *   · 完全访问 → 仅当 /capabilities 明确返回独立支持字段时可选；当前
 *     RuntimeCapabilities 无该字段 → 「当前不可用」（不得把 workspace
 *     伪装成完全访问，也不发送后端拒绝的模式）。
 */

export interface AgentCapabilityFacts {
  /** RuntimeCapabilities 原样公开字段（未来若新增独立完全访问支持位，
   *  以 true 显式声明后才允许选择；缺省一律视为不支持） */
  fullAccessSupported: boolean;
  /** 对话路径是否支持模型/推理强度入参（当前冻结契约：不支持） */
  chatModelSelectionSupported: boolean;
  /** 对话路径是否开放工作区自动批准（当前契约：不开放） */
  chatWorkspaceApprovalSupported: boolean;
}

/** 当前后端公开契约下的能力事实（不在前端扩大授权）。 */
export function currentAgentCapabilityFacts(
  capabilities: Record<string, unknown> | null
): AgentCapabilityFacts {
  return {
    fullAccessSupported: capabilities?.full_access_enabled === true,
    chatModelSelectionSupported: false,
    chatWorkspaceApprovalSupported: false,
  };
}

export interface AgentPermissionOption {
  id: "confirm" | "workspace" | "full_access";
  label: string;
  hint: string;
  available: boolean;
}

export function agentPermissionOptions(
  facts: AgentCapabilityFacts
): AgentPermissionOption[] {
  return [
    {
      id: "confirm",
      label: "总是询问",
      hint: "执行写入或命令前进入明确审批流（当前对话路径的真实语义）",
      available: true,
    },
    {
      id: "workspace",
      label: "替我批准",
      hint: facts.chatWorkspaceApprovalSupported
        ? "已授权工作区内匹配安全命令档案的操作自动执行"
        : "需要工作区与安全命令档案；当前对话路径未开放",
      available: facts.chatWorkspaceApprovalSupported,
    },
    {
      id: "full_access",
      label: "完全访问",
      hint: facts.fullAccessSupported
        ? "仍受路径、凭据、远程数据与审计边界约束"
        : "当前不可用：能力开关未提供独立支持",
      available: facts.fullAccessSupported,
    },
  ];
}

export const MODEL_SELECTION_DISABLED_HINT =
  "当前对话路径暂不支持切换模型，使用系统配置的模型；可在设置中修改";

export const REASONING_DISABLED_HINT =
  "当前对话路径暂不支持选择推理强度，使用系统默认";
