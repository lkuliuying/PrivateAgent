<script setup lang="ts">
/**
 * PaProgress · 进度条。value 为 null 时表示不确定进度（流动动画）。
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    value?: number | null;
    label?: string;
    tone?: "info" | "success" | "warning" | "danger";
  }>(),
  { value: null, label: "", tone: "info" }
);

const clamped = computed(() => {
  if (props.value === null) return null;
  return Math.min(100, Math.max(0, props.value));
});
</script>

<template>
  <div
    class="pa-progress"
    :class="[`tone-${tone}`, { 'is-indeterminate': clamped === null }]"
    role="progressbar"
    :aria-valuenow="clamped ?? undefined"
    :aria-valuemin="clamped === null ? undefined : 0"
    :aria-valuemax="clamped === null ? undefined : 100"
    :aria-label="label || '进度'"
  >
    <div
      class="pa-progress-bar"
      :style="clamped === null ? undefined : { width: `${clamped}%` }"
    />
  </div>
</template>

<style scoped>
.pa-progress {
  overflow: hidden;
  width: 100%;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
}
.pa-progress-bar {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--color-accent);
  transition: width var(--pa-motion-standard) var(--ease-out);
}
.tone-success .pa-progress-bar { background: var(--color-success); }
.tone-warning .pa-progress-bar { background: var(--color-warning); }
.tone-danger .pa-progress-bar { background: var(--color-danger); }
.is-indeterminate .pa-progress-bar {
  width: 40%;
  animation: pa-progress-slide 1.4s var(--ease) infinite;
}
@keyframes pa-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(260%); }
}
@media (prefers-reduced-motion: reduce) {
  .is-indeterminate .pa-progress-bar {
    animation: none;
    transform: none;
    width: 100%;
    opacity: 0.4;
  }
  .pa-progress-bar {
    transition: none;
  }
}
</style>
