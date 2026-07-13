<script setup lang="ts">
import { ref } from "vue";
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
import type { View } from "../types";

defineProps<{ active: View }>();
const emit = defineEmits<{
  navigate: [view: View];
  "open-command": [];
}>();
const advancedOpen = ref(false);

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
          :title="item.label"
          @click="emit('navigate', item.key)"
        >
          <component :is="item.icon" class="nav-icon" :size="20" weight="regular" />
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </li>
    </ul>

    <div class="navrail-utilities">
      <button
        class="nav-item utility-toggle"
        :class="{ active: advancedOpen || advancedItems.some((item) => item.key === active) }"
        :aria-expanded="advancedOpen"
        title="更多工具"
        @click="advancedOpen = !advancedOpen"
      >
        <PhDotsThree class="nav-icon" :size="20" weight="bold" />
        <span class="nav-label">更多</span>
      </button>

      <Transition name="nav-more">
        <ul v-if="advancedOpen" class="navrail-items advanced-items" aria-label="更多工具">
          <li v-for="item in advancedItems" :key="item.key">
            <button
              class="nav-item nav-item--compact"
              :class="{ active: active === item.key }"
              :aria-current="active === item.key ? 'page' : undefined"
              :title="item.label"
              @click="emit('navigate', item.key)"
            >
              <component :is="item.icon" class="nav-icon" :size="18" weight="regular" />
              <span class="nav-label">{{ item.label }}</span>
            </button>
          </li>
        </ul>
      </Transition>

      <button
        class="nav-item"
        :class="{ active: active === 'settings' }"
        title="设置"
        @click="emit('navigate', 'settings')"
      >
        <PhGearSix class="nav-icon" :size="20" weight="regular" />
        <span class="nav-label">设置</span>
      </button>
    </div>

    <div class="navrail-status">
      <span class="status-dot" />
      <div>
        <strong>本地运行中</strong>
        <span>Qwen3 · 本机向量库</span>
      </div>
    </div>

    <button class="command-shortcut" title="打开快捷命令" @click="emit('open-command')">
      <PhCommand :size="15" />
      <span>快捷命令</span>
      <kbd>Ctrl K</kbd>
    </button>
  </nav>
</template>

<style scoped>
.navrail {
  width: 100%;
  height: 100%;
  background: var(--color-rail-bg);
  border-right: 1px solid var(--color-rail-border);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  color: var(--color-rail-fg);
  padding: 24px 16px 18px;
  gap: 18px;
  box-shadow: inset -1px 0 rgba(255, 255, 255, 0.025);
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
  background: var(--color-accent);
  color: #fff;
  font-weight: 800;
  font-family: var(--font-display);
  font-size: 21px;
  flex-shrink: 0;
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
    color var(--duration-fast) var(--ease);
}
.nav-item:hover {
  background: var(--color-rail-surface);
  color: var(--color-rail-fg-strong);
}
.nav-item:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--color-rail-accent);
}
.nav-item.active {
  color: var(--color-rail-fg-strong);
  background: var(--color-rail-active);
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
  background: #22c55e;
  box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.12);
  margin-top: 5px;
  flex-shrink: 0;
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
  background: rgba(255, 255, 255, 0.025);
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
  border-color: rgba(120, 184, 166, 0.34);
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
  transform: translateY(-4px);
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
</style>
