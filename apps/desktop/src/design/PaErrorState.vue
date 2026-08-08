<script setup lang="ts">
/**
 * PaErrorState · 页面/区块级错误（原因 + 恢复动作槽）。
 */
import { PhWarningCircle } from "@phosphor-icons/vue";
import PaButton from "./PaButton.vue";

withDefaults(
  defineProps<{
    title?: string;
    message?: string;
    retryLabel?: string;
  }>(),
  { title: "加载失败", message: "", retryLabel: "重试" }
);

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <div class="pa-error" role="alert">
    <PhWarningCircle :size="28" weight="duotone" class="pa-error-icon" />
    <p class="pa-error-title">{{ title }}</p>
    <p v-if="message" class="pa-error-message">{{ message }}</p>
    <div class="pa-error-actions">
      <PaButton variant="ghost" size="sm" @click="emit('retry')">{{ retryLabel }}</PaButton>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.pa-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-6);
  text-align: center;
}
.pa-error-icon {
  color: var(--color-danger);
  margin-bottom: var(--space-2);
}
.pa-error-title {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--pa-text-section);
  font-weight: var(--font-semibold);
}
.pa-error-message {
  max-width: 520px;
  margin: var(--space-2) 0 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-body);
  line-height: var(--leading-normal);
  word-break: break-word;
}
.pa-error-actions {
  display: flex;
  margin-top: var(--space-4);
  gap: var(--space-2);
}
</style>
