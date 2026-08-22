<script setup lang="ts">
/**
 * ConversationList · v0.8.0 W6-R2（Agent 页左栏，240–280px）
 *
 * 使用真实 `sessions/currentSessionId`（计划 §6.7：不复制仅用于展示的假
 * 列表）；新建对话、会话搜索/筛选、最近会话（标题/更新时间/运行状态）。
 * 独立滚动；窄窗口时由父层切换为抽屉。
 */
import { computed, onMounted, ref } from "vue";
import { PhChatsCircle, PhMagnifyingGlass, PhPlus } from "@phosphor-icons/vue";
import type { Session } from "../../types";

const props = withDefaults(
  defineProps<{
    sessions: Session[];
    currentId?: number | null;
    /** 当前会话是否在流式运行（呈现运行状态点） */
    running?: boolean;
    /** W6-R3：重新展开时恢复列表滚动位置 */
    initialScrollTop?: number;
  }>(),
  { currentId: null, running: false, initialScrollTop: 0 }
);

const emit = defineEmits<{
  "new-session": [];
  "select-session": [id: number];
  /** 收起前保存滚动位置（父层缓存） */
  "scroll-pos": [top: number];
}>();

const query = ref("");
const listRef = ref<HTMLElement | null>(null);

onMounted(() => {
  if (listRef.value && props.initialScrollTop > 0) {
    listRef.value.scrollTop = props.initialScrollTop;
  }
});

function onListScroll(): void {
  if (listRef.value) emit("scroll-pos", listRef.value.scrollTop);
}

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase();
  const list = [...props.sessions].sort(
    (a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
  );
  if (!keyword) return list;
  return list.filter((session) => (session.title || "").toLowerCase().includes(keyword));
});

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
</script>

<template>
  <nav class="conversation-list" aria-label="会话记录" data-testid="agent-conversations">
    <div class="list-head">
      <strong>Agent</strong>
      <button
        class="new-session"
        type="button"
        title="新建对话"
        aria-label="新建对话"
        data-testid="agent-conversation-new"
        @click="emit('new-session')"
      >
        <PhPlus :size="15" weight="bold" />
        <span>新建对话</span>
      </button>
    </div>

    <label class="list-search">
      <PhMagnifyingGlass :size="14" aria-hidden="true" />
      <input
        v-model="query"
        type="search"
        placeholder="搜索会话…"
        aria-label="搜索会话"
        data-testid="agent-conversation-search"
      />
    </label>

    <div ref="listRef" class="list-scroll" @scroll.passive="onListScroll">
      <button
        v-for="session in filtered"
        :key="session.id"
        class="session-row"
        :class="{ active: session.id === currentId }"
        :aria-current="session.id === currentId ? 'page' : undefined"
        :title="session.title || `会话 ${session.id}`"
        :data-testid="`agent-conversation-${session.id}`"
        @click="emit('select-session', session.id)"
      >
        <PhChatsCircle :size="15" class="session-icon" aria-hidden="true" />
        <span class="session-copy">
          <span class="session-title">{{ session.title || `会话 ${session.id}` }}</span>
          <small>{{ formatRelative(session.updated_at) }}</small>
        </span>
        <span
          v-if="session.id === currentId && running"
          class="running-dot"
          aria-label="运行中"
          data-testid="agent-conversation-running"
        />
      </button>
      <div v-if="filtered.length === 0" class="list-empty" data-testid="agent-conversations-empty">
        {{ query.trim() ? "没有匹配的会话" : "暂无会话，点击「新建对话」开始" }}
      </div>
    </div>
  </nav>
</template>

<style scoped>
.conversation-list {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  background: var(--color-panel);
  border-right: 1px solid var(--color-border);
}
.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
}
.list-head strong {
  color: var(--color-fg);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
}
.new-session {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 28px;
  padding: 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-accent) 36%, var(--color-border));
  border-radius: var(--radius-md);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.list-search {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: 0 var(--space-3) var(--space-2);
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-subtle);
}
.list-search input {
  width: 100%;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
  outline: none;
}
.list-scroll {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: 0 var(--space-2) var(--space-3);
}
.session-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  text-align: left;
  cursor: pointer;
}
.session-row:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.session-row.active {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.session-icon {
  flex-shrink: 0;
}
.session-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}
.session-title {
  overflow: hidden;
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-copy small {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.running-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-accent);
}
.list-empty {
  padding: var(--space-3) var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
</style>
