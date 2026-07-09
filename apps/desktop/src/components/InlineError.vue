<script setup lang="ts">
/**
 * 行内错误展示（第七阶段 M4）。用于表单/操作区域的轻量错误反馈，
 * 替代 alert 的"弹一下就没了"的体验，错误可持续显示直至下次操作。
 */
import { PhWarningCircle } from "@phosphor-icons/vue";

withDefaults(defineProps<{ message?: string | null }>(), { message: null });
</script>

<template>
  <div v-if="message" class="inline-error" role="alert">
    <PhWarningCircle :size="14" weight="fill" />
    <span>{{ message }}</span>
  </div>
</template>

<style scoped>
.inline-error {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
  border-radius: var(--radius);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  word-break: break-word;
}
.inline-error :deep(svg) {
  flex-shrink: 0;
  margin-top: 2px;
}
</style>
