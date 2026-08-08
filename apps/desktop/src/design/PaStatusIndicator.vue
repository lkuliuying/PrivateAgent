<script setup lang="ts">
/**
 * PaStatusIndicator · 状态点 + 可选文字（运行/成功/等待/失败/空闲）。
 * pulse 仅用于实时连接态；reduced-motion 下自动退化为静态点。
 */
withDefaults(
  defineProps<{
    tone?: "ok" | "info" | "warn" | "bad" | "idle";
    label?: string;
    pulse?: boolean;
  }>(),
  { tone: "idle", label: "", pulse: false }
);
</script>

<template>
  <span class="pa-status" :class="`tone-${tone}`">
    <span
      class="pa-status-dot"
      :class="{ 'is-pulse': pulse }"
      aria-hidden="true"
    />
    <span v-if="label || $slots.default" class="pa-status-label">
      <slot>{{ label }}</slot>
    </span>
  </span>
</template>

<style scoped>
.pa-status {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--pa-text-meta);
  color: var(--color-fg-muted);
}
.pa-status-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--pa-status-color, var(--color-fg-faint));
}
.tone-ok { --pa-status-color: var(--color-success); }
.tone-info { --pa-status-color: var(--color-accent); }
.tone-warn { --pa-status-color: var(--color-warning); }
.tone-bad { --pa-status-color: var(--color-danger); }
.tone-idle { --pa-status-color: var(--color-fg-faint); }
.tone-ok .pa-status-label { color: var(--color-success-fg); }
.tone-warn .pa-status-label { color: var(--color-warning-fg); }
.tone-bad .pa-status-label { color: var(--color-danger-fg); }
.pa-status-dot.is-pulse {
  box-shadow: 0 0 0 0 var(--pa-status-color);
  animation: pa-status-pulse 1.8s var(--ease) infinite;
}
@keyframes pa-status-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--pa-status-color) 50%, transparent); }
  70% { box-shadow: 0 0 0 5px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
@media (prefers-reduced-motion: reduce) {
  .pa-status-dot.is-pulse {
    animation: none;
    box-shadow: none;
  }
}
</style>
