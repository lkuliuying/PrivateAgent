<script setup lang="ts">
/**
 * PaTextarea · 多行输入。rows 控制最小高度，autoGrow 时随内容增高至 maxRows。
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    placeholder?: string;
    disabled?: boolean;
    readonly?: boolean;
    error?: boolean;
    rows?: number;
    id?: string;
  }>(),
  {
    modelValue: "",
    placeholder: "",
    disabled: false,
    readonly: false,
    error: false,
    rows: 3,
    id: undefined,
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  keydown: [event: KeyboardEvent];
}>();

const minHeight = computed(() => `${props.rows * 22 + 16}px`);

function onInput(event: Event) {
  emit("update:modelValue", (event.target as HTMLTextAreaElement).value);
}
</script>

<template>
  <textarea
    class="pa-textarea"
    :class="{ 'has-error': error }"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :readonly="readonly"
    :id="id"
    :rows="rows"
    :aria-invalid="error || undefined"
    :style="{ minHeight }"
    @input="onInput"
    @keydown="emit('keydown', $event)"
  />
</template>

<style scoped>
.pa-textarea {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--pa-input-border);
  border-radius: var(--pa-input-radius);
  background: var(--pa-input-bg);
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  line-height: var(--leading-normal);
  resize: vertical;
  transition: border-color var(--pa-motion-fast) var(--ease),
    box-shadow var(--pa-motion-fast) var(--ease);
}
.pa-textarea::placeholder {
  color: var(--color-fg-faint);
}
.pa-textarea:focus {
  outline: none;
  border-color: var(--pa-input-border-focus);
  box-shadow: var(--pa-input-ring);
}
.pa-textarea:disabled {
  background: var(--color-surface-sunken);
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
.pa-textarea.has-error {
  border-color: var(--color-danger);
}
</style>
