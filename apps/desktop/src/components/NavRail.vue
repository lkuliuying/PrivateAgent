<script setup lang="ts">
import {
  PhChatsCircle,
  PhBooks,
  PhFolderSimple,
  PhGraduationCap,
  PhListChecks,
  PhBrain,
  PhGearSix,
  PhSparkle,
} from "@phosphor-icons/vue";

/** 工作台视图名（与 App.vue view union 对齐） */
type View = "chat" | "kb" | "projects" | "learning" | "tasks" | "memory" | "settings";

defineProps<{ active: View }>();
const emit = defineEmits<{ navigate: [view: View] }>();

const items: { key: View; label: string; icon: typeof PhChatsCircle }[] = [
  { key: "chat", label: "聊天", icon: PhChatsCircle },
  { key: "kb", label: "知识库", icon: PhBooks },
  { key: "projects", label: "项目", icon: PhFolderSimple },
  { key: "learning", label: "学习", icon: PhGraduationCap },
  { key: "tasks", label: "任务", icon: PhListChecks },
  { key: "memory", label: "记忆", icon: PhBrain },
  { key: "settings", label: "设置", icon: PhGearSix },
];
</script>

<template>
  <nav class="navrail" aria-label="主导航">
    <div class="navrail-brand" title="私人助手">
      <PhSparkle class="brand-icon" :size="22" weight="fill" />
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
}

/* 品牌 */
.navrail-brand {
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid var(--color-rail-border);
  flex-shrink: 0;
}
.brand-icon {
  color: var(--color-rail-accent);
}

/* 导航项 */
.navrail-items {
  list-style: none;
  margin: 0;
  padding: var(--space-2) 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-item {
  position: relative;
  width: 100%;
  height: 52px;
  border: none;
  background: transparent;
  color: var(--color-rail-fg-muted);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  border-radius: 0;
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
  color: var(--color-rail-accent);
  background: var(--color-rail-active);
}
/* 激活指示条 */
.nav-item.active::before {
  content: "";
  position: absolute;
  left: 0;
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
  font-size: var(--text-xs);
  line-height: 1;
  letter-spacing: 0.02em;
}
</style>
