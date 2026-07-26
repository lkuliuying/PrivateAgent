<script setup lang="ts">
/**
 * 全局搜索（第七阶段 M2）。跨会话/文档/切片/任务/证据/记忆/收件箱/提醒/目标/简报检索。
 * 结果点击跳转对应视图并记录最近打开（供排序）。
 */
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { PhMagnifyingGlass, PhX, PhDatabase, PhChatCircle, PhListChecks, PhBrain, PhBell, PhTarget, PhFileText, PhBooks } from "@phosphor-icons/vue";
import { search, recordRecentOpen, type SearchResult } from "../api";
import { useModalFocus } from "../composables/useModalFocus";
import { useNotifications } from "../stores/notifications";
import type { View } from "../types";

const emit = defineEmits<{ navigate: [view: View]; close: [] }>();
const notify = useNotifications();

const query = ref("");
const results = ref<SearchResult[]>([]);
const loading = ref(false);
const dialogEl = ref<HTMLElement | null>(null);
const inputEl = ref<HTMLInputElement | null>(null);
let debounce: number | null = null;
let requestSerial = 0;

const TYPE_FILTERS: { value: string | undefined; label: string }[] = [
  { value: undefined, label: "全部" },
  { value: "session", label: "会话" },
  { value: "message", label: "消息" },
  { value: "document", label: "文档" },
  { value: "chunk", label: "切片" },
  { value: "agent_task", label: "任务" },
  { value: "memory", label: "记忆" },
  { value: "inbox", label: "收件箱" },
  { value: "reminder", label: "提醒" },
  { value: "goal", label: "目标" },
  { value: "briefing", label: "简报" },
];
const activeType = ref<string | undefined>(undefined);

const iconFor = (type: string) => {
  switch (type) {
    case "session":
    case "message":
      return PhChatCircle;
    case "document":
    case "chunk":
    case "collection":
      return PhDatabase;
    case "agent_task":
    case "agent_evidence":
      return PhListChecks;
    case "memory":
      return PhBrain;
    case "reminder":
      return PhBell;
    case "goal":
    case "goal_checkin":
      return PhTarget;
    case "briefing":
      return PhFileText;
    case "learning_topic":
    case "learning_note":
      return PhBooks;
    default:
      return PhFileText;
  }
};

async function runSearch() {
  const serial = ++requestSerial;
  const q = query.value.trim();
  if (!q) {
    results.value = [];
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    const nextResults = await search(q, {
      types: activeType.value ? [activeType.value] : undefined,
      limit: 30,
    });
    if (serial === requestSerial) results.value = nextResults;
  } catch (e) {
    if (serial === requestSerial) notify.error("搜索失败", String(e));
  } finally {
    if (serial === requestSerial) loading.value = false;
  }
}

watch(query, () => {
  if (debounce) window.clearTimeout(debounce);
  debounce = window.setTimeout(runSearch, 250);
});
watch(activeType, runSearch);

async function open() {
  query.value = "";
  results.value = [];
  await nextTick();
  inputEl.value?.focus();
}

function actionToView(action: string): View {
  switch (action) {
    case "open_chat":
      return "chat";
    case "open_kb":
      return "kb";
    case "open_projects":
      return "projects";
    case "open_learning":
      return "learning";
    case "open_tasks":
      return "tasks";
    case "open_memory":
      return "memory";
    case "open_today":
      return "today";
    default:
      return "today";
  }
}

function onSelect(r: SearchResult) {
  const view = actionToView(r.action);
  emit("navigate", view);
  void recordRecentOpen(r.type, r.id, r.title).catch(() => {});
  emit("close");
}

defineExpose({ open });

onMounted(open);
onUnmounted(() => {
  requestSerial += 1;
  if (debounce) window.clearTimeout(debounce);
});
useModalFocus({
  container: dialogEl,
  initialFocus: inputEl,
  onEscape: () => emit("close"),
});
</script>

<template>
  <Teleport to="body">
    <Transition name="gs">
      <div class="gs-scrim" @click.self="emit('close')">
        <div
          ref="dialogEl"
          class="gs-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="global-search-title"
          tabindex="-1"
        >
          <h2 id="global-search-title" class="gs-sr-only">全局搜索</h2>
          <div class="gs-input-wrap">
            <PhMagnifyingGlass :size="16" class="gs-input-icon" />
            <input
              ref="inputEl"
              v-model="query"
              class="gs-input"
              aria-label="搜索会话、文档、任务或记忆"
              placeholder="搜索会话、文档、任务、记忆…"
            />
            <button class="gs-close" aria-label="关闭" @click="emit('close')">
              <PhX :size="16" weight="bold" />
            </button>
          </div>
          <div class="gs-filters">
            <button
              v-for="f in TYPE_FILTERS"
              :key="String(f.value)"
              class="gs-filter"
              :class="{ active: activeType === f.value }"
              :aria-pressed="activeType === f.value"
              @click="activeType = f.value"
            >
              {{ f.label }}
            </button>
          </div>
          <div class="gs-results">
            <p v-if="loading" class="gs-hint">搜索中…</p>
            <p v-else-if="query && results.length === 0" class="gs-hint">无匹配结果</p>
            <p v-else-if="!query" class="gs-hint">输入关键词开始搜索</p>
            <button
              v-for="r in results"
              :key="`${r.type}-${r.id}`"
              class="gs-result"
              @click="onSelect(r)"
            >
              <component :is="iconFor(r.type)" :size="15" class="gs-result-icon" />
              <div class="gs-result-body">
                <div class="gs-result-head">
                  <strong>{{ r.title }}</strong>
                  <span class="gs-result-source">{{ r.source }}</span>
                </div>
                <p v-if="r.snippet" class="gs-result-snippet">{{ r.snippet }}</p>
              </div>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.gs-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: var(--color-scrim);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 10vh;
}
.gs-card {
  width: 640px;
  max-width: calc(100vw - var(--space-8));
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 76vh;
}
.gs-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.gs-input-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}
.gs-input-icon {
  color: var(--color-fg-faint);
  flex-shrink: 0;
}
.gs-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--text-md);
  color: var(--color-fg);
}
.gs-close {
  border: none;
  background: transparent;
  color: var(--color-fg-faint);
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius-sm);
}
.gs-close:hover {
  color: var(--color-fg);
  background: var(--color-surface-sunken);
}
.gs-filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
}
.gs-filter {
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  cursor: pointer;
}
.gs-filter.active {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  border-color: var(--color-accent);
}
.gs-results {
  overflow-y: auto;
  padding: var(--space-2);
}
.gs-hint {
  margin: var(--space-6) auto;
  text-align: center;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.gs-result {
  display: flex;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius);
  color: var(--color-fg);
}
.gs-result:hover {
  background: var(--color-accent-soft);
}
.gs-result-icon {
  color: var(--color-fg-subtle);
  flex-shrink: 0;
  margin-top: 2px;
}
.gs-result-body {
  flex: 1;
  min-width: 0;
}
.gs-result-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}
.gs-result-head strong {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gs-result-source {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  flex-shrink: 0;
}
.gs-result-snippet {
  margin: 2px 0 0;
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gs-enter-active,
.gs-leave-active {
  transition: opacity var(--duration) var(--ease);
}
.gs-enter-from,
.gs-leave-to {
  opacity: 0;
}
</style>
