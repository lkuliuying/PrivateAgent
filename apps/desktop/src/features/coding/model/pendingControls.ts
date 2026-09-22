import type { ControlRequest, RunControlKind } from "../api/recovery";
export interface PendingControl { kind: RunControlKind | "queue"; data: ControlRequest }
const memory = new Map<string, PendingControl>();
/** 结果未确认时保留原请求标识，切换任务或刷新后重试不会生成第二次操作。 */
export function readPendingControl(runId: string): PendingControl | null {
  if (memory.has(runId)) return memory.get(runId)!;
  try {
    const raw = sessionStorage.getItem(`pa-control:${runId}`);
    if (!raw) return null;
    const value = JSON.parse(raw) as PendingControl;
    if (!["pause", "resume", "steer", "queue"].includes(value.kind) || typeof value.data?.request_id !== "string" || !Number.isSafeInteger(value.data.expected_state_version)) return null;
    memory.set(runId, value); return value;
  } catch { return null; }
}
export function savePendingControl(runId: string, value: PendingControl | null) {
  if (value) memory.set(runId, value); else memory.delete(runId);
  try { if (value) sessionStorage.setItem(`pa-control:${runId}`, JSON.stringify(value)); else sessionStorage.removeItem(`pa-control:${runId}`); }
  catch { /* 存储不可用时，仍在本次页面生命周期内保留幂等标识。 */ }
}
