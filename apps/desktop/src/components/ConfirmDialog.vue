<script setup lang="ts">
/**
 * 统一对话框（第七阶段 M4）。同时承担：
 * - 确认对话框（confirm opts -> Promise<boolean>），替代 window.confirm。
 * - 输入对话框（prompt opts -> Promise<string|null>），替代 window.prompt。
 * danger 操作走红色确认按钮，并展示影响范围（impact）。
 * Esc 取消、Enter 确认。
 */
import { onMounted, onBeforeUnmount, watch, nextTick, ref, computed } from "vue";
import { PhWarning } from "@phosphor-icons/vue";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const confirmBtn = ref<HTMLButtonElement | null>(null);
const inputEl = ref<HTMLInputElement | null>(null);
const inputValue = ref("");

const isPrompt = computed(() => notify.promptState.value.open);
const isOpen = computed(
  () => notify.confirmState.value.open || notify.promptState.value.open
);
const opts = computed(() =>
  notify.promptState.value.open
    ? notify.promptState.value.opts
    : notify.confirmState.value.opts
);
const isDanger = computed(
  () => !notify.promptState.value.open && !!notify.confirmState.value.opts.danger
);

function submit(): void {
  if (notify.promptState.value.open) {
    notify.resolvePrompt(inputValue.value);
  } else {
    notify.resolveConfirm(true);
  }
}
function cancel(): void {
  if (notify.promptState.value.open) {
    notify.resolvePrompt(null);
  } else {
    notify.resolveConfirm(false);
  }
}

function onKey(e: KeyboardEvent): void {
  if (!isOpen.value) return;
  if (e.key === "Escape") {
    e.preventDefault();
    cancel();
  } else if (e.key === "Enter") {
    e.preventDefault();
    submit();
  }
}

watch(
  () => notify.promptState.value.open,
  async (open) => {
    if (open) {
      inputValue.value = notify.promptState.value.opts.defaultValue ?? "";
      await nextTick();
      inputEl.value?.focus();
    }
  }
);
watch(
  () => notify.confirmState.value.open,
  async (open) => {
    if (open) {
      await nextTick();
      confirmBtn.value?.focus();
    }
  }
);

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <Transition name="confirm">
      <div v-if="isOpen" class="confirm-scrim" @click.self="cancel">
        <div
          class="confirm-card"
          :class="{ danger: isDanger }"
          role="dialog"
          aria-modal="true"
          :aria-label="opts.title"
        >
          <div class="confirm-head">
            <PhWarning
              v-if="isDanger"
              class="confirm-danger-icon"
              :size="20"
              weight="fill"
            />
            <h3 class="confirm-title">{{ opts.title }}</h3>
          </div>
          <p v-if="opts.message" class="confirm-message">{{ opts.message }}</p>
          <input
            v-if="isPrompt"
            ref="inputEl"
            v-model="inputValue"
            class="confirm-input"
            :placeholder="notify.promptState.value.opts.placeholder"
          />
          <p v-if="!isPrompt && (opts as any).impact" class="confirm-impact">
            <span class="impact-label">影响范围：</span>
            {{ (opts as any).impact }}
          </p>
          <div class="confirm-actions">
            <button class="pa-btn pa-btn--ghost" @click="cancel">
              {{ opts.cancelLabel || "取消" }}
            </button>
            <button
              ref="confirmBtn"
              class="pa-btn"
              :class="isDanger ? 'pa-btn--danger' : 'pa-btn--primary'"
              @click="submit"
            >
              {{ opts.confirmLabel || (isPrompt ? "确定" : "确认") }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.confirm-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: var(--color-scrim);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
}
.confirm-card {
  width: 440px;
  max-width: 100%;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.confirm-card.danger {
  border-top: 3px solid var(--color-danger);
}
.confirm-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.confirm-danger-icon {
  color: var(--color-danger);
  flex-shrink: 0;
}
.confirm-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.confirm-message {
  margin: 0;
  font-size: var(--text-base);
  color: var(--color-fg-muted);
  line-height: var(--leading-normal);
  word-break: break-word;
}
.confirm-input {
  width: 100%;
  height: 36px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius);
  padding: 0 var(--space-3);
  font-size: var(--text-base);
  color: var(--color-fg);
  background: var(--color-surface-sunken);
}
.confirm-input:focus {
  outline: none;
  border-color: var(--color-accent);
}
.confirm-impact {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  background: var(--color-danger-soft);
  border-radius: var(--radius);
  font-size: var(--text-sm);
  color: var(--color-danger-fg);
  line-height: var(--leading-normal);
}
.impact-label {
  font-weight: var(--font-semibold);
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.confirm-enter-active,
.confirm-leave-active {
  transition: opacity var(--duration) var(--ease);
}
.confirm-enter-from,
.confirm-leave-to {
  opacity: 0;
}
.confirm-enter-active .confirm-card,
.confirm-leave-active .confirm-card {
  transition: transform var(--duration) var(--ease-out);
}
.confirm-enter-from .confirm-card,
.confirm-leave-to .confirm-card {
  transform: scale(0.96);
}
</style>
