<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from "vue";
import WorkspaceShell from "./components/WorkspaceShell.vue";
import NavRail from "./components/NavRail.vue";
import InspectorPanel from "./components/InspectorPanel.vue";
import StatusBar from "./components/StatusBar.vue";
import TaskWorkspace from "./components/TaskWorkspace.vue";
import ChatView from "./components/ChatView.vue";
import KnowledgeView from "./components/KnowledgeView.vue";
import ProjectWorkspace from "./components/ProjectWorkspace.vue";
import LearningWorkspace from "./components/LearningWorkspace.vue";
import MemoryWorkspace from "./components/MemoryWorkspace.vue";
import TodayView from "./components/TodayView.vue";
import SettingsView from "./components/SettingsView.vue";
import DiagnosticsView from "./components/DiagnosticsView.vue";
import ExtensionRegistryPanel from "./components/ExtensionRegistryPanel.vue";
import IntegrationImportPanel from "./components/IntegrationImportPanel.vue";
import BackupUpgradePanel from "./components/BackupUpgradePanel.vue";
import ConfigWizard from "./components/ConfigWizard.vue";
import ToastHost from "./components/ToastHost.vue";
import ConfirmDialog from "./components/ConfirmDialog.vue";
import NotificationCenter from "./components/NotificationCenter.vue";
import CommandPalette from "./components/CommandPalette.vue";
import GlobalSearch from "./components/GlobalSearch.vue";
import { useNotifications } from "./stores/notifications";
import {
  createSession,
  getMessages,
  listSessions,
  setApiBase,
  setApiBaseDefault,
  streamChat,
  streamAgentRunContinuation,
  planTools,
  approveToolCall,
  approveAgentRunTool,
  rejectToolCall,
  rejectAgentRunTool,
  listToolCalls,
  listPendingAgentApprovals,
  cmdStartSidecar,
  cmdConfigExists,
  cmdRelaunchApp,
  isDesktopRuntime,
  candidateMemories,
  createInbox,
  getApiInfo,
  getRuntimeCapabilities,
  shouldUseLegacyToolPlanner,
} from "./api";
import type { Session, View } from "./types";
import { mountPageAnimations } from "./animations/page";
import type { AnimationHandle } from "./animations/utils";
import {
  deriveTaskState,
  type AgentWorkspaceMessage,
} from "./models/agentWorkspace";
import { createAgentWorkspacePreview } from "./dev/agentWorkspacePreview";

// 统一通知/确认/toast store（第七阶段 M4 基建）
const notify = useNotifications();
// 命令面板开关（Ctrl/Cmd+K）；CommandPalette 组件在 M2 接入。
const commandPaletteOpen = ref(false);
// 全局搜索开关（命令面板的「全局搜索」命令触发）
const searchOpen = ref(false);

// bootState：checking（检测中）/ wizard（配置向导）/ starting（启动后端中）
//   / done（就绪）/ dev（开发模式手动后端）/ error（失败）
type BootState = "checking" | "wizard" | "starting" | "done" | "dev" | "error";
const bootState = ref<BootState>("checking");
const wizardMode = ref<"first" | "reconfigure">("first");
const bootError = ref("");

const sessions = ref<Session[]>([]);
const currentSessionId = ref<number | null>(null);
const messages = ref<AgentWorkspaceMessage[]>([]);
const view = ref<View>("chat");
const streaming = ref(false);
// Capability discovery is backward-compatible: unknown/old backends retain the legacy planner.
const useLegacyToolPlanner = ref(true);
const knowledgeBase = ref(false);
const railCollapsed = ref(false);
const previewMode =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("workspace-preview") === "running";
const workspacePreview = previewMode ? createAgentWorkspacePreview() : null;
// 当前在检查器中展示的引用片段 id（点击来源后设置）
const currentChunkId = ref<number | null>(null);
// 右侧检查器折叠状态：宽屏默认展开，窄屏默认收起。
// rail(60)+list(280)+inspector(340)=680；低于 INSPECTOR_MIN_W 展开会挤压主工作区。
const INSPECTOR_MIN_W = 1320;
const viewportWidth = ref(
  typeof window !== "undefined" ? window.innerWidth : 1280
);
const inspectorOpen = ref(
  typeof window !== "undefined" && window.innerWidth >= INSPECTOR_MIN_W
);
// 仅在 chat 视图且视口足够宽时允许切换检查器，避免窄屏挤压主工作区
const inspectorToggleable = computed(
  () => view.value === "chat" && viewportWidth.value >= INSPECTOR_MIN_W
);
let controller: AbortController | null = null;
let pageAnimations: AnimationHandle | null = null;
// 流请求序号：停止后即使旧 reader/onClose 延迟回调，也不能再改写当前会话或新流状态。
let streamSeq = 0;
let chatMessageSeq = 0;
function nextChatKey(kind: "user" | "assistant" | "tool"): string {
  chatMessageSeq += 1;
  return `${kind}-${Date.now()}-${chatMessageSeq}`;
}
// plan 请求序号：每次 sendMessage 自增，旧 plan 解析回来时若序号不匹配则放弃，
// 避免「停止 planning 后立即发新消息」时旧 plan 结果交错插入。
let planSeq = 0;
// plan-then-reply：toolCallId -> 原始用户消息（批准后用于流式总结，按 id 索引避免单槽覆盖）
const pendingToolText = ref<Map<number, string>>(new Map());
// 用户在 planning 阶段点停止时置 true，阻止 plan 完成后继续回复
const planningCancelled = ref(false);
// 是否有未决工具调用（待审批时阻止发送新消息，避免交错持久化/单槽覆盖）
const hasPendingTool = computed(
  () => messages.value.some(
    (m) =>
      m.tool_call?.status === "pending_approval" ||
      m.agent_approval?.status === "pending"
  )
);
const taskState = computed(() => deriveTaskState(messages.value, streaming.value));

const currentSession = computed(
  () => sessions.value.find((s) => s.id === currentSessionId.value) ?? null
);

// 顶栏标题
const pageTitle = computed(() => {
  switch (view.value) {
    case "chat":
      return currentSession.value?.title || "新任务";
    case "today":
      return "今日";
    case "kb":
      return "知识库";
    case "projects":
      return "项目";
    case "learning":
      return "学习";
    case "tasks":
      return "任务";
    case "memory":
      return "记忆";
    case "settings":
      return "设置 / 状态";
    case "diagnostics":
      return "诊断中心";
    case "extensions":
      return "扩展注册表";
    case "integrations":
      return "本地集成";
    case "backup":
      return "备份恢复";
  }
});

function onResize() {
  viewportWidth.value = window.innerWidth;
  // 缩窄到阈值以下时强制收起检查器，防止挤压主工作区
  if (window.innerWidth < INSPECTOR_MIN_W) inspectorOpen.value = false;
}

/** 全局快捷键：Ctrl/Cmd+K 打开命令面板（M2 接入 CommandPalette 组件）。 */
function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    commandPaletteOpen.value = !commandPaletteOpen.value;
  }
}

onMounted(() => {
  window.addEventListener("resize", onResize);
  window.addEventListener("keydown", onKeydown);
  boot();
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", onResize);
  window.removeEventListener("keydown", onKeydown);
  planningCancelled.value = true;
  streamSeq += 1;
  controller?.abort();
  controller = null;
  pageAnimations?.destroy();
  pageAnimations = null;
});

watch(
  bootState,
  async (state) => {
    if (state !== "done" && state !== "dev") {
      pageAnimations?.destroy();
      pageAnimations = null;
      return;
    }
    await nextTick();
    if (state !== bootState.value || pageAnimations) return;
    const root = document.querySelector<HTMLElement>("[data-animation-root]");
    if (root) pageAnimations = mountPageAnimations(root);
  },
  { flush: "post" }
);

// ============ 启动引导 ============

async function boot() {
  // 浏览器开发：直接用默认端口。
  if (!isDesktopRuntime()) {
    setApiBaseDefault();
    bootState.value = "done";
    if (previewMode) {
      const preview = workspacePreview!;
      sessions.value = [preview.session];
      currentSessionId.value = preview.session.id;
      messages.value = preview.messages;
      streaming.value = true;
      return;
    }
    await initializeConnectedWorkspace();
    return;
  }

  bootState.value = "checking";
  let res;
  try {
    res = await cmdStartSidecar();
  } catch {
    bootError.value = "无法与桌面壳通信";
    bootState.value = "error";
    return;
  }

  // dev 模式：sidecar 返回 dev_mode，回退手动后端 127.0.0.1:8000。
  if (res.dev_mode) {
    setApiBaseDefault();
    bootState.value = "dev";
    await initializeConnectedWorkspace();
    return;
  }

  // 打包模式：sidecar 已 spawn。
  if (res.ok && res.port && res.token) {
    bootState.value = "starting";
    setApiBase(res.port, res.token);
    const ready = await pollApiReady(90);
    if (ready) {
      bootState.value = "done";
      await initializeConnectedWorkspace();
    } else {
      bootError.value = "后端 API 启动超时，请检查本地后端进程或重试。";
      bootState.value = "error";
    }
    return;
  }

  // ok:false —— 通常尚未配置连接；也可能是 spawn 失败。
  const exists = await cmdConfigExists().catch(() => false);
  if (!exists) {
    wizardMode.value = "first";
    bootState.value = "wizard";
  } else {
    bootError.value = res.error || "后端启动失败";
    bootState.value = "error";
  }
}

/** 轮询轻量 API 根路径直到后端 HTTP 服务可用。
 * 依赖健康（MySQL/Ollama/Chroma）交给状态页展示，不阻塞进入主界面。 */
async function pollApiReady(seconds: number): Promise<boolean> {
  for (let i = 0; i < seconds * 5; i++) {
    try {
      await getApiInfo();
      return true;
    } catch {
      // HTTP 服务尚未绑定
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

/** 向导完成（配置已写入）后：首次运行→启动 sidecar；重新配置→重启应用。 */
async function onWizardDone() {
  if (wizardMode.value === "reconfigure") {
    // 新配置需重启应用才能让 sidecar 重新加载 .env。
    try {
      await cmdRelaunchApp();
    } catch {
      bootError.value = "重启失败，请手动重启应用";
      bootState.value = "error";
    }
    return;
  }
  // 首次运行：启动 sidecar。
  bootState.value = "starting";
  const res = await cmdStartSidecar().catch(() => null);
  if (res && res.ok && res.port && res.token) {
    setApiBase(res.port, res.token);
    const ready = await pollApiReady(90);
    if (ready) {
      bootState.value = "done";
      await initializeConnectedWorkspace();
    } else {
      bootError.value = "后端 API 启动超时，请检查本地后端进程或重试。";
      bootState.value = "error";
    }
  } else {
    bootError.value = res?.error || "后端启动失败";
    bootState.value = "error";
  }
}

/** 从设置页触发重新配置。 */
function reconfigure() {
  wizardMode.value = "reconfigure";
  bootState.value = "wizard";
}

async function retryBoot() {
  await boot();
}

// ============ 导航 ============

function onNavigate(v: View) {
  view.value = v;
}

// 命令面板 / 全局搜索 跳转
function onPaletteNavigate(v: View) {
  commandPaletteOpen.value = false;
  onNavigate(v);
}
function onPaletteOpenSearch() {
  commandPaletteOpen.value = false;
  searchOpen.value = true;
}
function onSearchNavigate(v: View) {
  searchOpen.value = false;
  onNavigate(v);
}

// ============ 会话 / 对话 ============

async function initializeConnectedWorkspace() {
  try {
    const capabilities = await getRuntimeCapabilities();
    useLegacyToolPlanner.value = shouldUseLegacyToolPlanner(capabilities);
  } catch {
    // A pre-capabilities backend still owns planning through /tools/plan.
    useLegacyToolPlanner.value = shouldUseLegacyToolPlanner(null);
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
  if (switchToChat) view.value = "chat";
  try {
    messages.value = await getMessages(id);
  } catch {
    messages.value = [];
  }
  // 重水合未决工具调用卡片（重载/切换会话后仍可审批，避免 pending_approval 行孤立）
  await rehydrateToolCalls(id);
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
        // 原始用户消息可能未持久化（仅在 /chat/stream 时持久化），留空由批准时用默认提示
        pendingToolText.value.set(tc.id, "");
      }
    }
  } catch {
    // 工具调用加载失败不影响会话查看
  }
  try {
    const approvals = await listPendingAgentApprovals(sessionId);
    for (const approval of approvals) {
      if (!messages.value.some((message) => message.agent_approval?.id === approval.id)) {
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

type TodayComposerMode = "chat" | "knowledge" | "plan" | "code";

async function onTodaySubmit(text: string, mode: TodayComposerMode) {
  const value = text.trim();
  if (!value || streaming.value || hasPendingTool.value) return;

  if (!currentSession.value) {
    await newSession();
  }
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
        // 插入工具卡片，等待用户审批
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
      // plan 失败，降级普通回复
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
          for (const message of messages.value) {
            if (
              message.agent_approval?.run_id === e.run_id &&
              message.agent_approval.status === "approved"
            ) {
              message.agent_approval = { ...message.agent_approval, status: "consumed" };
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

/** 从当前对话生成候选记忆（落库 draft，待用户在记忆页确认）。 */
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
        if (event.message_id) assistantMessage.id = event.message_id;
        if (event.content) assistantMessage.content = event.content;
        for (const message of messages.value) {
          if (message.agent_approval?.run_id === runId) {
            message.agent_approval = { ...message.agent_approval, status: "consumed" };
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
  // 乐观更新为执行中
  messages.value[msgIdx].tool_call = {
    ...messages.value[msgIdx].tool_call!,
    status: "running",
  };
  streaming.value = true;
  try {
    const updated = await approveToolCall(id);
    messages.value[msgIdx].tool_call = updated;
    if (updated.status === "succeeded" && updated.output_json) {
      // 重水合的卡片可能无原始用户消息，用默认提示
      const text =
        pendingToolText.value.get(id) || "请基于以下工具结果回答。";
      pendingToolText.value.delete(id);
      streamAssistantReply(sid, text, knowledgeBase.value, {
        tool_name: updated.tool_name,
        output: updated.output_json,
      });
    } else {
      // failed
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
    (item) => item.agent_approval?.id === approvalId && item.agent_approval.run_id === runId
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
    (item) => item.agent_approval?.id === approvalId && item.agent_approval.run_id === runId
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
  // 标记 planning 取消，阻止 plan 完成后继续回复（plan 阶段 controller 尚未赋值）
  planningCancelled.value = true;
  streamSeq += 1;
  const activeController = controller;
  controller = null;
  activeController?.abort();
  streaming.value = false;
}
</script>

<template>
  <!-- 启动引导覆盖层 -->
  <div v-if="bootState !== 'done' && bootState !== 'dev'" class="boot">
    <div v-if="bootState === 'checking' || bootState === 'starting'" class="boot-card">
      <div class="spinner" />
      <p>{{ bootState === "checking" ? "正在检测环境…" : "正在启动本地后端…" }}</p>
      <p class="hint">首次启动可能需要数秒</p>
    </div>

    <ConfigWizard
      v-else-if="bootState === 'wizard'"
      :mode="wizardMode"
      @done="onWizardDone"
    />

    <div v-else class="boot-card">
      <p class="boot-err">⚠ 启动失败</p>
      <p class="hint">{{ bootError }}</p>
      <button class="pa-btn pa-btn--primary" @click="retryBoot">重试</button>
      <button
        v-if="isDesktopRuntime()"
        class="pa-btn pa-btn--ghost"
        @click="reconfigure"
      >
        重新配置连接
      </button>
    </div>
  </div>

  <!-- 主应用 · 四区工作台 -->
  <WorkspaceShell
    v-else
    data-animation-root
    :title="pageTitle"
    :task-state="taskState"
    :show-dev-tag="bootState === 'dev' || previewMode"
    :inspector-open="view === 'chat' && inspectorOpen"
    :inspector-toggleable="inspectorToggleable"
    :show-topbar="view === 'chat'"
    :show-statusbar="view !== 'today'"
    :rail-collapsed="railCollapsed"
    @toggle-inspector="inspectorOpen = !inspectorOpen"
  >
    <template #rail>
      <NavRail
        :active="view"
        :sessions="sessions"
        :current-id="currentSessionId"
        :collapsed="railCollapsed"
        @navigate="onNavigate"
        @open-command="commandPaletteOpen = true"
        @new-session="newSession"
        @select-session="selectSession"
        @toggle-collapse="railCollapsed = !railCollapsed"
      />
    </template>

    <!-- 主工作区 -->
    <SettingsView v-if="view === 'settings'" @reconfigure="reconfigure" />
    <DiagnosticsView v-else-if="view === 'diagnostics'" />
    <ExtensionRegistryPanel v-else-if="view === 'extensions'" />
    <IntegrationImportPanel v-else-if="view === 'integrations'" />
    <BackupUpgradePanel v-else-if="view === 'backup'" />
    <TodayView
      v-else-if="view === 'today'"
      @navigate="onNavigate"
      @submit="onTodaySubmit"
      @open-command="commandPaletteOpen = true"
    />
    <KnowledgeView v-else-if="view === 'kb'" />
    <ProjectWorkspace v-else-if="view === 'projects'" />
    <LearningWorkspace v-else-if="view === 'learning'" />
    <TaskWorkspace v-else-if="view === 'tasks'" />
    <MemoryWorkspace v-else-if="view === 'memory'" />
    <ChatView
      v-else-if="view === 'chat' && currentSession"
      :messages="messages"
      :streaming="streaming"
      :knowledge-base="knowledgeBase"
      :pending-tool="hasPendingTool"
      @send="sendMessage"
      @stop="stopGenerate"
      @toggle-kb="knowledgeBase = !knowledgeBase"
      @approve="onApproveToolCall"
      @reject="onRejectToolCall"
      @approve-agent="onApproveAgentRunTool"
      @reject-agent="onRejectAgentRunTool"
      @select-chunk="currentChunkId = $event"
      @gen-candidates="onGenCandidates"
      @save-inbox="onSaveMessageToInbox"
    />
    <div v-else class="welcome">
      <span class="welcome-kicker">PRIVATE AGENT WORKSPACE</span>
      <p class="welcome-title">准备好开始一个新任务</p>
      <p class="hint">PrivateAgent 会先建立计划，再清晰展示执行过程、工具调用与结果。</p>
      <button class="pa-btn pa-btn--primary" :disabled="streaming" @click="newSession">
        新建任务
      </button>
    </div>

    <template #inspector>
      <InspectorPanel
        :session="currentSession"
        :message-count="messages.length"
        :chunk-id="currentChunkId"
        :preview-trusted="workspacePreview?.trusted"
        :preview-activities="workspacePreview?.activities"
        @close="inspectorOpen = false"
      />
    </template>

    <template #statusbar>
      <StatusBar :task-label="streaming ? '生成中…' : '空闲'" />
    </template>
  </WorkspaceShell>

  <!-- 第七阶段全局覆盖层：toast / 确认对话框 / 通知中心（Teleport 到 body） -->
  <ToastHost />
  <ConfirmDialog />
  <NotificationCenter />
  <CommandPalette
    v-if="commandPaletteOpen"
    @navigate="onPaletteNavigate"
    @open-search="onPaletteOpenSearch"
    @close="commandPaletteOpen = false"
  />
  <GlobalSearch
    v-if="searchOpen"
    @navigate="onSearchNavigate"
    @close="searchOpen = false"
  />
</template>

<style scoped>
/* 启动引导覆盖层（工作台就绪前显示） */
.boot {
  height: 100vh;
  width: 100vw;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg);
}
.boot-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-10);
}
.boot-card p {
  margin: 0;
}
.boot-card .hint {
  font-size: var(--text-sm);
  color: var(--color-fg-faint);
}
.boot-err {
  color: var(--color-danger-fg);
  font-size: var(--text-lg);
}
.boot-card .pa-btn {
  margin-top: var(--space-3);
}
.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-fg);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: var(--space-2);
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* chat 无会话时的欢迎占位（位于主工作区） */
.welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  color: var(--color-fg-subtle);
  text-align: center;
}
.welcome-title {
  margin: var(--space-2) 0;
  color: var(--color-fg);
  font-size: var(--text-2xl);
  font-weight: var(--font-semibold);
}
.welcome-kicker {
  color: var(--color-accent-soft-fg);
  font-size: 10px;
  font-weight: var(--font-semibold);
  letter-spacing: 0.12em;
}
.welcome .hint {
  max-width: 520px;
  margin: 0 0 var(--space-5);
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
}
</style>
