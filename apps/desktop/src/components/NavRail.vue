<script setup lang="ts">
import { nextTick, ref } from "vue";
import {
  PhChatsCircle,
  PhSun,
  PhBooks,
  PhFolderSimple,
  PhGraduationCap,
  PhListChecks,
  PhBrain,
  PhGearSix,
  PhActivity,
  PhPuzzlePiece,
  PhPlugs,
  PhDatabase,
  PhCommand,
  PhDotsThree,
} from "@phosphor-icons/vue";
import AppearanceControl from "./AppearanceControl.vue";
import type { View } from "../types";

defineProps<{ active: View }>();
const emit = defineEmits<{
  navigate: [view: View];
  "open-command": [];
}>();
const advancedOpen = ref(false);
const advancedToggle = ref<HTMLButtonElement | null>(null);

const primaryItems: { key: View; label: string; icon: typeof PhChatsCircle }[] = [
  { key: "today", label: "今日", icon: PhSun },
  { key: "chat", label: "对话", icon: PhChatsCircle },
  { key: "kb", label: "知识库", icon: PhBooks },
];

const workItems: { key: View; label: string; icon: typeof PhChatsCircle }[] = [
  { key: "tasks", label: "任务", icon: PhListChecks },
  { key: "projects", label: "项目", icon: PhFolderSimple },
  { key: "learning", label: "学习", icon: PhGraduationCap },
  { key: "memory", label: "记忆", icon: PhBrain },
];

const advancedItems: { key: View; label: string; icon: typeof PhChatsCircle }[] = [
  { key: "diagnostics", label: "诊断", icon: PhActivity },
  { key: "extensions", label: "扩展", icon: PhPuzzlePiece },
  { key: "integrations", label: "集成", icon: PhPlugs },
  { key: "backup", label: "备份", icon: PhDatabase },
];

async function closeAdvanced(event?: KeyboardEvent): Promise<void> {
  if (!advancedOpen.value) return;
  event?.preventDefault();
  advancedOpen.value = false;
  await nextTick();
  advancedToggle.value?.focus();
}

function navigateAdvanced(view: View): void {
  advancedOpen.value = false;
  emit("navigate", view);
}
</script>

<template>
  <nav class="navrail" aria-label="主导航">
    <div class="navrail-brand" title="私人助手" data-motion-logo>
      <div class="brand-mark">P</div>
      <div class="brand-copy">
        <strong>PrivateAgent</strong>
        <span>本地优先</span>
      </div>
    </div>

    <ul class="navrail-items" aria-label="主要功能">
      <li v-for="item in primaryItems" :key="item.key">
        <button
          class="nav-item"
          :class="{ active: active === item.key }"
          :aria-current="active === item.key ? 'page' : undefined"
          :aria-label="item.label"
          :title="item.label"
          @click="emit('navigate', item.key)"
        >
          <component :is="item.icon" class="nav-icon" :size="20" weight="regular" />
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </li>
    </ul>

    <ul class="navrail-items navrail-group" aria-label="工作区">
      <li v-for="item in workItems" :key="item.key">
        <button
          class="nav-item"
          :class="{ active: active === item.key }"
          :aria-current="active === item.key ? 'page' : undefined"
          :aria-label="item.label"
          :title="item.label"
          @click="emit('navigate', item.key)"
        >
          <component :is="item.icon" class="nav-icon" :size="20" weight="regular" />
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </li>
    </ul>

    <div class="navrail-utilities" @keydown.esc.stop="closeAdvanced">
      <button
        ref="advancedToggle"
        class="nav-item utility-toggle"
        :class="{ active: advancedOpen || advancedItems.some((item) => item.key === active) }"
        :aria-expanded="advancedOpen"
        aria-controls="navrail-advanced-items"
        aria-label="更多工具"
        title="更多工具"
        @click="advancedOpen = !advancedOpen"
      >
        <PhDotsThree class="nav-icon" :size="20" weight="bold" />
        <span class="nav-label">更多</span>
      </button>

      <Transition name="nav-more">
        <ul
          v-if="advancedOpen"
          id="navrail-advanced-items"
          class="navrail-items advanced-items"
          aria-label="更多工具"
        >
          <li v-for="item in advancedItems" :key="item.key">
            <button
              class="nav-item nav-item--compact"
              :class="{ active: active === item.key }"
              :aria-current="active === item.key ? 'page' : undefined"
              :aria-label="item.label"
              :title="item.label"
              @click="navigateAdvanced(item.key)"
            >
              <component :is="item.icon" class="nav-icon" :size="18" weight="regular" />
              <span class="nav-label">{{ item.label }}</span>
            </button>
          </li>
        </ul>
      </Transition>

      <AppearanceControl />

      <button
        class="nav-item"
        :class="{ active: active === 'settings' }"
        :aria-current="active === 'settings' ? 'page' : undefined"
        aria-label="设置"
        title="设置"
        @click="emit('navigate', 'settings')"
      >
        <PhGearSix class="nav-icon" :size="20" weight="regular" />
        <span class="nav-label">设置</span>
      </button>
    </div>

    <div class="navrail-status">
      <span class="status-dot" aria-hidden="true" />
      <div>
        <strong>本地运行中</strong>
        <span>本机模型 · 本机向量库</span>
      </div>
    </div>

    <button
      class="command-shortcut"
      aria-label="打开快捷命令"
      title="打开快捷命令"
      @click="emit('open-command')"
    >
      <PhCommand :size="15" />
      <span>快捷命令</span>
      <kbd>Ctrl K</kbd>
    </button>
  </nav>
</template>

<style scoped>
.navrail {
  position: relative;
  isolation: isolate;
  overflow-x: hidden;
  overflow-y: auto;
  width: 100%;
  height: 100%;
  background:
    radial-gradient(circle at 20% 0%, var(--color-rail-glow), transparent 32%),
    linear-gradient(180deg, var(--color-rail-gradient-top), var(--color-rail-bg));
  border-right: 1px solid var(--color-rail-border);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  color: var(--color-rail-fg);
  padding: 24px 16px 18px;
  gap: 18px;
  box-shadow: inset -1px 0 var(--color-rail-highlight);
}
.navrail::after {
  content: "";
  position: absolute;
  z-index: -1;
  inset: 0;
  opacity: 0.28;
  pointer-events: none;
  background-image: linear-gradient(
    115deg,
    transparent 0 42%,
    var(--color-rail-sheen) 50%,
    transparent 58% 100%
  );
  background-size: 230% 100%;
  animation: rail-sheen 14s ease-in-out infinite;
}
@keyframes rail-sheen {
  0%,
  68% {
    background-position: 120% 0;
  }
  100% {
    background-position: -80% 0;
  }
}

/* 品牌 */
.navrail-brand {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-2);
  flex-shrink: 0;
}
.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  background:
    linear-gradient(145deg, var(--color-rail-brand-highlight), transparent 48%),
    var(--color-accent);
  color: var(--color-accent-fg);
  font-weight: 800;
  font-family: var(--font-display);
  font-size: 21px;
  flex-shrink: 0;
  box-shadow: var(--shadow-rail-mark);
  transition: transform var(--duration-gentle) var(--ease-spring),
    box-shadow var(--duration-gentle) var(--ease-out);
}
.navrail-brand:hover .brand-mark {
  transform: rotate(-4deg) scale(1.055);
  box-shadow: var(--shadow-rail-mark-hover);
}
.brand-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.brand-copy strong {
  font-size: var(--text-lg);
  color: var(--color-rail-fg-strong);
  line-height: 1.2;
}
.brand-copy span {
  font-size: var(--text-xs);
  color: var(--color-rail-fg-muted);
}
/* 导航项 */
.navrail-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.navrail-group {
  border-top: 1px solid var(--color-rail-border);
  padding-top: 14px;
}
.nav-item {
  position: relative;
  width: 100%;
  height: 44px;
  border: none;
  background: transparent;
  color: var(--color-rail-fg-muted);
  cursor: pointer;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-3);
  border-radius: 10px;
  padding: 0 var(--space-3);
  transition: background var(--duration-fast) var(--ease),
    color var(--duration-fast) var(--ease),
    transform var(--duration) var(--ease-out);
}
.nav-item:hover {
  background: var(--color-rail-surface);
  color: var(--color-rail-fg-strong);
  transform: translateX(var(--motion-distance-xs));
}
.nav-item:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--color-rail-accent);
}
.nav-item.active {
  color: var(--color-rail-fg-strong);
  background: var(--color-rail-active);
  box-shadow: var(--shadow-rail-active);
}
/* 激活指示条 */
.nav-item.active::before {
  content: "";
  position: absolute;
  left: -16px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 22px;
  border-radius: 0 var(--radius-full) var(--radius-full) 0;
  background: var(--color-rail-accent);
}
.nav-icon {
  flex-shrink: 0;
  transition: transform var(--duration-gentle) var(--ease-spring),
    color var(--duration-fast) var(--ease);
}
.nav-item:hover .nav-icon,
.nav-item.active .nav-icon {
  transform: scale(1.09) rotate(-2deg);
}
.nav-label {
  font-size: var(--text-base);
  line-height: 1;
  letter-spacing: 0;
}
.navrail-utilities {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  border-top: 1px solid var(--color-rail-border);
  padding-top: 14px;
}
.advanced-items {
  padding-left: 10px;
}
.nav-item--compact {
  height: 36px;
}
.utility-toggle.active:not(:hover) {
  background: transparent;
}
.navrail-status {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--color-rail-border);
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  color: var(--color-rail-fg-muted);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--color-status-online);
  box-shadow: 0 0 0 4px var(--color-status-online-soft);
  margin-top: 5px;
  flex-shrink: 0;
  animation: rail-status-pulse 2.4s var(--ease-out) infinite;
}
@keyframes rail-status-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 3px var(--color-status-online-soft);
  }
  50% {
    box-shadow: 0 0 0 7px transparent;
  }
}
.navrail-status strong,
.navrail-status span {
  display: block;
}
.navrail-status strong {
  font-size: var(--text-sm);
  color: var(--color-rail-fg-strong);
  font-weight: var(--font-medium);
}
.navrail-status span {
  margin-top: 2px;
  font-size: var(--text-xs);
  line-height: 1.45;
}
.command-shortcut {
  width: 100%;
  min-height: 40px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid var(--color-rail-border);
  border-radius: 10px;
  background: var(--color-rail-command-bg);
  color: var(--color-rail-fg-muted);
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease);
}
.command-shortcut:hover,
.command-shortcut:focus-visible {
  color: var(--color-rail-fg-strong);
  background: var(--color-rail-surface);
  border-color: var(--color-rail-focus-border);
  outline: none;
}
.command-shortcut span {
  font-size: var(--text-sm);
}
.command-shortcut kbd {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-rail-fg-muted);
  border: 1px solid var(--color-rail-border);
  border-radius: 5px;
  padding: 2px 5px;
}
.nav-more-enter-active,
.nav-more-leave-active {
  transition: opacity var(--duration-fast) var(--ease),
    transform var(--duration-fast) var(--ease-out);
}
.nav-more-enter-from,
.nav-more-leave-to {
  opacity: 0;
  transform: translateY(calc(var(--motion-distance-xs) * -1));
}

@media (max-width: 1180px) {
  .navrail {
    padding: 18px 10px;
    align-items: center;
  }
  .brand-copy,
    .nav-label,
    .navrail-status,
    .command-shortcut span,
    .command-shortcut kbd {
    display: none;
  }
  .nav-item {
    justify-content: center;
    padding: 0;
    width: 44px;
  }
  .nav-item.active::before {
    left: -10px;
  }
  .navrail-utilities {
    width: 100%;
  }
  .advanced-items {
    padding-left: 0;
  }
  .command-shortcut {
    width: 44px;
    justify-content: center;
    padding: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .navrail::after,
  .status-dot {
    animation: none;
  }
  .brand-mark,
  .nav-item,
  .nav-icon,
  .nav-more-enter-active,
  .nav-more-leave-active {
    transition: none;
  }
  .nav-item:hover,
  .navrail-brand:hover .brand-mark,
  .nav-item:hover .nav-icon,
  .nav-item.active .nav-icon {
    transform: none;
  }
}

@media (forced-colors: active) {
  .navrail::after {
    display: none;
  }
  .nav-item.active {
    color: HighlightText;
    outline: 2px solid Highlight;
    outline-offset: -3px;
  }
  .nav-item.active::before {
    background: HighlightText;
  }
  .status-dot {
    border: 1px solid CanvasText;
  }
}
</style>
