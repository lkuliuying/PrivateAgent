/**
 * useLegacyChatSession · v0.8.0 W4
 *
 * 旧 chat 视图（ui_v1 ChatView / v2 AgentWorkspace）的会话编排整体迁出
 * App.vue（计划 §5.2）：会话/消息/流式状态、planner 判定、plan-then-reply、
 * 审批（工具/Agent run）与续跑、上下文轮询、执行结果拉取、候选记忆/收件箱。
 * 行为与迁移前逐行一致；竞态防护（streamSeq/planSeq/contextSeq）原样保留。
 * App.vue 只保留壳与全局编排（boot/导航/浮层/coding 接线）。
 */
import { computed, ref, type ComputedRef, type Ref } from "vue";
import { useNotifications } from "../../stores/notifications";
import { deriveTaskState, type AgentWorkspaceMessage } from "../../models/agentWorkspace";
import {
  approveAgentRunTool,
  approveToolCall,
  candidateMemories,
  createInbox,
  createSession,
  getMessages,
  getRuntimeCapabilities,
  listActivities,
  listAgentRunExecutions,
  listPendingAgentApprovals,
  listSessions,
  listToolCalls,
  listTrustedPaths,
  planTools,
  rejectAgentRunTool,
  rejectToolCall,
  shouldUseLegacyToolPlanner,
  streamAgentRunContinuation,
  streamChat,
} from "../../api";
import type {
  Activity,
  AgentTaskState,
  AgentToolExecution,
  Session,
  TrustedPath,
} from "../../types";

/** ?workspace-preview=running 夹具的结构类型（dev 模块不进本模块依赖） */
export interface LegacyWorkspacePreview {
  session: Session;
  messages: AgentWorkspaceMessage[];
  trusted: TrustedPath[];
  activities: Activity[];
}

export interface LegacyChatSession {
  sessions: Ref<Session[]>;
  currentSessionId: Ref<number | null>;
  messages: Ref<AgentWorkspaceMessage[]>;
  streaming: Ref<boolean>;
  knowledgeBase: Ref<boolean>;
  runExecutions: Ref<AgentToolExecution[]>;
  sessionActivities: Ref<Activity[]>;
  trustedPaths: Ref<TrustedPath[]>;
  useLegacyToolPlanner: Ref<boolean>;
  /** W6-R3：公开 capability（自动化能力判断事实源） */
  runtimeCapabilities: Ref<Record<string, unknown> | null>;
  hasPendingTool: ComputedRef<boolean>;
  taskState: ComputedRef<AgentTaskState>;
  currentSession: ComputedRef<Session | null>;
  initializeLegacyWorkspace: () => Promise<void>;
  loadSessions: () => Promise<void>;
  selectSession: (id: number, switchToChat?: boolean) => Promise<void>;
  newSession: () => Promise<void>;
  sendMessage: (text: string) => void;
  stopGenerate: () => void;
  onApproveToolCall: (id: number) => Promise<void>;
  onRejectToolCall: (id: number) => Promise<void>;
  onApproveAgentRunTool: (runId: string, approvalId: string) => Promise<void>;
  onRejectAgentRunTool: (runId: string, approvalId: string) => Promise<void>;
  onGenCandidates: () => Promise<void>;
  onSaveMessageToInbox: (messageId: number, content: string) => Promise<void>;
  applyWorkspacePreview: (preview: LegacyWorkspacePreview) => void;
  dispose: () => void;
}

export function useLegacyChatSession(options: {
  navigateToChat: (sessionId: number) => void;
}): LegacyChatSession {
  const notify = useNotifications();

  const sessions = ref<Session[]>([]);
  const currentSessionId = ref<number | null>(null);
  const messages = ref<AgentWorkspaceMessage[]>([]);
  const streaming = ref(false);

  /** v0.5.0 B1：已脱敏/限长并持久化的工具执行结果（ContextRail Files/Diff 事实源）。 */
  const runExecutions = ref<AgentToolExecution[]>([]);

  async function loadRunExecutions(runId: string) {
    if (!runId) return;
    try {
      const executions = await listAgentRunExecutions(runId);
      const patchResults = executions.filter(
        (execution) => execution.tool_name === "apply_patch_to_workspace"
      );
      const merged = runExecutions.value.filter(
        (execution) =>
          !patchResults.some((candidate) => candidate.id === execution.id)
      );
      runExecutions.value = [...merged, ...patchResults];
    } catch {
      // 执行结果缺失不影响聊天流；后续可在同一 run 上重试
    }
  }

  // v2 上下文栏数据：会话活动（5s 轮询）与授权路径，与当前任务绑定
  const sessionActivities = ref<Activity[]>([]);
  const trustedPaths = ref<TrustedPath[]>([]);
  let activityTimer: number | null = null;
  // 上下文加载请求序号：快速切换会话时，旧调用在任一 await 后检查所有权，放弃自身并
  // 不建立定时器，保证任意时刻最多存在一个活动轮询。
  let contextSeq = 0;
  // Capability discovery is backward-compatible: unknown/old backends retain the legacy planner.
  const useLegacyToolPlanner = ref(true);
  /** W6-R3：公开 capability 原样缓存（供自动化能力判断，不猜测内部状态） */
  const runtimeCapabilities = ref<Record<string, unknown> | null>(null);
  const knowledgeBase = ref(false);

  let controller: AbortController | null = null;
  // 流请求序号：停止后即使旧 reader/onClose 延迟回调，也不能再改写当前会话或新流状态。
  let streamSeq = 0;
  let chatMessageSeq = 0;
  function nextChatKey(kind: "user" | "assistant" | "tool"): string {
    chatMessageSeq += 1;
    return `${kind}-${Date.now()}-${chatMessageSeq}`;
  }
  // plan 请求序号：每次 sendMessage 自增，旧 plan 解析回来时若序号不匹配则放弃
  let planSeq = 0;
  // plan-then-reply：toolCallId -> 原始用户消息（批准后用于流式总结）
  const pendingToolText = ref<Map<number, string>>(new Map());
  // 用户在 planning 阶段点停止时置 true，阻止 plan 完成后继续回复
  const planningCancelled = ref(false);

  const hasPendingTool = computed(
    () =>
      messages.value.some(
        (m) =>
          m.tool_call?.status === "pending_approval" ||
          m.agent_approval?.status === "pending"
      )
  );
  const taskState = computed(() =>
    deriveTaskState(messages.value, streaming.value)
  );
  const currentSession = computed(
    () => sessions.value.find((s) => s.id === currentSessionId.value) ?? null
  );

  async function initializeLegacyWorkspace() {
    let capabilities: import("../../api").RuntimeCapabilities | null = null;
    try {
      capabilities = await getRuntimeCapabilities();
    } catch {
      capabilities = null;
    }
    runtimeCapabilities.value = capabilities as unknown as Record<string, unknown> | null;
    useLegacyToolPlanner.value = shouldUseLegacyToolPlanner(capabilities);
    // W6-R3：知识检索改为自动运行——RAG 能力就绪时随每轮对话执行（公开
    // 证据 = 助手消息 sources）；移除手动按钮后不得静默关闭原启用能力。
    if (
      capabilities?.rag_chat_runtime_enabled === true &&
      capabilities?.chat_execution_mode === "agent_runtime"
    ) {
      knowledgeBase.value = true;
    }
    await loadSessions();
  }

  async function loadSessions() {
    try {
      sessions.value = await listSessions();
      if (sessions.value.length > 0 && currentSessionId.value === null) {
        await selectSession(sessions.value[0].id, false);
      }
    } catch {
      // 后端未连接，设置/状态页会展示提示
    }
  }

  async function selectSession(id: number, switchToChat = true) {
    if (streaming.value) return;
    currentSessionId.value = id;
    if (switchToChat) options.navigateToChat(id);
    try {
      messages.value = await getMessages(id);
    } catch {
      messages.value = [];
    }
    // 重水合未决工具调用卡片（重载/切换会话后仍可审批）
    await rehydrateToolCalls(id);
    loadSessionContext(id);
  }

  /** v2 上下文栏：加载授权路径并轮询会话活动；切换会话/卸载时清理旧定时器。 */
  async function loadSessionContext(sessionId: number) {
    const mine = ++contextSeq;
    if (activityTimer !== null) {
      window.clearInterval(activityTimer);
      activityTimer = null;
    }
    try {
      const paths = await listTrustedPaths();
      // W6-R2：同 activities——非数组响应不得污染只读数组（下游有可迭代假设）
      trustedPaths.value = Array.isArray(paths) ? paths : [];
    } catch {
      trustedPaths.value = [];
    }
    // 期间发生了更新的会话切换：放弃本次调用，不建立定时器
    if (mine !== contextSeq) return;
    const refreshActivities = async () => {
      if (mine !== contextSeq || currentSessionId.value !== sessionId) return;
      try {
        const data = await listActivities(sessionId);
        // W6-R2：非数组响应（异常/兼容后端）不得污染只读数组，避免下游渲染崩溃
        if (Array.isArray(data)) sessionActivities.value = data;
      } catch {
        // 后端未连接时保留现有数据，不因瞬时失败清空
      }
    };
    await refreshActivities();
    if (mine !== contextSeq) return;
    activityTimer = window.setInterval(() => void refreshActivities(), 5000);
  }

  /** 加载会话的工具调用，把未决（pending_approval）的重新渲染为审批卡片。 */
  async function rehydrateToolCalls(sessionId: number) {
    try {
      const calls = await listToolCalls(sessionId);
      for (const tc of calls) {
        if (
          tc.status === "pending_approval" &&
          !messages.value.some((m) => m.tool_call?.id === tc.id)
        ) {
          messages.value.push({
            id: -1000000 - tc.id,
            session_id: sessionId,
            role: "assistant",
            content: "",
            created_at: tc.created_at,
            tool_call: tc,
            clientKey: `tool-${tc.id}`,
          });
          pendingToolText.value.set(tc.id, "");
        }
      }
    } catch {
      // 工具调用加载失败不影响会话查看
    }
    try {
      const approvals = await listPendingAgentApprovals(sessionId);
      for (const approval of approvals) {
        if (
          !messages.value.some((message) => message.agent_approval?.id === approval.id)
        ) {
          messages.value.push({
            id: -Date.now() - messages.value.length,
            session_id: sessionId,
            role: "assistant",
            content: "",
            created_at: approval.created_at,
            agent_approval: approval,
            runId: approval.run_id,
            clientKey: `agent-approval-${approval.id}`,
          });
        }
      }
    } catch {
      // Agent Runtime is default-off; a hidden approval API must not break chat loading.
    }
    // B1：会话重载时对存在审批的 run 一并拉取已脱敏的执行结果（Files/Diff 事实源）。
    for (const message of messages.value) {
      if (message.agent_approval?.run_id) {
        loadRunExecutions(message.agent_approval.run_id);
      }
    }
  }

  async function newSession() {
    if (streaming.value) return;
    try {
      const s = await createSession();
      sessions.value.unshift(s);
      await selectSession(s.id);
    } catch (e) {
      notify.error("新建会话失败", String(e));
    }
  }

  function sendMessage(text: string) {
    if (!currentSession.value || streaming.value || hasPendingTool.value) return;
    const sid = currentSession.value.id;
    const now = new Date().toISOString();
    const kb = knowledgeBase.value;

    messages.value.push({
      id: -Date.now(),
      session_id: sid,
      role: "user",
      content: text,
      created_at: now,
      clientKey: nextChatKey("user"),
    });
    streaming.value = true;
    planningCancelled.value = false;
    const mySeq = ++planSeq;

    if (!useLegacyToolPlanner.value) {
      streamAssistantReply(sid, text, kb);
      return;
    }

    // Legacy compatibility only: Agent Runtime performs its own planning in /chat/stream.
    planTools(sid, text)
      .then((res) => {
        // 被用户停止或被新消息取代：放弃本次 plan 结果
        if (planningCancelled.value || mySeq !== planSeq) {
          if (mySeq === planSeq) streaming.value = false;
          return;
        }
        const tc = res?.tool_call ?? null;
        if (tc) {
          messages.value.push({
            id: -Date.now() - 1,
            session_id: sid,
            role: "assistant",
            content: "",
            created_at: new Date().toISOString(),
            tool_call: tc,
            clientKey: `tool-${tc.id}`,
          });
          pendingToolText.value.set(tc.id, text);
          streaming.value = false;
          return;
        }
        // 无工具：普通流式回复
        streamAssistantReply(sid, text, kb);
      })
      .catch(() => {
        if (planningCancelled.value || mySeq !== planSeq) {
          if (mySeq === planSeq) streaming.value = false;
          return;
        }
        streamAssistantReply(sid, text, kb);
      });
  }

  /** 流式助手回复（无工具，或工具执行后带 tool_result 总结）。 */
  function streamAssistantReply(
    sid: number,
    text: string,
    kb: boolean,
    toolResult?: { tool_name: string; output: Record<string, unknown> }
  ) {
    const streamId = ++streamSeq;
    const assistantMessage: AgentWorkspaceMessage = {
      id: -2,
      session_id: sid,
      role: "assistant",
      content: "",
      created_at: new Date().toISOString(),
      clientKey: nextChatKey("assistant"),
    };
    messages.value.push(assistantMessage);
    let responseMessage: AgentWorkspaceMessage | null = assistantMessage;
    let activeRunId: string | undefined;
    streaming.value = true;

    const ensureResponseMessage = (): AgentWorkspaceMessage => {
      if (responseMessage) return responseMessage;
      responseMessage = {
        id: -Date.now(),
        session_id: sid,
        role: "assistant",
        content: "",
        created_at: new Date().toISOString(),
        clientKey: nextChatKey("assistant"),
        runId: activeRunId,
      };
      messages.value.push(responseMessage);
      return responseMessage;
    };

    const isCurrentStream = () =>
      streamId === streamSeq && currentSessionId.value === sid;

    controller = streamChat(
      sid,
      text,
      kb,
      (e) => {
        if (!isCurrentStream()) return;
        if (e.type === "run" && e.run_id) {
          activeRunId = e.run_id;
          if (responseMessage) responseMessage.runId = e.run_id;
        } else if (e.type === "approval" && e.approval) {
          activeRunId = e.approval.run_id;
          const approvalMessage = ensureResponseMessage();
          approvalMessage.content = "";
          approvalMessage.runId = e.approval.run_id;
          approvalMessage.agent_approval = e.approval;
          approvalMessage.clientKey = `agent-approval-${e.approval.id}`;
          responseMessage = null;
        } else if (e.type === "token" && e.content) {
          ensureResponseMessage().content += e.content;
        } else if (e.type === "done") {
          const completedMessage = ensureResponseMessage();
          if (e.run_id) {
            loadRunExecutions(e.run_id);
            for (const message of messages.value) {
              if (
                message.agent_approval?.run_id === e.run_id &&
                message.agent_approval.status === "approved"
              ) {
                message.agent_approval = {
                  ...message.agent_approval,
                  status: "consumed",
                };
              }
            }
          }
          if (e.run_id) completedMessage.runId = e.run_id;
          if (e.message_id) completedMessage.id = e.message_id;
          if (e.content) completedMessage.content = e.content;
          if (e.sources) completedMessage.sources = e.sources;
          if (e.memories) completedMessage.memories = e.memories;
        } else if (e.type === "title" && e.title) {
          const s = sessions.value.find((x) => x.id === sid);
          if (s) s.title = e.title;
        } else if (e.type === "error" && e.message) {
          ensureResponseMessage().content += `\n\n[错误：${e.message}]`;
        }
      },
      (err) => {
        if (!isCurrentStream()) return;
        ensureResponseMessage().content += `\n\n[连接错误：${err}]`;
        streaming.value = false;
        controller = null;
      },
      () => {
        if (!isCurrentStream()) return;
        streaming.value = false;
        controller = null;
      },
      toolResult
    );
  }

  /** Agent run 审批后的续流（approve 且无活动流时）。 */
  function continueAgentReply(runId: string, sid: number) {
    const streamId = ++streamSeq;
    const assistantMessage: AgentWorkspaceMessage = {
      id: -Date.now(),
      session_id: sid,
      role: "assistant",
      content: "",
      created_at: new Date().toISOString(),
      clientKey: nextChatKey("assistant"),
      runId,
    };
    messages.value.push(assistantMessage);
    streaming.value = true;
    const isCurrentStream = () =>
      streamId === streamSeq && currentSessionId.value === sid;

    controller = streamAgentRunContinuation(
      runId,
      (event) => {
        if (!isCurrentStream()) return;
        if (event.type === "token" && event.content) {
          assistantMessage.content += event.content;
        } else if (event.type === "done") {
          loadRunExecutions(runId);
          if (event.message_id) assistantMessage.id = event.message_id;
          if (event.content) assistantMessage.content = event.content;
          if (event.sources) assistantMessage.sources = event.sources;
          if (event.memories) assistantMessage.memories = event.memories;
          for (const message of messages.value) {
            if (message.agent_approval?.run_id === runId) {
              message.agent_approval = {
                ...message.agent_approval,
                status: "consumed",
              };
            }
          }
        } else if (event.type === "error" && event.message) {
          assistantMessage.content += `\n\n[错误：${event.message}]`;
        }
      },
      (error) => {
        if (!isCurrentStream()) return;
        assistantMessage.content += `\n\n[连接错误：${error}]`;
        streaming.value = false;
        controller = null;
      },
      () => {
        if (!isCurrentStream()) return;
        streaming.value = false;
        controller = null;
      }
    );
  }

  /** 从当前对话生成候选记忆（落库 draft，待用户在记忆页确认）。 */
  async function onGenCandidates() {
    if (!currentSession.value) return;
    const sid = currentSession.value.id;
    try {
      const list = await candidateMemories({
        source_type: "chat_session",
        source_id: sid,
      });
      notify.success("候选记忆已生成", `${list.length} 条 draft，请在记忆页确认`);
    } catch (e) {
      notify.error("生成候选记忆失败", String(e));
    }
  }

  /** 把一条聊天消息保存到收件箱（保留 chat_message 来源引用）。 */
  async function onSaveMessageToInbox(messageId: number, content: string) {
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
    } catch (e) {
      notify.error("保存到收件箱失败", String(e));
    }
  }

  /** 批准工具调用：执行后流式总结结果。 */
  async function onApproveToolCall(id: number) {
    if (!currentSession.value) return;
    const sid = currentSession.value.id;
    const msgIdx = messages.value.findIndex((m) => m.tool_call?.id === id);
    if (msgIdx < 0) return;
    messages.value[msgIdx].tool_call = {
      ...messages.value[msgIdx].tool_call!,
      status: "running",
    };
    streaming.value = true;
    try {
      const updated = await approveToolCall(id);
      messages.value[msgIdx].tool_call = updated;
      if (updated.status === "succeeded" && updated.output_json) {
        const text =
          pendingToolText.value.get(id) || "请基于以下工具结果回答。";
        pendingToolText.value.delete(id);
        streamAssistantReply(sid, text, knowledgeBase.value, {
          tool_name: updated.tool_name,
          output: updated.output_json,
        });
      } else {
        streaming.value = false;
        pendingToolText.value.delete(id);
      }
    } catch (e) {
      streaming.value = false;
      pendingToolText.value.delete(id);
      messages.value[msgIdx].tool_call = {
        ...messages.value[msgIdx].tool_call!,
        status: "failed",
        error_message: String(e),
      };
    }
  }

  /** 拒绝工具调用：不执行，状态写回卡片。 */
  async function onRejectToolCall(id: number) {
    const msgIdx = messages.value.findIndex((m) => m.tool_call?.id === id);
    if (msgIdx < 0) return;
    try {
      const updated = await rejectToolCall(id);
      messages.value[msgIdx].tool_call = updated;
    } catch {
      messages.value[msgIdx].tool_call = {
        ...messages.value[msgIdx].tool_call!,
        status: "rejected",
      };
    }
    pendingToolText.value.delete(id);
  }

  async function onApproveAgentRunTool(runId: string, approvalId: string) {
    if (!currentSession.value) return;
    const sessionId = currentSession.value.id;
    const hasLiveStream = controller !== null && streaming.value;
    const message = messages.value.find(
      (item) =>
        item.agent_approval?.id === approvalId && item.agent_approval.run_id === runId
    );
    if (!message?.agent_approval) return;
    message.agent_approval = { ...message.agent_approval, status: "approved" };
    try {
      await approveAgentRunTool(runId, approvalId);
      if (!hasLiveStream) continueAgentReply(runId, sessionId);
    } catch (error) {
      message.agent_approval = { ...message.agent_approval, status: "pending" };
      notify.error("Agent 工具审批失败", String(error));
    }
  }

  async function onRejectAgentRunTool(runId: string, approvalId: string) {
    const message = messages.value.find(
      (item) =>
        item.agent_approval?.id === approvalId && item.agent_approval.run_id === runId
    );
    if (!message?.agent_approval) return;
    try {
      await rejectAgentRunTool(runId, approvalId);
      message.agent_approval = { ...message.agent_approval, status: "rejected" };
    } catch (error) {
      notify.error("Agent 工具拒绝失败", String(error));
    }
  }

  function stopGenerate() {
    planningCancelled.value = true;
    streamSeq += 1;
    const activeController = controller;
    controller = null;
    activeController?.abort();
    streaming.value = false;
  }

  /** ?workspace-preview=running 开发夹具注入（浏览器 boot 分支）。 */
  function applyWorkspacePreview(preview: LegacyWorkspacePreview) {
    sessions.value = [preview.session];
    currentSessionId.value = preview.session.id;
    messages.value = preview.messages;
    streaming.value = true;
  }

  /** 卸载清理：轮询/序号/在途流统一失效（App.vue onBeforeUnmount 调用）。 */
  function dispose() {
    contextSeq += 1;
    if (activityTimer !== null) {
      window.clearInterval(activityTimer);
      activityTimer = null;
    }
    planningCancelled.value = true;
    streamSeq += 1;
    controller?.abort();
    controller = null;
  }

  return {
    sessions,
    currentSessionId,
    messages,
    streaming,
    knowledgeBase,
    runExecutions,
    sessionActivities,
    trustedPaths,
    useLegacyToolPlanner,
    runtimeCapabilities,
    hasPendingTool,
    taskState,
    currentSession,
    initializeLegacyWorkspace,
    loadSessions,
    selectSession,
    newSession,
    sendMessage,
    stopGenerate,
    onApproveToolCall,
    onRejectToolCall,
    onApproveAgentRunTool,
    onRejectAgentRunTool,
    onGenCandidates,
    onSaveMessageToInbox,
    applyWorkspacePreview,
    dispose,
  };
}
