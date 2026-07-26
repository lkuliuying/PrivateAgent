import { computed, ref, type Ref } from "vue";
import {
  approveToolCall,
  candidateMemories,
  createInbox,
  createSession,
  getMessages,
  listSessions,
  listToolCalls,
  planTools,
  rejectToolCall,
  streamChat,
} from "../api";
import { useNotifications } from "../stores/notifications";
import type {
  MemorySource,
  Message,
  Session,
  Source,
  ToolCall,
  View,
} from "../types";

export type TodayComposerMode = "chat" | "knowledge" | "plan" | "code";

export type ChatMessage = Message & {
  sources?: Source[];
  memories?: MemorySource[];
  tool_call?: ToolCall;
  clientKey?: string;
};

interface UseChatWorkspaceOptions {
  view: Ref<View>;
  notify: ReturnType<typeof useNotifications>;
}

/**
 * Owns chat sessions, streaming and tool-approval state.
 * App.vue remains the composition root; this controller contains the cancellable
 * side effects and race guards that belong to the chat workspace lifecycle.
 */
export function useChatWorkspace({ view, notify }: UseChatWorkspaceOptions) {
  const sessions = ref<Session[]>([]);
  const currentSessionId = ref<number | null>(null);
  const messages = ref<ChatMessage[]>([]);
  const streaming = ref(false);
  const knowledgeBase = ref(false);
  const currentChunkId = ref<number | null>(null);
  const pendingToolText = new Map<number, string>();

  let controller: AbortController | null = null;
  let streamSeq = 0;
  let planSeq = 0;
  let chatMessageSeq = 0;
  let planningCancelled = false;
  let destroyed = false;

  const currentSession = computed(
    () => sessions.value.find((session) => session.id === currentSessionId.value) ?? null
  );
  const hasPendingTool = computed(() =>
    messages.value.some((message) => message.tool_call?.status === "pending_approval")
  );

  function nextChatKey(kind: "user" | "assistant"): string {
    chatMessageSeq += 1;
    return `${kind}-${Date.now()}-${chatMessageSeq}`;
  }

  async function loadSessions(): Promise<void> {
    try {
      sessions.value = await listSessions();
      if (sessions.value.length > 0 && currentSessionId.value === null) {
        await selectSession(sessions.value[0].id, false);
      }
    } catch {
      // 启动阶段允许后端暂不可用，状态页负责展示连接诊断。
    }
  }

  async function selectSession(id: number, switchToChat = true): Promise<void> {
    if (streaming.value || destroyed) return;
    currentSessionId.value = id;
    if (switchToChat) view.value = "chat";
    try {
      messages.value = await getMessages(id);
    } catch {
      messages.value = [];
    }
    await rehydrateToolCalls(id);
  }

  async function rehydrateToolCalls(sessionId: number): Promise<void> {
    try {
      const calls = await listToolCalls(sessionId);
      for (const toolCall of calls) {
        if (
          toolCall.status === "pending_approval" &&
          !messages.value.some((message) => message.tool_call?.id === toolCall.id)
        ) {
          messages.value.push({
            id: -1000000 - toolCall.id,
            session_id: sessionId,
            role: "assistant",
            content: "",
            created_at: toolCall.created_at,
            tool_call: toolCall,
            clientKey: `tool-${toolCall.id}`,
          });
          pendingToolText.set(toolCall.id, "");
        }
      }
    } catch {
      // 工具卡片重水合失败不影响已持久化消息的阅读。
    }
  }

  async function newSession(): Promise<void> {
    if (streaming.value || destroyed) return;
    try {
      const session = await createSession();
      sessions.value.unshift(session);
      await selectSession(session.id);
    } catch (error) {
      notify.error("新建会话失败", String(error));
    }
  }

  async function submitFromToday(text: string, mode: TodayComposerMode): Promise<void> {
    const value = text.trim();
    if (!value || streaming.value || hasPendingTool.value || destroyed) return;

    if (!currentSession.value) await newSession();
    if (!currentSession.value) return;

    const prefixes: Record<TodayComposerMode, string> = {
      chat: "",
      knowledge: "请优先结合本地知识库回答：",
      plan: "请帮我生成一个清晰、可执行的计划：",
      code: "请作为代码助手协助我：",
    };
    knowledgeBase.value = mode === "knowledge";
    view.value = "chat";
    sendMessage(`${prefixes[mode]}${value}`);
  }

  function sendMessage(text: string): void {
    if (
      !currentSession.value ||
      streaming.value ||
      hasPendingTool.value ||
      destroyed
    ) {
      return;
    }
    const sessionId = currentSession.value.id;
    const knowledgeEnabled = knowledgeBase.value;

    messages.value.push({
      id: -Date.now(),
      session_id: sessionId,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
      clientKey: nextChatKey("user"),
    });
    streaming.value = true;
    planningCancelled = false;
    const requestSeq = ++planSeq;

    planTools(sessionId, text)
      .then((result) => {
        if (destroyed || planningCancelled || requestSeq !== planSeq) {
          if (requestSeq === planSeq) streaming.value = false;
          return;
        }
        const toolCall = result?.tool_call ?? null;
        if (toolCall) {
          messages.value.push({
            id: -Date.now() - 1,
            session_id: sessionId,
            role: "assistant",
            content: "",
            created_at: new Date().toISOString(),
            tool_call: toolCall,
            clientKey: `tool-${toolCall.id}`,
          });
          pendingToolText.set(toolCall.id, text);
          streaming.value = false;
          return;
        }
        streamAssistantReply(sessionId, text, knowledgeEnabled);
      })
      .catch(() => {
        if (destroyed || planningCancelled || requestSeq !== planSeq) {
          if (requestSeq === planSeq) streaming.value = false;
          return;
        }
        streamAssistantReply(sessionId, text, knowledgeEnabled);
      });
  }

  function streamAssistantReply(
    sessionId: number,
    text: string,
    knowledgeEnabled: boolean,
    toolResult?: { tool_name: string; output: Record<string, unknown> }
  ): void {
    const activeStream = ++streamSeq;
    const assistantMessage: ChatMessage = {
      id: -2,
      session_id: sessionId,
      role: "assistant",
      content: "",
      created_at: new Date().toISOString(),
      clientKey: nextChatKey("assistant"),
    };
    messages.value.push(assistantMessage);
    streaming.value = true;

    const isCurrent = () =>
      !destroyed &&
      activeStream === streamSeq &&
      currentSessionId.value === sessionId;

    controller = streamChat(
      sessionId,
      text,
      knowledgeEnabled,
      (event) => {
        if (!isCurrent()) return;
        if (event.type === "token" && event.content) {
          assistantMessage.content += event.content;
        } else if (event.type === "done") {
          if (event.message_id) assistantMessage.id = event.message_id;
          if (event.content) assistantMessage.content = event.content;
          if (event.sources) assistantMessage.sources = event.sources;
          if (event.memories) assistantMessage.memories = event.memories;
        } else if (event.type === "title" && event.title) {
          const session = sessions.value.find((item) => item.id === sessionId);
          if (session) session.title = event.title;
        } else if (event.type === "error" && event.message) {
          assistantMessage.content += `\n\n[错误：${event.message}]`;
        }
      },
      (error) => {
        if (!isCurrent()) return;
        assistantMessage.content += `\n\n[连接错误：${error}]`;
        streaming.value = false;
        controller = null;
      },
      () => {
        if (!isCurrent()) return;
        streaming.value = false;
        controller = null;
      },
      toolResult
    );
  }

  async function generateCandidates(): Promise<void> {
    if (!currentSession.value) return;
    try {
      const list = await candidateMemories({
        source_type: "chat_session",
        source_id: currentSession.value.id,
      });
      notify.success("候选记忆已生成", `${list.length} 条 draft，请在记忆页确认`);
    } catch (error) {
      notify.error("生成候选记忆失败", String(error));
    }
  }

  async function saveMessageToInbox(messageId: number, content: string): Promise<void> {
    const text = content.trim();
    const title = (text.split("\n")[0] || text).slice(0, 255);
    try {
      await createInbox({
        title: title || `消息 #${messageId}`,
        item_type: "note",
        body_md: text || undefined,
        source_type: "chat_message",
        source_id: messageId,
      });
      notify.success("已保存到收件箱", "今日页可查看");
    } catch (error) {
      notify.error("保存到收件箱失败", String(error));
    }
  }

  async function approveTool(id: number): Promise<void> {
    if (!currentSession.value) return;
    const sessionId = currentSession.value.id;
    const messageIndex = messages.value.findIndex((message) => message.tool_call?.id === id);
    if (messageIndex < 0) return;

    messages.value[messageIndex].tool_call = {
      ...messages.value[messageIndex].tool_call!,
      status: "running",
    };
    streaming.value = true;
    try {
      const updated = await approveToolCall(id);
      if (destroyed) return;
      messages.value[messageIndex].tool_call = updated;
      if (updated.status === "succeeded" && updated.output_json) {
        const text = pendingToolText.get(id) || "请基于以下工具结果回答。";
        pendingToolText.delete(id);
        streamAssistantReply(sessionId, text, knowledgeBase.value, {
          tool_name: updated.tool_name,
          output: updated.output_json,
        });
      } else {
        streaming.value = false;
        pendingToolText.delete(id);
      }
    } catch (error) {
      if (destroyed) return;
      streaming.value = false;
      pendingToolText.delete(id);
      messages.value[messageIndex].tool_call = {
        ...messages.value[messageIndex].tool_call!,
        status: "failed",
        error_message: String(error),
      };
    }
  }

  async function rejectTool(id: number): Promise<void> {
    const messageIndex = messages.value.findIndex((message) => message.tool_call?.id === id);
    if (messageIndex < 0) return;
    try {
      const updated = await rejectToolCall(id);
      if (!destroyed) messages.value[messageIndex].tool_call = updated;
    } catch {
      if (!destroyed) {
        messages.value[messageIndex].tool_call = {
          ...messages.value[messageIndex].tool_call!,
          status: "rejected",
        };
      }
    }
    pendingToolText.delete(id);
  }

  function stopGenerate(): void {
    planningCancelled = true;
    planSeq += 1;
    streamSeq += 1;
    const activeController = controller;
    controller = null;
    activeController?.abort();
    streaming.value = false;
  }

  function destroy(): void {
    if (destroyed) return;
    destroyed = true;
    stopGenerate();
    pendingToolText.clear();
  }

  return {
    sessions,
    currentSessionId,
    messages,
    streaming,
    knowledgeBase,
    currentChunkId,
    currentSession,
    hasPendingTool,
    loadSessions,
    selectSession,
    newSession,
    submitFromToday,
    sendMessage,
    stopGenerate,
    generateCandidates,
    saveMessageToInbox,
    approveTool,
    rejectTool,
    destroy,
  };
}
