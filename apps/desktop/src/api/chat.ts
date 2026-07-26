import type {
  ChatEvent,
  Message,
  Session,
  ToolCall,
  ToolPlanResponse,
} from "../types";
import { ensureApiBase, requestJson } from "./http";

export function listSessions(): Promise<Session[]> {
  return requestJson<Session[]>("/sessions");
}

export function createSession(): Promise<Session> {
  return requestJson<Session>("/sessions", { method: "POST" });
}

export function getMessages(sessionId: number): Promise<Message[]> {
  return requestJson<Message[]>(`/sessions/${sessionId}/messages`);
}

export async function planTools(
  sessionId: number,
  message: string
): Promise<ToolPlanResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    return await requestJson<ToolPlanResponse>("/tools/plan", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, message }),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

export function approveToolCall(id: number): Promise<ToolCall> {
  return requestJson<ToolCall>(`/tool-calls/${id}/approve`, { method: "POST" });
}

export function rejectToolCall(id: number): Promise<ToolCall> {
  return requestJson<ToolCall>(`/tool-calls/${id}/reject`, { method: "POST" });
}

export function listToolCalls(sessionId?: number): Promise<ToolCall[]> {
  const query = sessionId ? `?session_id=${sessionId}` : "";
  return requestJson<ToolCall[]>(`/tool-calls${query}`);
}

/**
 * SSE streaming boundary. The returned controller is the single cancellation
 * handle owned by the chat workspace controller.
 */
export function streamChat(
  sessionId: number,
  message: string,
  knowledgeBase: boolean,
  onEvent: (event: ChatEvent) => void,
  onError: (error: string) => void,
  onClose?: () => void,
  toolResult?: { tool_name: string; output: Record<string, unknown> }
): AbortController {
  const controller = new AbortController();

  ensureApiBase()
    .then((base) =>
      fetch(`${base}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          knowledge_base: knowledgeBase,
          ...(toolResult ? { tool_result: toolResult } : {}),
        }),
        signal: controller.signal,
      })
    )
    .then(async (response) => {
      if (!response.ok || !response.body) {
        onError(`HTTP ${response.status}`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const rawEvent = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data:"));
          if (dataLine) {
            try {
              onEvent(JSON.parse(dataLine.slice(5).trim()) as ChatEvent);
            } catch {
              // A malformed event is isolated; subsequent valid events still stream.
            }
          }
          boundary = buffer.indexOf("\n\n");
        }
      }
      onClose?.();
    })
    .catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        onClose?.();
        return;
      }
      onError(String(error));
    });

  return controller;
}
