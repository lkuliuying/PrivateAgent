<script setup lang="ts">
/**
 * PaSelect · 下拉选择（原生 select 样式化，保证键盘与辅助技术行为完整）。
 */
withDefaults(
  defineProps<{
    modelValue?: string | number;
    options: { value: string | number; label: string; disabled?: boolean }[];
    disabled?: boolean;
    size?: "sm" | "md";
    id?: string;
  }>(),
  { modelValue: "", disabled: false, size: "md", id: undefined }
);

const emit = defineEmits<{ "update:modelValue": [value: string] }>();

function onChange(event: Event) {
  emit("update:modelValue", (event.target as HTMLSelectElement).value);
}
</script>

<template>
  <select
    class="pa-select"
    :class="`is-${size}`"
    :value="modelValue"
    :disabled="disabled"
    :id="id"
    @change="onChange"
  >
    <option
      v-for="option in options"
      :key="option.value"
      :value="option.value"
      :disabled="option.disabled"
    >
      {{ option.label }}
    </option>
  </select>
</template>

<style scoped>
.pa-select {
  width: 100%;
  height: var(--pa-input-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--pa-input-border);
  border-radius: var(--pa-input-radius);
  background: var(--pa-input-bg);
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  cursor: pointer;
  transition: border-color var(--pa-motion-fast) var(--ease),
    box-shadow var(--pa-motion-fast) var(--ease);
}
.pa-select.is-sm {
  height: 28px;
  font-size: var(--pa-text-compact);
}
.pa-select:focus {
  outline: none;
  border-color: var(--pa-input-border-focus);
  box-shadow: var(--pa-input-ring);
}
.pa-select:disabled {
  background: var(--color-surface-sunken);
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
</style>
