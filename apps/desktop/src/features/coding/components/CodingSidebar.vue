<script setup lang="ts">
/**
 * CodingSidebar · v0.8.0 W1（W6-R 增补）
 *
 * W0 冻结 §2.1 左侧栏：一级动作（新建任务/搜索/自动化/扩展）+
 * 个人工作区六入口（提醒/收件箱/长期目标/主动简报/快速捕获/隐私与维护，
 * W6-R 计划 §4.1）+ Project → Workspace/branch → Thread 树 + 底部（用户与本地数据状态/
 * 设置/诊断/折叠）。240px；折叠 72px 图标态；<1280px 抽屉模式
 * （Teleport 覆盖层 + 浮标入口，matchMedia 监听随卸载清理）。
 * 数据经 codingWorkspaceStore 注入（默认单例），组件不自取 API。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  PhActivity,
  PhArchive,
  PhArrowClockwise,
  PhBell,
  PhChatsCircle,
  PhFolderSimple,
  PhGearSix,
  PhGitBranch,
  PhListChecks,
  PhMagnifyingGlass,
  PhNewspaper,
  PhNotePencil,
  PhPencil,
  PhPlus,
  PhPushPin,
  PhPuzzlePiece,
  PhShieldCheck,
  PhSidebarSimple,
  PhSparkle,
  PhTarget,
  PhTray,
  PhUserCircle,
  PhX,
} from "@phosphor-icons/vue";
import type { View } from "../../../types";
import { formatRelative as timeFormatRelative } from "../../../services/timeDisplay";
import { useNotifications } from "../../../stores/notifications";
import {
  WORKSPACE_STATUS_META,
  type CodingProjectNode,
  type CodingThreadSummary,
} from "../model/contracts";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";
// v0.9.0 H4：线程管理（重命名/归档/置顶）与更多工作区（legacy 显式绑定迁移）
import {
  bindSessionToProject,
  fetchRecentThreads,
  fetchUnboundLegacyThreads,
  renameThread,
  setThreadArchived,
  setThreadPinned,
} from "../api/threads";
// v0.9.0 H1：新建项目对话框（选目录+授权；与新建对话拆分为两个清晰动作）
import NewProjectDialog from "./NewProjectDialog.vue";

const notify = useNotifications();

/** 个人工作区六入口（W6-R：今日页迁出的纵向模块，计划 §4.1/§6.6） */
const PERSONAL_ENTRIES: ReadonlyArray<{
  view: View;
  label: string;
  icon: typeof PhBell;
}> = [
  { view: "reminders", label: "提醒", icon: PhBell },
  { view: "inbox", label: "收件箱", icon: PhTray },
  { view: "goals", label: "长期目标", icon: PhTarget },
  { view: "briefings", label: "主动简报", icon: PhNewspaper },
  { view: "capture", label: "快速捕获", icon: PhNotePencil },
  { view: "privacy", label: "隐私与维护", icon: PhShieldCheck },
];

const props = withDefaults(
  defineProps<{
    store?: CodingWorkspaceStore;
    /** 当前壳视图（高亮首页/旧页入口） */
    activeView?: View;
    collapsed?: boolean;
    /** 待处理数量徽标（今日快照只读数字；缺省不展示） */
    personalCounts?: Partial<Record<View, number>> | null;
  }>(),
  {
    store: () => useCodingWorkspace(),
    activeView: "coding" as View,
    collapsed: false,
    personalCounts: null,
  }
);

const emit = defineEmits<{
  navigate: [view: View];
  "new-task": [];
  "open-command": [];
  "toggle-collapse": [];
  /** v0.9.0 H1：新建项目完成（父层可据此联动） */
  "project-created": [projectId: number];
}>();

const tree = computed(() => props.store.tree.value);
const loadPhase = computed(() => props.store.loadPhase.value);
const selectedProjectId = computed(() => props.store.selectedProjectId.value);
const selectedWorkspaceId = computed(() => props.store.selectedWorkspaceId.value);
const selectedThreadId = computed(() => props.store.selectedThreadId.value);

const personalEntries = PERSONAL_ENTRIES;

/** 待处理徽标：仅展示正整数（只读数字，不呈现完整模块） */
function personalCount(view: View): number | null {
  const value = props.personalCounts?.[view];
  return typeof value === "number" && value > 0 ? value : null;
}

const onCodingHome = computed(
  () => props.activeView === "coding" && selectedThreadId.value === null
);

// 树展开状态：默认折叠，选中变化时展开祖先（不整页重置）
const projectOpen = ref<Record<number, boolean>>({});
const workspaceOpen = ref<Record<string, boolean>>({});

function workspaceKey(projectId: number, workspaceId: number): string {
  return `${projectId}:${workspaceId}`;
}

watch([selectedProjectId, selectedWorkspaceId, selectedThreadId], () => {
  const projectId = selectedProjectId.value;
  if (projectId === null) return;
  if (selectedThreadId.value !== null || selectedWorkspaceId.value !== null) {
    projectOpen.value = { ...projectOpen.value, [projectId]: true };
  }
  const workspaceId = selectedWorkspaceId.value;
  if (workspaceId !== null) {
    const key = workspaceKey(projectId, workspaceId);
    workspaceOpen.value = { ...workspaceOpen.value, [key]: true };
  }
});

function toggleProject(node: CodingProjectNode): void {
  const next = !projectOpen.value[node.project.id];
  projectOpen.value = { ...projectOpen.value, [node.project.id]: next };
  if (next) {
    props.store.selectProject(node.project.id);
    emit("navigate", "coding");
  }
}

function toggleWorkspace(projectId: number, workspaceId: number): void {
  const key = workspaceKey(projectId, workspaceId);
  workspaceOpen.value = { ...workspaceOpen.value, [key]: !workspaceOpen.value[key] };
}

function openThread(threadId: number): void {
  props.store.selectThread(threadId);
  emit("navigate", "coding");
}

function onNewTask(): void {
  props.store.startNewTask();
  emit("new-task");
  emit("navigate", "coding");
}

// v0.9.0 H1：新建项目对话框状态；创建成功后刷新树并选中新项目。
const newProjectDialogOpen = ref(false);

function openNewProjectDialog(): void {
  newProjectDialogOpen.value = true;
}

async function onProjectCreated(projectId: number): Promise<void> {
  newProjectDialogOpen.value = false;
  emit("project-created", projectId);
  await props.store.refresh();
  if (projectId > 0) {
    props.store.selectProject(projectId);
    emit("navigate", "coding");
  }
}

function branchLabel(node: { workspace: { kind: string; branchName: string | null } }): string {
  if (node.workspace.branchName) return node.workspace.branchName;
  return node.workspace.kind === "root" ? "根工作区" : "工作区";
}

function workspaceStatusTone(status: keyof typeof WORKSPACE_STATUS_META): string {
  return WORKSPACE_STATUS_META[status].tone;
}

function formatRelative(value: string): string {
  // v0.9.0 H1：统一 Asia/Shanghai 显示服务（禁止组件各自调用本机 locale）
  const formatted = timeFormatRelative(value);
  return formatted === "—" ? "" : formatted;
}

// ============ v0.9.0 H4：线程管理（置顶/重命名/归档） ============
const threadActionBusy = ref(false);

async function onTogglePin(thread: CodingThreadSummary): Promise<void> {
  if (threadActionBusy.value) return;
  threadActionBusy.value = true;
  try {
    await setThreadPinned(thread.id, !thread.pinnedAt);
    await props.store.refresh();
  } finally {
    threadActionBusy.value = false;
  }
}

async function onRenameThread(thread: CodingThreadSummary): Promise<void> {
  if (threadActionBusy.value) return;
  const next = await notify.prompt({
    title: "重命名对话",
    defaultValue: thread.title,
    confirmLabel: "保存名称",
  });
  if (next === null || !next.trim()) return;
  threadActionBusy.value = true;
  try {
    await renameThread(thread.id, next.trim());
    await props.store.refresh();
  } finally {
    threadActionBusy.value = false;
  }
}

async function onArchiveThread(thread: CodingThreadSummary): Promise<void> {
  if (threadActionBusy.value) return;
  const confirmed = await notify.confirm({
    title: `归档对话「${thread.title}」？`,
    message: "归档为软删除，可从搜索或旧界面找回。",
    impact: "不会物理删除消息与审计记录。",
    confirmLabel: "归档",
  });
  if (!confirmed) return;
  threadActionBusy.value = true;
  try {
    await setThreadArchived(thread.id, true);
    await props.store.refresh();
  } finally {
    threadActionBusy.value = false;
  }
}

// ============ v0.9.0 H4：最近任务（置顶优先 → 更新时间倒序） ============
const recentThreads = ref<CodingThreadSummary[]>([]);

async function loadRecentThreads(): Promise<void> {
  try {
    recentThreads.value = await fetchRecentThreads(6);
  } catch {
    recentThreads.value = [];
  }
}

function openRecentThread(thread: CodingThreadSummary): void {
  if (thread.projectId) props.store.selectProject(thread.projectId);
  props.store.selectThread(thread.id);
  emit("navigate", "coding");
}

// ============ v0.9.0 H4：更多工作区（未绑定 legacy 会话次级入口） ============
// 契约（H0 §4.2）：只呈现，不批量/不猜测绑定；迁移必须逐条显式选择项目。
const legacyThreads = ref<CodingThreadSummary[]>([]);
const legacyOpen = ref(false);

async function loadLegacyThreads(): Promise<void> {
  try {
    legacyThreads.value = await fetchUnboundLegacyThreads();
  } catch {
    legacyThreads.value = [];
  }
}

async function onBindLegacyThread(thread: CodingThreadSummary, projectId: number): Promise<void> {
  if (threadActionBusy.value) return;
  const workspaces = props.store.workspacesByProject.value[projectId] ?? [];
  const target = workspaces[0];
  if (!target) return;
  threadActionBusy.value = true;
  try {
    await bindSessionToProject(thread.id, projectId, target.id);
    await loadLegacyThreads();
    await props.store.refresh();
  } finally {
    threadActionBusy.value = false;
  }
}

// <1280px 抽屉模式（W0 冻结 §2.2）：覆盖层 + 浮标；监听器随卸载清理
const DRAWER_MEDIA = "(max-width: 1279px)";
const isNarrow = ref(false);
const drawerOpen = ref(false);
let media: MediaQueryList | null = null;

function onMediaChange(event: MediaQueryListEvent): void {
  isNarrow.value = event.matches;
  drawerOpen.value = false;
}

onMounted(() => {
  void loadRecentThreads();
  if (typeof window.matchMedia !== "function") return;
  media = window.matchMedia(DRAWER_MEDIA);
  isNarrow.value = media.matches;
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", onMediaChange);
  }
});

onBeforeUnmount(() => {
  if (media && typeof media.removeEventListener === "function") {
    media.removeEventListener("change", onMediaChange);
  }
  media = null;
});
</script>

<template>
  <!-- 窄窗口浮标入口（覆盖层收起时呈现） -->
  <button
    v-if="isNarrow && !drawerOpen"
    class="coding-drawer-tab"
    data-testid="coding-drawer-tab"
    aria-label="打开侧栏"
    @click="drawerOpen = true"
  >
    <PhSidebarSimple :size="16" />
  </button>

  <!-- 窄窗口遮罩：点击关闭抽屉 -->
  <div
    v-if="isNarrow && drawerOpen"
    class="coding-drawer-backdrop"
    data-testid="coding-drawer-backdrop"
    @click="drawerOpen = false"
  />

  <Teleport to="body" :disabled="!isNarrow">
    <nav
      v-if="!isNarrow || drawerOpen"
      class="coding-sidebar"
      :class="{ 'is-collapsed': collapsed && !isNarrow, 'is-drawer': isNarrow }"
      data-testid="coding-sidebar"
      aria-label="Coding 导航"
    >
      <div class="sidebar-brand">
        <div class="brand-mark"><PhSparkle :size="20" weight="fill" /></div>
        <div class="brand-copy">
          <strong>PrivateAgent</strong>
          <span class="brand-tag">CODING</span>
        </div>
        <button
          v-if="isNarrow"
          class="icon-btn"
          aria-label="收起侧栏"
          data-testid="coding-drawer-close"
          @click="drawerOpen = false"
        >
          <PhX :size="16" />
        </button>
      </div>

      <div class="sidebar-actions">
        <button
          class="action-primary"
          :class="{ active: onCodingHome }"
          :title="collapsed && !isNarrow ? '新建对话' : undefined"
          :aria-label="collapsed && !isNarrow ? '新建对话' : undefined"
          data-testid="coding-new-task"
          @click="onNewTask"
        >
          <PhPlus :size="16" weight="bold" />
          <!-- v0.9.0 H1：新建任务更名为新建对话（任务由对话中的 run 表达） -->
          <span class="action-label">新建对话</span>
        </button>
        <button
          class="action-item"
          :title="collapsed && !isNarrow ? '新建项目' : undefined"
          :aria-label="collapsed && !isNarrow ? '新建项目' : undefined"
          data-testid="coding-new-project"
          @click="openNewProjectDialog"
        >
          <PhFolderSimple :size="16" />
          <span class="action-label">新建项目</span>
        </button>
        <button
          class="action-item"
          :title="collapsed && !isNarrow ? '搜索' : undefined"
          :aria-label="collapsed && !isNarrow ? '搜索' : undefined"
          data-testid="coding-open-search"
          @click="emit('open-command')"
        >
          <PhMagnifyingGlass :size="16" />
          <span class="action-label">搜索</span>
        </button>
        <button
          class="action-item"
          :class="{ active: activeView === 'tasks' }"
          :aria-current="activeView === 'tasks' ? 'page' : undefined"
          :title="collapsed && !isNarrow ? '自动化' : undefined"
          :aria-label="collapsed && !isNarrow ? '自动化' : undefined"
          data-testid="coding-nav-tasks"
          @click="emit('navigate', 'tasks')"
        >
          <PhListChecks :size="16" />
          <span class="action-label">自动化</span>
        </button>
        <button
          class="action-item"
          :class="{ active: activeView === 'extensions' }"
          :aria-current="activeView === 'extensions' ? 'page' : undefined"
          :title="collapsed && !isNarrow ? '扩展' : undefined"
          :aria-label="collapsed && !isNarrow ? '扩展' : undefined"
          data-testid="coding-nav-extensions"
          @click="emit('navigate', 'extensions')"
        >
          <PhPuzzlePiece :size="16" />
          <span class="action-label">扩展</span>
        </button>
      </div>

      <!-- W6-R：个人工作区六入口（独立主区；只读待处理徽标） -->
      <div class="sidebar-personal" data-testid="coding-personal">
        <div v-if="!collapsed || isNarrow" class="personal-heading">个人工作区</div>
        <div class="personal-items">
          <button
            v-for="entry in personalEntries"
            :key="entry.view"
            class="action-item personal-item"
            :class="{ active: activeView === entry.view }"
            :aria-current="activeView === entry.view ? 'page' : undefined"
            :title="collapsed && !isNarrow ? entry.label : undefined"
            :aria-label="entry.label"
            :data-testid="`coding-personal-${entry.view}`"
            @click="emit('navigate', entry.view)"
          >
            <component :is="entry.icon" :size="16" />
            <span class="action-label">{{ entry.label }}</span>
            <span
              v-if="personalCount(entry.view) !== null"
              class="personal-badge"
              :data-testid="`coding-personal-badge-${entry.view}`"
            >{{ personalCount(entry.view) }}</span>
          </button>
        </div>
      </div>

      <div v-if="!collapsed || isNarrow" class="sidebar-tree" data-testid="coding-tree">
        <div class="tree-heading">
          <span>项目</span>
          <button
            class="icon-btn"
            aria-label="刷新项目树"
            data-testid="coding-refresh"
            :disabled="loadPhase === 'loading'"
            @click="props.store.refresh(); void loadRecentThreads()"
          >
            <PhArrowClockwise :size="14" :class="{ spin: loadPhase === 'loading' }" />
          </button>
        </div>

        <!-- v0.9.0 H4：最近任务（置顶优先 → 更新时间倒序，不含已归档） -->
        <div
          v-if="recentThreads.length > 0"
          class="recent-block"
          data-testid="coding-recent"
        >
          <div class="recent-heading">最近任务</div>
          <button
            v-for="thread in recentThreads"
            :key="`recent-${thread.id}`"
            class="thread-row"
            :data-testid="`coding-recent-thread-${thread.id}`"
            :title="thread.title"
            @click="openRecentThread(thread)"
          >
            <PhChatsCircle :size="13" aria-hidden="true" />
            <PhPushPin
              v-if="thread.pinnedAt"
              :size="11"
              class="thread-pin"
              aria-label="已置顶"
            />
            <span class="row-label">{{ thread.title }}</span>
            <small>{{ formatRelative(thread.updatedAt) }}</small>
          </button>
        </div>

        <div v-if="tree.length === 0" class="tree-empty">
          {{ loadPhase === "loading" ? "正在加载项目…" : "暂无项目，先在项目页添加" }}
        </div>

        <div v-else class="tree-scroll" role="tree" aria-label="项目与任务树">
          <div v-for="node in tree" :key="node.project.id" class="tree-project" role="none">
            <button
              class="project-row"
              :class="{ active: selectedProjectId === node.project.id && selectedThreadId === null }"
              :data-testid="`coding-project-${node.project.id}`"
              :aria-expanded="projectOpen[node.project.id] ?? false"
              role="treeitem"
              @click="toggleProject(node)"
            >
              <span class="row-caret" :class="{ open: projectOpen[node.project.id] }" aria-hidden="true" />
              <PhFolderSimple :size="15" aria-hidden="true" />
              <span class="row-label">{{ node.project.name }}</span>
            </button>

            <div v-if="projectOpen[node.project.id]" class="tree-children" role="group">
              <div
                v-for="child in node.workspaces"
                :key="child.workspace.id"
                class="tree-workspace"
                role="none"
              >
                <button
                  class="workspace-row"
                  :class="{ active: selectedWorkspaceId === child.workspace.id && selectedThreadId === null }"
                  :data-testid="`coding-workspace-${child.workspace.id}`"
                  :data-status="child.workspace.status"
                  :aria-expanded="workspaceOpen[`${node.project.id}:${child.workspace.id}`] ?? false"
                  role="treeitem"
                  :title="`分支 ${branchLabel(child)} · ${WORKSPACE_STATUS_META[child.workspace.status].label}`"
                  @click="toggleWorkspace(node.project.id, child.workspace.id)"
                >
                  <span class="row-caret" :class="{ open: workspaceOpen[`${node.project.id}:${child.workspace.id}`] }" aria-hidden="true" />
                  <PhGitBranch :size="14" aria-hidden="true" />
                  <span class="row-label">{{ branchLabel(child) }}</span>
                  <span
                    class="status-dot"
                    :class="`tone-${workspaceStatusTone(child.workspace.status)}`"
                    :aria-label="WORKSPACE_STATUS_META[child.workspace.status].label"
                  />
                </button>

                <div
                  v-if="workspaceOpen[`${node.project.id}:${child.workspace.id}`]"
                  class="tree-threads"
                  role="group"
                >
                  <div
                    v-for="thread in child.threads"
                    :key="thread.id"
                    class="thread-row"
                    :class="{ active: selectedThreadId === thread.id }"
                    :data-testid="`coding-thread-${thread.id}`"
                    role="treeitem"
                    tabindex="0"
                    :aria-current="selectedThreadId === thread.id ? 'page' : undefined"
                    :title="thread.title"
                    @click="openThread(thread.id)"
                    @keydown.enter.prevent="openThread(thread.id)"
                  >
                    <PhChatsCircle :size="13" aria-hidden="true" />
                    <PhPushPin
                      v-if="thread.pinnedAt"
                      :size="11"
                      class="thread-pin"
                      aria-label="已置顶"
                    />
                    <span class="row-label">{{ thread.title }}</span>
                    <small>{{ formatRelative(thread.updatedAt) }}</small>
                    <!-- v0.9.0 H4：线程管理动作（置顶/重命名/归档） -->
                    <span class="thread-actions" @click.stop>
                      <button
                        class="thread-action"
                        :aria-label="thread.pinnedAt ? '取消置顶' : '置顶'"
                        :title="thread.pinnedAt ? '取消置顶' : '置顶'"
                        :disabled="threadActionBusy"
                        :data-testid="`coding-thread-pin-${thread.id}`"
                        @click="void onTogglePin(thread)"
                      >
                        <PhPushPin :size="12" />
                      </button>
                      <button
                        class="thread-action"
                        aria-label="重命名"
                        title="重命名"
                        :disabled="threadActionBusy"
                        :data-testid="`coding-thread-rename-${thread.id}`"
                        @click="void onRenameThread(thread)"
                      >
                        <PhPencil :size="12" />
                      </button>
                      <button
                        class="thread-action"
                        aria-label="归档"
                        title="归档（软删除）"
                        :disabled="threadActionBusy"
                        :data-testid="`coding-thread-archive-${thread.id}`"
                        @click="void onArchiveThread(thread)"
                      >
                        <PhArchive :size="12" />
                      </button>
                    </span>
                  </div>
                  <div v-if="child.threads.length === 0" class="thread-empty">暂无任务</div>
                </div>
              </div>

              <div v-if="node.orphanThreads.length > 0" class="tree-workspace">
                <div class="workspace-row is-static" title="工作区已归档或缺失">
                  <PhGitBranch :size="14" aria-hidden="true" />
                  <span class="row-label">其他任务</span>
                </div>
                <div class="tree-threads" role="group">
                  <button
                    v-for="thread in node.orphanThreads"
                    :key="thread.id"
                    class="thread-row"
                    :class="{ active: selectedThreadId === thread.id }"
                    :data-testid="`coding-thread-${thread.id}`"
                    role="treeitem"
                    :aria-current="selectedThreadId === thread.id ? 'page' : undefined"
                    :title="thread.title"
                    @click="openThread(thread.id)"
                  >
                    <PhChatsCircle :size="13" aria-hidden="true" />
                    <span class="row-label">{{ thread.title }}</span>
                    <small>{{ formatRelative(thread.updatedAt) }}</small>
                  </button>
                </div>
              </div>

              <div v-if="node.workspaces.length === 0" class="tree-empty">
                无工作区，请在首页创建
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- v0.9.0 H4（计划 §8 任务 3）：更多工作区——未绑定 legacy 会话次级入口。
           只呈现与显式逐条绑定（不批量/不猜测）；旧会话仍可读可导出。 -->
      <div v-if="(!collapsed || isNarrow) && loadPhase === 'ready'" class="sidebar-legacy" data-testid="coding-legacy-section">
        <button
          class="legacy-toggle"
          :aria-expanded="legacyOpen"
          data-testid="coding-legacy-toggle"
          @click="legacyOpen = !legacyOpen; legacyOpen && void loadLegacyThreads()"
        >
          <span class="row-caret" :class="{ open: legacyOpen }" aria-hidden="true" />
          更多工作区
          <small v-if="legacyThreads.length">{{ legacyThreads.length }}</small>
        </button>
        <div v-if="legacyOpen" class="legacy-list">
          <div v-if="legacyThreads.length === 0" class="legacy-empty">
            无未绑定的旧会话；也可通过旧界面（?ui=v1）访问全部历史数据。
          </div>
          <div
            v-for="thread in legacyThreads"
            :key="thread.id"
            class="legacy-row"
            :data-testid="`coding-legacy-thread-${thread.id}`"
          >
            <span class="legacy-title" :title="thread.title">{{ thread.title }}</span>
            <select
              class="legacy-bind-select"
              aria-label="绑定到项目"
              :disabled="threadActionBusy"
              :data-testid="`coding-legacy-bind-${thread.id}`"
              @change="(e) => { const v = Number((e.target as HTMLSelectElement).value); if (v) void onBindLegacyThread(thread, v); }"
            >
              <option value="">绑定到项目…</option>
              <option
                v-for="project in props.store.projects.value"
                :key="project.id"
                :value="project.id"
              >{{ project.name }}</option>
            </select>
          </div>
        </div>
      </div>

      <div class="sidebar-footer">
        <div class="footer-rows">
          <button
            class="footer-row"
            :class="{ active: activeView === 'settings' }"
            :aria-current="activeView === 'settings' ? 'page' : undefined"
            :title="collapsed && !isNarrow ? '设置' : undefined"
            :aria-label="collapsed && !isNarrow ? '设置' : undefined"
            data-testid="coding-nav-settings"
            @click="emit('navigate', 'settings')"
          >
            <PhGearSix :size="15" />
            <span class="action-label">设置</span>
          </button>
          <button
            class="footer-row"
            :class="{ active: activeView === 'diagnostics' }"
            :aria-current="activeView === 'diagnostics' ? 'page' : undefined"
            :title="collapsed && !isNarrow ? '诊断' : undefined"
            :aria-label="collapsed && !isNarrow ? '诊断' : undefined"
            data-testid="coding-nav-diagnostics"
            @click="emit('navigate', 'diagnostics')"
          >
            <PhActivity :size="15" />
            <span class="action-label">诊断</span>
          </button>
        </div>

        <div class="footer-user" title="本地用户，数据仅存储在此设备">
          <PhUserCircle :size="22" weight="fill" aria-hidden="true" />
          <div class="user-copy">
            <strong>本地用户</strong>
            <small>数据仅存此设备</small>
          </div>
          <button
            v-if="!isNarrow"
            class="icon-btn"
            :title="collapsed ? '展开侧栏' : '折叠侧栏'"
            :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
            data-testid="coding-toggle-collapse"
            @click="emit('toggle-collapse')"
          >
            <PhSidebarSimple :size="16" />
          </button>
        </div>
      </div>

      <!-- v0.9.0 H1：新建项目对话框（选择并授权工作目录） -->
      <NewProjectDialog
        v-if="newProjectDialogOpen"
        @close="newProjectDialogOpen = false"
        @created="(id) => void onProjectCreated(id)"
      />
    </nav>
  </Teleport>
</template>

<style scoped>
.coding-sidebar {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  background: var(--color-panel);
  border-right: 1px solid var(--color-border);
}
.is-drawer {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: var(--z-overlay);
  width: var(--rail-w);
  max-width: 86vw;
  box-shadow: var(--shadow-lg);
}
.coding-drawer-tab {
  position: fixed;
  top: var(--space-4);
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
.coding-drawer-tab:hover {
  color: var(--color-fg);
}
.coding-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: color-mix(in srgb, var(--color-fg) 24%, transparent);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3);
  border-bottom: 1px solid var(--color-border);
}
.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.brand-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.brand-copy strong {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.brand-tag {
  font-size: var(--pa-text-meta);
  letter-spacing: 0.14em;
  color: var(--color-accent-soft-fg);
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.icon-btn:hover:not(:disabled) {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.icon-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.icon-btn .spin {
  animation: sidebar-spin 0.9s linear infinite;
}
@keyframes sidebar-spin {
  to { transform: rotate(360deg); }
}

.sidebar-actions {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-2) 0;
}
.action-primary {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 34px;
  padding: 0 var(--space-3);
  border: 1px solid color-mix(in srgb, var(--color-accent) 36%, var(--color-border));
  border-radius: var(--radius-md);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
}
.action-primary:hover {
  filter: brightness(0.97);
}
.action-primary.active {
  outline: var(--focus-ring);
  outline-offset: -2px;
}
.action-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 30px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  cursor: pointer;
}
.action-item:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.action-item.active {
  background: var(--color-surface-muted);
  color: var(--color-fg);
  font-weight: var(--font-medium);
}
.action-item[aria-current="page"] {
  box-shadow: inset 2px 0 0 var(--color-accent);
}

.sidebar-personal {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-2) 0;
  border-top: 1px solid var(--color-border);
  margin-top: var(--space-2);
}
.personal-heading {
  padding: 0 var(--space-2) var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  letter-spacing: 0.08em;
}
.personal-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.personal-item {
  position: relative;
}
.personal-badge {
  margin-left: auto;
  min-width: 18px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
  text-align: center;
}
.is-collapsed .personal-badge {
  position: absolute;
  top: 2px;
  right: 10px;
  min-width: 8px;
  height: 8px;
  padding: 0;
  overflow: hidden;
  color: transparent;
}

.sidebar-tree {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  padding: var(--space-2) var(--space-2) 0;
}
.tree-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  letter-spacing: 0.08em;
}
.tree-empty {
  padding: var(--space-2) var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
}
.tree-scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding-bottom: var(--space-2);
}

.row-caret {
  width: 0;
  height: 0;
  flex-shrink: 0;
  border-top: 3px solid transparent;
  border-bottom: 3px solid transparent;
  border-left: 4px solid var(--color-fg-subtle);
  transition: transform var(--pa-motion-fast) var(--ease);
}
.row-caret.open {
  transform: rotate(90deg);
}

.project-row,
.workspace-row,
.thread-row {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-muted);
  text-align: left;
  cursor: pointer;
}
.project-row {
  height: 30px;
  padding: 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.project-row:hover,
.workspace-row:hover,
.thread-row:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.project-row.active,
.workspace-row.active {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.thread-row {
  height: 28px;
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
}
.thread-row.active {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.row-label {
  overflow: hidden;
  min-width: 0;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-row small {
  flex-shrink: 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
/* v0.9.0 H4：线程管理动作与更多工作区 */
.recent-block {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: var(--space-1) var(--space-2) var(--space-2);
}
.recent-heading {
  padding: var(--space-1) var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.thread-row:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring, 0 0 0 2px rgba(80, 140, 200, 0.55));
}
.thread-pin {
  flex-shrink: 0;
  color: var(--color-accent);
}
.thread-actions {
  display: none;
  flex-shrink: 0;
  align-items: center;
  gap: 2px;
}
.thread-row:hover .thread-actions,
.thread-row:focus-within .thread-actions {
  display: inline-flex;
}
.thread-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
}
.thread-action:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.thread-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.sidebar-legacy {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border);
}
.legacy-toggle {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-2);
  border: none;
  background: transparent;
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
  cursor: pointer;
}
.legacy-toggle small {
  color: var(--color-fg-subtle);
}
.legacy-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) 0 0 var(--space-3);
}
.legacy-empty {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  line-height: 1.5;
}
.legacy-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.legacy-title {
  overflow: hidden;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.legacy-bind-select {
  height: 22px;
  padding: 0 var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.tree-children {
  padding-left: var(--space-3);
}
.tree-threads {
  padding-left: var(--space-4);
}
.thread-empty {
  padding: var(--space-1) var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.workspace-row.is-static {
  cursor: default;
}
.workspace-row.is-static:hover {
  background: transparent;
}

.status-dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-fg-subtle);
}
.status-dot.tone-info {
  background: var(--color-accent);
}
.status-dot.tone-warning {
  background: var(--color-warning);
}
.status-dot.tone-danger {
  background: var(--color-danger);
}

.sidebar-footer {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
}
.footer-rows {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.footer-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 30px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  cursor: pointer;
}
.footer-row:hover,
.footer-row.active {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.footer-row[aria-current="page"] {
  box-shadow: inset 2px 0 0 var(--color-accent);
}
.footer-user {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-1) 0;
  color: var(--color-fg-muted);
}
.footer-user .icon-btn {
  margin-left: auto;
}
.user-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.user-copy strong {
  color: var(--color-fg);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
}
.user-copy small {
  font-size: var(--pa-text-meta);
  color: var(--color-fg-subtle);
}

/* 折叠态（72px 图标侧栏）：隐藏文字标签与树，仅保留图标动作 */
.is-collapsed .brand-copy,
.is-collapsed .action-label,
.is-collapsed .user-copy {
  display: none;
}
.is-collapsed .sidebar-brand,
.is-collapsed .action-primary,
.is-collapsed .action-item,
.is-collapsed .footer-row {
  justify-content: center;
  padding: 0;
}
.is-collapsed .footer-user {
  justify-content: center;
}
.is-collapsed .sidebar-actions {
  align-items: stretch;
}

@media (prefers-reduced-motion: reduce) {
  .row-caret,
  .icon-btn .spin {
    transition: none;
    animation: none;
  }
}
</style>
