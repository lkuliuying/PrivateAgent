import { codingFetch, codingFetchJson, codingJsonInit } from "./codingHttp";
export interface BrowserEvidence { url: string; screenshot_id: string; created_at: string; checks: { action: string; selector: string; passed?: boolean; performed?: boolean }[]; notice: string }
export interface ChildAgent { id: string; title: string; status: string; output: string; error?: string; input_tokens: number; output_tokens: number; cost_usd: number | null }
export const fetchBrowserEvidence = (runId: string, signal?: AbortSignal) => codingFetchJson<{ items: BrowserEvidence[] }>(`/agent-runs/${runId}/browser-evidence`, { signal });
export async function fetchBrowserImage(runId: string, imageId: string, signal?: AbortSignal) {
  const response = await codingFetch(`/agent-runs/${runId}/browser-evidence/${imageId}`, { signal });
  if (!response.ok) throw new Error("截图读取失败");
  return response.blob();
}
export const fetchChildAgents = (runId: string, signal?: AbortSignal) => codingFetchJson<{ items: ChildAgent[] }>(`/agent-runs/${runId}/agents`, { signal });
export const cancelChildAgent = (runId: string, childId: string) => codingFetchJson(`/agent-runs/${runId}/agents/${childId}/cancel`, codingJsonInit("POST", {}));
