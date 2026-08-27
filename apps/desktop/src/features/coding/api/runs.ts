/**
 * v0.8.0 W2 · Coding run API（POST /agent-runs、快照、durable 事件、SSE、取消、审批）
 *
 * SSE 帧格式（routes_agent_runs.py:1506-1523）：`data: {sequence,type,payload}\n\n`；
 * `: heartbeat` 注释帧忽略；终态后补发合成 `run.terminal` 帧并关闭。
 * 断线不取消后台 run；重连带 after_sequence=最后已应用序号续读。
 */
import { codingFetchJson, codingJsonInit } from "./codingHttp";
import { apiFetch, ensureApiBase } from "../../../api/http";
import {
  approveAgentRunTool,
  getAgentApprovalPreview,
  getAgentToolOutput,
  listAgentRunExecutions,
  rejectAgentRunTool,
} from "../../../api/agentRuns";
import type { AgentApprovalPreview, AgentToolExecution } from "../../../types";
import type {
  CodingRunCreateInput,
  RunApprovalPreviewRecord,
  RunApprovalRecord,
  RunCancelResult,
  RunEventPage,
  RunExecutionOutputPage,
  RunExecutionRecord,
  RunSnapshot,
  RunStreamFrame,
} from "../model/runContracts";

export async function createCodingRun(input: CodingRunCreateInput): Promise<RunSnapshot> {
  return codingFetchJson<RunSnapshot>("/agent-runs", codingJsonInit("POST", input));
}

export async function fetchRunSnapshot(runId: string): Promise<RunSnapshot> {
  return codingFetchJson<RunSnapshot>(`/agent-runs/${encodeURIComponent(runId)}`);
}

export async function fetchRunEvents(
  runId: string,
  afterSequence: number,
  limit = 1000
): Promise<RunEventPage> {
  return codingFetchJson<RunEventPage>(
    `/agent-runs/${encodeURIComponent(runId)}/events?after_sequence=${afterSequence}&limit=${limit}`
  );
}

export async function cancelCodingRun(runId: string): Promise<RunCancelResult> {
  return codingFetchJson<RunCancelResult>(
    `/agent-runs/${encodeURIComponent(runId)}/cancel`,
    codingJsonInit("POST", {})
  );
}

export async function fetchRunApprovals(runId: string): Promise<RunApprovalRecord[]> {
  return codingFetchJson<RunApprovalRecord[]>(
    `/agent-runs/${encodeURIComponent(runId)}/approvals`
  );
}

export async function approveRunApproval(runId: string, approvalId: string): Promise<void> {
  await approveAgentRunTool(runId, approvalId);
}

export async function rejectRunApproval(runId: string, approvalId: string): Promise<void> {
  await rejectAgentRunTool(runId, approvalId);
}

/** 审批影响范围预览（基于当前磁盘事实重算的 diff；previewable=false 时仅 reason） */
export async function fetchRunApprovalPreview(
  runId: string,
  approvalId: string
): Promise<RunApprovalPreviewRecord> {
  const preview = (await getAgentApprovalPreview(runId, approvalId)) as AgentApprovalPreview;
  return {
    tool_name: preview.tool_name,
    previewable: preview.previewable,
    rel_path: preview.rel_path,
    creates_file: preview.creates_file,
    old_sha256: preview.old_sha256,
    new_sha256: preview.new_sha256,
    diff: preview.diff,
    truncated: preview.truncated,
    reason: preview.reason,
  };
}

/** 已脱敏有界的工具执行结果（命令输出 parsed 摘要在此） */
export async function fetchRunExecutions(runId: string): Promise<RunExecutionRecord[]> {
  const list = (await listAgentRunExecutions(runId)) as AgentToolExecution[];
  return list.map((item) => ({
    id: item.id,
    tool_name: item.tool_name,
    tool_version: item.tool_version,
    status: item.status,
    error_code: item.error_code,
    error_message: item.error_message,
    output: item.output,
    created_at: item.created_at,
    completed_at: item.completed_at ?? null,
  }));
}

/** 流式输出行续读（after_seq 增量；finished=false 时轮询） */
export async function fetchRunExecutionOutput(
  runId: string,
  executionId: string,
  afterSeq = -1
): Promise<RunExecutionOutputPage> {
  return (await getAgentToolOutput(runId, executionId, afterSeq)) as RunExecutionOutputPage;
}

export interface RunStreamCallbacks {
  onFrame: (frame: RunStreamFrame) => void;
  onError: (message: string) => void;
  onClose: () => void;
}

/**
 * 打开 durable 事件 SSE（GET /agent-runs/{id}/events/stream?after_sequence=）。
 * 返回 AbortController；abort 视为主动关闭（onClose，不触发重连）。
 */
export function streamRunEvents(
  runId: string,
  afterSequence: number,
  callbacks: RunStreamCallbacks
): AbortController {
  const controller = new AbortController();
  void (async () => {
    try {
      // apiFetch 注入 Bearer；SSE 经 fetch reader 增量解析
      const base = await ensureApiBase();
      const response = await apiFetch(
        `${base}/agent-runs/${encodeURIComponent(runId)}/events/stream?after_sequence=${afterSequence}`,
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
          if (!line) continue; // `: heartbeat` 等注释帧
          try {
            callbacks.onFrame(JSON.parse(line.slice(5).trim()) as RunStreamFrame);
          } catch {
            // 畸形传输帧忽略：durable 事实可经快照+events 重放恢复
          }
        }
      }
      callbacks.onClose();
    } catch (error) {
      if ((error as { name?: string })?.name === "AbortError") {
        callbacks.onClose();
      } else {
        callbacks.onError(String(error));
      }
    }
  })();
  return controller;
}
