import { apiFetch, ensureApiBase } from "./http";
import type { AgentTask } from "../types";

// ---- 多步 Agent 任务（第三阶段 M6）----
export async function listAgentTasks(): Promise<AgentTask[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createAgentTask(data: {
  title: string;
  goal?: string;
  project_id?: number;
  steps?: Array<{
    title: string;
    tool_name: string;
    input_json: Record<string, unknown>;
  }>;
}): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function createAgentTaskPlan(data: {
  title: string;
  goal: string;
  project_id?: number;
}): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function runAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/${id}/run`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateAgentTaskPlan(
  id: number,
  data: {
    title?: string;
    goal?: string;
    steps: Array<{
      title: string;
      tool_name: string;
      input_json: Record<string, unknown>;
    }>;
  }
): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/${id}/plan`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function approveAgentTaskPlan(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/${id}/approve-plan`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function pauseAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/${id}/pause`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function cancelAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/${id}/cancel`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function resumeAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/${id}/resume`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function resumeAgentTaskFrom(id: number, stepId: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-tasks/${id}/resume-from/${stepId}`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function approveAgentTaskStep(stepId: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-task-steps/${stepId}/approve`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function retryAgentTaskStep(stepId: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/agent-task-steps/${stepId}/retry`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
