<script setup lang="ts">
/**
 * PaDropdownMenu · 下拉菜单（按钮触发，Esc/外点关闭，方向键遍历）。
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { PhCaretDown } from "@phosphor-icons/vue";

export interface PaMenuItem {
  key: string;
  label: string;
  danger?: boolean;
  disabled?: boolean;
}

withDefaults(
  defineProps<{
    items: PaMenuItem[];
    label?: string;
    align?: "left" | "right";
  }>(),
  { label: "", align: "left" }
);

const emit = defineEmits<{ select: [key: string] }>();

const open = ref(false);
const rootRef = ref<HTMLElement | null>(null);
const itemRefs = ref<HTMLButtonElement[]>([]);

function toggle() {
  open.value = !open.value;
}

function close() {
  open.value = false;
}

function onSelect(item: PaMenuItem) {
  if (item.disabled) return;
  emit("select", item.key);
  close();
}

function onDocClick(event: MouseEvent) {
  if (!rootRef.value?.contains(event.target as Node)) close();
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    close();
    return;
  }
  if (!open.value) return;
  const items = itemRefs.value.filter((el) => !el.disabled);
  if (!items.length) return;
  const current = items.indexOf(document.activeElement as HTMLButtonElement);
  if (event.key === "ArrowDown") {
    event.preventDefault();
    items[(current + 1) % items.length]?.focus();
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    items[(current - 1 + items.length) % items.length]?.focus();
  }
}

onMounted(() => {
  document.addEventListener("mousedown", onDocClick);
  document.addEventListener("keydown", onKeydown);
});
onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onDocClick);
  document.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <div ref="rootRef" class="pa-menu">
    <button
      type="button"
      class="pa-menu-trigger"
      :aria-expanded="open"
      aria-haspopup="menu"
      @click="toggle"
    >
      <slot name="trigger">{{ label }}</slot>
      <PhCaretDown :size="12" weight="bold" aria-hidden="true" />
    </button>
    <Transition name="pa-menu-pop">
      <div
        v-if="open"
        class="pa-menu-list"
        :class="`align-${align}`"
        role="menu"
      >
        <button
          v-for="(item, index) in items"
          :key="item.key"
          :ref="(el) => { if (el) itemRefs[index] = el as HTMLButtonElement; }"
          type="button"
          class="pa-menu-item"
          :class="{ 'is-danger': item.danger }"
          role="menuitem"
          :disabled="item.disabled"
          @click="onSelect(item)"
        >
          {{ item.label }}
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.pa-menu {
  position: relative;
  display: inline-flex;
}
.pa-menu-trigger {
  display: inline-flex;
  height: 32px;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
  cursor: pointer;
}
.pa-menu-trigger:hover {
  background: var(--color-surface-sunken);
}
.pa-menu-trigger:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.pa-menu-list {
  position: absolute;
  top: calc(100% + 4px);
  z-index: var(--z-overlay);
  min-width: 160px;
  padding: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow);
}
.align-left { left: 0; }
.align-right { right: 0; }
.pa-menu-item {
  display: flex;
  width: 100%;
  align-items: center;
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
  text-align: left;
  cursor: pointer;
}
.pa-menu-item:hover {
  background: var(--color-surface-sunken);
}
.pa-menu-item:focus-visible {
  outline: none;
  box-shadow: inset var(--focus-ring);
}
.pa-menu-item.is-danger {
  color: var(--color-danger-fg);
}
.pa-menu-item:disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
.pa-menu-pop-enter-active,
.pa-menu-pop-leave-active {
  transition: opacity var(--pa-motion-fast) var(--ease),
    transform var(--pa-motion-fast) var(--ease);
}
.pa-menu-pop-enter-from,
.pa-menu-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@media (prefers-reduced-motion: reduce) {
  .pa-menu-pop-enter-active,
  .pa-menu-pop-leave-active {
    transition: none;
  }
}
</style>
