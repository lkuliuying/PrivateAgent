<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { PhMagnifyingGlass } from "@phosphor-icons/vue";
import type { View } from "../types";
import { VIEW_REGISTRY } from "../models/viewRegistry";
import { searchWorkspace, type WorkspaceSearchHit } from "../features/coding/api/workspaceSearch";
const props = withDefaults(defineProps<{ projects?: { id: number; name: string }[] }>(), { projects: () => [] });
const emit = defineEmits<{ navigate: [view: View]; close: []; "open-result": [hit: WorkspaceSearchHit] }>();
const query = ref("");
const inputEl = ref<HTMLInputElement | null>(null);
const card = ref<HTMLElement | null>(null);
const selected = ref(0);
const mode = ref("tasks");
const projectId = ref("");
const status = ref("");
const period = ref("");
const archived = ref(false);
const results = ref<WorkspaceSearchHit[]>([]);
const cursor = ref<number | null>(null);
const loading = ref(false);
const error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;
let generation = 0;
let restoreFocus: HTMLElement | null = null;
const filtered = computed(() => Object.values(VIEW_REGISTRY).filter(meta => ["coding", "extensions", "settings"].includes(meta.key)).filter(meta => `${meta.label} ${meta.keywords.join(" ")}`.toLowerCase().includes(query.value.trim().toLowerCase())));
const count = computed(() => mode.value === "tasks" ? results.value.length : filtered.value.length);
async function load(more = false) {
  controller?.abort(); const current = ++generation; controller = new AbortController();
  loading.value = true; error.value = "";
  if (!more) { results.value = []; cursor.value = null; selected.value = 0; }
  try {
    const page = await searchWorkspace({ q: query.value, project_id: projectId.value ? Number(projectId.value) : undefined,
      status: status.value || undefined, archived: archived.value,
      since: period.value ? new Date(Date.now() - Number(period.value) * 86400000).toISOString() : undefined,
      before: more ? cursor.value ?? undefined : undefined }, controller.signal);
    if (current !== generation) return;
    results.value = more ? [...results.value, ...page.items] : page.items; cursor.value = page.next_cursor;
  } catch (cause) { if (current === generation && !controller.signal.aborted) error.value = (cause as { message?: string }).message || "搜索失败，请重试"; }
  finally { if (current === generation) loading.value = false; }
}
watch([query, projectId, status, period, archived, mode], () => {
  clearTimeout(timer); controller?.abort(); generation++; selected.value = 0;
  if (mode.value === "tasks") timer = setTimeout(() => void load(), 180);
});
function select(index: number) {
  if (mode.value === "commands") { const command = filtered.value[index]; if (command) { emit("navigate", command.key); emit("close"); } }
  else { const hit = results.value[index]; if (hit) emit("open-result", hit); }
}
function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") emit("close");
  if (["ArrowDown", "ArrowUp"].includes(event.key) && event.target === inputEl.value) {
    event.preventDefault(); selected.value = Math.max(0, Math.min(count.value - 1, selected.value + (event.key === "ArrowDown" ? 1 : -1)));
    card.value?.querySelector(`[data-index="${selected.value}"]`)?.scrollIntoView?.({ block: "nearest" });
  }
  if (event.key === "Enter" && event.target === inputEl.value) { event.preventDefault(); select(selected.value); }
  if (event.key === "Tab") {
    const focusable = [...(card.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input, select, [tabindex="0"]') ?? [])];
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
}
async function open() { await nextTick(); inputEl.value?.focus(); }
defineExpose({ open });
onMounted(() => { restoreFocus = document.activeElement as HTMLElement; void open(); void load(); });
onBeforeUnmount(() => { clearTimeout(timer); generation++; controller?.abort(); restoreFocus?.focus(); });
</script>
<template>
  <Teleport to="body">
    <div class="cp-scrim" @click.self="emit('close')">
      <div ref="card" class="cp-card" role="dialog" aria-modal="true" aria-label="搜索与命令" @keydown="onKey">
        <div class="cp-input-wrap"><PhMagnifyingGlass :size="18" /><input ref="inputEl" v-model="query" class="cp-input" maxlength="200" :placeholder="mode === 'tasks' ? '搜索项目、任务或消息正文…' : '输入导航命令…'" aria-label="搜索内容" /><button class="pa-btn pa-btn--ghost" aria-label="关闭搜索" @click="emit('close')">Esc</button></div>
        <div class="cp-filters"><button class="pa-btn pa-btn--subtle" :aria-pressed="mode === 'tasks'" @click="mode = 'tasks'">任务与消息</button><button class="pa-btn pa-btn--subtle" :aria-pressed="mode === 'commands'" @click="mode = 'commands'">导航命令</button></div>
        <div v-if="mode === 'tasks'" class="cp-filters">
          <select v-model="projectId" class="pa-input" aria-label="按项目筛选"><option value="">所有项目</option><option v-for="p in props.projects" :key="p.id" :value="p.id">{{ p.name }}</option></select>
          <select v-model="status" class="pa-input" aria-label="按状态筛选"><option value="">所有状态</option><option value="running">运行中</option><option value="paused">已暂停</option><option value="completed">已结束</option><option value="failed">失败</option><option value="cancelled">已取消</option></select>
          <select v-model="period" class="pa-input" aria-label="按时间筛选"><option value="">全部时间</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option></select>
          <label><input v-model="archived" type="checkbox" />已归档</label>
        </div>
        <p v-if="error" class="cp-empty" role="alert">{{ error }} <button class="pa-btn" @click="load()">重试</button></p>
        <ul class="cp-list" :aria-busy="loading">
          <template v-if="mode === 'tasks'">
            <li v-for="(hit, i) in results" :key="`${hit.kind}:${hit.message_id ?? hit.session_id ?? hit.project_id}`"><button class="cp-item cp-result" :class="{ active: i === selected }" :data-index="i" @mouseenter="selected = i" @click="select(i)"><strong>{{ hit.title }}</strong><span>{{ hit.excerpt }}</span><small>{{ hit.project_name }} · {{ hit.kind === 'message' ? '消息正文' : hit.kind === 'project' ? '项目' : '任务' }}{{ hit.archived ? ' · 恢复并打开' : '' }}</small></button></li>
            <li v-if="!results.length && !loading && !error" class="cp-empty">没有匹配结果{{ cursor ? '，可继续搜索更早记录' : '' }}</li>
          </template>
          <template v-else><li v-for="(item, i) in filtered" :key="item.key"><button class="cp-item cp-command" :class="{ active: i === selected }" @click="select(i)"><component :is="item.icon" :size="16" />打开{{ item.label }}</button></li><li v-if="!filtered.length" class="cp-empty">无匹配命令</li></template>
        </ul>
        <div v-if="mode === 'tasks'" class="cp-footer" aria-live="polite"><span v-if="loading">正在检索…</span><button v-if="cursor" class="pa-btn pa-btn--subtle" :disabled="loading" @click="load(true)">继续搜索更早记录</button><span v-else-if="!loading">↑↓ 选择 · Enter 打开</span></div>
      </div>
    </div>
  </Teleport>
</template>
<style scoped>
.cp-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: var(--color-scrim);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 12vh;
}
.cp-card {
  width: 560px;
  max-width: calc(100vw - var(--space-8));
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.cp-input-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}
.cp-input-icon {
  color: var(--color-fg-faint);
  flex-shrink: 0;
}
.cp-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--text-base);
  color: var(--color-fg);
}
.cp-list {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  max-height: 50vh;
  overflow-y: auto;
}
.cp-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  cursor: pointer;
  color: var(--color-fg);
}
.cp-item.active {
  background: var(--color-accent-soft);
}
.cp-item-icon {
  color: var(--color-fg-subtle);
  flex-shrink: 0;
}
.cp-item.active .cp-item-icon {
  color: var(--color-accent);
}
.cp-item-label {
  font-size: var(--text-base);
}
.cp-item-hint {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.cp-empty {
  padding: var(--space-4);
  text-align: center;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.cp-enter-active,
.cp-leave-active {
  transition: opacity var(--duration) var(--ease);
}
.cp-enter-active .cp-card,
.cp-leave-active .cp-card {
  transition: transform var(--duration) var(--ease-out);
}
.cp-enter-from,
.cp-leave-to {
  opacity: 0;
}
.cp-enter-from .cp-card,
.cp-leave-to .cp-card {
  transform: translateY(-12px);
}
.cp-filters { display: flex; gap: 8px; padding: 10px 16px 0; flex-wrap: wrap; align-items: center; }
.cp-filters select { width: auto; max-width: 170px; font-size: 13px; }
.cp-filters label { font-size: 13px; display: flex; gap: 4px; align-items: center; }
.cp-filters [aria-pressed="true"] { background: var(--color-accent-soft); }
.cp-result { width: 100%; border: 0; background: transparent; text-align: left; flex-direction: column; align-items: stretch; gap: 4px; margin-bottom: 4px; }
.cp-result strong { font-size: 14px; font-weight: 500; }
.cp-result span { font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--color-fg-subtle); }
.cp-result small { color: var(--color-fg-muted); }
.cp-command { width: 100%; border: 0; background: transparent; }
.cp-footer { padding: 8px 16px 14px; color: var(--color-fg-muted); font-size: 12px; }
</style>
