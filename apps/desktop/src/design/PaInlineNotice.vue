<script setup lang="ts">
/**
 * PaInlineNotice · 行内通知横幅（连接中断、权限提示、轻量告警）。
 */
import type { Component } from "vue";
import {
  PhCheckCircle,
  PhInfo,
  PhWarning,
  PhWarningCircle,
} from "@phosphor-icons/vue";

const props = withDefaults(
  defineProps<{
    tone?: "info" | "success" | "warning" | "danger";
    title?: string;
  }>(),
  { tone: "info", title: "" }
);

const ICONS: Record<string, Component> = {
  info: PhInfo,
  success: PhCheckCircle,
  warning: PhWarning,
  danger: PhWarningCircle,
};
</script>

<template>
  <div
    class="pa-notice"
    :class="`tone-${tone}`"
    :role="tone === 'danger' || tone === 'warning' ? 'alert' : 'status'"
  >
    <component :is="ICONS[props.tone]" :size="16" weight="fill" class="pa-notice-icon" />
    <div class="pa-notice-body">
      <strong v-if="title" class="pa-notice-title">{{ title }}</strong>
      <div class="pa-notice-content"><slot /></div>
    </div>
    <div v-if="$slots.actions" class="pa-notice-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.pa-notice {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-size: var(--pa-text-compact);
  line-height: var(--leading-normal);
}
.pa-notice-icon {
  flex-shrink: 0;
  margin-top: 1px;
}
.pa-notice-body {
  min-width: 0;
  flex: 1;
}
.pa-notice-title {
  display: block;
  margin-bottom: 1px;
  font-weight: var(--font-semibold);
}
.pa-notice-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-2);
}
.tone-info {
  border-color: color-mix(in srgb, var(--color-accent) 30%, var(--color-border));
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.tone-success {
  border-color: color-mix(in srgb, var(--color-success) 28%, var(--color-border));
  background: var(--color-success-soft);
  color: var(--color-success-fg);
}
.tone-warning {
  border-color: color-mix(in srgb, var(--color-warning) 32%, var(--color-border));
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
}
.tone-danger {
  border-color: color-mix(in srgb, var(--color-danger) 30%, var(--color-border));
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
}
</style>
