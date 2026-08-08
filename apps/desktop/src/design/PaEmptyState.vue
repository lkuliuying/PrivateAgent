<script setup lang="ts">
/**
 * PaEmptyState · 空状态（图标 + 标题 + 描述 + 可选动作）。
 */
import type { Component } from "vue";

withDefaults(
  defineProps<{
    icon?: Component;
    title: string;
    description?: string;
    /** 首次引导等少量场景使用大标题 */
    display?: boolean;
  }>(),
  { icon: undefined, description: "", display: false }
);
</script>

<template>
  <div class="pa-empty" :class="{ 'is-display': display }">
    <div v-if="icon" class="pa-empty-icon">
      <component :is="icon" :size="display ? 40 : 28" weight="duotone" />
    </div>
    <p class="pa-empty-title">{{ title }}</p>
    <p v-if="description" class="pa-empty-description">{{ description }}</p>
    <div v-if="$slots.default" class="pa-empty-actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.pa-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10) var(--space-6);
  text-align: center;
}
.pa-empty-icon {
  display: grid;
  place-items: center;
  margin-bottom: var(--space-3);
  color: var(--color-fg-faint);
}
.pa-empty-title {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--pa-text-section);
  font-weight: var(--font-semibold);
}
.is-display .pa-empty-title {
  font-size: var(--pa-text-display);
}
.pa-empty-description {
  max-width: 480px;
  margin: var(--space-2) 0 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-body);
  line-height: var(--leading-normal);
}
.pa-empty-actions {
  display: flex;
  margin-top: var(--space-5);
  gap: var(--space-2);
}
</style>
