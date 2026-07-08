<script setup lang="ts">
import { PhArrowClockwise, PhPlus, PhSlidersHorizontal } from "@phosphor-icons/vue";
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
      <div>
        <span class="list-title">新建对话</span>
        <span class="list-subtitle">最近上下文</span>
      </div>
      <button
        class="new-btn"
        title="新建会话"
        @click="emit('new')"
      >
        <PhPlus :size="16" weight="bold" />
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
        <div class="s-row">
          <div class="s-title">{{ s.title }}</div>
          <div class="s-time">{{ fmt(s.updated_at) }}</div>
        </div>
        <div class="s-preview">继续整理这条对话里的重点和下一步...</div>
      </button>
    </div>

    <div class="list-foot">
      <button class="foot-action">
        <PhArrowClockwise :size="14" />
        <span>同步上下文</span>
      </button>
      <button class="foot-action" title="筛选">
        <PhSlidersHorizontal :size="14" />
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-6) var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}
.list-title {
  display: block;
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.list-subtitle {
  display: block;
  margin-top: 4px;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.new-btn {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
}
.new-btn:hover {
  color: var(--color-accent);
  border-color: var(--color-accent);
}

.list-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-3) var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
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
  padding: var(--space-3);
  border: 1px solid transparent;
  background: transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease);
}
.session-item:hover {
  background: rgba(255, 255, 255, 0.54);
  border-color: var(--color-border);
}
.session-item:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.session-item.active {
  background: var(--color-accent-soft);
  border-color: color-mix(in srgb, var(--color-accent) 28%, var(--color-border));
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
.s-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.session-item.active .s-title {
  color: var(--color-accent-soft-fg);
  font-weight: var(--font-medium);
}
.s-time {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  white-space: nowrap;
}
.s-preview {
  margin-top: var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
  line-height: 1.45;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.list-foot {
  flex-shrink: 0;
  display: flex;
  gap: var(--space-2);
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
}
.foot-action {
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
}
.foot-action:first-child {
  flex: 1;
}
.foot-action:hover {
  background: var(--color-surface);
  color: var(--color-accent);
}
</style>
