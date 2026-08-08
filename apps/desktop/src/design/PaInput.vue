<script setup lang="ts">
/**
 * PaInput · 单行输入框。error 时展示危险边框，配合 PaField 展示校验文案。
 */
withDefaults(
  defineProps<{
    modelValue?: string;
    type?: string;
    placeholder?: string;
    disabled?: boolean;
    readonly?: boolean;
    error?: boolean;
    /** 紧凑尺寸（高密度工具栏） */
    size?: "sm" | "md";
    id?: string;
    name?: string;
    autocomplete?: string;
  }>(),
  {
    modelValue: "",
    type: "text",
    placeholder: "",
    disabled: false,
    readonly: false,
    error: false,
    size: "md",
    id: undefined,
    name: undefined,
    autocomplete: undefined,
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  keydown: [event: KeyboardEvent];
  focus: [event: FocusEvent];
  blur: [event: FocusEvent];
}>();

function onInput(event: Event) {
  emit("update:modelValue", (event.target as HTMLInputElement).value);
}
</script>

<template>
  <input
    class="pa-input-field"
    :class="[`is-${size}`, { 'has-error': error }]"
    :value="modelValue"
    :type="type"
    :placeholder="placeholder"
    :disabled="disabled"
    :readonly="readonly"
    :id="id"
    :name="name"
    :autocomplete="autocomplete"
    :aria-invalid="error || undefined"
    @input="onInput"
    @keydown="emit('keydown', $event)"
    @focus="emit('focus', $event)"
    @blur="emit('blur', $event)"
  />
</template>

<style scoped>
.pa-input-field {
  width: 100%;
  height: var(--pa-input-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--pa-input-border);
  border-radius: var(--pa-input-radius);
  background: var(--pa-input-bg);
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  transition: border-color var(--pa-motion-fast) var(--ease),
    box-shadow var(--pa-motion-fast) var(--ease);
}
.pa-input-field.is-sm {
  height: 28px;
  font-size: var(--pa-text-compact);
}
.pa-input-field::placeholder {
  color: var(--color-fg-faint);
}
.pa-input-field:focus {
  outline: none;
  border-color: var(--pa-input-border-focus);
  box-shadow: var(--pa-input-ring);
}
.pa-input-field:disabled {
  background: var(--color-surface-sunken);
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
.pa-input-field.has-error {
  border-color: var(--color-danger);
}
.pa-input-field.has-error:focus {
  box-shadow: 0 0 0 3px var(--color-danger-soft);
}
</style>
