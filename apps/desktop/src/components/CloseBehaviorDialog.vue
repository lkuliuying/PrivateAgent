<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { PhX } from "@phosphor-icons/vue";

import type { WindowCloseBehavior } from "../services/windowClose";

const props = defineProps<{
  open: boolean;
  selected: WindowCloseBehavior;
  dontAskAgain: boolean;
  busy?: boolean;
  error?: string;
}>();

const emit = defineEmits<{
  (event: "update:selected", value: WindowCloseBehavior): void;
  (event: "update:dontAskAgain", value: boolean): void;
  (event: "cancel"): void;
  (event: "confirm"): void;
}>();

const confirmButton = ref<HTMLButtonElement | null>(null);

function cancel(): void {
  if (!props.busy) emit("cancel");
}

function confirm(): void {
  if (!props.busy) emit("confirm");
}

function handleKeydown(event: KeyboardEvent): void {
  if (!props.open || props.busy) return;
  if (event.key === "Escape") {
    event.preventDefault();
    cancel();
  } else if (event.key === "Enter") {
    event.preventDefault();
    confirm();
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    await nextTick();
    confirmButton.value?.focus();
  }
);

onMounted(() => window.addEventListener("keydown", handleKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", handleKeydown));
</script>

<template>
  <Teleport to="body">
    <Transition name="close-choice">
      <div v-if="open" class="close-choice-scrim" @click.self="cancel">
        <section
          class="close-choice-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="close-choice-title"
        >
          <header class="close-choice-header">
            <h2 id="close-choice-title">点击关闭按钮以后：</h2>
            <button
              type="button"
              class="close-choice-x"
              aria-label="取消关闭"
              title="取消"
              :disabled="busy"
              @click="cancel"
            >
              <PhX :size="22" />
            </button>
          </header>

          <div class="close-choice-options">
            <label class="close-choice-option">
              <input
                type="radio"
                name="window-close-behavior"
                value="background"
                :checked="selected === 'background'"
                :disabled="busy"
                @change="emit('update:selected', 'background')"
              />
              <span>
                <strong>保留后台运行</strong>
                <small>隐藏到系统托盘，可随时重新打开</small>
              </span>
            </label>
            <label class="close-choice-option">
              <input
                type="radio"
                name="window-close-behavior"
                value="exit"
                :checked="selected === 'exit'"
                :disabled="busy"
                @change="emit('update:selected', 'exit')"
              />
              <span>
                <strong>退出应用</strong>
                <small>停止本地服务并完全退出</small>
              </span>
            </label>
          </div>

          <label class="close-choice-remember">
            <input
              type="checkbox"
              :checked="dontAskAgain"
              :disabled="busy"
              @change="
                emit(
                  'update:dontAskAgain',
                  ($event.target as HTMLInputElement).checked
                )
              "
            />
            <span>不再提示</span>
          </label>

          <p v-if="error" class="close-choice-error" role="alert">{{ error }}</p>

          <footer class="close-choice-actions">
            <button
              type="button"
              class="pa-btn pa-btn--ghost"
              :disabled="busy"
              @click="cancel"
            >
              取消
            </button>
            <button
              ref="confirmButton"
              type="button"
              class="pa-btn pa-btn--primary"
              :disabled="busy"
              @click="confirm"
            >
              {{ busy ? "处理中…" : "确定" }}
            </button>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.close-choice-scrim {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-overlay) + 10);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  background: var(--color-scrim);
}

.close-choice-card {
  width: 420px;
  max-width: 100%;
  padding: var(--space-6);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.close-choice-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.close-choice-header h2 {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
}

.close-choice-x {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: var(--radius);
  color: var(--color-fg-muted);
  background: transparent;
  cursor: pointer;
}

.close-choice-x:hover:not(:disabled) {
  color: var(--color-fg);
  background: var(--color-surface-sunken);
}

.close-choice-options {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-5);
}

.close-choice-option {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius);
  cursor: pointer;
}

.close-choice-option:hover {
  border-color: var(--color-border);
  background: var(--color-surface-sunken);
}

.close-choice-option input,
.close-choice-remember input {
  margin-top: 3px;
  accent-color: var(--color-accent);
}

.close-choice-option span {
  display: grid;
  gap: 2px;
}

.close-choice-option strong {
  color: var(--color-fg);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
}

.close-choice-option small {
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
}

.close-choice-remember {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin: var(--space-4) 0 0 var(--space-3);
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  cursor: pointer;
}

.close-choice-error {
  margin: var(--space-3) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
  font-size: var(--text-sm);
}

.close-choice-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  margin-top: var(--space-6);
}

.close-choice-actions .pa-btn {
  justify-content: center;
}

.close-choice-enter-active,
.close-choice-leave-active {
  transition: opacity var(--duration) var(--ease);
}

.close-choice-enter-from,
.close-choice-leave-to {
  opacity: 0;
}

.close-choice-enter-active .close-choice-card,
.close-choice-leave-active .close-choice-card {
  transition: transform var(--duration) var(--ease-out);
}

.close-choice-enter-from .close-choice-card,
.close-choice-leave-to .close-choice-card {
  transform: translateY(8px) scale(0.98);
}
</style>
