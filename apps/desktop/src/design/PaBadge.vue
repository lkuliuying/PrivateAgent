<script setup lang="ts">
/**
 * PaBadge · 语义徽标（状态/计数/标签）。tone 映射语义状态色。
 */
withDefaults(
  defineProps<{
    tone?: "neutral" | "info" | "success" | "warning" | "danger" | "muted";
  }>(),
  { tone: "neutral" }
);
</script>

<template>
  <span class="pa-badge" :class="`tone-${tone}`">
    <slot />
  </span>
</template>

<style scoped>
.pa-badge {
  display: inline-flex;
  height: 20px;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-size: var(--pa-t-11);
  font-weight: var(--font-medium);
  line-height: 1;
  white-space: nowrap;
}
.tone-info {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.tone-success {
  background: var(--color-success-soft);
  color: var(--color-success-fg);
}
.tone-warning {
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
}
.tone-danger {
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
}
.tone-muted {
  background: var(--color-surface-muted);
  color: var(--color-fg-faint);
}
</style>
