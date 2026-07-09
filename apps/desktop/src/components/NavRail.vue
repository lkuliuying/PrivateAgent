<script setup lang="ts">
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
  PhCaretDoubleLeft,
} from "@phosphor-icons/vue";
import type { View } from "../types";

defineProps<{ active: View }>();
const emit = defineEmits<{ navigate: [view: View] }>();

const items: { key: View; label: string; icon: typeof PhChatsCircle }[] = [
  { key: "today", label: "今日", icon: PhSun },
  { key: "chat", label: "对话", icon: PhChatsCircle },
  { key: "kb", label: "知识库", icon: PhBooks },
  { key: "projects", label: "项目", icon: PhFolderSimple },
  { key: "learning", label: "学习", icon: PhGraduationCap },
  { key: "tasks", label: "任务", icon: PhListChecks },
  { key: "memory", label: "记忆", icon: PhBrain },
  { key: "diagnostics", label: "诊断", icon: PhActivity },
  { key: "extensions", label: "扩展", icon: PhPuzzlePiece },
  { key: "integrations", label: "集成", icon: PhPlugs },
  { key: "backup", label: "备份", icon: PhDatabase },
  { key: "settings", label: "设置", icon: PhGearSix },
];
</script>

<template>
  <nav class="navrail" aria-label="主导航">
    <div class="navrail-brand" title="私人助手">
      <div class="brand-mark">P</div>
      <div class="brand-copy">
        <strong>PrivateAgent</strong>
        <span>本地优先</span>
      </div>
      <PhCaretDoubleLeft class="brand-collapse" :size="16" />
    </div>

    <ul class="navrail-items">
      <li v-for="item in items" :key="item.key">
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
    <div class="navrail-status">
      <span class="status-dot" />
      <div>
        <strong>本地运行中</strong>
        <span>Qwen3 · 本机向量库</span>
      </div>
    </div>
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
  padding: var(--space-5) var(--space-4);
  gap: var(--space-5);
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
  width: 30px;
  height: 30px;
  border-radius: var(--radius);
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #11bfd9, #075f78);
  color: #fff;
  font-weight: 800;
  font-size: var(--text-lg);
  flex-shrink: 0;
}
.brand-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.brand-copy strong {
  font-size: var(--text-md);
  color: var(--color-rail-fg-strong);
  line-height: 1.2;
}
.brand-copy span {
  font-size: var(--text-xs);
  color: var(--color-rail-fg-muted);
}
.brand-collapse {
  margin-left: auto;
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
.nav-item {
  position: relative;
  width: 100%;
  height: 42px;
  border: none;
  background: transparent;
  color: var(--color-rail-fg-muted);
  cursor: pointer;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-3);
  border-radius: var(--radius-md);
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
.navrail-status {
  margin-top: auto;
  padding-top: var(--space-5);
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

@media (max-width: 1120px) {
  .navrail {
    padding: var(--space-4) var(--space-2);
    align-items: center;
  }
  .brand-copy,
  .brand-collapse,
  .nav-label,
  .navrail-status {
    display: none;
  }
  .nav-item {
    justify-content: center;
    padding: 0;
    width: 44px;
  }
  .nav-item.active::before {
    left: -14px;
  }
}
</style>
