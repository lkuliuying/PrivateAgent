<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch, shallowRef } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import WorkspaceShell from "./components/WorkspaceShell.vue";
import NavRail from "./components/NavRail.vue";
import InspectorPanel from "./components/InspectorPanel.vue";
import StatusBar from "./components/StatusBar.vue";
import AppShell from "./components/AppShell.vue";
import NavRailV2 from "./components/NavRailV2.vue";
import ContextRail from "./components/ContextRail.vue";
import TaskWorkspace from "./components/TaskWorkspace.vue";
import ChatView from "./components/ChatView.vue";
import KnowledgeView from "./components/KnowledgeView.vue";
import ProjectWorkspace from "./components/ProjectWorkspace.vue";
import LearningWorkspace from "./components/LearningWorkspace.vue";
import MemoryWorkspace from "./components/MemoryWorkspace.vue";
import TodayView from "./components/TodayView.vue";
// v0.8.0 W6-R：今日页六模块迁入左侧栏独立主区（计划 §4.1/§6.6）
import ReminderPanel from "./components/ReminderPanel.vue";
import InboxPanel from "./components/InboxPanel.vue";
import GoalsWorkspace from "./components/GoalsWorkspace.vue";
import BriefingPanel from "./components/BriefingPanel.vue";
import CapturePanel from "./components/CapturePanel.vue";
import PrivacyAuditPanel from "./components/PrivacyAuditPanel.vue";
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
import {
  setApiBase,
  setApiBaseDefault,
  cmdStartSidecar,
  cmdConfigExists,
  cmdRelaunchApp,
  isDesktopRuntime,
  getApiInfo,
  getToday,
  getRuntimeCapabilities,
} from "./api";
import type { View } from "./types";
import { viewLabel } from "./models/viewRegistry";
import { mountPageAnimations } from "./animations/page";
import type { AnimationHandle } from "./animations/utils";
import { createAgentWorkspacePreview } from "./dev/agentWorkspacePreview";
import { useLegacyChatSession } from "./features/agent/useLegacyChatSession";
import {
  isUiV2,
  isCodingWorkbench,
  setCodingUiCapability,
  hasExplicitCodingChoice,
} from "./config/uiFlags";
import {
  recordCodingFallback,
  recordCodingViewEntry,
} from "./features/coding/model/codingUiTelemetry";
import { useViewHistory } from "./composables/useViewHistory";
import { useShortcuts } from "./composables/useShortcuts";
import { AgentWorkspace } from "./features/agent";
import {
  CodingHome,
  CodingSidebar,
  CodingThreadWorkspace,
  useCodingWorkspace,
  type CodingWorkspaceStore,
} from "./features/coding";
import UiLab from "./dev/UiLab.vue";

// UI Lab：仅开发模式且显式开启（?ui-lab=1），生产构建不可达。
const uiLabEnabled =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("ui-lab") === "1";
// ui_v2：alpha.1 默认兼容壳，新壳按开关开启（?ui=v2 / pa_ui_v2=1）。
const uiV2 = isUiV2();
// v0.9.0 H1：Coding UI 默认开启（计划 §3.1）；启动后按 /capabilities 的
// coding_agent_ui_enabled 能力位回退（仅非显式选择时），回退原因本地计数。
const codingUiActive = ref(uiV2 && isCodingWorkbench());
const codingEnabled = computed(() => codingUiActive.value);
const codingStore = useCodingWorkspace();
// ?coding-preview=<key>：首页六状态开发预览（动态 import，生产构建不进入）
const codingPreviewKey = import.meta.env.DEV
  ? new URLSearchParams(window.location.search).get("coding-preview")
  : null;
const codingPreviewStore = shallowRef<CodingWorkspaceStore | null>(null);
// 活动 store 用 shallowRef 持有（预览夹具异步就绪后整体替换，避免深层解包改写 Ref 字段类型）
const codingActiveStoreRef = shallowRef<CodingWorkspaceStore>(codingStore);
if (codingPreviewKey) {
  void import("./features/coding/dev/codingHomePreview").then((preview) => {
    const keys: readonly string[] = preview.CODING_HOME_PREVIEW_KEYS;
    if (keys.includes(codingPreviewKey)) {
      const previewStore = preview.createCodingWorkspacePreviewStore(
        codingPreviewKey as Parameters<typeof preview.createCodingWorkspacePreviewStore>[0]
      );
      codingPreviewStore.value = previewStore;
      codingActiveStoreRef.value = previewStore;
    }
  });
}
const codingThreadSelected = computed(
  () => codingActiveStoreRef.value.selectedThreadId.value !== null
);
// 任务页按 thread 重建（:key）：切换任务即卸载 run 流/定时器（W2 清理语义）
const codingThreadKey = computed(
  () => codingActiveStoreRef.value.selectedThreadId.value ?? "none"
);
// 命令面板开关（Ctrl/Cmd+K）
const commandPaletteOpen = ref(false);
// 全局搜索开关（命令面板的「全局搜索」命令触发）
const searchOpen = ref(false);

// v0.8.0 W6-R：个人工作区待处理徽标（今日快照只读数字；拉取失败不阻断导航）
const personalCounts = ref<Partial<Record<View, number>>>({});
async function loadPersonalCounts(): Promise<void> {
  try {
    const snapshot = await getToday();
    personalCounts.value = {
      reminders: snapshot.summary.due_reminders,
      inbox: snapshot.summary.open_inbox,
      privacy:
        snapshot.maintenance.failed_activities + snapshot.maintenance.orphan_evidence,
    };
  } catch {
    /* 徽标缺失不影响入口可用性 */
  }
}

// bootState：checking（检测中）/ wizard（配置向导）/ starting（启动后端中）
//   / done（就绪）/ dev（开发模式手动后端）/ error（失败）
type BootState = "checking" | "wizard" | "starting" | "done" | "dev" | "error";
const bootState = ref<BootState>("checking");
const wizardMode = ref<"first" | "reconfigure">("first");
const bootError = ref("");
// 加载态延迟：长于 500ms 才展示，避免快速启动闪屏
const bootLoadingVisible = ref(false);
let bootLoadingTimer: number | null = null;
function showBootLoadingAfterDelay() {
  if (bootLoadingTimer !== null) window.clearTimeout(bootLoadingTimer);
  bootLoadingTimer = window.setTimeout(() => {
    bootLoadingVisible.value = true;
  }, 500);
}
function clearBootLoading() {
  if (bootLoadingTimer !== null) window.clearTimeout(bootLoadingTimer);
  bootLoadingTimer = null;
  bootLoadingVisible.value = false;
}

// 导航历史：视图切换/返回/前进/恢复上次视图（本地存储）
const history = useViewHistory("chat");
const view = history.current;

// v0.8.0 W4：旧 chat 编排（会话/消息/流式/planner/审批/上下文轮询/执行结果）
// 整体迁至 features/agent/useLegacyChatSession.ts；App.vue 只保留壳与全局编排。
const legacyChat = useLegacyChatSession({
  navigateToChat: (sessionId) => history.navigate({ view: "chat", sessionId }),
});
const {
  sessions,
  currentSessionId,
  messages,
  streaming,
  knowledgeBase,
  runExecutions,
  sessionActivities,
  trustedPaths,
  hasPendingTool,
  taskState,
  currentSession,
  runtimeCapabilities,
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
} = legacyChat;

const railCollapsed = ref(false);
const previewMode =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("workspace-preview") === "running";
const workspacePreview = previewMode ? createAgentWorkspacePreview() : null;
// 当前在上下文中展示的引用片段 id（点击来源后设置）
const currentChunkId = ref<number | null>(null);
// 右侧上下文栏：W6-R2 改为按需抽屉（不作永久第三列），经 SessionHeader 入口打开
const INSPECTOR_MIN_W = 1320;
// v0.8.0 W1：coding 侧栏 <1280px 进入抽屉模式（W0 冻结 §2.2），rail 槽收为 0 宽
const CODING_RAIL_DRAWER_MAX = 1280;
const viewportWidth = ref(
  typeof window !== "undefined" ? window.innerWidth : 1280
);
// 右侧上下文栏：W6-R3 已移除顶部上下文按钮（上下文由 Runtime 自动装配，
// 底部用量模块反馈）；v2 壳不再提供顶栏切换入口，旧壳保留既有行为。
const inspectorOpen = ref(false);
const inspectorToggleable = computed(() => false);
let pageAnimations: AnimationHandle | null = null;

// 顶栏标题（视图注册表 + 会话标题）
const pageTitle = computed(() => {
  if (view.value === "chat") return currentSession.value?.title || "新任务";
  return viewLabel(view.value);
});

function onResize() {
  viewportWidth.value = window.innerWidth;
  if (window.innerWidth < INSPECTOR_MIN_W) inspectorOpen.value = false;
}

onMounted(() => {
  window.addEventListener("resize", onResize);
  boot();
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", onResize);
  clearBootLoading();
  legacyChat.dispose(); // 在途上下文轮询/流/序号统一失效
  pageAnimations?.destroy();
  pageAnimations = null;
});

// 全局快捷键：Ctrl/Cmd+K 命令面板；Ctrl/Cmd+N 新建任务；Alt+←/→ 视图历史
useShortcuts({
  openCommand: () => (commandPaletteOpen.value = true),
  // v0.8.0 W1：coding 模式下 Ctrl+N 进入首页输入器而非旧会话
  newSession: () => (codingEnabled.value ? onCodingNewTask() : void newSession()),
  goBack: () => {
    const target = history.back();
    if (target?.sessionId && target.view === "chat") {
      void selectSession(target.sessionId, false);
    }
  },
  goForward: () => {
    const target = history.forward();
    if (target?.sessionId && target.view === "chat") {
      void selectSession(target.sessionId, false);
    }
  },
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
      applyWorkspacePreview(workspacePreview!);
      return;
    }
    await initializeConnectedWorkspace();
    return;
  }

  bootState.value = "checking";
  showBootLoadingAfterDelay();
  let res;
  try {
    res = await cmdStartSidecar();
  } catch {
    clearBootLoading();
    bootError.value = "无法与桌面壳通信";
    bootState.value = "error";
    return;
  }

  // dev 模式：sidecar 返回 dev_mode，回退手动后端 127.0.0.1:8000。
  if (res.dev_mode) {
    setApiBaseDefault();
    bootState.value = "dev";
    clearBootLoading();
    await initializeConnectedWorkspace();
    return;
  }

  // 打包模式：sidecar 已 spawn。
  if (res.ok && res.port && res.token) {
    bootState.value = "starting";
    setApiBase(res.port, res.token);
    const ready = await pollApiReady(90);
    clearBootLoading();
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
  clearBootLoading();
  if (!exists) {
    wizardMode.value = "first";
    bootState.value = "wizard";
  } else {
    bootError.value = res.error || "后端启动失败";
    bootState.value = "error";
  }
}

/** 轮询轻量 API 根路径直到后端 HTTP 服务可用。 */
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
    try {
      await cmdRelaunchApp();
    } catch {
      bootError.value = "重启失败，请手动重启应用";
      bootState.value = "error";
    }
    return;
  }
  bootState.value = "starting";
  showBootLoadingAfterDelay();
  const res = await cmdStartSidecar().catch(() => null);
  if (res && res.ok && res.port && res.token) {
    setApiBase(res.port, res.token);
    const ready = await pollApiReady(90);
    clearBootLoading();
    if (ready) {
      bootState.value = "done";
      await initializeConnectedWorkspace();
    } else {
      bootError.value = "后端 API 启动超时，请检查本地后端进程或重试。";
      bootState.value = "error";
    }
  } else {
    clearBootLoading();
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

/** 退出应用（Tauri 窗口关闭）；浏览器开发模式仅提示。 */
async function quitApp() {
  if (isDesktopRuntime()) {
    try {
      await getCurrentWindow().close();
    } catch {
      bootError.value = "退出失败，请手动关闭窗口";
    }
  }
}

// ============ 导航 ============

function onNavigate(v: View) {
  // coding 视图仅在启用时可达；命令面板等入口在关闭时回落旧 Agent 视图
  history.navigate({ view: v === "coding" && !codingEnabled.value ? "chat" : v });
}

// v0.9.0 H1-D（计划 §5.8）：配置闭环——PrivateAgent 入口与 Coding 首页阻塞操作都进入同一个模型管理区；
// 往返保留项目/会话/草稿（由各自组件维护），保存后自动返回并原位重探测解除阻塞。
const settingsFocus = ref<{ section: string; returnTo: View } | null>(null);

function openModelSettings(returnTo: View) {
  settingsFocus.value = { section: "model-profiles", returnTo };
  onNavigate("settings");
}

function onSettingsReturn() {
  const target = settingsFocus.value?.returnTo ?? null;
  settingsFocus.value = null;
  if (target === null) return;
  // 返回后重拉 profile/能力位：首页阻塞原位解除，无需新建项目或重启应用。
  if (target === "coding") void codingActiveStoreRef.value.refresh();
  onNavigate(target);
}

// v0.8.0 W1：coding 首页/侧栏动作接线（线程选择由 codingWorkspaceStore 维护）
function onCodingNewTask() {
  codingActiveStoreRef.value.startNewTask();
  onNavigate("coding");
}

function onCodingThreadCreated() {
  onNavigate("coding");
}

function onGoBack() {
  const target = history.back();
  if (target?.sessionId && target.view === "chat") {
    void selectSession(target.sessionId, false);
  }
}
function onGoForward() {
  const target = history.forward();
  if (target?.sessionId && target.view === "chat") {
    void selectSession(target.sessionId, false);
  }
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
  await legacyChat.initializeLegacyWorkspace();
  // v0.9.0 H1：启动后核对后端能力位——PA_CODING_AGENT_UI_ENABLED=false 短期回退：
  // 非显式选择时回落旧 UI 并本地计数（计划 §3.3；回退原因可解释）。
  try {
    const caps = await getRuntimeCapabilities();
    if (caps.coding_agent_ui_enabled === false && !hasExplicitCodingChoice()) {
      setCodingUiCapability(false);
      if (codingUiActive.value) {
        codingUiActive.value = false;
        recordCodingFallback("capability_disabled");
        if (view.value === "coding") onNavigate("chat");
      }
    }
  } catch {
    /* 能力位获取失败不阻断启动；保持默认呈现 */
  }
  // v0.8.0 W1：coding 工作台就绪后加载项目树并落在首页（计划 §1：首页为核心入口）；
  // W6-R：深链/刷新后保持已恢复的视图（仅默认 chat 回落 coding 首页）。
  if (codingEnabled.value) {
    if (!codingPreviewStore.value) void codingStore.bootstrap();
    if (view.value === "chat") onNavigate("coding");
    recordCodingViewEntry("coding");
    void loadPersonalCounts();
  } else {
    recordCodingViewEntry("legacy");
  }
}

// v0.8.0 W6-R2：今日页已移除 Agent 对话框，onTodaySubmit 发送链随之删除；
// 发起对话统一进入 Agent 页（计划 §4.2 布局约束）。

</script>

<template>
  <!-- UI Lab：仅开发模式（?ui-lab=1），独立于工作台壳层 -->
  <UiLab v-if="uiLabEnabled" />

  <!-- 启动引导覆盖层 -->
  <div v-else-if="bootState !== 'done' && bootState !== 'dev'" class="boot">
    <div
      v-if="(bootState === 'checking' || bootState === 'starting') && bootLoadingVisible"
      class="boot-card"
    >
      <div class="spinner" />
      <p>{{ bootState === "checking" ? "正在检测环境…" : "正在启动本地后端…" }}</p>
      <p class="hint">首次启动可能需要数秒</p>
    </div>

    <ConfigWizard
      v-else-if="bootState === 'wizard'"
      :mode="wizardMode"
      @done="onWizardDone"
    />

    <div v-else-if="bootState === 'error'" class="boot-card">
      <p class="boot-err">⚠ 启动失败</p>
      <p class="hint">{{ bootError }}</p>
      <p class="hint">本地数据未受影响；你可以重试启动，或重新配置连接。</p>
      <div class="boot-actions">
        <button class="pa-btn pa-btn--primary" @click="retryBoot">重试</button>
        <button
          v-if="isDesktopRuntime()"
          class="pa-btn pa-btn--ghost"
          @click="reconfigure"
        >
          重新配置连接
        </button>
        <button
          v-if="isDesktopRuntime()"
          class="pa-btn pa-btn--ghost"
          @click="quitApp"
        >
          退出应用
        </button>
      </div>
    </div>
  </div>

  <!-- ============ 主应用 · v2 三栏工作台（ui_v2）============ -->
  <template v-else-if="uiV2">
    <AppShell
      data-animation-root
      :view="view"
      :title="pageTitle"
      :task-state="taskState"
      :show-dev-tag="bootState === 'dev' || previewMode || !!codingPreviewStore"
      :context-open="view === 'chat' && inspectorOpen"
      :context-toggleable="inspectorToggleable"
      :rail-collapsed="railCollapsed"
      :rail-hidden="codingEnabled && viewportWidth < CODING_RAIL_DRAWER_MAX"
      :can-go-back="history.state().canGoBack"
      :can-go-forward="history.state().canGoForward"
      @toggle-context="inspectorOpen = !inspectorOpen"
      @go-back="onGoBack"
      @go-forward="onGoForward"
    >
      <template #rail>
        <CodingSidebar
          v-if="codingEnabled"
          :store="codingActiveStoreRef"
          :active-view="view"
          :collapsed="railCollapsed"
          :personal-counts="personalCounts"
          @navigate="onNavigate"
          @new-task="onCodingNewTask"
          @open-command="commandPaletteOpen = true"
          @toggle-collapse="railCollapsed = !railCollapsed"
        />
        <NavRailV2
          v-else
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

      <!-- v0.8.0 W1：coding 首页/任务页（内部 flag 启用；任务页 W2 起补全） -->
      <CodingHome
        v-if="codingEnabled && view === 'coding' && !codingThreadSelected"
        :store="codingActiveStoreRef"
        @navigate="onNavigate"
        @configure-provider="openModelSettings('coding')"
        @thread-created="onCodingThreadCreated"
      />
      <CodingThreadWorkspace
        v-else-if="codingEnabled && view === 'coding'"
        :key="codingThreadKey"
        :store="codingActiveStoreRef"
        @navigate="onNavigate"
        @configure-provider="openModelSettings('coding')"
      />
      <SettingsView
        v-else-if="view === 'settings'"
        :focus-section="settingsFocus?.section ?? null"
        :return-to="settingsFocus?.returnTo ?? null"
        @reconfigure="reconfigure"
        @return="onSettingsReturn"
      />
      <DiagnosticsView v-else-if="view === 'diagnostics'" />
      <ExtensionRegistryPanel v-else-if="view === 'extensions'" />
      <IntegrationImportPanel v-else-if="view === 'integrations'" />
      <BackupUpgradePanel v-else-if="view === 'backup'" />
      <TodayView
        v-else-if="view === 'today'"
        @navigate="onNavigate"
        @open-command="commandPaletteOpen = true"
      />
      <!-- v0.8.0 W6-R：六模块独立主区（沿用既有业务组件，能力/确认/通知语义保真） -->
      <section v-else-if="view === 'reminders'" class="personal-view" aria-label="提醒">
        <ReminderPanel />
      </section>
      <section v-else-if="view === 'inbox'" class="personal-view" aria-label="收件箱">
        <InboxPanel />
      </section>
      <section v-else-if="view === 'goals'" class="personal-view" aria-label="长期目标">
        <GoalsWorkspace />
      </section>
      <section v-else-if="view === 'briefings'" class="personal-view" aria-label="主动简报">
        <BriefingPanel />
      </section>
      <section v-else-if="view === 'capture'" class="personal-view" aria-label="快速捕获">
        <CapturePanel />
      </section>
      <section v-else-if="view === 'privacy'" class="personal-view" aria-label="隐私与维护">
        <PrivacyAuditPanel />
      </section>
      <KnowledgeView v-else-if="view === 'kb'" />
      <ProjectWorkspace v-else-if="view === 'projects'" />
      <LearningWorkspace v-else-if="view === 'learning'" />
      <TaskWorkspace v-else-if="view === 'tasks'" />
      <MemoryWorkspace v-else-if="view === 'memory'" />
      <AgentWorkspace
        v-else-if="view === 'chat' && currentSession"
        :messages="messages"
        :streaming="streaming"
        :pending-tool="hasPendingTool"
        :task-state="taskState"
        :sessions="sessions"
        :current-session-id="currentSessionId"
        :capabilities="runtimeCapabilities"
        @send="sendMessage"
        @stop="stopGenerate"
        @approve="onApproveToolCall"
        @reject="onRejectToolCall"
        @approve-agent="onApproveAgentRunTool"
        @reject-agent="onRejectAgentRunTool"
        @select-chunk="currentChunkId = $event"
        @save-inbox="onSaveMessageToInbox"
        @select-session="(id) => void selectSession(id, false)"
        @new-session="newSession"
        @configure-model="openModelSettings('chat')"
      />
      <div v-else class="welcome">
        <span class="welcome-kicker">PRIVATE AGENT WORKSPACE</span>
        <p class="welcome-title">准备好开始一个新任务</p>
        <p class="hint">PrivateAgent 会先建立计划，再清晰展示执行过程、工具调用与结果。</p>
        <button class="pa-btn pa-btn--primary" :disabled="streaming" @click="newSession">
          新建任务
        </button>
      </div>

      <template #context>
        <ContextRail
          :session="currentSession"
          :messages="messages"
          :activities="workspacePreview?.activities ?? sessionActivities"
          :trusted="workspacePreview?.trusted ?? trustedPaths"
          :patch-results="runExecutions"
          :chunk-id="currentChunkId"
          @close="inspectorOpen = false"
          @select-chunk="currentChunkId = $event"
        />
      </template>

      <template #statusbar>
        <StatusBar :task-label="streaming ? '生成中…' : '空闲'" />
      </template>
    </AppShell>
  </template>

  <!-- ============ 主应用 · 兼容壳（legacy，ui_v2 关闭时回退）============ -->
  <template v-else>
    <WorkspaceShell
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

      <SettingsView
        v-if="view === 'settings'"
        :focus-section="settingsFocus?.section ?? null"
        :return-to="settingsFocus?.returnTo ?? null"
        @reconfigure="reconfigure"
        @return="onSettingsReturn"
      />
      <DiagnosticsView v-else-if="view === 'diagnostics'" />
      <ExtensionRegistryPanel v-else-if="view === 'extensions'" />
      <IntegrationImportPanel v-else-if="view === 'integrations'" />
      <BackupUpgradePanel v-else-if="view === 'backup'" />
      <TodayView
        v-else-if="view === 'today'"
        @navigate="onNavigate"
        @open-command="commandPaletteOpen = true"
      />
      <!-- v0.8.0 W6-R：旧壳回退路径同样可经命令面板/今日页链接到达六模块 -->
      <section v-else-if="view === 'reminders'" class="personal-view" aria-label="提醒">
        <ReminderPanel />
      </section>
      <section v-else-if="view === 'inbox'" class="personal-view" aria-label="收件箱">
        <InboxPanel />
      </section>
      <section v-else-if="view === 'goals'" class="personal-view" aria-label="长期目标">
        <GoalsWorkspace />
      </section>
      <section v-else-if="view === 'briefings'" class="personal-view" aria-label="主动简报">
        <BriefingPanel />
      </section>
      <section v-else-if="view === 'capture'" class="personal-view" aria-label="快速捕获">
        <CapturePanel />
      </section>
      <section v-else-if="view === 'privacy'" class="personal-view" aria-label="隐私与维护">
        <PrivacyAuditPanel />
      </section>
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
  </template>

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
.boot-actions {
  display: flex;
  gap: var(--space-2);
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

/* v0.8.0 W6-R：个人工作区独立主区容器（面板自带内部布局，壳层仅提供滚动与边距） */
.personal-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-6);
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
