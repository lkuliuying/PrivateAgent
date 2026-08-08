<script setup lang="ts">
/**
 * PaIconButton · 仅图标的方形按钮，必须提供 aria-label。
 */
import PaButton from "./PaButton.vue";

withDefaults(
  defineProps<{
    label: string;
    variant?: "default" | "primary" | "ghost" | "subtle" | "danger";
    size?: "sm" | "md";
    disabled?: boolean;
    active?: boolean;
  }>(),
  { variant: "ghost", size: "md", disabled: false, active: false }
);

const emit = defineEmits<{ click: [event: MouseEvent] }>();
</script>

<template>
  <PaButton
    :variant="variant"
    :size="size"
    :disabled="disabled"
    icon-only
    class="pa-icon-button"
    :class="{ 'is-active': active }"
    :aria-label="label"
    :aria-pressed="active || undefined"
    :title="label"
    @click="emit('click', $event)"
  >
    <template #icon><slot /></template>
  </PaButton>
</template>

<style scoped>
.pa-icon-button.is-active {
  border-color: color-mix(in srgb, var(--color-accent) 42%, var(--color-border));
  background: var(--color-accent-soft);
  color: var(--color-accent);
}
</style>
