<script setup lang="ts">
/**
 * AppShell v2 · 0.4.0 三栏工作台壳
 * 左导航 / 中央主工作区 / 上下文栏；独立滚动边界；底部状态栏。
 * 页面层级统一：面包屑 → 标题 → 状态/操作 → 主体（docs/v0.4.0 计划 §4.3）。
 */
import type { Component } from "vue";
import {
  PhCheckCircle,
  PhCircle,
  PhCircleNotch,
  PhHourglassMedium,
  PhSidebarSimple,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { AgentTaskState, View } from "../types";
import { TASK_STATE_META } from "../models/agentWorkspace";
import { viewMeta } from "../models/viewRegistry";
import PaIconButton from "../design/PaIconButton.vue";

const props = withDefaults(
  defineProps<{
    view: View;
    title: string;
    taskState?: AgentTaskState;
    showDevTag?: boolean;
    contextOpen?: boolean;
    contextToggleable?: boolean;
    railCollapsed?: boolean;
    /** v0.8.0 W1：coding 窄窗口抽屉模式下侧栏以覆盖层呈现，rail 槽收起为 0 宽 */
    railHidden?: boolean;
    canGoBack?: boolean;
    canGoForward?: boolean;
  }>(),
  {
    taskState: "idle",
    showDevTag: false,
    contextOpen: false,
    contextToggleable: false,
    railCollapsed: false,
    railHidden: false,
    canGoBack: false,
    canGoForward: false,
  }
);

const emit = defineEmits<{
  "toggle-context": [];
  "go-back": [];
  "go-forward": [];
}>();

const STATE_ICONS: Record<AgentTaskState, Component> = {
  idle: PhCircle,
  running: PhCircleNotch,
  waiting: PhHourglassMedium,
  completed: PhCheckCircle,
  failed: PhWarningCircle,
  stopped: PhCircle,
};

const meta = () => viewMeta(props.view);
</script>

<template>
  <div
    class="appshell"
    :class="{ 'is-rail-collapsed': railCollapsed, 'is-rail-hidden': railHidden }"
  >
    <div class="appshell-body">
      <aside class="appshell-rail">
        <slot name="rail" />
      </aside>

      <main class="appshell-main">
        <header v-if="meta().showTopbar !== false" class="appshell-topbar">
          <div class="topbar-nav">
            <PaIconButton
              label="返回上一视图"
              :disabled="!canGoBack"
              size="sm"
              @click="emit('go-back')"
            >
              <PhSidebarSimple :size="15" style="transform: rotate(180deg)" />
            </PaIconButton>
          </div>
          <div class="topbar-copy">
            <div class="topbar-breadcrumb">
              <span>{{ meta().group === 'system' ? '系统' : viewMeta(props.view).label }}</span>
            </div>
            <div class="topbar-title-row">
              <h1 :title="title">{{ title }}</h1>
              <span v-if="showDevTag" class="topbar-dev">DEV</span>
            </div>
          </div>

          <div class="topbar-actions">
            <span
              v-if="meta().showsTaskState"
              class="task-state"
              :class="`tone-${TASK_STATE_META[taskState].tone}`"
            >
              <component
                :is="STATE_ICONS[taskState]"
                :size="15"
                :weight="taskState === 'completed' ? 'fill' : 'regular'"
                :class="{ spin: taskState === 'running' }"
              />
              {{ TASK_STATE_META[taskState].label }}
            </span>
            <PaIconButton
              v-if="contextToggleable"
              label="切换上下文栏"
              :active="contextOpen"
              @click="emit('toggle-context')"
            >
              <PhSidebarSimple :size="18" />
            </PaIconButton>
            <slot name="topbar-actions" />
          </div>
        </header>

        <div class="appshell-content">
          <slot />
        </div>
      </main>

      <Transition name="pa-zone">
        <aside v-if="contextOpen" class="appshell-context">
          <slot name="context" />
        </aside>
      </Transition>
    </div>

    <footer v-if="meta().showStatusbar !== false && $slots.statusbar" class="appshell-statusbar">
      <slot name="statusbar" />
    </footer>
  </div>
</template>

<style scoped>
.appshell {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  flex-direction: column;
  background: var(--color-bg);
}
.appshell-body {
  display: flex;
  flex: 1;
  min-height: 0;
}
.appshell-rail {
  width: var(--rail-w);
  min-width: 0;
  flex-shrink: 0;
  transition: width var(--pa-motion-standard) var(--ease);
}
.is-rail-collapsed .appshell-rail {
  width: var(--rail-collapsed-w);
}
/* v0.8.0 W1：coding 抽屉模式（<1280px）时侧栏走覆盖层，rail 槽收为 0 宽 */
.is-rail-hidden .appshell-rail {
  width: 0;
  overflow: hidden;
  border-right: none;
}
.appshell-main {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  background: var(--color-bg);
}
.appshell-topbar {
  display: flex;
  min-height: 72px;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.topbar-nav {
  display: flex;
  align-items: center;
}
.topbar-copy {
  min-width: 0;
}
.topbar-breadcrumb {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 3px;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.topbar-title-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
}
.topbar-title-row h1 {
  overflow: hidden;
  margin: 0;
  color: var(--color-fg);
  font-size: var(--pa-text-page-title);
  font-weight: var(--font-semibold);
  line-height: var(--leading-tight);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-dev {
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
  white-space: nowrap;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-left: auto;
}
.task-state {
  display: inline-flex;
  height: 32px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  font-weight: var(--font-medium);
  white-space: nowrap;
}
.task-state.tone-info { border-color: color-mix(in srgb, var(--color-accent) 32%, var(--color-border)); background: var(--color-accent-soft); color: var(--color-accent-soft-fg); }
.task-state.tone-success { border-color: color-mix(in srgb, var(--color-success) 28%, var(--color-border)); background: var(--color-success-soft); color: var(--color-success-fg); }
.task-state.tone-warning { border-color: color-mix(in srgb, var(--color-warning) 28%, var(--color-border)); background: var(--color-warning-soft); color: var(--color-warning-fg); }
.task-state.tone-danger { border-color: color-mix(in srgb, var(--color-danger) 28%, var(--color-border)); background: var(--color-danger-soft); color: var(--color-danger-fg); }
.spin {
  animation: shell-spin 0.9s linear infinite;
}
@keyframes shell-spin {
  to { transform: rotate(360deg); }
}
.appshell-content {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}
.appshell-context {
  display: flex;
  width: var(--inspector-w);
  min-width: 0;
  flex-shrink: 0;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--color-border);
  background: var(--color-panel);
}
.appshell-statusbar {
  height: var(--statusbar-h);
  flex-shrink: 0;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}
.pa-zone-enter-active,
.pa-zone-leave-active {
  transition: opacity var(--pa-motion-standard) var(--ease),
    transform var(--pa-motion-standard) var(--ease);
}
.pa-zone-enter-from,
.pa-zone-leave-to {
  opacity: 0;
  transform: translateX(8px);
}
@media (max-width: 1420px) {
  .appshell-context { width: 320px; }
}
@media (max-width: 1319px) {
  .appshell-context { display: none; }
}
@media (max-width: 920px) {
  .appshell-rail { width: var(--rail-collapsed-w); }
  .appshell-topbar { padding-inline: var(--space-4); }
}
@media (prefers-reduced-motion: reduce) {
  .appshell-rail,
  .pa-zone-enter-active,
  .pa-zone-leave-active {
    transition: none;
  }
  .spin {
    animation: none;
  }
}
</style>
