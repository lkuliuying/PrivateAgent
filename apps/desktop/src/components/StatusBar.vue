<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import { PhActivity, PhBell } from "@phosphor-icons/vue";
import { useNotifications } from "../stores/notifications";

/**
 * 底部状态栏只呈现用户可操作的通知与当前任务状态。
 * 服务端部署后不在工作台底部暴露 API/MySQL/Chroma 拓扑；详细健康状态
 * 仍由设置页与诊断页按需展示。
 */
defineProps<{ taskLabel?: string }>();

const notify = useNotifications();
let notifyTimer: number | null = null;

onMounted(() => {
  // 拉取持久化通知，让铃铛角标反映后端未读（导入/备份等异步结果）
  void notify.loadPersisted();
  notifyTimer = window.setInterval(() => void notify.loadPersisted(), 30000);
});
onUnmounted(() => {
  if (notifyTimer) window.clearInterval(notifyTimer);
});
</script>

<template>
  <div class="statusbar" role="status" aria-label="任务与通知状态">
    <div class="sb-right">
      <button
        class="sb-bell"
        :class="{ hasunread: notify.unreadCount.value > 0 }"
        :title="notify.unreadCount.value > 0 ? `通知中心（${notify.unreadCount.value} 条未读）` : '通知中心'"
        aria-label="通知中心"
        @click="notify.openCenter()"
      >
        <PhBell :size="13" weight="regular" />
        <span v-if="notify.unreadCount.value > 0" class="sb-bell-badge">{{
          notify.unreadCount.value
        }}</span>
      </button>
      <div class="sb-item">
        <PhActivity :size="12" weight="regular" />
        <span class="sb-value">{{ taskLabel || "空闲" }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.statusbar {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 var(--space-3);
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}
.sb-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-shrink: 0;
}
.sb-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  white-space: nowrap;
}
.sb-value {
  max-width: 220px;
  font-variant-numeric: tabular-nums;
}
.sb-bell {
  position: relative;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius);
  display: grid;
  place-items: center;
  transition: background var(--duration-fast) var(--ease),
    color var(--duration-fast) var(--ease);
}
.sb-bell:hover {
  background: var(--color-surface-sunken);
  color: var(--color-fg);
}
.sb-bell.hasunread {
  color: var(--color-accent);
}
.sb-bell-badge {
  position: absolute;
  top: -2px;
  right: -2px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  background: var(--color-danger);
  color: var(--pa-btn-danger-fg);
  font-size: 9px;
  font-weight: var(--font-semibold);
  line-height: 14px;
  border-radius: var(--radius-full);
  text-align: center;
}
</style>
