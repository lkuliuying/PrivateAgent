<script setup lang="ts">
/**
 * PaSegmentedControl · 分段选择器（等价单选，用于视图/模式切换）。
 */
defineProps<{
  modelValue: string;
  options: { value: string; label: string; disabled?: boolean }[];
  size?: "sm" | "md";
}>();

const emit = defineEmits<{ "update:modelValue": [value: string] }>();
</script>

<template>
  <div class="pa-segmented" :class="`is-${size ?? 'md'}`" role="radiogroup">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      class="pa-segment"
      :class="{ 'is-active': modelValue === option.value }"
      role="radio"
      :aria-checked="modelValue === option.value"
      :disabled="option.disabled"
      @click="emit('update:modelValue', option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.pa-segmented {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-sunken);
  gap: 2px;
}
.pa-segment {
  height: 28px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: background var(--pa-motion-fast) var(--ease),
    color var(--pa-motion-fast) var(--ease);
}
.is-sm .pa-segment {
  height: 22px;
  padding: 0 var(--space-2);
  font-size: var(--pa-text-meta);
}
.pa-segment:hover {
  color: var(--color-fg);
}
.pa-segment.is-active {
  background: var(--color-surface);
  color: var(--color-fg);
  box-shadow: var(--shadow-sm);
}
.pa-segment:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.pa-segment:disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
@media (prefers-reduced-motion: reduce) {
  .pa-segment {
    transition: none;
  }
}
</style>
