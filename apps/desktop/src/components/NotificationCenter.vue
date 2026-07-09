<script setup lang="ts">
/**
 * 通知中心（第七阶段 M4）。右上滑出面板，回看 notifications store 历史记录。
 * M4 接入 app_notifications 后端后，历史与 DB 合并（此处先消费内存历史）。
 * 由 store.openCenter() 触发，Esc/遮罩/关闭按钮关闭。
 */
import { computed, onMounted, onBeforeUnmount } from "vue";
import {
  PhX,
  PhBell,
  PhCheckCircle,
  PhWarning,
  PhInfo,
  PhXCircle,
  PhChecks,
  PhTrash,
} from "@phosphor-icons/vue";
import { useNotifications } from "../stores/notifications";
import type { NotificationLevel } from "../types";

const notify = useNotifications();

const iconOf: Record<NotificationLevel, typeof PhInfo> = {
  info: PhInfo,
  success: PhCheckCircle,
  warning: PhWarning,
  error: PhXCircle,
};

const levelClass: Record<NotificationLevel, string> = {
  info: "nc-entry--info",
  success: "nc-entry--success",
  warning: "nc-entry--warning",
  error: "nc-entry--error",
};

const list = computed(() => notify.history.value);

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  return `${Math.floor(diff / 86_400_000)} 天前`;
}

function onKey(e: KeyboardEvent): void {
  if (e.key === "Escape" && notify.centerOpen.value) {
    notify.closeCenter();
  }
}

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <Transition name="nc">
      <div v-if="notify.centerOpen.value" class="nc-scrim" @click.self="notify.closeCenter()">
        <aside class="nc-panel" role="dialog" aria-modal="true" aria-label="通知中心">
          <header class="nc-head">
            <div class="nc-title">
              <PhBell :size="18" weight="regular" />
              <span>通知中心</span>
              <span v-if="notify.unreadCount.value > 0" class="nc-badge">
                {{ notify.unreadCount.value }}
              </span>
            </div>
            <div class="nc-tools">
              <button
                class="nc-tool"
                title="全部标为已读"
                @click="notify.markAllRead()"
              >
                <PhChecks :size="15" />
              </button>
              <button
                class="nc-tool"
                title="清空历史"
                @click="notify.clearHistory()"
              >
                <PhTrash :size="15" />
              </button>
              <button class="nc-tool" title="关闭" @click="notify.closeCenter()">
                <PhX :size="16" weight="bold" />
              </button>
            </div>
          </header>

          <div class="nc-body">
            <p v-if="list.length === 0" class="nc-empty">暂无通知</p>
            <article
              v-for="h in list"
              :key="h.id"
              class="nc-entry"
              :class="[levelClass[h.level], { unread: !h.read }]"
            >
              <component :is="iconOf[h.level]" class="nc-icon" :size="16" weight="fill" />
              <div class="nc-content">
                <div class="nc-entry-head">
                  <strong class="nc-entry-title">{{ h.title }}</strong>
                  <span class="nc-time">{{ relativeTime(h.created_at) }}</span>
                </div>
                <p v-if="h.message" class="nc-entry-msg">{{ h.message }}</p>
              </div>
            </article>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.nc-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: var(--color-scrim);
  display: flex;
  justify-content: flex-end;
}
.nc-panel {
  width: 420px;
  max-width: 100vw;
  height: 100vh;
  background: var(--color-surface-raised);
  border-left: 1px solid var(--color-border);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
}
.nc-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}
.nc-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.nc-badge {
  background: var(--color-danger);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  border-radius: var(--radius-full);
  padding: 1px var(--space-2);
  min-width: 18px;
  text-align: center;
}
.nc-tools {
  display: flex;
  gap: var(--space-1);
}
.nc-tool {
  border: none;
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
  padding: var(--space-2);
  border-radius: var(--radius);
  display: grid;
  place-items: center;
  transition: background var(--duration-fast) var(--ease),
    color var(--duration-fast) var(--ease);
}
.nc-tool:hover {
  background: var(--color-surface-sunken);
  color: var(--color-fg);
}
.nc-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.nc-empty {
  margin: var(--space-10) auto;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.nc-entry {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border-left: 3px solid transparent;
  transition: background var(--duration-fast) var(--ease);
}
.nc-entry.unread {
  background: var(--color-accent-soft);
}
.nc-entry--info {
  border-left-color: var(--color-info);
}
.nc-entry--info .nc-icon {
  color: var(--color-info);
}
.nc-entry--success {
  border-left-color: var(--color-success);
}
.nc-entry--success .nc-icon {
  color: var(--color-success);
}
.nc-entry--warning {
  border-left-color: var(--color-warning);
}
.nc-entry--warning .nc-icon {
  color: var(--color-warning);
}
.nc-entry--error {
  border-left-color: var(--color-danger);
}
.nc-entry--error .nc-icon {
  color: var(--color-danger);
}
.nc-icon {
  flex-shrink: 0;
  margin-top: 1px;
}
.nc-content {
  flex: 1;
  min-width: 0;
}
.nc-entry-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}
.nc-entry-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.nc-time {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  flex-shrink: 0;
}
.nc-entry-msg {
  margin: 2px 0 0;
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  line-height: var(--leading-normal);
  word-break: break-word;
}

.nc-enter-active,
.nc-leave-active {
  transition: opacity var(--duration) var(--ease);
}
.nc-enter-active .nc-panel,
.nc-leave-active .nc-panel {
  transition: transform var(--duration) var(--ease-out);
}
.nc-enter-from,
.nc-leave-to {
  opacity: 0;
}
.nc-enter-from .nc-panel,
.nc-leave-to .nc-panel {
  transform: translateX(100%);
}
</style>
