<script setup lang="ts">
import { PhSidebarSimple } from "@phosphor-icons/vue";

/**
 * 工作台四区布局容器。
 * 结构：导航 rail · 列表区 · 主工作区 · 右侧检查器 · 底部状态栏。
 * 纯布局组件，不持有业务状态；各区内容由具名 slot 注入，App.vue 为组合根。
 *
 * 列表区仅在 chat 视图显示（showList）；检查器可折叠（inspectorOpen）。
 * 900px 起：rail(60) + list(280) + main(flex) + inspector(折叠) 不重叠。
 */
withDefaults(
  defineProps<{
    title: string;
    showDevTag?: boolean;
    showList?: boolean;
    inspectorOpen?: boolean;
    inspectorToggleable?: boolean;
    showTopbar?: boolean;
  }>(),
  {
    showDevTag: false,
    showList: false,
    inspectorOpen: false,
    inspectorToggleable: false,
    showTopbar: true,
  }
);

const emit = defineEmits<{ "toggle-inspector": [] }>();
</script>

<template>
  <div class="workspace">
    <div class="workspace-body">
      <!-- 左侧导航 rail -->
      <div class="workspace-rail">
        <slot name="rail" />
      </div>

      <!-- 列表区（仅 chat） -->
      <Transition name="pa-zone">
        <div v-if="showList" class="workspace-list">
          <slot name="list" />
        </div>
      </Transition>

      <!-- 主工作区 -->
      <div class="workspace-main">
        <header v-if="showTopbar" class="workspace-topbar">
          <div class="topbar-copy">
            <span class="topbar-kicker">PrivateAgent</span>
            <span class="topbar-title">{{ title }}</span>
          </div>
          <span v-if="showDevTag" class="topbar-dev">DEV · 手动后端 8000</span>
          <div class="topbar-spacer" />
          <button
            v-if="inspectorToggleable"
            class="pa-btn pa-btn--subtle pa-btn--icon pa-btn--sm inspector-toggle"
            :class="{ active: inspectorOpen }"
            :aria-pressed="inspectorOpen"
            aria-label="切换检查器面板"
            title="检查器面板"
            @click="emit('toggle-inspector')"
          >
            <PhSidebarSimple :size="16" weight="regular" />
          </button>
        </header>
        <div class="workspace-content">
          <slot />
        </div>
      </div>

      <!-- 右侧检查器 -->
      <Transition name="pa-zone">
        <div v-if="inspectorOpen" class="workspace-inspector">
          <slot name="inspector" />
        </div>
      </Transition>
    </div>

    <!-- 底部状态栏 -->
    <div class="workspace-statusbar">
      <slot name="statusbar" />
    </div>
  </div>
</template>

<style scoped>
.workspace {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: var(--color-bg);
}
.workspace-body {
  flex: 1;
  display: flex;
  flex-direction: row;
  min-height: 0;
}

/* 导航 rail */
.workspace-rail {
  flex-shrink: 0;
  width: var(--rail-w);
  min-width: 0;
}

/* 列表区 */
.workspace-list {
  flex-shrink: 0;
  width: var(--list-w);
  min-width: 0;
  border-right: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-panel) 88%, white);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 主工作区 */
.workspace-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: radial-gradient(circle at 45% 0%, rgba(7, 135, 163, 0.05), transparent 36%),
    var(--color-bg);
}

.workspace-topbar {
  flex-shrink: 0;
  min-height: var(--topbar-h);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-6);
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-bg) 92%, white);
}
.topbar-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.topbar-kicker {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  letter-spacing: 0.04em;
}
.topbar-title {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60%;
}
.topbar-dev {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  padding: 2px var(--space-2);
  white-space: nowrap;
}
.topbar-spacer {
  flex: 1;
}
.inspector-toggle.active {
  color: var(--color-accent);
  background: var(--color-accent-soft);
}
.workspace-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 检查器 */
.workspace-inspector {
  flex-shrink: 0;
  width: var(--inspector-w);
  min-width: 0;
  border-left: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-panel) 88%, white);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 状态栏 */
.workspace-statusbar {
  flex-shrink: 0;
  height: var(--statusbar-h);
  border-top: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-bg) 92%, white);
}

@media (max-width: 1120px) {
  .workspace-rail {
    width: 72px;
  }
}

/* 区块进入/离开过渡（短滑入淡入，120–180ms） */
.pa-zone-enter-active,
.pa-zone-leave-active {
  transition: opacity var(--duration) var(--ease),
    transform var(--duration) var(--ease);
}
.pa-zone-enter-from,
.pa-zone-leave-to {
  opacity: 0;
}
.workspace-list.pa-zone-enter-from,
.workspace-list.pa-zone-leave-to {
  transform: translateX(-8px);
}
.workspace-inspector.pa-zone-enter-from,
.workspace-inspector.pa-zone-leave-to {
  transform: translateX(8px);
}
</style>
