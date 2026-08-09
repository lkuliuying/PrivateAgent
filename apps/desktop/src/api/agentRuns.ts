import type {
  AgentApprovalPreview,
  AgentRunApproval,
  AgentToolExecution,
  AgentToolOutputPage,
  ChatEvent,
} from "../types";
import { apiFetch as fetch, ensureApiBase } from "./http";

async function requireOk(response: Response): Promise<void> {
  if (response.ok) return;
  const body = await response.json().catch(() => null);
  throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
}

/** v0.5.0 B1：已脱敏/限长并持久化的工具执行结果（产物与 Diff 入口的事实源）。 */
export async function listAgentRunExecutions(
  runId: string
): Promise<AgentToolExecution[]> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/agent-runs/${encodeURIComponent(runId)}/executions`
  );
  await requireOk(response);
  return response.json();
}

/**
 * v0.5.0 B2：按 seq 续读流式输出（实时输出轮询）。afterSeq 传上次返回的
 * last_seq；默认 -1 返回全部（含 seq=0 首行）。
 */
export async function getAgentToolOutput(
  runId: string,
  executionId: string,
  afterSeq: number = -1
): Promise<AgentToolOutputPage> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/agent-runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/output?after_seq=${afterSeq}`
  );
  await requireOk(response);
  return response.json();
}

export async function listPendingAgentApprovals(
  sessionId: number
): Promise<AgentRunApproval[]> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/agent-runs/sessions/${sessionId}/pending-approvals`
  );
  await requireOk(response);
  return response.json();
}

/**
 * v0.5.0 B1：只读的文件变更预览（审批时展示 diff，不触碰审批 token）。
 * 后端基于当前磁盘事实重新计算；不可预览时 previewable=false。
 */
export async function getAgentApprovalPreview(
  runId: string,
  approvalId: string
): Promise<AgentApprovalPreview> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/agent-runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/preview`
  );
  await requireOk(response);
  return response.json();
}

export async function approveAgentRunTool(
  runId: string,
  approvalId: string
): Promise<void> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/agent-runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/approve`,
    { method: "POST" }
  );
  await requireOk(response);
}

export async function rejectAgentRunTool(
  runId: string,
  approvalId: string
): Promise<void> {
  const base = await ensureApiBase();
  const response = await fetch(
    `${base}/agent-runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/reject`,
    { method: "POST" }
  );
  await requireOk(response);
}

export function streamAgentRunContinuation(
  runId: string,
  onEvent: (event: ChatEvent) => void,
  onError: (error: string) => void,
  onClose?: () => void
): AbortController {
  const controller = new AbortController();
  ensureApiBase()
    .then(async (base) => {
      const response = await fetch(
        `${base}/chat/agent-runs/${encodeURIComponent(runId)}/stream`,
        { signal: controller.signal }
      );
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index: number;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const line = block.split("\n").find((item) => item.startsWith("data:"));
          if (!line) continue;
          try {
            onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent);
          } catch {
            // Ignore malformed external transport frames; the durable run remains queryable.
          }
        }
      }
      onClose?.();
    })
    .catch((error) => {
      if (error?.name === "AbortError") onClose?.();
      else onError(String(error));
    });
  return controller;
}
