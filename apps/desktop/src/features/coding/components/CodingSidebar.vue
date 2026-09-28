<script setup lang="ts">
/**
 * Coding Agent 左侧栏。
 *
 * 常规窗口使用紧凑导航，并把对话归入所属项目。窄窗口以覆盖抽屉呈现，
 * 避免压缩主工作区。组件只消费 codingWorkspaceStore，不直接读取项目 API。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhCaretDown,
  PhGearSix,
  PhHouse,
  PhChatsCircle,
  PhFolderSimple,
  PhGitBranch,
  PhMagnifyingGlass,
  PhNotePencil,
  PhPencil,
  PhPlus,
  PhPushPin,
  PhPuzzlePiece,
  PhSidebarSimple,
  PhTrash,
  PhX,
} from "@phosphor-icons/vue";
import type { View } from "../../../types";
import { formatRelative as timeFormatRelative } from "../../../services/timeDisplay";
import { useNotifications } from "../../../stores/notifications";
import {
  WORKSPACE_STATUS_META,
  type CodingProjectNode,
  type CodingProjectSummary,
  type CodingThreadSummary,
  type CodingWorkspaceSummary,
} from "../model/contracts";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";
import {
  renameThread,
  deleteThread,
  setThreadPinned,
} from "../api/threads";
import { deleteCodingProject, setCodingProjectPinned } from "../api/projects";
import NewProjectDialog from "./NewProjectDialog.vue";
import EditProjectDialog from "./EditProjectDialog.vue";
import UserMenu from "../../../components/UserMenu.vue";

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
const selectedThreadId = computed(() => props.store.selectedThreadId.value);
const onCodingHome = computed(
  () => props.activeView === "coding" && selectedThreadId.value === null
);

const sidebarRoot = ref<HTMLElement>();
function closeRowMenus(event?: PointerEvent) {
  sidebarRoot.value?.querySelectorAll<HTMLDetailsElement>(".row-actions-menu[open]").forEach(menu => {
    if (!event || !menu.contains(event.target as Node)) menu.open = false;
  });
}
async function toggleRowMenu(event: Event) {
  const menu = event.target as HTMLDetailsElement;
  if (!menu.open) return;
  activeThreadDetails.value = null;
  sidebarRoot.value?.querySelectorAll<HTMLDetailsElement>(".row-actions-menu[open]").forEach(other => { if (other !== menu) other.open = false; });
  await nextTick();
  const trigger = menu.querySelector("summary")!, list = menu.querySelector<HTMLElement>(".row-actions-list")!;
  const rect = trigger.getBoundingClientRect();
  list.style.left = `${Math.max(8, Math.min(rect.right - list.offsetWidth, window.innerWidth - list.offsetWidth - 8))}px`;
  list.style.top = `${Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - list.offsetHeight - 8))}px`;
}
function rowMenuClick(event: MouseEvent) {
  if ((event.target as HTMLElement).closest("button")) (event.currentTarget as HTMLDetailsElement).open = false;
}
function rowMenuKeydown(event: KeyboardEvent) {
  const menu = event.currentTarget as HTMLDetailsElement;
  if (event.key === "Escape") {
    event.preventDefault(); menu.open = false; menu.querySelector("summary")?.focus(); return;
  }
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault(); menu.open = true;
  const buttons = [...menu.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
  buttons[event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
}

const projectsExpanded = ref(true);
const projectOpen = ref<Record<number, boolean>>({});

interface ProjectThreadItem {
  thread: CodingThreadSummary;
  workspace: CodingWorkspaceSummary | null;
}

interface ThreadDetailsState {
  threadId: number;
  top: number;
  left: number;
}

const activeThreadDetails = ref<ThreadDetailsState | null>(null);

function navigate(view: View): void {
  emit("navigate", view);
  if (isNarrow.value) drawerOpen.value = false;
}

function toggleProjects(): void {
  projectsExpanded.value = !projectsExpanded.value;
}

function toggleProject(node: CodingProjectNode): void {
  const next = !isProjectOpen(node.project.id);
  projectOpen.value = { ...projectOpen.value, [node.project.id]: next };
  if (next) {
    props.store.selectProject(node.project.id);
    navigate("coding");
  }
}

function isProjectOpen(projectId: number): boolean {
  return projectOpen.value[projectId] ?? true;
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
const editingProjectId = ref<number | null>(null);

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

function projectThreads(node: CodingProjectNode): ProjectThreadItem[] {
  const items: ProjectThreadItem[] = [];
  for (const child of node.workspaces) {
    for (const thread of child.threads) {
      items.push({ thread, workspace: child.workspace });
    }
  }
  for (const thread of node.orphanThreads) {
    items.push({ thread, workspace: null });
  }
  return items.sort((left, right) => {
    const pinOrder = Number(Boolean(right.thread.pinnedAt)) - Number(Boolean(left.thread.pinnedAt));
    return pinOrder || right.thread.updatedAt.localeCompare(left.thread.updatedAt);
  });
}

const activeThreadContext = computed(() => {
  const threadId = activeThreadDetails.value?.threadId;
  if (threadId === undefined) return null;
  for (const node of tree.value) {
    const item = projectThreads(node).find((candidate) => candidate.thread.id === threadId);
    if (item) return { node, item };
  }
  return null;
});

function branchLabel(node: { workspace: { kind: string; branchName: string | null } }): string {
  if (node.workspace.branchName) return node.workspace.branchName;
  return node.workspace.kind === "root" ? "根工作区" : "工作区";
}

function formatRelative(value: string): string {
  const formatted = timeFormatRelative(value);
  return formatted === "—" ? "" : formatted;
}

function detailBranch(item: ProjectThreadItem): string {
  return item.workspace ? branchLabel({ workspace: item.workspace }) : "工作区已归档或缺失";
}

function detailWorkspaceStatus(item: ProjectThreadItem): string {
  return item.workspace ? WORKSPACE_STATUS_META[item.workspace.status].label : "不可用";
}

function showThreadDetails(threadId: number, event: Event): void {
  const row = event.currentTarget as HTMLElement | null;
  if (!row || typeof window === "undefined") return;
  const rect = row.getBoundingClientRect();
  const width = 360;
  const estimatedHeight = 142;
  const gap = 8;
  const viewportPadding = 8;
  const preferredLeft = rect.right + gap;
  const left =
    preferredLeft + width <= window.innerWidth - viewportPadding
      ? preferredLeft
      : Math.max(viewportPadding, rect.left - width - gap);
  const top = Math.min(
    Math.max(viewportPadding, rect.top - 8),
    Math.max(viewportPadding, window.innerHeight - estimatedHeight - viewportPadding)
  );
  activeThreadDetails.value = { threadId, top, left };
}

function hideThreadDetails(threadId: number, event?: FocusEvent): void {
  if (activeThreadDetails.value?.threadId !== threadId) return;
  const row = event?.currentTarget as HTMLElement | null;
  const next = event?.relatedTarget as Node | null;
  if (row && next && row.contains(next)) return;
  activeThreadDetails.value = null;
}

const threadActionBusy = ref(false);
let alive = true;

async function refreshThreads(): Promise<void> {
  await props.store.refresh();
}

async function performAction(action: () => Promise<void>): Promise<void> {
  if (threadActionBusy.value) return;
  threadActionBusy.value = true;
  try {
    await action();
  } catch (cause) {
    if (alive) notify.error("操作失败", (cause as { message?: string } | null)?.message || "请稍后重试");
  } finally {
    if (alive) threadActionBusy.value = false;
  }
}

async function onToggleProjectPin(project: CodingProjectSummary): Promise<void> {
  await performAction(async () => {
    await setCodingProjectPinned(project.id, !project.pinnedAt);
    await props.store.refresh();
  });
}

function onEditProject(project: CodingProjectSummary): void {
  if (!threadActionBusy.value) editingProjectId.value = project.id;
}

async function onProjectSaved(): Promise<void> {
  editingProjectId.value = null;
  await props.store.refresh();
}

async function onWorkspaceCreated(workspaceId: number): Promise<void> {
  const projectId = editingProjectId.value;
  editingProjectId.value = null;
  await props.store.refresh();
  if (projectId !== null) props.store.selectProject(projectId);
  props.store.selectWorkspace(workspaceId);
}

async function onDeleteProject(project: CodingProjectSummary): Promise<void> {
  await performAction(async () => {
    const confirmed = await notify.confirm({
      title: "删除项目？",
      message: "将删除该项目及其全部对话、消息和运行记录。",
      impact: "此操作无法撤销，磁盘上的项目目录和文件保持不变。",
      confirmLabel: "删除项目",
      danger: true,
    });
    if (!alive || !confirmed) return;
    await deleteCodingProject(project.id);
    props.store.removeDeletedProject(project.id);
    activeThreadDetails.value = null;
    await props.store.refresh();
  });
}

async function onTogglePin(thread: CodingThreadSummary): Promise<void> {
  await performAction(async () => {
    await setThreadPinned(thread.id, !thread.pinnedAt);
    await refreshThreads();
  });
}

async function onRenameThread(thread: CodingThreadSummary): Promise<void> {
  await performAction(async () => {
    const next = await notify.prompt({
      title: "重命名对话",
      defaultValue: thread.title,
      confirmLabel: "保存名称",
    });
    if (!alive || next === null || !next.trim()) return;
    await renameThread(thread.id, next.trim());
    await refreshThreads();
  });
}

async function onDeleteThread(thread: CodingThreadSummary): Promise<void> {
  await performAction(async () => {
    const confirmed = await notify.confirm({
      title: "删除对话？",
      message: "将删除此对话的消息、运行和相关记录。",
      impact: "此操作无法撤销，项目文件保持不变。",
      confirmLabel: "删除",
      danger: true,
    });
    if (!alive || !confirmed) return;
    await deleteThread(thread.id);
    props.store.removeDeletedThread(thread.id);
    activeThreadDetails.value = null;
    await refreshThreads();
  });
}

function openSearch(): void {
  emit("open-command");
  if (isNarrow.value) drawerOpen.value = false;
}

function goHome(): void {
  props.store.startNewTask();
  navigate("coding");
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
  document.addEventListener("pointerdown", closeRowMenus);
  window.addEventListener("resize", closeRowMenusOnResize);
  if (typeof window.matchMedia !== "function") return;
  media = window.matchMedia(DRAWER_MEDIA);
  isNarrow.value = media.matches;
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", onMediaChange);
  }
});

function closeRowMenusOnResize() { closeRowMenus(); }
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", closeRowMenus);
  window.removeEventListener("resize", closeRowMenusOnResize);
  alive = false;
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
      ref="sidebarRoot"
      class="coding-sidebar"
      :class="{ 'is-collapsed': collapsed && !isNarrow, 'is-drawer': isNarrow }"
      data-testid="coding-sidebar"
      aria-label="Coding Agent 导航"
    >
      <header class="sidebar-tools">
        <button type="button" class="sidebar-search" aria-label="搜索" data-testid="coding-open-search" @click="openSearch">
          <PhMagnifyingGlass :size="17" aria-hidden="true" /><span v-if="!collapsed || isNarrow">搜索项目与对话</span><kbd v-if="!collapsed || isNarrow">Ctrl K</kbd>
        </button>
        <button v-if="isNarrow" type="button" class="icon-btn" aria-label="收起侧栏" data-testid="coding-drawer-close" @click="drawerOpen = false"><PhX :size="17" /></button>
      </header>

      <div class="sidebar-scroll-region" @scroll.passive="activeThreadDetails = null; closeRowMenus()">
        <div class="sidebar-actions">
          <button v-if="collapsed && !isNarrow" type="button" class="nav-row" aria-label="项目" data-testid="coding-toggle-projects" :aria-expanded="projectsExpanded" @click="projectsExpanded = true; emit('toggle-collapse')"><PhFolderSimple :size="18" /></button>
          <button type="button" class="nav-row" :class="{ active: onCodingHome }" :aria-current="onCodingHome ? 'page' : undefined" aria-label="首页" data-testid="coding-nav-home" @click="goHome"><PhHouse :size="18" /><span class="action-label">首页</span></button>
          <button
            type="button"
            class="nav-row"
            :title="collapsed && !isNarrow ? '新对话' : undefined"
            :aria-label="collapsed && !isNarrow ? '新对话' : undefined"
            data-testid="coding-new-task"
            @click="onNewTask"
          >
            <PhNotePencil :size="18" />
            <span class="action-label">新对话</span>
            <span class="row-trailing"><PhPlus :size="15" /></span>
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
          v-if="!collapsed || isNarrow"
          class="project-section"
          data-testid="coding-tree"
          aria-label="项目与工作区"
        >
          <div class="section-heading">
            <button type="button" class="section-project-toggle" :aria-expanded="projectsExpanded" data-testid="coding-toggle-projects" @click="toggleProjects">项目<PhCaretDown :size="12" :class="{ 'is-closed': !projectsExpanded }" /></button>
            <button type="button" class="icon-btn" aria-label="新建项目" data-testid="coding-new-project" @click="openNewProjectDialog"><PhPlus :size="15" /></button>
            <button
              type="button"
              class="icon-btn"
              aria-label="刷新项目"
              data-testid="coding-refresh"
              :disabled="loadPhase === 'loading'"
              @click="props.store.refresh()"
            >
              <PhArrowClockwise :size="14" :class="{ spin: loadPhase === 'loading' }" />
            </button>
          </div>

          <div v-if="projectsExpanded && tree.length === 0" class="tree-empty">
            {{ loadPhase === "loading" ? "正在加载项目…" : "暂无项目，新建后会显示在这里" }}
          </div>

          <div v-else-if="projectsExpanded" class="project-tree" role="tree" aria-label="项目与对话树">
            <div v-for="node in tree" :key="node.project.id" role="none">
              <div
                class="tree-row project-row"
                :class="{ active: selectedProjectId === node.project.id && selectedThreadId === null }"
                :data-testid="`coding-project-${node.project.id}`"
                :aria-expanded="isProjectOpen(node.project.id)"
                role="treeitem"
                tabindex="0"
                @click="toggleProject(node)"
                @keydown.enter.self.prevent="toggleProject(node)"
                @keydown.space.self.prevent="toggleProject(node)"
              >
                <span class="row-caret" :class="{ open: isProjectOpen(node.project.id) }" />
                <PhPushPin v-if="node.project.pinnedAt" :size="15" class="thread-pin" />
                <PhFolderSimple v-else :size="15" />
                <span class="row-label" :title="node.project.name">{{ node.project.name }}</span>
                <details class="project-actions row-actions-menu" @click.stop="rowMenuClick" @keydown.stop="rowMenuKeydown" @toggle="toggleRowMenu"><summary aria-label="项目操作" title="项目操作">···</summary><div class="row-actions-list" role="menu">
                  <button
                    type="button"
                    class="thread-action"
                    role="menuitem"
                    :aria-label="node.project.pinnedAt ? '取消置顶项目' : '置顶项目'"
                    :title="node.project.pinnedAt ? '取消置顶项目' : '置顶项目'"
                    :disabled="threadActionBusy"
                    :data-testid="`coding-project-pin-${node.project.id}`"
                    @click="onToggleProjectPin(node.project)"
                  ><PhPushPin :size="13" />{{ node.project.pinnedAt ? "取消置顶项目" : "置顶项目" }}</button>
                  <button
                    type="button"
                    class="thread-action"
                    role="menuitem"
                    aria-label="编辑项目"
                    title="编辑项目"
                    :disabled="threadActionBusy"
                    :data-testid="`coding-project-edit-${node.project.id}`"
                    @click="onEditProject(node.project)"
                  ><PhPencil :size="13" />编辑项目</button>
                  <button
                    type="button"
                    class="thread-action"
                    role="menuitem"
                    aria-label="删除项目"
                    title="删除项目"
                    :disabled="threadActionBusy"
                    :data-testid="`coding-project-delete-${node.project.id}`"
                    @click="onDeleteProject(node.project)"
                  ><PhTrash :size="13" />删除项目</button>
                </div></details>
              </div>

              <div v-if="isProjectOpen(node.project.id)" class="project-threads" role="group">
                <div
                  v-for="item in projectThreads(node)"
                  :key="item.thread.id"
                  class="thread-node"
                  role="none"
                >
                  <div
                    class="tree-row thread-row"
                    :class="{ active: selectedThreadId === item.thread.id }"
                    :data-testid="`coding-thread-${item.thread.id}`"
                    :data-project-id="node.project.id"
                    :data-workspace-id="item.thread.workspaceId ?? undefined"
                    role="treeitem"
                    tabindex="0"
                    :aria-current="selectedThreadId === item.thread.id ? 'page' : undefined"
                    :aria-describedby="activeThreadDetails?.threadId === item.thread.id ? `coding-thread-details-${item.thread.id}` : undefined"
                    @mouseenter="showThreadDetails(item.thread.id, $event)"
                    @mouseleave="hideThreadDetails(item.thread.id)"
                    @focusin="showThreadDetails(item.thread.id, $event)"
                    @focusout="hideThreadDetails(item.thread.id, $event)"
                    @click="openThread(item.thread.id)"
                    @keydown.enter.self.prevent="openThread(item.thread.id)"
                    @keydown.space.self.prevent="openThread(item.thread.id)"
                  >
                    <PhPushPin v-if="item.thread.pinnedAt" :size="12" class="thread-pin" />
                    <PhChatsCircle v-else :size="13" />
                    <span class="row-label">{{ item.thread.title }}</span>
                    <PhGitBranch class="thread-branch" :size="13" />
                    <details class="thread-actions row-actions-menu" @click.stop="rowMenuClick" @keydown.stop="rowMenuKeydown" @toggle="toggleRowMenu"><summary aria-label="任务操作" title="任务操作">···</summary><div class="row-actions-list" role="menu">
                      <button
                        type="button"
                        class="thread-action"
                    role="menuitem"
                        :aria-label="item.thread.pinnedAt ? '取消置顶' : '置顶'"
                        :title="item.thread.pinnedAt ? '取消置顶' : '置顶'"
                        :disabled="threadActionBusy"
                        :data-testid="`coding-thread-pin-${item.thread.id}`"
                        @click="void onTogglePin(item.thread)"
                      >
                        <PhPushPin :size="12" />{{ item.thread.pinnedAt ? "取消置顶" : "置顶" }}
                      </button>
                      <button
                        type="button"
                        class="thread-action"
                    role="menuitem"
                        aria-label="重命名"
                        title="重命名"
                        :disabled="threadActionBusy"
                        :data-testid="`coding-thread-rename-${item.thread.id}`"
                        @click="void onRenameThread(item.thread)"
                      >
                        <PhPencil :size="12" />重命名
                      </button>
                      <button
                        type="button"
                        class="thread-action"
                    role="menuitem"
                        aria-label="删除对话"
                        title="删除对话"
                        :disabled="threadActionBusy"
                        :data-testid="`coding-thread-delete-${item.thread.id}`"
                        @click="void onDeleteThread(item.thread)"
                      >
                        <PhTrash :size="12" />删除对话
                      </button>
                    </div></details>
                  </div>

                </div>

                <div v-if="projectThreads(node).length === 0" class="thread-empty">
                  暂无对话
                </div>
              </div>
            </div>
          </div>

          <aside
            v-if="activeThreadDetails && activeThreadContext"
            :id="`coding-thread-details-${activeThreadContext.item.thread.id}`"
            class="thread-details"
            :style="{ top: `${activeThreadDetails.top}px`, left: `${activeThreadDetails.left}px` }"
            role="tooltip"
            :data-testid="`coding-thread-details-${activeThreadContext.item.thread.id}`"
          >
            <div class="thread-details-heading">
              <strong>{{ activeThreadContext.item.thread.title }}</strong>
              <span>{{ formatRelative(activeThreadContext.item.thread.updatedAt) }}</span>
            </div>
            <div class="thread-detail-row">
              <PhFolderSimple :size="16" />
              <span>{{ activeThreadContext.node.project.name }}</span>
            </div>
            <div class="thread-detail-row">
              <PhGitBranch :size="16" />
              <span>{{ detailBranch(activeThreadContext.item) }}</span>
              <span class="thread-detail-status">{{ detailWorkspaceStatus(activeThreadContext.item) }}</span>
            </div>
          </aside>
        </section>
      </div>

      <button type="button" class="sidebar-settings nav-row" aria-label="设置" @click="navigate('settings')"><PhGearSix :size="19" /><span class="action-label">设置</span></button>
      <footer class="sidebar-footer">
        <UserMenu
          inline
          :collapsed="collapsed && !isNarrow"
          @settings="navigate('settings')"
        />
        <div v-if="!isNarrow" class="footer-tools">
          <button
            type="button"
            class="icon-btn"
            :title="collapsed ? '展开侧栏' : '折叠侧栏'"
            :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
            :aria-expanded="!collapsed"
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
      <EditProjectDialog v-if="editingProjectId !== null" :project-id="editingProjectId" :worktree-enabled="store.capabilities.value?.coding_worktree_enabled === true" @close="editingProjectId = null" @saved="onProjectSaved" @workspace-created="onWorkspaceCreated" />
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
  background: var(--color-rail-bg);
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
.tree-row:focus-visible,
.coding-sidebar button:focus-visible { outline: 2px solid var(--color-accent); outline-offset: -2px; }
.coding-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: color-mix(in srgb, var(--color-fg) 22%, transparent);
}
.sidebar-tools {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-3) var(--space-5);
}
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
  height: 40px;
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
.nav-row.active { background: var(--color-accent-soft); color: var(--color-accent-soft-fg); font-weight: var(--font-semibold); box-shadow: inset 2px 0 var(--color-accent); }
.row-trailing {
  display: inline-grid;
  width: 24px;
  height: 32px;
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
  height: 32px;
  border-radius: var(--radius-full);
}
.action-label { overflow: hidden; min-width: 0; text-overflow: ellipsis; white-space: nowrap; }
.project-section { margin-top: var(--space-6); padding-top: var(--space-4); border-top: 1px solid var(--color-border); }
.section-heading {
  display: flex;
  min-height: 26px;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  font-weight: var(--font-medium);
}
.tree-empty,
.thread-empty {
  padding: var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
}
.project-tree,
.project-threads { display: flex; flex-direction: column; gap: 1px; }
.project-threads { padding-left: var(--space-4); }
.thread-node { min-width: 0; }
.tree-row {
  display: flex;
  width: 100%;
  min-width: 0;
  min-height: 36px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.project-row { min-height: 42px; font-size: var(--pa-text-body); font-weight: var(--font-medium); }
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
.thread-pin { flex-shrink: 0; color: var(--color-accent); }
.thread-branch {
  flex-shrink: 0;
  color: var(--color-fg-subtle);
}
.project-actions,
.thread-actions { display: inline-flex; flex-shrink: 0; align-items: center; gap: 1px; }
.thread-row:hover .thread-actions,
.thread-row:focus-within .thread-actions { display: inline-flex; }
.thread-row:hover .thread-branch,
.thread-row:focus-within .thread-branch { display: none; }
.thread-action { width: 32px; height: 32px; border-radius: var(--radius-sm); }
.thread-action:disabled { opacity: .45; cursor: default; }
.thread-details {
  position: fixed;
  z-index: calc(var(--z-overlay) + 1);
  display: grid;
  width: min(360px, calc(100vw - 16px));
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  color: var(--color-fg);
  box-shadow: var(--shadow-lg);
  cursor: default;
  pointer-events: none;
}
.thread-details-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-3);
}
.thread-details-heading strong {
  overflow: hidden;
  min-width: 0;
  flex: 1;
  font-size: var(--text-base);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-details-heading > span {
  flex-shrink: 0;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.thread-detail-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
}
.thread-detail-row > svg { flex-shrink: 0; color: var(--color-fg-subtle); }
.thread-detail-row > span:not(.thread-detail-status) {
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-detail-status {
  flex-shrink: 0;
  margin-left: auto;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.sidebar-footer {
  display: flex;
  min-height: 68px;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
}
.footer-tools { display: flex; align-items: center; }
.icon-btn.active { background: var(--color-surface-muted); color: var(--color-fg); }
.spin { animation: sidebar-spin .9s linear infinite; }
@keyframes sidebar-spin { to { transform: rotate(360deg); } }

.is-collapsed .action-label,
.is-collapsed .row-trailing { display: none; }
.is-collapsed .nav-row { justify-content: center; padding-inline: 0; }
.is-collapsed .sidebar-scroll-region { padding-inline: var(--space-2); }
.is-collapsed .sidebar-footer { flex-direction: column; justify-content: center; }

@media (max-height: 620px) {
  .nav-row { height: 32px; }
  .project-section { margin-top: var(--space-3); }
  .sidebar-footer { min-height: 50px; }
}
@media (prefers-reduced-motion: reduce) {
  .row-caret { transition: none; }
  .spin { animation: none; }
}
.row-actions-menu { position: relative; margin-left: auto; }
.row-actions-menu summary { list-style: none; cursor: pointer; display: grid; place-items: center; width: 32px; height: 32px; border-radius: var(--radius); font-size: 20px; }
.row-actions-menu summary::-webkit-details-marker { display: none; }
.row-actions-menu summary:focus-visible { outline: 2px solid var(--color-accent); }
.row-actions-menu:not([open]) .row-actions-list { display: none; }
.row-actions-list { position: fixed; left: 8px; top: 8px; min-width: 176px; display: grid; padding: 6px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius); box-shadow: var(--shadow-md); z-index: 30; }
.row-actions-list .thread-action { display: flex; align-items: center; width: 100%; height: 36px; padding: 0 10px; gap: 10px; justify-content: flex-start; font-size: 13px; }
.row-actions-list [aria-label^="删除"] { color: var(--color-danger-fg); }
.thread-row .thread-branch { display: none; }
@media (hover: hover) { .tree-row:not(:hover):not(:focus-within) .row-actions-menu:not([open]) { opacity: .35; } }
.sidebar-search { display: flex; flex: 1; min-width: 0; height: 36px; align-items: center; gap: var(--space-2); padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-panel); color: var(--color-fg-subtle); cursor: pointer; }
.sidebar-search span { min-width: 0; flex: 1; overflow: hidden; font-size: var(--pa-text-meta); text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.sidebar-search kbd { flex-shrink: 0; font-family: var(--font-sans); font-size: 10px; }
.sidebar-settings { width: calc(100% - 24px); flex-shrink: 0; margin: var(--space-2) var(--space-3); }
.section-project-toggle { display: flex; flex: 1; align-items: center; gap: var(--space-2); padding: 0; border: 0; background: transparent; color: var(--color-fg-subtle); font-size: var(--pa-text-meta); cursor: pointer; }
.section-project-toggle .is-closed { transform: rotate(-90deg); }
.is-collapsed .sidebar-search { justify-content: center; }
</style>
