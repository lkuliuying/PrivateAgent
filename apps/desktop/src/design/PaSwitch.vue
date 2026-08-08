<script setup lang="ts">
/**
 * PaSwitch · 开关（role=switch，aria-checked 完整）。
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
</script>

<template>
  <button
    type="button"
    class="pa-switch"
    :class="{ 'is-on': modelValue }"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="label || undefined"
    :disabled="disabled"
    @click="emit('update:modelValue', !modelValue)"
  >
    <span class="pa-switch-thumb" aria-hidden="true" />
    <span v-if="label" class="pa-switch-label">{{ label }}</span>
  </button>
</template>

<style scoped>
.pa-switch {
  display: inline-flex;
  position: relative;
  align-items: center;
  gap: var(--space-2);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  cursor: pointer;
}
.pa-switch::before {
  content: "";
  display: inline-block;
  width: 34px;
  height: 20px;
  border-radius: var(--radius-full);
  background: var(--color-border-strong);
  transition: background var(--pa-motion-fast) var(--ease);
}
.pa-switch.is-on::before {
  background: var(--color-accent);
}
.pa-switch-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 14px;
  height: 14px;
  border-radius: var(--radius-full);
  background: #fff;
  box-shadow: var(--shadow-sm);
  transition: transform var(--pa-motion-fast) var(--ease-out);
}
.pa-switch.is-on .pa-switch-thumb {
  transform: translateX(14px);
}
.pa-switch:focus-visible {
  outline: none;
}
.pa-switch:focus-visible::before {
  box-shadow: var(--focus-ring);
}
.pa-switch:disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
  opacity: 0.7;
}
@media (prefers-reduced-motion: reduce) {
  .pa-switch-thumb,
  .pa-switch::before {
    transition: none;
  }
}
</style>
