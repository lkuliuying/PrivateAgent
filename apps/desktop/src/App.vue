<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import WorkspaceShell from "./components/WorkspaceShell.vue";
import NavRail from "./components/NavRail.vue";
import SessionList from "./components/SessionList.vue";
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
  planTools,
  approveToolCall,
  rejectToolCall,
  listToolCalls,
  cmdStartSidecar,
  cmdConfigExists,
  cmdRelaunchApp,
  isDesktopRuntime,
  candidateMemories,
  createInbox,
  getApiInfo,
} from "./api";
import type { Message, MemorySource, Session, Source, ToolCall, View } from "./types";

type ChatMessage = Message & {
  sources?: Source[];
  memories?: MemorySource[];
  tool_call?: ToolCall;
};

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
const messages = ref<ChatMessage[]>([]);
const view = ref<View>("today");
const streaming = ref(false);
const knowledgeBase = ref(false);
// 当前在检查器中展示的引用片段 id（点击来源后设置）
const currentChunkId = ref<number | null>(null);
// 右侧检查器折叠状态：宽屏默认展开，窄屏默认收起。
// rail(60)+list(280)+inspector(340)=680；低于 INSPECTOR_MIN_W 展开会挤压主工作区。
const INSPECTOR_MIN_W = 1100;
const viewportWidth = ref(
  typeof window !== "undefined" ? window.innerWidth : 1280
);
const inspectorOpen = ref(
  typeof window !== "undefined" && window.innerWidth >= 1280
);
// 仅在 chat 视图且视口足够宽时允许切换检查器，避免窄屏挤压主工作区
const inspectorToggleable = computed(
  () => view.value === "chat" && viewportWidth.value >= INSPECTOR_MIN_W
);
let controller: AbortController | null = null;
// plan 请求序号：每次 sendMessage 自增，旧 plan 解析回来时若序号不匹配则放弃，
// 避免「停止 planning 后立即发新消息」时旧 plan 结果交错插入。
let planSeq = 0;
// plan-then-reply：toolCallId -> 原始用户消息（批准后用于流式总结，按 id 索引避免单槽覆盖）
const pendingToolText = ref<Map<number, string>>(new Map());
// 用户在 planning 阶段点停止时置 true，阻止 plan 完成后继续回复
const planningCancelled = ref(false);
// 是否有未决工具调用（待审批时阻止发送新消息，避免交错持久化/单槽覆盖）
const hasPendingTool = computed(
  () => messages.value.some((m) => m.tool_call?.status === "pending_approval")
);

const currentSession = computed(
  () => sessions.value.find((s) => s.id === currentSessionId.value) ?? null
);

// 顶栏标题
const pageTitle = computed(() => {
  switch (view.value) {
    case "chat":
      return currentSession.value?.title || "私人助手";
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
  controller?.abort();
  controller = null;
});

// ============ 启动引导 ============

async function boot() {
  // 浏览器开发：直接用默认端口。
  if (!isDesktopRuntime()) {
    setApiBaseDefault();
    bootState.value = "done";
    await loadSessions();
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
    await loadSessions();
    return;
  }

  // 打包模式：sidecar 已 spawn。
  if (res.ok && res.port) {
    bootState.value = "starting";
    setApiBase(res.port);
    const ready = await pollApiReady(90);
    if (ready) {
      bootState.value = "done";
      await loadSessions();
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
  if (res && res.ok && res.port) {
    setApiBase(res.port);
    const ready = await pollApiReady(90);
    if (ready) {
      bootState.value = "done";
      await loadSessions();
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
        });
        // 原始用户消息可能未持久化（仅在 /chat/stream 时持久化），留空由批准时用默认提示
        pendingToolText.value.set(tc.id, "");
      }
    }
  } catch {
    // 工具调用加载失败不影响会话查看
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

  messages.value.push({
    id: -Date.now(),
    session_id: sid,
    role: "user",
    content: text,
    created_at: now,
  });
  streaming.value = true;
  planningCancelled.value = false;
  const mySeq = ++planSeq;

  // plan-then-reply：先判断是否需工具
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
        });
        pendingToolText.value.set(tc.id, text);
        streaming.value = false;
        return;
      }
      // 无工具：普通流式回复
      streamAssistantReply(sid, text, knowledgeBase.value);
    })
    .catch(() => {
      if (planningCancelled.value || mySeq !== planSeq) {
        if (mySeq === planSeq) streaming.value = false;
        return;
      }
      // plan 失败，降级普通回复
      streamAssistantReply(sid, text, knowledgeBase.value);
    });
}

/** 流式助手回复（无工具，或工具执行后带 tool_result 总结）。 */
function streamAssistantReply(
  sid: number,
  text: string,
  kb: boolean,
  toolResult?: { tool_name: string; output: Record<string, unknown> }
) {
  messages.value.push({
    id: -2,
    session_id: sid,
    role: "assistant",
    content: "",
    created_at: new Date().toISOString(),
  });
  const aiIdx = messages.value.length - 1;
  streaming.value = true;

  controller = streamChat(
    sid,
    text,
    kb,
    (e) => {
      if (e.type === "token" && e.content) {
        messages.value[aiIdx].content += e.content;
      } else if (e.type === "done") {
        if (e.message_id) messages.value[aiIdx].id = e.message_id;
        if (e.content) messages.value[aiIdx].content = e.content;
        if (e.sources) messages.value[aiIdx].sources = e.sources;
        if (e.memories) messages.value[aiIdx].memories = e.memories;
      } else if (e.type === "title" && e.title && currentSession.value) {
        currentSession.value.title = e.title;
        const s = sessions.value.find((x) => x.id === sid);
        if (s) s.title = e.title;
      } else if (e.type === "error" && e.message) {
        messages.value[aiIdx].content += `\n\n[错误：${e.message}]`;
      }
    },
    (err) => {
      messages.value[aiIdx].content += `\n\n[连接错误：${err}]`;
      streaming.value = false;
    },
    () => {
      streaming.value = false;
    },
    toolResult
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

function stopGenerate() {
  // 标记 planning 取消，阻止 plan 完成后继续回复（plan 阶段 controller 尚未赋值）
  planningCancelled.value = true;
  controller?.abort();
  controller = null;
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
    :title="pageTitle"
    :show-dev-tag="bootState === 'dev'"
    :show-list="view === 'chat' || view === 'today'"
    :inspector-open="view === 'chat' && inspectorOpen"
    :inspector-toggleable="inspectorToggleable"
    :show-topbar="view === 'chat'"
    @toggle-inspector="inspectorOpen = !inspectorOpen"
  >
    <template #rail>
      <NavRail :active="view" @navigate="onNavigate" />
    </template>

    <template #list>
      <SessionList
        :sessions="sessions"
        :current-id="currentSessionId"
        @select="selectSession"
        @new="newSession"
      />
    </template>

    <!-- 主工作区 -->
    <SettingsView v-if="view === 'settings'" @reconfigure="reconfigure" />
    <DiagnosticsView v-else-if="view === 'diagnostics'" />
    <ExtensionRegistryPanel v-else-if="view === 'extensions'" />
    <IntegrationImportPanel v-else-if="view === 'integrations'" />
    <BackupUpgradePanel v-else-if="view === 'backup'" />
    <TodayView v-else-if="view === 'today'" @navigate="onNavigate" />
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
      @select-chunk="currentChunkId = $event"
      @gen-candidates="onGenCandidates"
      @save-inbox="onSaveMessageToInbox"
    />
    <div v-else class="welcome">
      <p class="welcome-title">👋 欢迎使用私人助手</p>
      <p class="hint">点击左侧「新建」开始对话</p>
    </div>

    <template #inspector>
      <InspectorPanel
        :session="currentSession"
        :message-count="messages.length"
        :chunk-id="currentChunkId"
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
  color: var(--color-fg-subtle);
}
.welcome-title {
  margin: var(--space-1) 0;
  font-size: var(--text-lg);
}
.welcome .hint {
  font-size: var(--text-sm);
  color: var(--color-fg-faint);
}
</style>
