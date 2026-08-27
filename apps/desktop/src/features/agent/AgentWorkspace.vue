<script setup lang="ts">
/**
 * AgentWorkspace · Agent 核心工作区（0.4.0 D3；W6-R2 两区；W6-R3 三次修订）
 *
 * §4.5 最终信息架构：
 * - AgentHeader（SessionHeader）：标题/运行状态 + 当前授权工作目录 + Git 分支
 *   （公开 workspace 事实；切换时原子更新，不沿用上一会话旧值）。
 * - ConversationList：可展开；收起后条件卸载——零宽、无命中区、退出键盘
 *   顺序与读屏语义；窄窗口为覆盖式抽屉（Escape/遮罩关闭并恢复焦点）。
 * - ConversationSurface：TurnTranscript（逐轮公开过程；无独立执行计划大卡，
 *   计划/工具/审批/验证事实按所属 turn 呈现）+ AgentComposer（固定底部：
 *   权限下拉/模型与 Provider 配置/上下文用量/执行或停止）。
 * 资源清理：媒体监听、焦点监听、序号防护随卸载失效。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { PhChatsCircle, PhSidebarSimple } from "@phosphor-icons/vue";
import type { AgentTaskState, Session } from "../../types";
import type { AgentWorkspaceMessage } from "../../models/agentWorkspace";
import { getSettings, listWorkspaces } from "../../api";
import { useActivityFollow } from "./useActivityFollow";
import { groupAgentTurns } from "./model/agentTurns";
import {
  deriveAgentWorkspaceFacts,
  type AgentWorkspaceFacts,
} from "./model/workspaceFacts";
import ConversationList from "./ConversationList.vue";
import SessionHeader from "./SessionHeader.vue";
import TurnTranscript from "./TurnTranscript.vue";
import AgentComposer from "./AgentComposer.vue";

const props = withDefaults(
  defineProps<{
    messages: AgentWorkspaceMessage[];
    streaming: boolean;
    pendingTool?: boolean;
    taskState?: AgentTaskState;
    /** W6-R2：左栏真实会话数据 */
    sessions?: Session[];
    currentSessionId?: number | null;
    /** W6-R3：公开 capability（原样传入，不猜测） */
    capabilities?: Record<string, unknown> | null;
  }>(),
  {
    pendingTool: false,
    taskState: "idle",
    sessions: () => [],
    currentSessionId: null,
    capabilities: null,
  }
);

const emit = defineEmits<{
  send: [text: string];
  stop: [];
  "select-session": [id: number];
  "new-session": [];
  "configure-model": [];
  approve: [id: number];
  reject: [id: number];
  "approve-agent": [runId: string, approvalId: string];
  "reject-agent": [runId: string, approvalId: string];
  "select-chunk": [chunkId: number];
  "save-inbox": [messageId: number, content: string];
}>();

const currentSession = computed(
  () => props.sessions.find((s) => s.id === props.currentSessionId) ?? null
);

// ============ 逐轮分组（稳定 turn 容器；计划事实随过程条目进入所属 turn） ============
const turns = computed(() => groupAgentTurns(props.messages, props.streaming));
const waitingApproval = computed(() =>
  turns.value.some((turn) => turn.phase === "waiting_approval")
);

// ============ 草稿按会话保存（切换/重命名不串线不重置） ============
const draftBySession = ref<Record<number, string>>({});
const draft = computed<string>({
  get() {
    const id = props.currentSessionId;
    return id === null ? "" : (draftBySession.value[id] ?? "");
  },
  set(value: string) {
    const id = props.currentSessionId;
    if (id === null) return;
    draftBySession.value = { ...draftBySession.value, [id]: value };
  },
});

// ============ W6-R3 T2：工作目录 / Git 分支（generation 防迟到响应） ============
const workspaceFacts = ref<AgentWorkspaceFacts>({
  rootPath: null,
  git: { kind: "loading" },
});
let workspaceGen = 0;

const sessionFactsKey = computed(() => {
  const session = currentSession.value;
  return `${session?.id ?? "none"}:${session?.project_id ?? ""}:${session?.workspace_id ?? ""}`;
});

async function refreshWorkspaceFacts(): Promise<void> {
  const session = currentSession.value;
  // 切换时立即清空旧值：加载期间不得短暂显示上一会话路径/分支
  workspaceFacts.value = {
    rootPath: null,
    git: session ? { kind: "loading" } : { kind: "no-project" },
  };
  if (!session || session.project_id === null || session.project_id === undefined) {
    workspaceFacts.value = { rootPath: null, git: { kind: "no-project" } };
    return;
  }
  const gen = ++workspaceGen;
  const projectId = session.project_id;
  const workspaceId = session.workspace_id ?? null;
  try {
    const list = await listWorkspaces(projectId);
    if (gen !== workspaceGen) return; // 迟到响应：拒绝写入
    const workspace =
      list.find((w) => w.id === workspaceId) ??
      (workspaceId === null
        ? (list.find((w) => w.kind === "root") ?? list[0] ?? null)
        : null);
    workspaceFacts.value = deriveAgentWorkspaceFacts({
      hasProject: true,
      workspace,
    });
  } catch {
    if (gen !== workspaceGen) return;
    workspaceFacts.value = { rootPath: null, git: { kind: "read-failed" } };
  }
}

watch(sessionFactsKey, () => void refreshWorkspaceFacts(), { immediate: true });

// ============ W6-R3 T7：模型/Provider 配置事实（返回后刷新） ============
interface SettingsFacts {
  modelName: string | null;
  providerLabel: string;
  providerWarning: string | null;
  contextLimit: number | null;
  /**
   * v0.9.0 H1-B（计划 §5.6）：执行阻断原因——仅「模型未配置」这一硬阻断项；
   * 远程未开启/配置读取失败仍是警告态（不阻断发送，保持既有行为）。
   */
  blockedReason: string | null;
}

const settingsFacts = ref<SettingsFacts>({
  modelName: null,
  providerLabel: "本地",
  providerWarning: null,
  contextLimit: null,
  blockedReason: null,
});

async function refreshSettings(): Promise<void> {
  try {
    const settings = await getSettings();
    const providerType = settings.provider_type;
    const modelName =
      providerType === "openai"
        ? settings.openai_model
        : providerType === "claude"
          ? settings.claude_model
          : settings.llm_model;
    const trimmed = typeof modelName === "string" ? modelName.trim() : "";
    const remoteEnabled = settings.remote_provider_enabled === true;
    const providerLabel =
      providerType === "ollama" ? "本地" : remoteEnabled ? "远程" : "未配置";
    let providerWarning: string | null = null;
    if (!trimmed) providerWarning = "模型未配置：请先进入设置完成模型配置";
    else if (providerType !== "ollama" && !remoteEnabled)
      providerWarning = "远程 Provider 未开启：当前模型可能不可用";
    settingsFacts.value = {
      modelName: trimmed || null,
      providerLabel,
      providerWarning,
      contextLimit:
        typeof settings.llm_context_length === "number" && settings.llm_context_length > 0
          ? settings.llm_context_length
          : null,
      // §5.6：只有「模型未配置」阻断执行；配置完成后无需新建会话即可执行。
      blockedReason: !trimmed ? "模型未配置：请先配置 PrivateAgent" : null,
    };
  } catch {
    settingsFacts.value = {
      modelName: null,
      providerLabel: "未配置",
      providerWarning: "配置读取失败：请检查后端连接",
      contextLimit: null,
      blockedReason: null,
    };
  }
}

function onWindowFocus(): void {
  // 从设置/配置页返回后刷新真实配置（监听随卸载清理）
  void refreshSettings();
}

// ============ v0.9.0 H1-A：上下文用量圆环（真实 typed budget） ============
// 矩形「上下文用量不可用」模块已移除；圆环按当前会话拉取后端真实计量，
// 能力位未开启/不可用时如实呈现（不伪造百分比，零容忍）。

// ============ W6-R3 T4：会话栏完全收起 / 窄窗口抽屉 ============
const CONVERSATIONS_MEDIA = "(max-width: 1279px)";
const isNarrow = ref(false);
const listCollapsed = ref(false);
const conversationsOpen = ref(false);
const listScrollTop = ref(0);
const drawerTabRef = ref<HTMLElement | null>(null);
let media: MediaQueryList | null = null;

const showList = computed(() => (isNarrow.value ? conversationsOpen.value : !listCollapsed.value));

function onMediaChange(event: MediaQueryListEvent): void {
  isNarrow.value = event.matches;
  conversationsOpen.value = false;
}

function openDrawer(): void {
  conversationsOpen.value = true;
}

function closeDrawer(restoreFocus: boolean): void {
  conversationsOpen.value = false;
  if (restoreFocus) {
    // 关闭后焦点回到触发按钮（键盘可达性）
    requestAnimationFrame(() => drawerTabRef.value?.focus());
  }
}

function collapseList(): void {
  listCollapsed.value = true;
}

function onDrawerKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && conversationsOpen.value) {
    event.preventDefault();
    closeDrawer(true);
  }
}

// ============ 活动流跟随（主时间线独立滚动） ============
const scrollRef = ref<HTMLElement | null>(null);
const feedVersion = ref(0);
const lastContent = ref("");

watch(
  () => props.messages.length,
  () => {
    feedVersion.value += 1;
  }
);
watch(
  () => props.messages[props.messages.length - 1]?.content ?? "",
  (content) => {
    if (content !== lastContent.value) {
      lastContent.value = content;
      feedVersion.value += 1;
    }
  }
);

const { newActivity, onScroll, scrollToLatest } = useActivityFollow(scrollRef, feedVersion);

// 停止状态：点击停止 →「正在请求停止」至少呈现 700ms，随后「已停止」4s。
const stopRequested = ref(false);
const stopped = ref(false);
let stoppedTimer: number | null = null;
let stopTransitionTimer: number | null = null;

function onStop() {
  if (props.streaming && !stopRequested.value) {
    stopRequested.value = true;
    emit("stop");
    if (stopTransitionTimer !== null) window.clearTimeout(stopTransitionTimer);
    stopTransitionTimer = window.setTimeout(() => {
      stopTransitionTimer = null;
      stopRequested.value = false;
      if (!props.streaming) {
        stopped.value = true;
        if (stoppedTimer !== null) window.clearTimeout(stoppedTimer);
        stoppedTimer = window.setTimeout(() => {
          stopped.value = false;
          stoppedTimer = null;
        }, 4000);
      }
    }, 700);
  }
}

function onSelectSession(id: number) {
  if (isNarrow.value) closeDrawer(false);
  emit("select-session", id);
}

onMounted(() => {
  void refreshSettings();
  window.addEventListener("focus", onWindowFocus);
  document.addEventListener("visibilitychange", onWindowFocus);
  document.addEventListener("keydown", onDrawerKeydown);
  if (typeof window.matchMedia === "function") {
    media = window.matchMedia(CONVERSATIONS_MEDIA);
    isNarrow.value = media.matches;
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onMediaChange);
    }
  }
});

onBeforeUnmount(() => {
  workspaceGen += 1;
  window.removeEventListener("focus", onWindowFocus);
  document.removeEventListener("visibilitychange", onWindowFocus);
  document.removeEventListener("keydown", onDrawerKeydown);
  if (media && typeof media.removeEventListener === "function") {
    media.removeEventListener("change", onMediaChange);
  }
  media = null;
  if (stoppedTimer !== null) {
    window.clearTimeout(stoppedTimer);
    stoppedTimer = null;
  }
  if (stopTransitionTimer !== null) {
    window.clearTimeout(stopTransitionTimer);
    stopTransitionTimer = null;
  }
});
</script>

<template>
  <div class="agent-page">
    <!-- 窄窗口浮标入口（抽屉收起时呈现；关闭后焦点回到此按钮） -->
    <button
      v-if="isNarrow && !conversationsOpen"
      ref="drawerTabRef"
      class="conversations-tab"
      type="button"
      aria-label="打开会话记录"
      data-testid="agent-conversations-tab"
      @click="openDrawer"
    >
      <PhChatsCircle :size="16" />
    </button>
    <div
      v-if="isNarrow && conversationsOpen"
      class="conversations-backdrop"
      data-testid="agent-conversations-backdrop"
      @click="closeDrawer(true)"
    />

    <!-- 收起 = 条件卸载：零宽、无命中区、退出键盘顺序与读屏语义 -->
    <div
      v-if="showList"
      class="agent-conversations"
      :class="{ 'is-drawer': isNarrow }"
    >
      <div v-if="!isNarrow" class="list-toolbar">
        <button
          class="list-collapse-btn"
          type="button"
          title="收起会话列表"
          aria-label="收起会话列表"
          data-testid="agent-conversations-collapse"
          @click="collapseList"
        >
          <PhSidebarSimple :size="14" />
          <span>收起</span>
        </button>
      </div>
      <ConversationList
        :sessions="sessions"
        :current-id="currentSessionId"
        :running="streaming"
        :initial-scroll-top="listScrollTop"
        @new-session="emit('new-session')"
        @select-session="onSelectSession"
        @scroll-pos="(top) => (listScrollTop = top)"
      />
    </div>

    <div class="agent-main">
      <!-- 桌面端收起后的可发现展开按钮 -->
      <div v-if="!isNarrow && listCollapsed" class="list-expand-row">
        <button
          class="list-expand-btn"
          type="button"
          title="展开会话列表"
          aria-label="展开会话列表"
          data-testid="agent-conversations-expand"
          @click="listCollapsed = false"
        >
          <PhChatsCircle :size="14" />
          <span>展开会话</span>
        </button>
      </div>

      <SessionHeader
        :title="currentSession?.title ?? ''"
        :running="streaming"
        :waiting-approval="waitingApproval"
        :workspace-facts="workspaceFacts"
      />

      <div
        ref="scrollRef"
        class="agent-scroll"
        data-testid="agent-scroll"
        @scroll.passive="onScroll"
      >
        <div class="agent-inner">
          <TurnTranscript
            :turns="turns"
            :streaming="streaming"
            :task-state="taskState"
            @approve-tool="(id) => emit('approve', id)"
            @reject-tool="(id) => emit('reject', id)"
            @approve-agent="(runId, approvalId) => emit('approve-agent', runId, approvalId)"
            @reject-agent="(runId, approvalId) => emit('reject-agent', runId, approvalId)"
            @select-chunk="(chunkId) => emit('select-chunk', chunkId)"
            @save-inbox="(messageId, content) => emit('save-inbox', messageId, content)"
          />
        </div>
      </div>

      <button
        v-if="newActivity"
        class="new-activity-pill"
        data-testid="new-activity-pill"
        @click="scrollToLatest(true)"
      >
        有新活动
        <span class="pill-dot" />
      </button>

      <AgentComposer
        v-model="draft"
        :streaming="streaming"
        :pending-tool="pendingTool"
        :stop-requested="stopRequested"
        :stopped="stopped"
        :model-name="settingsFacts.modelName"
        :provider-label="settingsFacts.providerLabel"
        :provider-warning="settingsFacts.providerWarning"
        :blocked-reason="settingsFacts.blockedReason"
        :session-id="currentSessionId"
        :capabilities="capabilities"
        @send="(text) => emit('send', text)"
        @stop="onStop"
        @configure-model="emit('configure-model')"
      />
    </div>
  </div>
</template>

<style scoped>
.agent-page {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
  background: var(--color-bg);
}
.agent-conversations {
  display: flex;
  width: 260px;
  flex-shrink: 0;
  flex-direction: column;
}
.agent-conversations.is-drawer {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: var(--z-overlay);
  width: min(280px, 86vw);
  box-shadow: var(--shadow-lg);
}
.list-toolbar {
  display: flex;
  flex-shrink: 0;
  justify-content: flex-end;
  padding: var(--space-2) var(--space-2) 0;
}
.list-collapse-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.list-collapse-btn:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.conversations-tab {
  position: absolute;
  top: var(--space-3);
  left: var(--space-2);
  z-index: var(--z-overlay);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
}
.conversations-tab:hover {
  color: var(--color-fg);
}
.conversations-backdrop {
  position: absolute;
  inset: 0;
  z-index: calc(var(--z-overlay) - 1);
  background: color-mix(in srgb, var(--color-fg) 24%, transparent);
}
.agent-main {
  position: relative;
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}
.list-expand-row {
  display: flex;
  flex-shrink: 0;
  padding: var(--space-2) var(--space-4) 0;
}
.list-expand-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.list-expand-btn:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.agent-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scroll-padding-bottom: 160px;
}
.agent-inner {
  /* 回答正文可读宽度（760–920px 目标）居中 */
  width: min(100%, 880px);
  min-height: 100%;
  margin: 0 auto;
  padding: var(--space-5) var(--space-6) var(--space-8);
}
.new-activity-pill {
  display: inline-flex;
  position: absolute;
  z-index: var(--z-raised);
  right: var(--space-6);
  bottom: 150px;
  align-items: center;
  gap: var(--space-2);
  height: 32px;
  padding: 0 var(--space-4);
  border: 1px solid color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  box-shadow: var(--shadow);
  cursor: pointer;
}
.new-activity-pill:hover {
  background: var(--color-accent-soft);
}
.new-activity-pill:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.pill-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--color-accent);
}
@media (max-width: 900px) {
  .agent-inner {
    padding: var(--space-4);
  }
}
</style>
