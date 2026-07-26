<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useModalFocus } from "../composables/useModalFocus";

const props = defineProps<{ error?: Error }>();
const emit = defineEmits<{ close: [] }>();

const dialogEl = ref<HTMLElement | null>(null);
const reloadButton = ref<HTMLButtonElement | null>(null);
const preferredFocus = computed(() =>
  props.error ? reloadButton.value : dialogEl.value
);

function close(): void {
  emit("close");
}

function reload(): void {
  window.location.reload();
}

useModalFocus({
  container: dialogEl,
  initialFocus: preferredFocus,
  onEscape: close,
});

watch(
  () => props.error,
  async (error) => {
    if (!error) return;
    await nextTick();
    reloadButton.value?.focus();
  }
);
</script>

<template>
  <Teleport to="body">
    <div class="async-overlay" @click.self="close">
      <div
        ref="dialogEl"
        class="async-overlay-card"
        :role="props.error ? 'alertdialog' : 'dialog'"
        aria-modal="true"
        aria-labelledby="async-overlay-title"
        aria-describedby="async-overlay-description"
        :aria-busy="props.error ? undefined : 'true'"
        tabindex="-1"
      >
        <span v-if="!props.error" class="async-overlay-signal" aria-hidden="true" />
        <span v-else class="async-overlay-error-signal" aria-hidden="true">!</span>
        <strong id="async-overlay-title">
          {{ props.error ? "面板加载失败" : "正在打开面板…" }}
        </strong>
        <p id="async-overlay-description">
          {{
            props.error
              ? "本地界面资源未能载入，请重新加载应用后重试。"
              : "正在装配本地界面，按 Esc 可返回当前工作区。"
          }}
        </p>
        <button
          v-if="props.error"
          ref="reloadButton"
          class="pa-btn pa-btn--primary"
          type="button"
          @click="reload"
        >
          重新加载
        </button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.async-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  display: grid;
  place-items: center;
  padding: var(--space-6);
  background: color-mix(in srgb, var(--color-bg) 74%, transparent);
  backdrop-filter: blur(12px);
  animation: async-overlay-in var(--duration) var(--ease-out) both;
}
.async-overlay-card {
  width: min(420px, 100%);
  min-height: 164px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: var(--space-3);
  padding: var(--space-6);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  outline: none;
  background: var(--color-surface);
  color: var(--color-fg-subtle);
  text-align: center;
  box-shadow: var(--shadow-lg);
  animation: async-overlay-card-in var(--duration-slow) var(--ease-spring) both;
}
.async-overlay-card:focus-visible {
  box-shadow: var(--shadow-lg), var(--focus-ring);
}
.async-overlay-card strong { color: var(--color-fg); }
.async-overlay-card p { margin: 0; font-size: var(--text-sm); line-height: 1.6; }
.async-overlay-signal {
  width: 24px;
  height: 24px;
  border: 2px solid var(--color-border-strong);
  border-top-color: var(--color-accent);
  border-radius: 50%;
  animation: async-overlay-spin 720ms linear infinite;
}
.async-overlay-error-signal {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--color-danger-soft);
  color: var(--color-danger);
  font-weight: var(--font-semibold);
}
@keyframes async-overlay-in {
  from { opacity: 0; }
}
@keyframes async-overlay-card-in {
  from { transform: translateY(var(--motion-distance-sm)) scale(0.98); opacity: 0; }
}
@keyframes async-overlay-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .async-overlay,
  .async-overlay-card,
  .async-overlay-signal { animation: none; }
}
</style>
