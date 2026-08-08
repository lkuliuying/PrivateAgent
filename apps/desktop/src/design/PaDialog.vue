<script setup lang="ts">
/**
 * PaDialog · 模态对话框基座（Teleport + 焦点圈禁 + Esc 关闭 + 初始焦点）。
 * 打开时焦点移入面板，关闭时归还触发者；Tab/Shift+Tab 在面板内循环。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    width?: number;
    /** 点击遮罩是否关闭（破坏性确认对话框应关闭此选项） */
    dismissible?: boolean;
  }>(),
  { width: 480, dismissible: true }
);

const emit = defineEmits<{ close: [] }>();

const panelRef = ref<HTMLElement | null>(null);
let previousFocus: HTMLElement | null = null;

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && props.dismissible) {
    event.stopPropagation();
    emit("close");
    return;
  }
  if (event.key !== "Tab" || !panelRef.value) return;
  const focusable = Array.from(
    panelRef.value.querySelectorAll<HTMLElement>(FOCUSABLE)
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement as HTMLElement | null;
  if (event.shiftKey && (active === first || !panelRef.value.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

function onScrimClick() {
  if (props.dismissible) emit("close");
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    previousFocus = document.activeElement as HTMLElement | null;
    await nextTick();
    const target =
      panelRef.value?.querySelector<HTMLElement>("[data-autofocus]") ??
      panelRef.value?.querySelector<HTMLElement>(FOCUSABLE);
    target?.focus();
  }
);

onMounted(() => document.addEventListener("keydown", onKeydown, true));
onBeforeUnmount(() => {
  document.removeEventListener("keydown", onKeydown, true);
  previousFocus?.focus?.();
});
</script>

<template>
  <Teleport to="body">
    <Transition name="pa-dialog">
      <div
        v-if="open"
        class="pa-dialog-scrim"
        @mousedown.self="onScrimClick"
      >
        <div
          ref="panelRef"
          class="pa-dialog-panel"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          :style="{ maxWidth: `${width}px` }"
        >
          <header class="pa-dialog-header">
            <h2 class="pa-dialog-title">{{ title }}</h2>
            <slot name="header-actions" />
          </header>
          <div class="pa-dialog-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="pa-dialog-footer">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.pa-dialog-scrim {
  display: flex;
  position: fixed;
  z-index: var(--z-overlay);
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background: var(--color-scrim);
  inset: 0;
}
.pa-dialog-panel {
  width: 100%;
  max-height: 85vh;
  overflow: auto;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
}
.pa-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5) var(--space-3);
  border-bottom: 1px solid var(--color-border);
}
.pa-dialog-title {
  margin: 0;
  font-size: var(--pa-text-section);
  font-weight: var(--font-semibold);
}
.pa-dialog-body {
  padding: var(--space-4) var(--space-5);
  font-size: var(--pa-text-body);
  line-height: var(--leading-normal);
}
.pa-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5) var(--space-4);
  border-top: 1px solid var(--color-border);
}
.pa-dialog-enter-active,
.pa-dialog-leave-active {
  transition: opacity var(--pa-motion-standard) var(--ease);
}
.pa-dialog-enter-active .pa-dialog-panel,
.pa-dialog-leave-active .pa-dialog-panel {
  transition: transform var(--pa-motion-standard) var(--ease-out);
}
.pa-dialog-enter-from,
.pa-dialog-leave-to {
  opacity: 0;
}
.pa-dialog-enter-from .pa-dialog-panel,
.pa-dialog-leave-to .pa-dialog-panel {
  transform: translateY(8px);
}
@media (prefers-reduced-motion: reduce) {
  .pa-dialog-enter-active,
  .pa-dialog-leave-active,
  .pa-dialog-enter-active .pa-dialog-panel,
  .pa-dialog-leave-active .pa-dialog-panel {
    transition: none;
  }
}
</style>
