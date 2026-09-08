import { codingFetchJson, codingJsonInit } from "./codingHttp";

export interface ManagedExecution {
  execution_id: string;
  run_id: string;
  argv: string[];
  cwd: string;
  status: "starting" | "running" | "exited" | "cancelled" | "timed_out" | "failed" | "unknown";
  retention: "run" | "session";
  state_version: number;
  stdin_open: boolean;
  stopped: boolean;
  exit_code: number | null;
  error: string | null;
  dropped_bytes: number;
  last_output_sequence: number;
}
export interface ExecutionPage extends ManagedExecution {
  chunks: { sequence: number; stream: "stdout" | "stderr"; data: string }[];
  next_cursor: number;
  gap: boolean;
  has_more: boolean;
}
const path = (session: number, id?: string) => `/sessions/${session}/executions${id ? `/${encodeURIComponent(id)}` : ""}`;
export const listExecutions = (session: number, signal?: AbortSignal): Promise<{ items: ManagedExecution[] }> => codingFetchJson(path(session), { signal });
export const readExecution = (session: number, id: string, cursor: number, signal?: AbortSignal): Promise<ExecutionPage> => codingFetchJson(`${path(session, id)}?cursor=${cursor}`, { signal });
export const cancelExecution = (session: number, id: string): Promise<ManagedExecution> => codingFetchJson(`${path(session, id)}/cancel`, codingJsonInit("POST", { execution_id: id, request_id: crypto.randomUUID() }));
export const writeExecution = (session: number, item: ManagedExecution, data: string, eof: boolean): Promise<ExecutionPage> => codingFetchJson(`${path(session, item.execution_id)}/stdin`, codingJsonInit("POST", { execution_id: item.execution_id, data, eof, expected_state_version: item.state_version }));
export const closeExecutions = (session: number): Promise<{ items: ManagedExecution[] }> => codingFetchJson(`${path(session)}/close`, codingJsonInit("POST", {}));

export function executionText(text: string): string {
  return text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "").replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g, "").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "");
}
