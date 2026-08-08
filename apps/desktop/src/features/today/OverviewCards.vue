<script setup lang="ts">
/**
 * OverviewCards · 今日概览卡片（0.4.0 D4 拆分自 TodayView）
 * 纯展示组件：label/value/hint/tone + 点击导航。
 */
import type { View } from "../../types";

export interface OverviewCardItem {
  label: string;
  value: number;
  hint: string;
  view: View;
  tone?: string;
}

defineProps<{ items: OverviewCardItem[] }>();

const emit = defineEmits<{ navigate: [view: View] }>();
</script>

<template>
  <section class="today-overview" aria-label="今日概览">
    <button
      v-for="item in items"
      :key="item.label"
      :class="['overview-item', item.tone ?? '']"
      data-agent-card
      @click="emit('navigate', item.view)"
    >
      <span class="overview-label">{{ item.label }}</span>
      <strong>{{ item.value }}</strong>
      <small>{{ item.hint }}</small>
    </button>
  </section>
</template>

<style scoped>
.today-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.overview-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  text-align: left;
  cursor: pointer;
}
.overview-item:hover {
  border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
}
.overview-item:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.overview-item.danger {
  border-color: color-mix(in srgb, var(--color-danger) 35%, var(--color-border));
}
.overview-label {
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.overview-item strong {
  font-size: var(--pa-text-section);
  font-variant-numeric: tabular-nums;
}
.overview-item.danger strong {
  color: var(--color-danger-fg);
}
.overview-item small {
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
}
@media (max-width: 900px) {
  .today-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
