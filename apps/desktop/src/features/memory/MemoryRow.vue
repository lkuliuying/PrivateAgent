<script setup lang="ts">
/**
 * MemoryRow · 记忆列表项（0.4.0 D4 拆分自 MemoryWorkspace）
 */
import type { MemoryItem } from "../../types";

defineProps<{
  memory: MemoryItem;
  active: boolean;
  /** 类型/状态展示文案由父层传入（KIND_LABEL/statusLabel） */
  kindLabel: string;
  statusLabel: string;
  statusTone: string;
}>();

const emit = defineEmits<{ select: [id: number] }>();
</script>

<template>
  <button
    class="mem-row"
    :class="{ active, disabled: !memory.enabled }"
    @click="emit('select', memory.id)"
  >
    <span class="mem-title">{{ memory.title }}</span>
    <span class="mem-meta">
      <span class="status-dot" :class="statusTone" />
      {{ kindLabel }} · {{ statusLabel }}
      <span v-if="!memory.enabled"> · 已禁用</span>
      <span v-if="memory.sensitive"> · 敏感</span>
    </span>
  </button>
</template>

<style scoped>
.mem-row {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
  padding: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg);
  text-align: left;
  cursor: pointer;
}
.mem-row:hover {
  background: var(--color-surface-hover);
}
.mem-row.active {
  border-color: color-mix(in srgb, var(--color-accent) 40%, var(--color-border));
  background: var(--color-accent-soft);
}
.mem-row.disabled {
  opacity: 0.55;
}
.mem-row:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.mem-title {
  overflow: hidden;
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mem-meta {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
  color: var(--color-fg-subtle);
  font-size: var(--pa-t-11);
  white-space: nowrap;
}
.status-dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-fg-faint);
}
.status-dot.warn {
  background: var(--color-warning);
}
.status-dot.ok {
  background: var(--color-success);
}
.status-dot.bad {
  background: var(--color-danger);
}
.status-dot.muted {
  background: var(--color-fg-faint);
}
</style>
