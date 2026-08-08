<script setup lang="ts">
/**
 * PaButton · 设计系统基础按钮（tokens v2 组件层）
 * 覆盖 default / primary / ghost / subtle / danger 五种变体与 sm / md 两种尺寸，
 * 内置 loading / disabled 状态；hover 位移 ≤1px（D0 动效冻结）。
 */
import { computed } from "vue";
import PaSpinner from "./PaSpinner.vue";

const props = withDefaults(
  defineProps<{
    variant?: "default" | "primary" | "ghost" | "subtle" | "danger";
    size?: "sm" | "md";
    type?: "button" | "submit" | "reset";
    disabled?: boolean;
    loading?: boolean;
    /** 无文字、仅图标时设为正方形 */
    iconOnly?: boolean;
  }>(),
  {
    variant: "default",
    size: "md",
    type: "button",
    disabled: false,
    loading: false,
    iconOnly: false,
  }
);

const emit = defineEmits<{ click: [event: MouseEvent] }>();

const isDisabled = computed(() => props.disabled || props.loading);

function onClick(event: MouseEvent) {
  if (isDisabled.value) return;
  emit("click", event);
}
</script>

<template>
  <button
    class="pa-button"
    :class="[`is-${variant}`, `is-${size}`, { 'is-icon-only': iconOnly, 'is-loading': loading }]"
    :type="type"
    :disabled="isDisabled"
    :aria-busy="loading || undefined"
    @click="onClick"
  >
    <PaSpinner v-if="loading" :size="size === 'sm' ? 12 : 14" class="pa-button-spinner" />
    <slot v-else name="icon" />
    <span v-if="$slots.default" class="pa-button-label"><slot /></span>
  </button>
</template>

<style scoped>
.pa-button {
  display: inline-flex;
  height: var(--pa-btn-height);
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 0 var(--pa-btn-padding-x);
  border: 1px solid transparent;
  border-radius: var(--pa-btn-radius);
  background: var(--pa-btn-bg);
  color: var(--pa-btn-fg);
  font-size: var(--pa-text-body);
  font-weight: var(--font-medium);
  line-height: 1;
  white-space: nowrap;
  user-select: none;
  cursor: pointer;
  transition: background var(--pa-motion-fast) var(--ease),
    border-color var(--pa-motion-fast) var(--ease),
    color var(--pa-motion-fast) var(--ease),
    box-shadow var(--pa-motion-fast) var(--ease),
    transform var(--pa-motion-instant) var(--ease-out);
}
.pa-button:hover {
  background: var(--pa-btn-bg-hover);
  transform: translateY(-1px);
}
.pa-button:active {
  transform: translateY(0);
}
.pa-button:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.pa-button:disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
  opacity: 0.7;
  transform: none;
}
.pa-button:disabled:hover {
  background: var(--pa-btn-bg);
}

.is-primary {
  background: var(--pa-btn-primary-bg);
  border-color: var(--pa-btn-primary-bg);
  color: var(--pa-btn-primary-fg);
}
.is-primary:hover {
  background: var(--pa-btn-primary-bg-hover);
  border-color: var(--pa-btn-primary-bg-hover);
}
.is-primary:disabled,
.is-primary:disabled:hover {
  background: var(--pa-btn-primary-bg);
  border-color: var(--pa-btn-primary-bg);
}

.is-ghost {
  background: transparent;
  border-color: var(--color-border-strong);
}
.is-ghost:hover {
  background: var(--pa-btn-bg-hover);
}
.is-ghost:disabled:hover {
  background: transparent;
}

.is-subtle {
  background: transparent;
  color: var(--color-fg-muted);
}
.is-subtle:hover {
  background: var(--pa-btn-bg-hover);
  color: var(--color-fg);
}
.is-subtle:disabled:hover {
  background: transparent;
}

.is-danger {
  background: var(--pa-btn-danger-bg);
  border-color: var(--pa-btn-danger-bg);
  color: #fff;
}
.is-danger:hover {
  background: var(--pa-btn-danger-bg-hover);
  border-color: var(--pa-btn-danger-bg-hover);
}
.is-danger:disabled,
.is-danger:disabled:hover {
  background: var(--pa-btn-danger-bg);
  border-color: var(--pa-btn-danger-bg);
}

.is-sm {
  height: var(--pa-btn-height-sm);
  padding: 0 var(--space-2);
  font-size: var(--pa-text-meta);
}
.is-icon-only {
  width: 32px;
  padding: 0;
}
.is-icon-only.is-sm {
  width: var(--pa-btn-height-sm);
}
.is-loading {
  cursor: progress;
}
@media (prefers-reduced-motion: reduce) {
  .pa-button,
  .pa-button:hover {
    transform: none;
    transition: none;
  }
}
</style>
