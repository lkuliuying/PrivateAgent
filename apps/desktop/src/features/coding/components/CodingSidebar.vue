<script setup lang="ts">
/**
 * Coding Agent 左侧栏。
 *
 * 常规窗口使用紧凑的单层导航与最近对话；项目树按需展开。窄窗口以覆盖抽屉
 * 呈现，避免压缩主工作区。组件只消费 codingWorkspaceStore，不直接读取项目 API。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  PhActivity,
  PhArchive,
  PhArrowClockwise,
  PhBell,
  PhCaretDown,
  PhChatsCircle,
  PhFolderSimple,
  PhGitBranch,
  PhListChecks,
  PhMagnifyingGlass,
  PhNotePencil,
  PhPencil,
  PhPlus,
  PhPushPin,
  PhPuzzlePiece,
  PhQuestion,
  PhSidebarSimple,
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
import {
  fetchRecentThreads,
  renameThread,
  setThreadArchived,
  setThreadPinned,
} from "../api/threads";
import NewProjectDialog from "./NewProjectDialog.vue";

const notify = useNotifications();

const props = withDefaults(
  defineProps<{
    store?: CodingWorkspaceStore;
    activeView?: View;
    collapsed?: boolean;
  }>(),
  {
    store: () => useCodingWorkspace(),
    activeView: "coding" as View,
    collapsed: false,
  }
);

const emit = defineEmits<{
  navigate: [view: View];
  "new-task": [];
  "open-command": [];
  "toggle-collapse": [];
  "project-created": [projectId: number];
}>();

const tree = computed(() => props.store.tree.value);
const loadPhase = computed(() => props.store.loadPhase.value);
const selectedProjectId = computed(() => props.store.selectedProjectId.value);
const selectedWorkspaceId = computed(() => props.store.selectedWorkspaceId.value);
const selectedThreadId = computed(() => props.store.selectedThreadId.value);
const onCodingHome = computed(
  () => props.activeView === "coding" && selectedThreadId.value === null
);

const projectsExpanded = ref(false);
const projectOpen = ref<Record<number, boolean>>({});
const workspaceOpen = ref<Record<string, boolean>>({});

function workspaceKey(projectId: number, workspaceId: number): string {
  return `${projectId}:${workspaceId}`;
}

function navigate(view: View): void {
  emit("navigate", view);
  if (isNarrow.value) drawerOpen.value = false;
}

function toggleProjects(): void {
  projectsExpanded.value = !projectsExpanded.value;
  if (!projectsExpanded.value) return;

  const projectId = selectedProjectId.value ?? tree.value[0]?.project.id ?? null;
  if (projectId !== null) {
    projectOpen.value = { ...projectOpen.value, [projectId]: true };
  }
}

function toggleProject(node: CodingProjectNode): void {
  const next = !projectOpen.value[node.project.id];
  projectOpen.value = { ...projectOpen.value, [node.project.id]: next };
  if (next) {
    props.store.selectProject(node.project.id);
    navigate("coding");
  }
}

function toggleWorkspace(projectId: number, workspaceId: number): void {
  const key = workspaceKey(projectId, workspaceId);
  workspaceOpen.value = { ...workspaceOpen.value, [key]: !workspaceOpen.value[key] };
}

function openThread(threadId: number): void {
  props.store.selectThread(threadId);
  navigate("coding");
}

function onNewTask(): void {
  props.store.startNewTask();
  emit("new-task");
  navigate("coding");
}

const newProjectDialogOpen = ref(false);

function openNewProjectDialog(): void {
  newProjectDialogOpen.value = true;
}

async function onProjectCreated(projectId: number): Promise<void> {
  newProjectDialogOpen.value = false;
  emit("project-created", projectId);
  await props.store.refresh();
  if (projectId > 0) {
    projectsExpanded.value = true;
    projectOpen.value = { ...projectOpen.value, [projectId]: true };
    props.store.selectProject(projectId);
    navigate("coding");
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
  const formatted = timeFormatRelative(value);
  return formatted === "—" ? "" : formatted;
}

const threadActionBusy = ref(false);

async function refreshThreads(): Promise<void> {
  await props.store.refresh();
  await loadRecentThreads();
}

async function onTogglePin(thread: CodingThreadSummary): Promise<void> {
  if (threadActionBusy.value) return;
  threadActionBusy.value = true;
  try {
    await setThreadPinned(thread.id, !thread.pinnedAt);
    await refreshThreads();
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
    await refreshThreads();
  } finally {
    threadActionBusy.value = false;
  }
}

async function onArchiveThread(thread: CodingThreadSummary): Promise<void> {
  if (threadActionBusy.value) return;
  const confirmed = await notify.confirm({
    title: `归档对话「${thread.title}」？`,
    message: "归档为软删除，可通过搜索恢复。",
    impact: "不会物理删除消息与审计记录。",
    confirmLabel: "归档",
  });
  if (!confirmed) return;

  threadActionBusy.value = true;
  try {
    await setThreadArchived(thread.id, true);
    await refreshThreads();
  } finally {
    threadActionBusy.value = false;
  }
}

const recentThreads = ref<CodingThreadSummary[]>([]);

const treeRecentThreads = computed(() => {
  const deduped = new Map<number, CodingThreadSummary>();
  for (const node of tree.value) {
    for (const child of node.workspaces) {
      for (const thread of child.threads) deduped.set(thread.id, thread);
    }
    for (const thread of node.orphanThreads) deduped.set(thread.id, thread);
  }
  return [...deduped.values()]
    .sort((left, right) => {
      const pinOrder = Number(Boolean(right.pinnedAt)) - Number(Boolean(left.pinnedAt));
      return pinOrder || right.updatedAt.localeCompare(left.updatedAt);
    })
    .slice(0, 14);
});

const visibleRecentThreads = computed(() => {
  const merged = new Map<number, CodingThreadSummary>();
  for (const thread of recentThreads.value) merged.set(thread.id, thread);
  for (const thread of treeRecentThreads.value) merged.set(thread.id, thread);
  return [...merged.values()]
    .sort((left, right) => {
      const pinOrder = Number(Boolean(right.pinnedAt)) - Number(Boolean(left.pinnedAt));
      return pinOrder || right.updatedAt.localeCompare(left.updatedAt);
    })
    .slice(0, 14);
});

async function loadRecentThreads(): Promise<void> {
  try {
    recentThreads.value = await fetchRecentThreads(14);
  } catch {
    recentThreads.value = [];
  }
}

function openRecentThread(thread: CodingThreadSummary): void {
  if (thread.projectId) props.store.selectProject(thread.projectId);
  props.store.selectThread(thread.id);
  navigate("coding");
}

function openNotifications(): void {
  notify.openCenter();
  if (isNarrow.value) drawerOpen.value = false;
}

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
  <Teleport to="body">
    <button
      v-if="isNarrow && !drawerOpen"
      class="coding-drawer-tab"
      data-testid="coding-drawer-tab"
      aria-label="打开 Coding Agent 侧栏"
      @click="drawerOpen = true"
    >
      <PhSidebarSimple :size="17" />
    </button>

    <div
      v-if="isNarrow && drawerOpen"
      class="coding-drawer-backdrop"
      data-testid="coding-drawer-backdrop"
      @click="drawerOpen = false"
    />
  </Teleport>

  <Teleport to="body" :disabled="!isNarrow">
    <nav
      v-if="!isNarrow || drawerOpen"
      class="coding-sidebar"
      :class="{ 'is-collapsed': collapsed && !isNarrow, 'is-drawer': isNarrow }"
      data-testid="coding-sidebar"
      aria-label="Coding Agent 导航"
    >
      <header class="sidebar-brand">
        <button
          type="button"
          class="brand-home"
          aria-label="返回 Coding Agent 首页"
          @click="navigate('coding')"
        >
          <span class="brand-copy">PrivateAgent</span>
          <PhCaretDown class="brand-caret" :size="13" />
        </button>
        <div class="brand-tools">
          <button
            type="button"
            class="icon-btn"
            aria-label="搜索"
            data-testid="coding-open-search"
            @click="emit('open-command')"
          >
            <PhMagnifyingGlass :size="17" />
          </button>
          <button type="button" class="icon-btn notification-button" aria-label="通知" @click="openNotifications">
            <PhBell :size="17" />
            <span v-if="notify.unreadCount.value > 0" class="notification-dot" />
          </button>
          <button
            v-if="isNarrow"
            type="button"
            class="icon-btn"
            aria-label="收起侧栏"
            data-testid="coding-drawer-close"
            @click="drawerOpen = false"
          >
            <PhX :size="17" />
          </button>
        </div>
      </header>

      <div class="sidebar-scroll-region">
        <div class="sidebar-actions">
          <button
            type="button"
            class="nav-row"
            :class="{ active: onCodingHome }"
            :title="collapsed && !isNarrow ? '新对话' : undefined"
            :aria-label="collapsed && !isNarrow ? '新对话' : undefined"
            data-testid="coding-new-task"
            @click="onNewTask"
          >
            <PhNotePencil :size="18" />
            <span class="action-label">新对话</span>
            <span class="row-trailing"><PhPlus :size="15" /></span>
          </button>

          <div class="nav-row-wrap">
            <button
              type="button"
              class="nav-row"
              :class="{ active: projectsExpanded }"
              :aria-expanded="projectsExpanded"
              :title="collapsed && !isNarrow ? '项目' : undefined"
              :aria-label="collapsed && !isNarrow ? '项目' : undefined"
              data-testid="coding-toggle-projects"
              @click="toggleProjects"
            >
              <PhFolderSimple :size="18" />
              <span class="action-label">项目</span>
            </button>
            <button
              v-if="!collapsed || isNarrow"
              type="button"
              class="row-action"
              aria-label="新建项目"
              title="新建项目"
              data-testid="coding-new-project"
              @click="openNewProjectDialog"
            >
              <PhPlus :size="15" />
            </button>
          </div>

          <button
            type="button"
            class="nav-row"
            :class="{ active: activeView === 'tasks' }"
            :aria-current="activeView === 'tasks' ? 'page' : undefined"
            :title="collapsed && !isNarrow ? '自动化' : undefined"
            :aria-label="collapsed && !isNarrow ? '自动化' : undefined"
            data-testid="coding-nav-tasks"
            @click="navigate('tasks')"
          >
            <PhListChecks :size="18" />
            <span class="action-label">自动化</span>
          </button>

          <button
            type="button"
            class="nav-row"
            :class="{ active: activeView === 'extensions' }"
            :aria-current="activeView === 'extensions' ? 'page' : undefined"
            :title="collapsed && !isNarrow ? '插件' : undefined"
            :aria-label="collapsed && !isNarrow ? '插件' : undefined"
            data-testid="coding-nav-extensions"
            @click="navigate('extensions')"
          >
            <PhPuzzlePiece :size="18" />
            <span class="action-label">插件</span>
          </button>
        </div>

        <section
          v-if="(!collapsed || isNarrow) && projectsExpanded"
          class="project-section"
          data-testid="coding-tree"
          aria-label="项目与工作区"
        >
          <div class="section-heading">
            <span>项目</span>
            <button
              type="button"
              class="icon-btn"
              aria-label="刷新项目"
              data-testid="coding-refresh"
              :disabled="loadPhase === 'loading'"
              @click="props.store.refresh(); void loadRecentThreads()"
            >
              <PhArrowClockwise :size="14" :class="{ spin: loadPhase === 'loading' }" />
            </button>
          </div>

          <div v-if="tree.length === 0" class="tree-empty">
            {{ loadPhase === "loading" ? "正在加载项目…" : "暂无项目，新建后会显示在这里" }}
          </div>

          <div v-else class="project-tree" role="tree" aria-label="项目与对话树">
            <div v-for="node in tree" :key="node.project.id" role="none">
              <button
                type="button"
                class="tree-row project-row"
                :class="{ active: selectedProjectId === node.project.id && selectedThreadId === null }"
                :data-testid="`coding-project-${node.project.id}`"
                :aria-expanded="projectOpen[node.project.id] ?? false"
                role="treeitem"
                @click="toggleProject(node)"
              >
                <span class="row-caret" :class="{ open: projectOpen[node.project.id] }" />
                <PhFolderSimple :size="15" />
                <span class="row-label">{{ node.project.name }}</span>
              </button>

              <div v-if="projectOpen[node.project.id]" class="tree-children" role="group">
                <div v-for="child in node.workspaces" :key="child.workspace.id" role="none">
                  <button
                    type="button"
                    class="tree-row workspace-row"
                    :class="{ active: selectedWorkspaceId === child.workspace.id && selectedThreadId === null }"
                    :data-testid="`coding-workspace-${child.workspace.id}`"
                    :data-status="child.workspace.status"
                    :aria-expanded="workspaceOpen[workspaceKey(node.project.id, child.workspace.id)] ?? false"
                    role="treeitem"
                    :title="`分支 ${branchLabel(child)} · ${WORKSPACE_STATUS_META[child.workspace.status].label}`"
                    @click="toggleWorkspace(node.project.id, child.workspace.id)"
                  >
                    <span
                      class="row-caret"
                      :class="{ open: workspaceOpen[workspaceKey(node.project.id, child.workspace.id)] }"
                    />
                    <PhGitBranch :size="14" />
                    <span class="row-label">{{ branchLabel(child) }}</span>
                    <span
                      class="status-dot"
                      :class="`tone-${workspaceStatusTone(child.workspace.status)}`"
                      :aria-label="WORKSPACE_STATUS_META[child.workspace.status].label"
                    />
                  </button>

                  <div
                    v-if="workspaceOpen[workspaceKey(node.project.id, child.workspace.id)]"
                    class="tree-threads"
                    role="group"
                  >
                    <div
                      v-for="thread in child.threads"
                      :key="thread.id"
                      class="tree-row thread-row"
                      :class="{ active: selectedThreadId === thread.id }"
                      :data-testid="`coding-tree-thread-${thread.id}`"
                      role="treeitem"
                      tabindex="0"
                      :aria-current="selectedThreadId === thread.id ? 'page' : undefined"
                      :title="thread.title"
                      @click="openThread(thread.id)"
                      @keydown.enter.prevent="openThread(thread.id)"
                    >
                      <PhChatsCircle :size="13" />
                      <span class="row-label">{{ thread.title }}</span>
                      <small>{{ formatRelative(thread.updatedAt) }}</small>
                      <span class="thread-actions" @click.stop>
                        <button
                          type="button"
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
                          type="button"
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
                          type="button"
                          class="thread-action"
                          aria-label="归档"
                          title="归档"
                          :disabled="threadActionBusy"
                          :data-testid="`coding-thread-archive-${thread.id}`"
                          @click="void onArchiveThread(thread)"
                        >
                          <PhArchive :size="12" />
                        </button>
                      </span>
                    </div>
                    <div v-if="child.threads.length === 0" class="thread-empty">暂无对话</div>
                  </div>
                </div>

                <div v-if="node.orphanThreads.length > 0">
                  <div class="tree-row workspace-row is-static" title="工作区已归档或缺失">
                    <PhGitBranch :size="14" />
                    <span class="row-label">其他对话</span>
                  </div>
                  <div class="tree-threads" role="group">
                    <button
                      v-for="thread in node.orphanThreads"
                      :key="thread.id"
                      type="button"
                      class="tree-row thread-row"
                      :class="{ active: selectedThreadId === thread.id }"
                      :data-testid="`coding-tree-thread-${thread.id}`"
                      role="treeitem"
                      :aria-current="selectedThreadId === thread.id ? 'page' : undefined"
                      :title="thread.title"
                      @click="openThread(thread.id)"
                    >
                      <PhChatsCircle :size="13" />
                      <span class="row-label">{{ thread.title }}</span>
                    </button>
                  </div>
                </div>

                <div v-if="node.workspaces.length === 0" class="tree-empty">暂无工作区</div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="!collapsed || isNarrow" class="recent-section" data-testid="coding-recent">
          <div class="section-heading recent-heading"><span>最近</span></div>
          <div v-if="visibleRecentThreads.length === 0" class="recent-empty">
            新建对话后会显示在这里
          </div>
          <button
            v-for="thread in visibleRecentThreads"
            :key="`recent-${thread.id}`"
            type="button"
            class="recent-row"
            :class="{ active: selectedThreadId === thread.id }"
            :data-testid="`coding-thread-${thread.id}`"
            :title="thread.title"
            @click="openRecentThread(thread)"
          >
            <PhPushPin v-if="thread.pinnedAt" :size="13" class="recent-pin" />
            <span class="row-label">{{ thread.title }}</span>
            <PhGitBranch class="recent-branch" :size="14" />
          </button>
        </section>
      </div>

      <footer class="sidebar-footer">
        <button
          type="button"
          class="footer-user"
          :class="{ active: activeView === 'settings' }"
          aria-label="打开设置"
          data-testid="coding-nav-settings"
          @click="navigate('settings')"
        >
          <PhUserCircle :size="24" weight="fill" />
          <span class="user-copy">
            <strong>本地用户</strong>
            <small>数据仅存此设备</small>
          </span>
        </button>
        <div class="footer-tools">
          <button
            type="button"
            class="icon-btn"
            :class="{ active: activeView === 'diagnostics' }"
            aria-label="诊断"
            title="诊断"
            data-testid="coding-nav-diagnostics"
            @click="navigate('diagnostics')"
          >
            <PhActivity :size="16" />
          </button>
          <button type="button" class="icon-btn" aria-label="帮助与诊断" title="帮助与诊断" @click="navigate('diagnostics')">
            <PhQuestion :size="16" />
          </button>
          <button
            v-if="!isNarrow"
            type="button"
            class="icon-btn"
            :title="collapsed ? '展开侧栏' : '折叠侧栏'"
            :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
            data-testid="coding-toggle-collapse"
            @click="emit('toggle-collapse')"
          >
            <PhSidebarSimple :size="16" />
          </button>
        </div>
      </footer>

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
  overflow: hidden;
  border-right: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-panel) 86%, var(--color-surface-muted));
  color: var(--color-fg);
}
.is-drawer {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: var(--z-overlay);
  width: min(var(--rail-w), calc(100vw - 48px));
  box-shadow: var(--shadow-lg);
}
.coding-drawer-tab {
  position: fixed;
  top: var(--space-4);
  left: var(--space-3);
  z-index: var(--z-overlay);
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface);
  color: var(--color-fg-muted);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
}
.coding-drawer-tab:hover { background: var(--color-surface-muted); color: var(--color-fg); }
.coding-drawer-tab:focus-visible,
.coding-sidebar button:focus-visible { outline: var(--focus-ring); outline-offset: -2px; }
.coding-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: color-mix(in srgb, var(--color-fg) 22%, transparent);
}
.sidebar-brand {
  display: flex;
  min-height: 58px;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
}
.brand-home {
  display: flex;
  min-width: 0;
  height: 36px;
  align-items: center;
  gap: 4px;
  padding: 0 var(--space-1);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg);
  cursor: pointer;
}
.brand-home:hover { background: var(--color-surface-muted); }
.brand-copy {
  overflow: hidden;
  font-size: var(--pa-text-section);
  font-weight: var(--font-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.brand-caret { flex-shrink: 0; color: var(--color-fg-subtle); }
.brand-tools { display: flex; align-items: center; gap: 2px; margin-left: auto; }
.icon-btn,
.row-action,
.thread-action {
  display: inline-grid;
  flex-shrink: 0;
  place-items: center;
  border: 0;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.icon-btn { width: 30px; height: 30px; border-radius: var(--radius-md); }
.icon-btn:hover:not(:disabled),
.row-action:hover,
.thread-action:hover { background: var(--color-surface-hover); color: var(--color-fg); }
.icon-btn:disabled { opacity: .45; cursor: default; }
.notification-button { position: relative; }
.notification-dot {
  position: absolute;
  top: 5px;
  right: 5px;
  width: 6px;
  height: 6px;
  border: 1px solid var(--color-panel);
  border-radius: var(--radius-full);
  background: var(--color-danger);
}
.sidebar-scroll-region {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 var(--space-2) var(--space-3);
  scrollbar-width: thin;
  scrollbar-color: var(--color-border-strong) transparent;
}
.sidebar-actions { display: flex; flex-direction: column; gap: 2px; }
.nav-row-wrap { position: relative; }
.nav-row {
  display: flex;
  width: 100%;
  min-width: 0;
  height: 36px;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-base);
  text-align: left;
  cursor: pointer;
}
.nav-row:hover,
.nav-row.active { background: var(--color-surface-muted); color: var(--color-fg); }
.nav-row.active { font-weight: var(--font-medium); }
.row-trailing {
  display: inline-grid;
  width: 24px;
  height: 24px;
  margin-left: auto;
  place-items: center;
  border-radius: var(--radius-full);
  color: var(--color-fg-subtle);
}
.row-action {
  position: absolute;
  top: 6px;
  right: var(--space-2);
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full);
}
.action-label { overflow: hidden; min-width: 0; text-overflow: ellipsis; white-space: nowrap; }
.project-section,
.recent-section { margin-top: var(--space-5); }
.section-heading {
  display: flex;
  min-height: 26px;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
}
.tree-empty,
.recent-empty,
.thread-empty {
  padding: var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
}
.project-tree,
.tree-children,
.tree-threads { display: flex; flex-direction: column; gap: 1px; }
.tree-children { padding-left: var(--space-3); }
.tree-threads { padding-left: var(--space-4); }
.tree-row {
  display: flex;
  width: 100%;
  min-width: 0;
  height: 30px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  text-align: left;
  cursor: pointer;
}
.project-row { font-size: var(--text-sm); font-weight: var(--font-medium); }
.tree-row:hover,
.tree-row.active { background: var(--color-surface-muted); color: var(--color-fg); }
.thread-row.active { background: var(--color-surface-hover); }
.row-caret {
  width: 0;
  height: 0;
  flex-shrink: 0;
  border-top: 3px solid transparent;
  border-bottom: 3px solid transparent;
  border-left: 4px solid currentColor;
  transition: transform var(--pa-motion-fast) var(--ease);
}
.row-caret.open { transform: rotate(90deg); }
.row-label { overflow: hidden; min-width: 0; flex: 1; text-overflow: ellipsis; white-space: nowrap; }
.thread-row small { flex-shrink: 0; color: var(--color-fg-faint); font-size: var(--pa-text-meta); }
.status-dot {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-fg-faint);
}
.status-dot.tone-info { background: var(--color-accent); }
.status-dot.tone-warning { background: var(--color-warning); }
.status-dot.tone-danger { background: var(--color-danger); }
.workspace-row.is-static { cursor: default; }
.workspace-row.is-static:hover { background: transparent; }
.thread-actions { display: none; flex-shrink: 0; align-items: center; gap: 1px; }
.thread-row:hover .thread-actions,
.thread-row:focus-within .thread-actions { display: inline-flex; }
.thread-action { width: 19px; height: 19px; border-radius: var(--radius-sm); }
.recent-heading { margin-bottom: 2px; }
.recent-row {
  display: flex;
  width: 100%;
  min-width: 0;
  height: 34px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-base);
  text-align: left;
  cursor: pointer;
}
.recent-row:hover,
.recent-row.active { background: var(--color-surface-hover); color: var(--color-fg); }
.recent-pin { flex-shrink: 0; color: var(--color-accent); }
.recent-branch { flex-shrink: 0; color: color-mix(in srgb, var(--color-accent) 72%, #8d4cff); }
.sidebar-footer {
  display: flex;
  min-height: 58px;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
}
.footer-user {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  text-align: left;
  cursor: pointer;
}
.footer-user:hover,
.footer-user.active { background: var(--color-surface-muted); color: var(--color-fg); }
.user-copy { display: flex; min-width: 0; flex-direction: column; }
.user-copy strong { overflow: hidden; color: var(--color-fg); font-size: var(--text-xs); font-weight: var(--font-medium); text-overflow: ellipsis; white-space: nowrap; }
.user-copy small { overflow: hidden; color: var(--color-fg-faint); font-size: var(--pa-text-meta); text-overflow: ellipsis; white-space: nowrap; }
.footer-tools { display: flex; align-items: center; }
.icon-btn.active { background: var(--color-surface-muted); color: var(--color-fg); }
.spin { animation: sidebar-spin .9s linear infinite; }
@keyframes sidebar-spin { to { transform: rotate(360deg); } }

.is-collapsed .brand-copy,
.is-collapsed .brand-caret,
.is-collapsed .action-label,
.is-collapsed .row-trailing,
.is-collapsed .user-copy,
.is-collapsed .footer-tools { display: none; }
.is-collapsed .sidebar-brand,
.is-collapsed .nav-row,
.is-collapsed .footer-user { justify-content: center; padding-inline: 0; }
.is-collapsed .brand-tools { display: none; }
.is-collapsed .sidebar-scroll-region { padding-inline: var(--space-2); }
.is-collapsed .sidebar-footer { justify-content: center; }

@media (max-height: 620px) {
  .sidebar-brand { min-height: 50px; }
  .nav-row { height: 32px; }
  .project-section,
  .recent-section { margin-top: var(--space-3); }
  .sidebar-footer { min-height: 50px; }
}
@media (prefers-reduced-motion: reduce) {
  .row-caret { transition: none; }
  .spin { animation: none; }
}
</style>
