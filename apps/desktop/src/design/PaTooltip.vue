<script setup lang="ts">
/**
 * PaTooltip · 轻量提示（CSS 实现，hover/focus 触发；不放关键操作）。
 */
withDefaults(
  defineProps<{
    text: string;
    placement?: "top" | "bottom";
  }>(),
  { placement: "top" }
);
</script>

<template>
  <span class="pa-tooltip" :data-tip="text" :class="`place-${placement}`">
    <slot />
  </span>
</template>

<style scoped>
.pa-tooltip {
  position: relative;
  display: inline-flex;
}
.pa-tooltip::after {
  content: attr(data-tip);
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  z-index: var(--z-overlay);
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-fg);
  color: var(--color-surface);
  font-size: var(--pa-text-meta);
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, 2px);
  transition: opacity var(--pa-motion-fast) var(--ease),
    transform var(--pa-motion-fast) var(--ease);
}
.pa-tooltip.place-bottom::after {
  top: calc(100% + 6px);
  bottom: auto;
  transform: translate(-50%, -2px);
}
.pa-tooltip:hover::after,
.pa-tooltip:focus-within::after {
  opacity: 1;
  transform: translate(-50%, 0);
}
@media (prefers-reduced-motion: reduce) {
  .pa-tooltip::after {
    transition: none;
  }
}
</style>
