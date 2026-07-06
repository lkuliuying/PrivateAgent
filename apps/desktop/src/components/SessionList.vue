<script setup lang="ts">
import { PhPlus } from "@phosphor-icons/vue";
import type { Session } from "../types";

/** 会话列表 · chat 视图的列表区。从原 Sidebar 抽出（导航与品牌已迁至 NavRail）。 */
defineProps<{ sessions: Session[]; currentId: number | null }>();
const emit = defineEmits<{ select: [id: number]; new: [] }>();

function fmt(s: string): string {
  const d = new Date(s);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? `今天 ${d.getHours().toString().padStart(2, "0")}:${d
        .getMinutes()
        .toString()
        .padStart(2, "0")}`
    : `${d.getMonth() + 1}/${d.getDate()}`;
}
</script>

<template>
  <div class="session-list">
    <div class="list-head">
      <span class="list-title">会话</span>
      <button
        class="pa-btn pa-btn--subtle pa-btn--sm new-btn"
        title="新建会话"
        @click="emit('new')"
      >
        <PhPlus :size="14" weight="bold" />
        <span>新建</span>
      </button>
    </div>

    <div class="list-body">
      <div v-if="sessions.length === 0" class="empty">
        <div class="empty-title">暂无会话</div>
        <div class="empty-sub">点击「新建」开始对话</div>
      </div>
      <button
        v-for="s in sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === currentId }"
        :aria-current="s.id === currentId ? 'true' : undefined"
        @click="emit('select', s.id)"
      >
        <div class="s-title">{{ s.title }}</div>
        <div class="s-time">{{ fmt(s.updated_at) }}</div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.session-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.list-head {
  flex-shrink: 0;
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-3);
  border-bottom: 1px solid var(--color-border);
}
.list-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-fg-muted);
  letter-spacing: 0.04em;
}
.new-btn {
  height: 26px;
}

.list-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.empty {
  text-align: center;
  color: var(--color-fg-subtle);
  padding: var(--space-8) 0;
}
.empty-title {
  font-size: var(--text-base);
}
.empty-sub {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: var(--space-1);
}

.session-item {
  position: relative;
  display: block;
  width: 100%;
  text-align: left;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease);
}
.session-item:hover {
  background: var(--color-surface-sunken);
}
.session-item:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.session-item.active {
  background: var(--color-accent-soft);
}
.session-item.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  border-radius: 0 var(--radius-full) var(--radius-full) 0;
  background: var(--color-accent);
}
.s-title {
  font-size: var(--text-sm);
  color: var(--color-fg);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-item.active .s-title {
  color: var(--color-accent-soft-fg);
  font-weight: var(--font-medium);
}
.s-time {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: 2px;
}
</style>
