<script setup lang="ts">
/**
 * PaTabs · 页签（role=tablist，方向键切换，aria-selected 完整）。
 */
import { ref, watch } from "vue";

const props = defineProps<{
  modelValue: string;
  items: { key: string; label: string; badge?: string | number; disabled?: boolean }[];
}>();

const emit = defineEmits<{ "update:modelValue": [key: string] }>();

const tabRefs = ref<HTMLButtonElement[]>([]);

function select(key: string, disabled?: boolean) {
  if (disabled) return;
  emit("update:modelValue", key);
}

function onKeydown(event: KeyboardEvent, index: number) {
  const enabled = props.items
    .map((item, i) => ({ item, i }))
    .filter((entry) => !entry.item.disabled);
  if (!enabled.length) return;
  const currentPos = enabled.findIndex((entry) => entry.i === index);
  let nextPos = -1;
  if (event.key === "ArrowRight") nextPos = (currentPos + 1) % enabled.length;
  else if (event.key === "ArrowLeft")
    nextPos = (currentPos - 1 + enabled.length) % enabled.length;
  else if (event.key === "Home") nextPos = 0;
  else if (event.key === "End") nextPos = enabled.length - 1;
  if (nextPos < 0) return;
  event.preventDefault();
  const target = enabled[nextPos];
  select(target.item.key);
  tabRefs.value[target.i]?.focus();
}

watch(
  () => props.modelValue,
  () => {
    tabRefs.value = tabRefs.value.slice(0, props.items.length);
  }
);
</script>

<template>
  <div class="pa-tabs" role="tablist">
    <button
      v-for="(item, index) in items"
      :key="item.key"
      :ref="(el) => { if (el) tabRefs[index] = el as HTMLButtonElement; }"
      class="pa-tab"
      :class="{ 'is-active': modelValue === item.key }"
      role="tab"
      :aria-selected="modelValue === item.key"
      :tabindex="modelValue === item.key ? 0 : -1"
      :disabled="item.disabled"
      @click="select(item.key, item.disabled)"
      @keydown="onKeydown($event, index)"
    >
      {{ item.label }}
      <span v-if="item.badge !== undefined" class="pa-tab-badge">{{ item.badge }}</span>
    </button>
  </div>
</template>

<style scoped>
.pa-tabs {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  border-bottom: 1px solid var(--color-border);
}
.pa-tab {
  display: inline-flex;
  position: relative;
  height: 36px;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-3);
  border: none;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-body);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: color var(--pa-motion-fast) var(--ease);
}
.pa-tab:hover {
  color: var(--color-fg);
}
.pa-tab.is-active {
  color: var(--color-accent);
}
.pa-tab.is-active::after {
  content: "";
  position: absolute;
  right: var(--space-2);
  bottom: -1px;
  left: var(--space-2);
  height: 2px;
  border-radius: var(--radius-full);
  background: var(--color-accent);
}
.pa-tab:focus-visible {
  outline: none;
  box-shadow: inset var(--focus-ring);
}
.pa-tab:disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
.pa-tab-badge {
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-size: var(--pa-t-11);
}
.pa-tab.is-active .pa-tab-badge {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
</style>
