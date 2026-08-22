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
  PhPlus,
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
import {
  WORKSPACE_STATUS_META,
  type CodingProjectNode,
} from "../model/contracts";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";

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

function branchLabel(node: { workspace: { kind: string; branchName: string | null } }): string {
  if (node.workspace.branchName) return node.workspace.branchName;
  return node.workspace.kind === "root" ? "根工作区" : "工作区";
}

function workspaceStatusTone(status: keyof typeof WORKSPACE_STATUS_META): string {
  return WORKSPACE_STATUS_META[status].tone;
}

function formatRelative(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (date.toDateString() === new Date().toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return `${date.getMonth() + 1}/${date.getDate()}`;
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
          :title="collapsed && !isNarrow ? '新建任务' : undefined"
          :aria-label="collapsed && !isNarrow ? '新建任务' : undefined"
          data-testid="coding-new-task"
          @click="onNewTask"
        >
          <PhPlus :size="16" weight="bold" />
          <span class="action-label">新建任务</span>
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
            @click="props.store.refresh()"
          >
            <PhArrowClockwise :size="14" :class="{ spin: loadPhase === 'loading' }" />
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
                  <button
                    v-for="thread in child.threads"
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
