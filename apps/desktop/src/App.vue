<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from "vue";
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
  setApiBase,
  setApiBaseDefault,
  cmdStartSidecar,
  cmdConfigExists,
  cmdRelaunchApp,
  isDesktopRuntime,
  getApiInfo,
} from "./api";
import type { View } from "./types";
import { mountPageAnimations } from "./animations/page";
import type { AnimationHandle } from "./animations/utils";
import { useChatWorkspace } from "./composables/useChatWorkspace";

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

const view = ref<View>("today");
const chatWorkspace = useChatWorkspace({ view, notify });
const {
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
} = chatWorkspace;
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
let pageAnimations: AnimationHandle | null = null;

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
  chatWorkspace.destroy();
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
    :show-dev-tag="bootState === 'dev'"
    :show-list="view === 'chat'"
    :inspector-open="view === 'chat' && inspectorOpen"
    :inspector-toggleable="inspectorToggleable"
    :show-topbar="view === 'chat'"
    :show-statusbar="view !== 'today'"
    @toggle-inspector="inspectorOpen = !inspectorOpen"
  >
    <template #rail>
      <NavRail
        :active="view"
        @navigate="onNavigate"
        @open-command="commandPaletteOpen = true"
      />
    </template>

    <template #list>
      <SessionList
        :sessions="sessions"
        :current-id="currentSessionId"
        @select="selectSession"
        @new="newSession"
      />
    </template>

    <!-- 主工作区：统一的 keyed transition 保证视图切换动效可预测且可降级。 -->
    <Transition name="workspace-view" mode="out-in">
      <div :key="view" class="workspace-view-frame" data-workspace-view>
        <SettingsView v-if="view === 'settings'" @reconfigure="reconfigure" />
        <DiagnosticsView v-else-if="view === 'diagnostics'" />
        <ExtensionRegistryPanel v-else-if="view === 'extensions'" />
        <IntegrationImportPanel v-else-if="view === 'integrations'" />
        <BackupUpgradePanel v-else-if="view === 'backup'" />
        <TodayView
          v-else-if="view === 'today'"
          @navigate="onNavigate"
          @submit="submitFromToday"
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
          @approve="approveTool"
          @reject="rejectTool"
          @select-chunk="currentChunkId = $event"
          @gen-candidates="generateCandidates"
          @save-inbox="saveMessageToInbox"
        />
        <div v-else class="welcome">
          <p class="welcome-title">欢迎回来</p>
          <p class="hint">新建会话，或从命令面板开始一项工作。</p>
        </div>
      </div>
    </Transition>

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

.workspace-view-frame {
  position: relative;
  z-index: 1;
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.workspace-view-enter-active,
.workspace-view-leave-active {
  transition: opacity var(--duration-slow) var(--ease-out),
    transform var(--duration-slow) var(--ease-out),
    filter var(--duration-slow) var(--ease-out);
}
.workspace-view-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.995);
  filter: blur(3px);
}
.workspace-view-leave-to {
  opacity: 0;
  transform: translateY(-5px) scale(0.998);
  filter: blur(2px);
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

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation-duration: 1.8s;
  }
  .workspace-view-enter-active,
  .workspace-view-leave-active {
    transition: none;
  }
}
</style>
