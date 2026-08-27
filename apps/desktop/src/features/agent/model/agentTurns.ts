/**
 * v0.8.0 W6-R2 · Agent 会话 turn 分组（typed projector，纯函数）
 *
 * 每条用户消息创建稳定 turn 分组；同一轮的工具/审批/公开过程与最终回答
 * 归入该分组（计划 §4.4 逐轮内容结构）。归属只依赖消息顺序与公开事实
 * （用户消息边界），不按时间或文案猜测。
 *
 * 阶段语义（真实状态，不虚构）：
 * - waiting_approval：本轮存在待审批事实（工具/Agent run 审批）；
 * - running：流式进行中且为本轮（由调用方传入全局流式状态与末轮判定）；
 * - settled：其余情况（完成/停止/历史重水合）。
 */
import type { AgentWorkspaceMessage } from "../../../models/agentWorkspace";

export type AgentTurnPhase = "running" | "waiting_approval" | "settled";

export interface AgentTurn {
  /** 稳定键：用户消息 clientKey/id；首条用户消息之前的公开过程归入 "pre" */
  key: string;
  userMessage: AgentWorkspaceMessage | null;
  /** 公开过程：工具卡/审批卡/中间 Agent 公开消息（按发生顺序） */
  process: AgentWorkspaceMessage[];
  /** 最终回答：本轮最后一条有内容的普通助手消息（公开事实） */
  finalAnswer: AgentWorkspaceMessage | null;
  phase: AgentTurnPhase;
}

function isFinalAnswerCandidate(message: AgentWorkspaceMessage): boolean {
  return (
    message.role === "assistant" &&
    !message.tool_call &&
    !message.agent_approval &&
    Boolean(message.content.trim())
  );
}

function hasPendingApproval(turn: { userMessage: AgentWorkspaceMessage | null; process: AgentWorkspaceMessage[] }): boolean {
  const all = turn.userMessage ? [turn.userMessage, ...turn.process] : turn.process;
  return all.some(
    (message) =>
      message.agent_approval?.status === "pending" ||
      message.tool_call?.status === "pending_approval"
  );
}

/**
 * 把会话消息聚合为稳定 turn。
 * `streaming` 为全局流式状态；仅最后一个 turn 可能处于 running/等待阶段。
 */
export function groupAgentTurns(
  messages: AgentWorkspaceMessage[],
  streaming: boolean
): AgentTurn[] {
  const turns: AgentTurn[] = [];
  let current: AgentTurn | null = null;

  const openPre = (): AgentTurn => {
    const pre: AgentTurn = {
      key: "pre",
      userMessage: null,
      process: [],
      finalAnswer: null,
      phase: "settled",
    };
    turns.push(pre);
    return pre;
  };

  for (const message of messages) {
    if (message.role === "user" && !message.tool_call && !message.agent_approval) {
      const turn: AgentTurn = {
        key: message.clientKey ?? `user-${message.id}`,
        userMessage: message,
        process: [],
        finalAnswer: null,
        phase: "settled",
      };
      turns.push(turn);
      current = turn;
      continue;
    }
    const target = current ?? (turns.length ? turns[turns.length - 1] : openPre());
    if (isFinalAnswerCandidate(message)) {
      // 更晚的最终回答覆盖早先候选；早先候选降回公开过程（保持顺序）
      if (target.finalAnswer) target.process.push(target.finalAnswer);
      target.finalAnswer = message;
    } else {
      target.process.push(message);
    }
  }

  if (turns.length) {
    const last = turns[turns.length - 1];
    if (hasPendingApproval(last)) {
      last.phase = "waiting_approval";
    } else if (streaming) {
      last.phase = "running";
    }
  }
  return turns;
}

/**
 * 本轮公开状态标签（仅在尚无最终回答时呈现）：
 * 只依据审批/工具/流式事实，不生成解释性内容冒充模型思考。
 */
export function turnPublicStatusLabel(turn: AgentTurn): string | null {
  if (turn.finalAnswer) return null;
  if (turn.phase === "waiting_approval") return "等待审批";
  const executing = turn.process.some(
    (message) =>
      message.tool_call &&
      ["running", "approved"].includes(message.tool_call.status)
  );
  if (executing) return "正在执行工具";
  if (turn.phase === "running") return "正在分析";
  return null;
}
