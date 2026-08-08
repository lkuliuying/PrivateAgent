<script setup lang="ts">
/**
 * PaDisclosure · 可折叠分区（渐进披露：默认摘要，细节按需展开）。
 */
import { ref } from "vue";
import { PhCaretRight } from "@phosphor-icons/vue";

const props = withDefaults(
  defineProps<{
    title: string;
    open?: boolean;
    /** 标题右侧摘要（折叠时仍可见） */
    summary?: string;
  }>(),
  { open: false, summary: "" }
);

const emit = defineEmits<{ toggle: [open: boolean] }>();

const isOpen = ref(props.open);

function toggle() {
  isOpen.value = !isOpen.value;
  emit("toggle", isOpen.value);
}
</script>

<template>
  <div class="pa-disclosure" :class="{ 'is-open': isOpen }">
    <button
      type="button"
      class="pa-disclosure-trigger"
      :aria-expanded="isOpen"
      @click="toggle"
    >
      <PhCaretRight class="pa-disclosure-caret" :size="14" weight="bold" aria-hidden="true" />
      <span class="pa-disclosure-title">{{ title }}</span>
      <span v-if="summary" class="pa-disclosure-summary pa-ellipsis">{{ summary }}</span>
      <slot name="actions" />
    </button>
    <div v-if="isOpen" class="pa-disclosure-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.pa-disclosure {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.pa-disclosure-trigger {
  display: flex;
  width: 100%;
  min-height: 36px;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  text-align: left;
  cursor: pointer;
}
.pa-disclosure-trigger:hover {
  background: var(--color-surface-hover);
}
.pa-disclosure-trigger:focus-visible {
  outline: none;
  box-shadow: inset var(--focus-ring);
}
.pa-disclosure-caret {
  flex-shrink: 0;
  color: var(--color-fg-faint);
  transition: transform var(--pa-motion-fast) var(--ease);
}
.is-open .pa-disclosure-caret {
  transform: rotate(90deg);
}
.pa-disclosure-title {
  flex-shrink: 0;
}
.pa-disclosure-summary {
  min-width: 0;
  flex: 1;
  color: var(--color-fg-faint);
  font-weight: var(--font-normal);
}
.pa-disclosure-body {
  padding: 0 var(--space-3) var(--space-3) calc(var(--space-3) + 22px);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  line-height: var(--leading-normal);
}
@media (prefers-reduced-motion: reduce) {
  .pa-disclosure-caret {
    transition: none;
  }
}
</style>
