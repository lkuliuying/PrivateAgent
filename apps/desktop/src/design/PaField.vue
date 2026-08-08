<script setup lang="ts">
/**
 * PaField · 表单字段包装：label + 控件 + 帮助/校验文案。
 * error 文案带 role=alert，供校验失败即时播报。
 */
import { useId } from "vue";

withDefaults(
  defineProps<{
    label?: string;
    hint?: string;
    error?: string;
    required?: boolean;
  }>(),
  { label: "", hint: "", error: "", required: false }
);

const fieldId = useId();
</script>

<template>
  <div class="pa-field" :class="{ 'has-error': Boolean(error) }">
    <label v-if="label" class="pa-field-label" :for="fieldId">
      {{ label }}
      <span v-if="required" class="pa-field-required" aria-hidden="true">*</span>
    </label>
    <div class="pa-field-control">
      <slot :id="fieldId" :error="Boolean(error)" />
    </div>
    <p v-if="error" class="pa-field-message is-error" role="alert">{{ error }}</p>
    <p v-else-if="hint" class="pa-field-message">{{ hint }}</p>
  </div>
</template>

<style scoped>
.pa-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.pa-field-label {
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
}
.pa-field-required {
  color: var(--color-danger);
}
.pa-field-message {
  margin: 0;
  font-size: var(--pa-text-meta);
  color: var(--color-fg-faint);
  line-height: var(--leading-normal);
}
.pa-field-message.is-error {
  color: var(--color-danger-fg);
}
</style>
