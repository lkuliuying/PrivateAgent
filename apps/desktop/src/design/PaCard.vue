<script setup lang="ts">
/**
 * PaCard · 基础卡片（仅用于独立对象：消息/文档/活动/审批）。
 * hoverable 时位移 ≤2px（D0 动效冻结），不默认缩放。
 */
withDefaults(
  defineProps<{
    padding?: "sm" | "md" | "lg";
    raised?: boolean;
    hoverable?: boolean;
  }>(),
  { padding: "md", raised: false, hoverable: false }
);
</script>

<template>
  <div
    class="pa-card"
    :class="[`pad-${padding}`, { 'is-raised': raised, 'is-hoverable': hoverable }]"
  >
    <slot />
  </div>
</template>

<style scoped>
.pa-card {
  border: 1px solid var(--pa-card-border);
  border-radius: var(--pa-card-radius);
  background: var(--pa-card-bg);
}
.pad-sm { padding: var(--space-3); }
.pad-md { padding: var(--pa-card-padding); }
.pad-lg { padding: var(--space-5); }
.is-raised {
  box-shadow: var(--shadow);
}
.is-hoverable {
  transition: transform var(--pa-motion-fast) var(--ease-out),
    border-color var(--pa-motion-fast) var(--ease),
    box-shadow var(--pa-motion-fast) var(--ease);
}
.is-hoverable:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
  transform: translateY(calc(-1 * var(--pa-card-hover-lift)));
}
@media (prefers-reduced-motion: reduce) {
  .is-hoverable,
  .is-hoverable:hover {
    transform: none;
    transition: none;
  }
}
</style>
