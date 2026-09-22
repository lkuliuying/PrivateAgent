import { codingFetchJson, codingJsonInit } from "./codingHttp";
export interface QueuedTurn { request_id: string; after_run_id: string; message: string; state: "pending" | "blocked" | "launched" | "cancelled"; result_run_id: string | null; error: string | null }
export const fetchTurnQueue = (sessionId: number, signal?: AbortSignal) => codingFetchJson<{ item: QueuedTurn | null }>(`/sessions/${sessionId}/turn-queue`, { signal });
export const enqueueTurn = (sessionId: number, runId: string, requestId: string, message: string) => codingFetchJson<QueuedTurn>(`/sessions/${sessionId}/turn-queue`, codingJsonInit("POST", { run_id: runId, request_id: requestId, message }));
export const removeQueuedTurn = (sessionId: number, requestId: string) => codingFetchJson<QueuedTurn>(`/sessions/${sessionId}/turn-queue/${encodeURIComponent(requestId)}`, { method: "DELETE" });
