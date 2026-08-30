<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch, shallowRef } from "vue";
import { useRoute } from "vue-router";
import { getCurrentWindow } from "@tauri-apps/api/window";
import AppShell from "./components/AppShell.vue";
import TaskWorkspace from "./components/TaskWorkspace.vue";
import SettingsView from "./components/SettingsView.vue";
import SettingsModuleNav from "./components/SettingsModuleNav.vue";
import DiagnosticsView from "./components/DiagnosticsView.vue";
import ExtensionRegistryPanel from "./components/ExtensionRegistryPanel.vue";
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
  getApiConnection,
  cmdConfigExists,
  cmdRelaunchApp,
  isDesktopRuntime,
  getApiInfo,
  hasConfiguredRemoteApi,
} from "./api";
import type { View } from "./types";
import type { SettingsSection } from "./models/settingsSections";
import { viewLabel } from "./models/viewRegistry";
import { useAuthStore } from "./stores/auth";
import { mountPageAnimations } from "./animations/page";
import type { AnimationHandle } from "./animations/utils";
import { isCodingWorkspaceEnabled } from "./config/uiFlags";
import { recordCodingViewEntry } from "./features/coding/model/codingUiTelemetry";
import { useViewHistory } from "./composables/useViewHistory";
import { useShortcuts } from "./composables/useShortcuts";
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
const authStore = useAuthStore();
const route = useRoute();
// 普通用户端固定使用 Coding 工作台；管理员由路由隔离到独立后台。
const codingEnabled = computed(() => isCodingWorkspaceEnabled(authStore.isAdmin));
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

// 普通用户工作区只保留图二中的 Coding、自动化、插件及其设置/诊断入口。
const CODING_ALLOWED_VIEWS = new Set<View>([
  "coding",
  "tasks",
  "extensions",
  "settings",
  "diagnostics",
]);

// 导航历史：旧版本持久化的模块在渲染和初始化时统一归一到 Coding 首页。
const history = useViewHistory("coding");
const view = history.current;
const workspaceView = computed<View>(() =>
  CODING_ALLOWED_VIEWS.has(view.value) ? view.value : "coding"
);

const railCollapsed = ref(false);
const modelSettingsPreviewMode =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("settings-preview") === "providers-v2";
// v0.8.0 W1：coding 侧栏 <1280px 进入抽屉模式（W0 冻结 §2.2），rail 槽收为 0 宽
const CODING_RAIL_DRAWER_MAX = 1280;
const viewportWidth = ref(
  typeof window !== "undefined" ? window.innerWidth : 1280
);
let pageAnimations: AnimationHandle | null = null;

const pageTitle = computed(() => viewLabel(workspaceView.value));

function onResize() {
  viewportWidth.value = window.innerWidth;
}

onMounted(() => {
  window.addEventListener("resize", onResize);
  boot();
  if (route.query.view === "settings") onNavigate("settings");
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", onResize);
  clearBootLoading();
  pageAnimations?.destroy();
  pageAnimations = null;
});

// 全局快捷键：Ctrl/Cmd+K 命令面板；Ctrl/Cmd+N 新建任务；Alt+←/→ 视图历史
useShortcuts({
  openCommand: () => (commandPaletteOpen.value = true),
  newSession: onCodingNewTask,
  goBack: onGoBack,
  goForward: onGoForward,
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
  // 远程部署：客户端直接连接配置的 HTTPS API，不再启动本地 sidecar。
  if (hasConfiguredRemoteApi()) {
    setApiBaseDefault();
    bootState.value = "done";
    await initializeConnectedWorkspace();
    return;
  }
  // 浏览器开发：直接用默认端口。
  if (!isDesktopRuntime()) {
    setApiBaseDefault();
    bootState.value = "done";
    if (modelSettingsPreviewMode) {
      history.navigate({ view: "settings" });
      settingsSection.value = "provider";
      return;
    }
    if (codingPreviewKey) {
      history.navigate({ view: "coding" });
      return;
    }
    await initializeConnectedWorkspace();
    return;
  }

  bootState.value = "checking";
  showBootLoadingAfterDelay();
  const existingConnection = await getApiConnection().catch(() => null);
  if (existingConnection) {
    setApiBase(existingConnection.port, existingConnection.token);
    bootState.value = "starting";
    if (await pollApiReady(5)) {
      clearBootLoading();
      bootState.value = "done";
      await initializeConnectedWorkspace();
      return;
    }
  }
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

const settingsSection = ref<SettingsSection>("current-model");

function onNavigate(v: View) {
  const target = CODING_ALLOWED_VIEWS.has(v) ? v : "coding";
  if (target === "settings" && view.value !== "settings" && settingsFocus.value === null) {
    settingsSection.value = "current-model";
  }
  history.navigate({ view: target });
}

// v0.9.0 H1-D（计划 §5.8）：配置闭环——PrivateAgent 入口与 Coding 首页阻塞操作都进入同一个模型管理区；
// 往返保留项目/会话/草稿（由各自组件维护），保存后自动返回并原位重探测解除阻塞。
const settingsFocus = ref<{ section: SettingsSection; returnTo: View } | null>(null);

function openModelSettings(returnTo: View) {
  settingsFocus.value = { section: "provider", returnTo };
  settingsSection.value = "provider";
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

function exitSettings() {
  if (settingsFocus.value) {
    onSettingsReturn();
    return;
  }
  onNavigate("coding");
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
  if (target && !CODING_ALLOWED_VIEWS.has(target.view)) onNavigate("coding");
}
function onGoForward() {
  const target = history.forward();
  if (target && !CODING_ALLOWED_VIEWS.has(target.view)) onNavigate("coding");
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
  if (!codingEnabled.value) return;
  if (!codingPreviewStore.value) void codingStore.bootstrap();
  if (!CODING_ALLOWED_VIEWS.has(view.value)) onNavigate("coding");
  recordCodingViewEntry("coding");
}

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

  <!-- 普通用户唯一工作区：与图二一致，不再保留旧模块回退壳。 -->
  <AppShell
    v-else
    data-animation-root
    :view="workspaceView"
    :title="pageTitle"
    :show-dev-tag="bootState === 'dev' || !!codingPreviewStore"
    :rail-collapsed="railCollapsed"
    :rail-hidden="viewportWidth < CODING_RAIL_DRAWER_MAX"
    :can-go-back="history.state().canGoBack"
    :can-go-forward="history.state().canGoForward"
    @go-back="onGoBack"
    @go-forward="onGoForward"
  >
    <template #rail>
      <SettingsModuleNav
        v-if="workspaceView === 'settings'"
        :active="settingsSection"
        :narrow="viewportWidth < CODING_RAIL_DRAWER_MAX"
        @select="settingsSection = $event"
        @exit="exitSettings"
      />
      <CodingSidebar
        v-else
        :store="codingActiveStoreRef"
        :active-view="workspaceView"
        :collapsed="railCollapsed"
        @navigate="onNavigate"
        @new-task="onCodingNewTask"
        @open-command="commandPaletteOpen = true"
        @toggle-collapse="railCollapsed = !railCollapsed"
      />
    </template>

    <CodingHome
      v-if="workspaceView === 'coding' && !codingThreadSelected"
      :store="codingActiveStoreRef"
      @navigate="onNavigate"
      @configure-provider="openModelSettings('coding')"
      @thread-created="onCodingThreadCreated"
    />
    <CodingThreadWorkspace
      v-else-if="workspaceView === 'coding'"
      :key="codingThreadKey"
      :store="codingActiveStoreRef"
      @navigate="onNavigate"
      @configure-provider="openModelSettings('coding')"
    />
    <SettingsView
      v-else-if="workspaceView === 'settings'"
      :active-section="settingsSection"
      :focus-section="settingsFocus?.section ?? null"
      :return-to="settingsFocus?.returnTo ?? null"
      @reconfigure="reconfigure"
      @return="onSettingsReturn"
      @select-section="settingsSection = $event"
    />
    <DiagnosticsView v-else-if="workspaceView === 'diagnostics'" />
    <ExtensionRegistryPanel v-else-if="workspaceView === 'extensions'" />
    <TaskWorkspace v-else-if="workspaceView === 'tasks'" />

  </AppShell>

  <!-- 第七阶段全局覆盖层：toast / 确认对话框 / 通知中心（Teleport 到 body） -->
  <ToastHost />
  <ConfirmDialog />
  <NotificationCenter />
  <CommandPalette
    v-if="commandPaletteOpen"
    coding-only
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

</style>
