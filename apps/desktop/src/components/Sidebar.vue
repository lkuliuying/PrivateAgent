<script setup lang="ts">
import type { Session } from "../types";

defineProps<{ sessions: Session[]; currentId: number | null }>();
const emit = defineEmits<{
  select: [id: number];
  new: [];
  "show-kb": [];
  "show-settings": [];
}>();

function fmt(s: string): string {
  const d = new Date(s);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? `今天 ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`
    : `${d.getMonth() + 1}/${d.getDate()}`;
}
</script>

<template>
  <div class="sidebar">
    <div class="sidebar-head">
      <span class="brand">私人助手</span>
      <button class="new-btn" @click="emit('new')">+ 新建</button>
    </div>
    <div class="sessions">
      <div v-if="sessions.length === 0" class="empty">
        暂无会话
        <div class="empty-sub">点击「新建」开始对话</div>
      </div>
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === currentId }"
        @click="emit('select', s.id)"
      >
        <div class="s-title">{{ s.title }}</div>
        <div class="s-time">{{ fmt(s.updated_at) }}</div>
      </div>
    </div>
    <div class="sidebar-foot">
      <button @click="emit('show-kb')">📚 知识库</button>
      <button @click="emit('show-settings')">⚙ 设置 / 状态</button>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 240px;
  flex-shrink: 0;
  background: #1e1f22;
  color: #d8d9da;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #2d2e31;
}
.sidebar-head {
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #2d2e31;
}
.brand {
  font-weight: 600;
  font-size: 15px;
}
.new-btn {
  background: #2a2b2e;
  color: #d8d9da;
  border: 1px solid #3a3b3e;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 13px;
  cursor: pointer;
}
.new-btn:hover {
  background: #34353a;
}
.sessions {
  flex: 1;
  overflow: auto;
  padding: 8px;
}
.empty {
  text-align: center;
  color: #6a6b6e;
  font-size: 13px;
  padding: 40px 0;
}
.empty-sub {
  font-size: 11px;
  color: #4a4b4e;
  margin-top: 4px;
}
.session-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
}
.session-item:hover {
  background: #2a2b2e;
}
.session-item.active {
  background: #2f3033;
}
.s-title {
  font-size: 13px;
  color: #e0e1e2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.s-time {
  font-size: 11px;
  color: #6a6b6e;
  margin-top: 3px;
}
.sidebar-foot {
  padding: 12px 16px;
  border-top: 1px solid #2d2e31;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sidebar-foot button {
  background: transparent;
  color: #9a9b9e;
  border: 1px solid #3a3b3e;
  border-radius: 6px;
  padding: 8px;
  font-size: 13px;
  cursor: pointer;
}
.sidebar-foot button:hover {
  background: #2a2b2e;
  color: #d8d9da;
}
</style>
