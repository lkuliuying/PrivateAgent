<script setup lang="ts">
/**
 * PaSkeleton · 骨架屏（加载占位）。lines 控制行数，reduced-motion 下静态展示。
 */
withDefaults(
  defineProps<{
    lines?: number;
    /** 首行缩窄比例（0–1），模拟自然段落 */
    lastLineWidth?: number;
  }>(),
  { lines: 3, lastLineWidth: 0.6 }
);
</script>

<template>
  <div class="pa-skeleton" aria-hidden="true">
    <div
      v-for="line in lines"
      :key="line"
      class="pa-skeleton-line"
      :style="line === lines ? { width: `${lastLineWidth * 100}%` } : undefined"
    />
  </div>
</template>

<style scoped>
.pa-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2) 0;
}
.pa-skeleton-line {
  height: 12px;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    90deg,
    var(--color-surface-sunken) 25%,
    var(--color-surface-muted) 50%,
    var(--color-surface-sunken) 75%
  );
  background-size: 200% 100%;
  animation: pa-skeleton-shimmer 1.6s var(--ease) infinite;
}
@keyframes pa-skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .pa-skeleton-line {
    animation: none;
    background: var(--color-surface-sunken);
  }
}
</style>
