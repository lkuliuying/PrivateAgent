<script setup lang="ts">
/**
 * Toast 宿主（第七阶段 M4）。渲染 notifications store 的 toast 队列，
 * 固定在右上角（z-toast），替代关键路径的 window.alert。
 * error/warning 常驻需手动关闭；info/success 自动消失。
 */
import { PhX, PhCheckCircle, PhWarning, PhInfo, PhXCircle } from "@phosphor-icons/vue";
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
  info: "toast--info",
  success: "toast--success",
  warning: "toast--warning",
  error: "toast--error",
};
</script>

<template>
  <div class="toast-host" role="region" aria-label="通知" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="t in notify.toasts.value"
        :key="t.id"
        class="toast"
        :class="levelClass[t.level]"
        role="status"
      >
        <component :is="iconOf[t.level]" class="toast-icon" :size="18" weight="fill" />
        <div class="toast-body">
          <strong class="toast-title">{{ t.title }}</strong>
          <p v-if="t.message" class="toast-message">{{ t.message }}</p>
        </div>
        <button
          v-if="t.action"
          class="toast-action"
          @click="t.action.run(); notify.dismiss(t.id)"
        >
          {{ t.action.label }}
        </button>
        <button
          class="toast-close"
          aria-label="关闭通知"
          title="关闭"
          @click="notify.dismiss(t.id)"
        >
          <PhX :size="14" weight="bold" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: var(--space-5);
  right: var(--space-5);
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 380px;
  max-width: calc(100vw - var(--space-8));
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-left: 3px solid var(--color-fg-subtle);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
}
.toast--info {
  border-left-color: var(--color-info);
}
.toast--success {
  border-left-color: var(--color-success);
}
.toast--success .toast-icon {
  color: var(--color-success);
}
.toast--warning {
  border-left-color: var(--color-warning);
}
.toast--warning .toast-icon {
  color: var(--color-warning);
}
.toast--error {
  border-left-color: var(--color-danger);
}
.toast--error .toast-icon {
  color: var(--color-danger);
}
.toast--info .toast-icon {
  color: var(--color-info);
}
.toast-icon {
  flex-shrink: 0;
  margin-top: 1px;
}
.toast-body {
  flex: 1;
  min-width: 0;
}
.toast-title {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
  display: block;
}
.toast-message {
  margin: 2px 0 0;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
  line-height: var(--leading-normal);
  word-break: break-word;
}
.toast-action {
  flex-shrink: 0;
  align-self: center;
  border: 1px solid var(--color-border-strong);
  background: transparent;
  color: var(--color-accent);
  border-radius: var(--radius);
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease);
}
.toast-action:hover {
  background: var(--color-accent-soft);
}
.toast-close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--color-fg-faint);
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  transition: color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease);
}
.toast-close:hover {
  color: var(--color-fg);
  background: var(--color-surface-sunken);
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--duration) var(--ease),
    transform var(--duration) var(--ease);
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(16px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
</style>
