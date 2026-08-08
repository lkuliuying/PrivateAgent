<script setup lang="ts">
/**
 * PaSpinner · 加载指示器。
 * reduced-motion 下不旋转，由调用方搭配文字说明（动效不承载状态信息）。
 */
withDefaults(
  defineProps<{
    size?: number;
    /** 无文字说明时提供给辅助技术的标签 */
    label?: string;
  }>(),
  { size: 16, label: "加载中" }
);
</script>

<template>
  <span
    class="pa-spinner"
    role="status"
    :aria-label="label"
    :style="{ width: `${size}px`, height: `${size}px` }"
  />
</template>

<style scoped>
.pa-spinner {
  display: inline-block;
  flex-shrink: 0;
  border: 2px solid var(--color-border-strong);
  border-top-color: var(--color-accent);
  border-radius: var(--radius-full);
  animation: pa-spinner-rotate 0.8s linear infinite;
}
@keyframes pa-spinner-rotate {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .pa-spinner {
    animation: none;
    border-top-color: var(--color-border-strong);
  }
}
</style>
