<script setup lang="ts">
/**
 * PaCheckbox · 复选框（标签可点击，focus-visible 环）。
 */
withDefaults(
  defineProps<{
    modelValue?: boolean;
    label?: string;
    disabled?: boolean;
  }>(),
  { modelValue: false, label: "", disabled: false }
);

const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();

function onChange(event: Event) {
  emit("update:modelValue", (event.target as HTMLInputElement).checked);
}
</script>

<template>
  <label class="pa-checkbox" :class="{ 'is-disabled': disabled }">
    <input
      type="checkbox"
      class="pa-checkbox-input"
      :checked="modelValue"
      :disabled="disabled"
      @change="onChange"
    />
    <span class="pa-checkbox-box" aria-hidden="true" />
    <span v-if="label || $slots.default" class="pa-checkbox-label">
      <slot>{{ label }}</slot>
    </span>
  </label>
</template>

<style scoped>
.pa-checkbox {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--pa-text-body);
  color: var(--color-fg);
  cursor: pointer;
  user-select: none;
}
.pa-checkbox.is-disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
.pa-checkbox-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}
.pa-checkbox-box {
  display: inline-grid;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  transition: background var(--pa-motion-fast) var(--ease),
    border-color var(--pa-motion-fast) var(--ease);
}
.pa-checkbox-box::after {
  content: "";
  width: 9px;
  height: 5px;
  border: 2px solid var(--color-accent-fg);
  border-top: none;
  border-right: none;
  opacity: 0;
  transform: rotate(-45deg) translateY(-1px);
}
.pa-checkbox-input:checked + .pa-checkbox-box {
  border-color: var(--color-accent);
  background: var(--color-accent);
}
.pa-checkbox-input:checked + .pa-checkbox-box::after {
  opacity: 1;
}
.pa-checkbox-input:focus-visible + .pa-checkbox-box {
  box-shadow: var(--focus-ring);
}
.pa-checkbox-input:disabled + .pa-checkbox-box {
  background: var(--color-surface-sunken);
  border-color: var(--color-border);
}
.pa-checkbox-label {
  min-width: 0;
}
</style>
