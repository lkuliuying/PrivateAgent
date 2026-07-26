<script setup lang="ts">
import { computed } from "vue";
import { PhDesktop, PhEye, PhMoon, PhSun } from "@phosphor-icons/vue";
import { useAppearance } from "../stores/appearance";

const appearance = useAppearance();

const themeMeta = computed(() => {
  switch (appearance.theme.value) {
    case "light":
      return { label: "浅色", icon: PhSun };
    case "dark":
      return { label: "深色", icon: PhMoon };
    default:
      return { label: "系统", icon: PhDesktop };
  }
});

const contrastMore = computed(() => appearance.contrast.value === "more");
</script>

<template>
  <div class="appearance-control" role="group" aria-label="外观设置">
    <button
      class="appearance-action appearance-theme"
      :aria-label="`主题：${themeMeta.label}，点击切换`"
      :title="`主题：${themeMeta.label}（系统、浅色、深色）`"
      @click="appearance.cycleTheme()"
    >
      <component :is="themeMeta.icon" :size="18" weight="regular" />
      <span>{{ themeMeta.label }}</span>
    </button>
    <button
      class="appearance-action appearance-contrast"
      :class="{ active: contrastMore }"
      :aria-label="contrastMore ? '关闭高对比度' : '开启高对比度'"
      :aria-pressed="contrastMore"
      :title="contrastMore ? '高对比度：已开启' : '高对比度：未开启'"
      @click="appearance.toggleContrast()"
    >
      <PhEye :size="18" :weight="contrastMore ? 'fill' : 'regular'" />
    </button>
  </div>
</template>

<style scoped>
.appearance-control {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 36px;
  gap: var(--space-1);
  width: 100%;
}
.appearance-action {
  min-width: 0;
  height: 36px;
  border: 1px solid var(--color-rail-border);
  border-radius: var(--radius-md);
  background: var(--color-rail-command-bg);
  color: var(--color-rail-fg-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  transition: color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease),
    transform var(--duration-fast) var(--ease-out);
}
.appearance-theme {
  justify-content: flex-start;
  padding: 0 10px;
}
.appearance-action span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-sm);
}
.appearance-action:hover {
  color: var(--color-rail-fg-strong);
  background: var(--color-rail-surface);
  border-color: var(--color-rail-focus-border);
  transform: translateY(-1px);
}
.appearance-action:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--color-rail-accent);
}
.appearance-action.active {
  color: var(--color-rail-fg-strong);
  background: var(--color-rail-active);
  border-color: var(--color-rail-focus-border);
}

@media (max-width: 1180px) {
  .appearance-control {
    grid-template-columns: 44px;
    justify-content: center;
  }
  .appearance-action {
    width: 44px;
  }
  .appearance-theme {
    justify-content: center;
    padding: 0;
  }
  .appearance-action span {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .appearance-action,
  .appearance-action:hover {
    transform: none;
  }
}

@media (forced-colors: active) {
  .appearance-action.active {
    outline: 2px solid Highlight;
    outline-offset: -3px;
  }
}
</style>
