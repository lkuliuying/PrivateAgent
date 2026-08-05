import type {
  WorkspacePlanStep,
  WorkspaceStepStatus,
  AgentTaskState,
  Message,
  ToolCall,
  ToolCallStatus,
} from "../types";

export type AgentWorkspaceMessage = Message & {
  sources?: import("../types").Source[];
  memories?: import("../types").MemorySource[];
  tool_call?: ToolCall;
  agent_approval?: import("../types").AgentRunApproval;
  clientKey?: string;
  runId?: string;
};

export const STEP_STATUS_META: Record<
  WorkspaceStepStatus,
  { label: string; tone: string }
> = {
  pending: { label: "待处理", tone: "neutral" },
  running: { label: "进行中", tone: "info" },
  completed: { label: "已完成", tone: "success" },
  blocked: { label: "等待确认", tone: "warning" },
  failed: { label: "失败", tone: "danger" },
};

export const TASK_STATE_META: Record<
  AgentTaskState,
  { label: string; tone: string }
> = {
  idle: { label: "就绪", tone: "neutral" },
  running: { label: "正在执行", tone: "info" },
  waiting: { label: "等待确认", tone: "warning" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "执行失败", tone: "danger" },
  stopped: { label: "已停止", tone: "neutral" },
};

export const TOOL_STATUS_META: Record<
  ToolCallStatus,
  { label: string; tone: string }
> = {
  pending_approval: { label: "等待审批", tone: "warning" },
  approved: { label: "准备执行", tone: "info" },
  running: { label: "执行中", tone: "info" },
  succeeded: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  rejected: { label: "已拒绝", tone: "muted" },
  cancelled: { label: "已取消", tone: "muted" },
};

const TOOL_LABELS: Record<string, string> = {
  read_file: "读取文件",
  write_file: "修改文件",
  apply_patch: "应用代码变更",
  list_directory: "查看目录",
  scan_directory: "扫描目录",
  search_files: "搜索项目文件",
  run_command: "运行命令",
  web_search: "搜索资料",
};

export function toolLabel(toolName: string): string {
  return TOOL_LABELS[toolName] ?? toolName.replace(/_/g, " ");
}

export function toolSummary(tool: ToolCall): string {
  const values = tool.input_json ? Object.values(tool.input_json) : [];
  const target = values.find(
    (value) => typeof value === "string" && value.trim().length > 0
  );
  if (typeof target !== "string") return toolLabel(tool.tool_name);
  const compact = target.replace(/\s+/g, " ").trim();
  return `${toolLabel(tool.tool_name)} · ${compact.length > 72 ? `${compact.slice(0, 72)}…` : compact}`;
}

export function formatActivityTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function buildAgentPlan(
  messages: AgentWorkspaceMessage[],
  streaming: boolean
): WorkspacePlanStep[] {
  const hasUserRequest = messages.some((message) => message.role === "user");
  const toolCalls = messages
    .map((message) => message.tool_call)
    .filter((tool): tool is ToolCall => Boolean(tool));
  const hasAssistantResult = messages.some(
    (message) => message.role === "assistant" && Boolean(message.content.trim())
  );
  const hasFailedTool = toolCalls.some((tool) => tool.status === "failed");
  const hasWaitingTool = toolCalls.some(
    (tool) => tool.status === "pending_approval"
  ) || messages.some((message) => message.agent_approval?.status === "pending");
  const hasRunningTool = toolCalls.some(
    (tool) => tool.status === "running" || tool.status === "approved"
  ) || messages.some((message) => message.agent_approval?.status === "approved");
  const allToolsSettled =
    toolCalls.length > 0 &&
    toolCalls.every((tool) =>
      ["succeeded", "rejected", "cancelled"].includes(tool.status)
    );

  let executeStatus: WorkspaceStepStatus = "pending";
  if (hasFailedTool) executeStatus = "failed";
  else if (hasWaitingTool) executeStatus = "blocked";
  else if (hasRunningTool) executeStatus = "running";
  else if (allToolsSettled || (hasUserRequest && toolCalls.length === 0)) {
    executeStatus = "completed";
  }

  let responseStatus: WorkspaceStepStatus = "pending";
  if (streaming && !hasWaitingTool && !hasRunningTool) responseStatus = "running";
  else if (hasAssistantResult && !streaming) responseStatus = "completed";
  else if (hasFailedTool) responseStatus = "blocked";

  const verifyStatus: WorkspaceStepStatus =
    hasAssistantResult && !streaming && !hasFailedTool ? "completed" : "pending";

  return [
    {
      id: "understand",
      title: "理解任务",
      detail: hasUserRequest ? "目标与上下文已确认" : "等待任务说明",
      status: hasUserRequest ? "completed" : "running",
    },
    {
      id: "execute",
      title: "执行操作",
      detail: hasWaitingTool
        ? "需要你的确认"
        : hasRunningTool
          ? "正在调用本地工具"
          : hasFailedTool
            ? "工具执行遇到问题"
            : toolCalls.length > 0
              ? `已处理 ${toolCalls.length} 个工具调用`
              : "按需调用工具与资料",
      status: executeStatus,
    },
    {
      id: "respond",
      title: "整理结果",
      detail: streaming ? "正在生成可读结果" : "汇总关键结论与变更",
      status: responseStatus,
    },
    {
      id: "verify",
      title: "完成检查",
      detail: verifyStatus === "completed" ? "本轮任务已完成" : "等待最终结果",
      status: verifyStatus,
    },
  ];
}

export function deriveTaskState(
  messages: AgentWorkspaceMessage[],
  streaming: boolean
): AgentTaskState {
  const calls = messages
    .map((message) => message.tool_call)
    .filter((tool): tool is ToolCall => Boolean(tool));
  if (
    calls.some((tool) => tool.status === "pending_approval") ||
    messages.some((message) => message.agent_approval?.status === "pending")
  ) return "waiting";
  if (calls.some((tool) => tool.status === "failed")) return "failed";
  if (
    streaming ||
    calls.some((tool) => ["approved", "running"].includes(tool.status)) ||
    messages.some((message) => message.agent_approval?.status === "approved")
  ) {
    return "running";
  }
  if (messages.some((message) => message.role === "assistant" && message.content.trim())) {
    return "completed";
  }
  return "idle";
}
