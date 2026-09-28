<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { PhDotsThree, PhListBullets, PhSidebarSimple, PhPencilSimple, PhPushPin, PhTrash, PhCopy, PhX } from "@phosphor-icons/vue";
import type { CodingWorkspaceStore } from "../model/codingWorkspaceStore";
import { useResizablePanel } from "../../../composables/useResizablePanel";
import { deleteThread, renameThread, setThreadPinned, setThreadArchived } from "../api/threads";
import { useNotifications } from "../../../stores/notifications";

const props = defineProps<{ store: CodingWorkspaceStore; filesOpen: boolean; running: boolean; panelTarget?: string }>();
const emit = defineEmits<{ "toggle-files": []; "environment-open": []; "panel-change": [open: boolean] }>();
const notify = useNotifications();
const root = ref<HTMLElement>();
const panel = ref<HTMLElement>();
const open = ref<"menu" | "environment" | null>(null);
const tab = ref("changes");
const panelSize = useResizablePanel("pa_inspector_width", 440, 320, 800, -1);
const busy = ref(false);
const error = ref("");
const thread = computed(() => props.store.selectedThread.value);
let alive = true;
const tabs = [{ key: "overview", label: "环境" }, { key: "changes", label: "变更" }, { key: "execution", label: "进程" }, { key: "evidence", label: "验证" }, { key: "context", label: "上下文" }];

async function toggle(value: "menu" | "environment") {
  open.value = open.value === value ? null : value;
  error.value = "";
  emit("panel-change", open.value === "environment");
  if (open.value === "environment") emit("environment-open");
  if (open.value) {
    await nextTick();
    (value === "menu" ? root.value : panel.value)?.querySelector<HTMLElement>(value === "menu" ? '[role="menuitem"]' : '[role="tab"][aria-selected="true"]')?.focus();
  }
}
function close(restore = false) {
  const value = open.value;
  open.value = null;
  emit("panel-change", false);
  if (restore && value) root.value?.querySelector<HTMLElement>(`[data-tool="${value}"]`)?.focus();
}
function outside(event: PointerEvent) { if (open.value === "menu" && !root.value?.contains(event.target as Node)) close(); }
function keyboard(event: KeyboardEvent) {
  if (event.key === "Escape" && open.value) { event.stopPropagation(); close(true); }
  if (open.value === "menu" && ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    const buttons = [...(root.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
  }
  if (open.value === "environment" && (event.target as HTMLElement).getAttribute("role") === "tab" && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    const index = tabs.findIndex(item => item.key === tab.value);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tab.value = tabs[next].key;
    panel.value?.querySelector<HTMLElement>(`#environment-tab-${tab.value}`)?.focus();
  }
}
onMounted(() => document.addEventListener("pointerdown", outside));
onBeforeUnmount(() => { alive = false; document.removeEventListener("pointerdown", outside); });

async function action(kind: "rename" | "pin" | "delete" | "copy" | "archive") {
  const current = thread.value;
  if (!current || busy.value || ["delete", "archive"].includes(kind) && props.running) return;
  busy.value = true;
  error.value = "";
  try {
    if (kind === "rename") {
      const title = await notify.prompt({ title: "重命名任务", defaultValue: current.title, confirmLabel: "保存" });
      if (!alive || !title?.trim()) return;
      await renameThread(current.id, title.trim());
    } else if (kind === "pin") await setThreadPinned(current.id, !current.pinnedAt);
    else if (kind === "delete") {
      const accepted = await notify.confirm({ title: "删除对话？", message: "将删除此对话的消息、运行和相关记录。", impact: "此操作无法撤销，项目文件保持不变。", confirmLabel: "删除", danger: true });
      if (!alive || !accepted) return;
      await deleteThread(current.id);
      props.store.removeDeletedThread(current.id);
    } else if (kind === "archive") { await setThreadArchived(current.id, true); props.store.removeDeletedThread(current.id); }
    else await navigator.clipboard.writeText(current.title);
    if (alive && kind !== "copy") await props.store.refresh();
    if (alive) close(true);
  } catch (cause) {
    if (alive) {
      error.value = (cause as { message?: string }).message || "操作失败，请重试";
      if (!open.value) notify.error("任务操作失败", error.value);
    }
  } finally { if (alive) busy.value = false; }
}
defineExpose({ close, focusFiles: () => root.value?.querySelector<HTMLElement>('[data-testid="thread-files-toggle"]')?.focus() });
</script>

<template>
  <div ref="root" class="thread-tools" @keydown="keyboard">
    <button class="tool-button" data-tool="menu" data-testid="thread-menu-toggle" title="任务操作" aria-label="任务操作" aria-haspopup="menu" :aria-expanded="open === 'menu'" @click="toggle('menu')"><PhDotsThree :size="22" weight="bold" /></button>
    <button class="tool-button" data-tool="environment" data-testid="thread-environment-toggle" title="环境与变更" aria-label="环境与变更" aria-haspopup="dialog" :aria-expanded="open === 'environment'" @click="toggle('environment')"><PhListBullets :size="19" /></button>
    <button class="tool-button" data-testid="thread-files-toggle" :class="{ active: filesOpen }" title="文件工作区" aria-label="文件工作区" :aria-expanded="filesOpen" @click="close(); emit('toggle-files')"><PhSidebarSimple :size="19" /></button>
    <div v-if="open === 'menu'" class="task-menu" role="menu" aria-label="任务操作">
      <button role="menuitem" :disabled="busy" @click="action('rename')"><PhPencilSimple :size="17" />重命名</button>
      <button role="menuitem" :disabled="busy" @click="action('pin')"><PhPushPin :size="17" />{{ thread?.pinnedAt ? "取消置顶" : "置顶" }}</button>
      <button role="menuitem" :disabled="busy" @click="action('copy')"><PhCopy :size="17" />复制任务名称</button>
      <button role="menuitem" :disabled="busy || running" @click="action('archive')">归档任务</button>
      <button role="menuitem" @click="toggle('environment'); tab = 'observer'">观察诊断</button>
      <button role="menuitem" @click="toggle('environment'); tab = 'recovery'">恢复现场详情</button>
      <button role="menuitem" data-testid="thread-menu-delete" :disabled="busy || running" :title="running ? '请先停止正在运行的任务' : undefined" @click="action('delete')"><PhTrash :size="17" />删除对话</button>
      <p v-if="error" role="alert">{{ error }}</p>
    </div>
    <Teleport v-if="open === 'environment'" :to="panelTarget || 'body'" :disabled="!panelTarget">
    <section ref="panel" class="environment-panel" :class="{ docked: !!panelTarget }" :style="{ width: `${panelSize.width.value}px` }" @keydown.stop="keyboard" data-testid="thread-environment-panel" role="dialog" aria-label="环境与变更">
      <div v-if="panelTarget" class="panel-resizer" role="separator" tabindex="0" aria-label="调整审阅面板宽度" aria-orientation="vertical" :aria-valuenow="panelSize.width.value" :aria-valuemin="320" :aria-valuemax="800" @pointerdown="panelSize.start" @keydown="panelSize.keyboard" />
      <header><strong>{{ tab === 'observer' ? '观察诊断' : tab === 'recovery' ? '恢复现场详情' : '任务工作台' }}</strong><button class="tool-button" aria-label="关闭环境面板" @click="close(true)"><PhX :size="16" /></button></header>
      <nav class="environment-tabs" role="tablist" aria-label="环境信息分类">
        <button v-for="item in tabs" :key="item.key" :id="`environment-tab-${item.key}`" role="tab" :tabindex="tab === item.key ? 0 : -1" :aria-selected="tab === item.key" :aria-controls="`environment-pane-${item.key}`" :class="{ active: tab === item.key }" @click="tab = item.key">{{ item.label }}</button>
      </nav>
      <div :id="`environment-pane-${tab}`" class="environment-body" role="tabpanel" :aria-labelledby="tabs.some(item => item.key === tab) ? `environment-tab-${tab}` : undefined" :aria-label="tab === 'observer' ? '观察诊断' : tab === 'recovery' ? '恢复现场详情' : undefined"><slot :name="tab" /></div>
    </section>
    </Teleport>
  </div>
</template>

<style scoped>
.thread-tools { display: flex; align-items: center; gap: 4px; position: relative; }
.tool-button { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 8px; color: var(--color-fg-muted); background: transparent; cursor: pointer; }
.tool-button:hover, .tool-button.active, .tool-button[aria-expanded="true"] { background: var(--color-surface-sunken); color: var(--color-fg); }
button:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.task-menu, .environment-panel { position: absolute; right: 0; top: calc(100% + 12px); z-index: 60; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 14px; box-shadow: 0 14px 48px #0002; color: var(--color-fg); }
.task-menu { width: 230px; padding: 6px; }
.task-menu > button { display: flex; align-items: center; gap: 12px; width: 100%; border: 0; border-radius: 8px; background: transparent; color: inherit; padding: 11px 12px; cursor: pointer; text-align: left; }
.task-menu > button:hover { background: var(--color-surface-sunken); }
.task-menu > button:disabled { opacity: .45; cursor: default; }
.task-menu p { padding: 8px; font-size: 12px; color: var(--color-danger-fg); }
.environment-panel { width: min(490px, calc(100vw - 32px)); max-height: calc(100dvh - 104px); display: flex; flex-direction: column; overflow: hidden; }
.environment-panel header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; }
.environment-tabs { display: flex; padding: 0 12px; border-bottom: 1px solid var(--color-border); overflow-x: auto; flex-shrink: 0; }
.environment-tabs button { flex: 1; white-space: nowrap; padding: 10px 8px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--color-fg-muted); cursor: pointer; font-size: 13px; }
.environment-tabs button.active { border-bottom-color: var(--color-fg); color: var(--color-fg); }
.environment-body { padding: 16px; min-height: 150px; overflow-y: auto; overflow-wrap: anywhere; }
.environment-body :deep(.patch-panel), .environment-body :deep(.execution-panel), .environment-body :deep(.recovery-panel) { width: 100%; margin: 0; }
.environment-body :deep(.context-drawer) { width: 100%; border: 0; }
.environment-body :deep(.drawer-head), .environment-body :deep(.drawer-foot) { display: none; }
.environment-body :deep(.drawer-body) { padding: 12px 0; }
.environment-panel.docked { position: relative; top: auto; right: auto; height: 100%; max-height: none; max-width: min(60vw, 800px); border: 0; border-radius: 0; box-shadow: none; }
.environment-panel.docked .environment-body { flex: 1; min-height: 0; }
.panel-resizer { position: absolute; top: 0; bottom: 0; left: 0; width: 5px; z-index: 2; cursor: col-resize; touch-action: none; }
.panel-resizer:hover, .panel-resizer:focus-visible { background: var(--color-accent); outline: 2px solid var(--color-accent); }
@media (max-width: 900px) { .environment-panel.docked { width: 100% !important; max-width: none; } .panel-resizer { display: none; } }
</style>
