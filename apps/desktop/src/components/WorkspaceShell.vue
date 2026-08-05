<script setup lang="ts">
import type { Component } from "vue";
import {
  PhCheckCircle,
  PhCircle,
  PhCircleNotch,
  PhHourglassMedium,
  PhSidebarSimple,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { AgentTaskState } from "../types";
import { TASK_STATE_META } from "../models/agentWorkspace";

const props = withDefaults(
  defineProps<{
    title: string;
    taskState?: AgentTaskState;
    showDevTag?: boolean;
    inspectorOpen?: boolean;
    inspectorToggleable?: boolean;
    showTopbar?: boolean;
    showStatusbar?: boolean;
    railCollapsed?: boolean;
  }>(),
  {
    taskState: "idle",
    showDevTag: false,
    inspectorOpen: false,
    inspectorToggleable: false,
    showTopbar: true,
    showStatusbar: true,
    railCollapsed: false,
  }
);

const emit = defineEmits<{ "toggle-inspector": [] }>();
const STATE_ICONS: Record<AgentTaskState, Component> = {
  idle: PhCircle,
  running: PhCircleNotch,
  waiting: PhHourglassMedium,
  completed: PhCheckCircle,
  failed: PhWarningCircle,
  stopped: PhCircle,
};
</script>

<template>
  <div class="workspace" :class="{ 'is-rail-collapsed': railCollapsed }">
    <div class="workspace-body">
      <aside class="workspace-rail">
        <slot name="rail" />
      </aside>

      <main class="workspace-main">
        <header v-if="showTopbar" class="workspace-topbar">
          <div class="topbar-copy">
            <div class="topbar-breadcrumb">
              <span>Agent</span>
              <span aria-hidden="true">/</span>
              <span class="breadcrumb-current">{{ title }}</span>
            </div>
            <div class="topbar-title-row">
              <h1 :title="title">{{ title }}</h1>
              <span v-if="showDevTag" class="topbar-dev">DEV · 8000</span>
            </div>
          </div>

          <div class="topbar-actions">
            <span class="task-state" :class="`tone-${TASK_STATE_META[props.taskState].tone}`">
              <component
                :is="STATE_ICONS[props.taskState]"
                :size="15"
                :weight="props.taskState === 'completed' ? 'fill' : 'regular'"
                :class="{ spin: props.taskState === 'running' }"
              />
              {{ TASK_STATE_META[props.taskState].label }}
            </span>
            <button
              v-if="inspectorToggleable"
              class="pa-btn pa-btn--ghost pa-btn--icon inspector-toggle"
              :class="{ active: inspectorOpen }"
              :aria-pressed="inspectorOpen"
              aria-label="切换上下文面板"
              title="切换上下文面板"
              @click="emit('toggle-inspector')"
            >
              <PhSidebarSimple :size="18" />
            </button>
          </div>
        </header>

        <div class="workspace-content">
          <slot />
        </div>
      </main>

      <Transition name="pa-zone">
        <aside v-if="inspectorOpen" class="workspace-inspector">
          <slot name="inspector" />
        </aside>
      </Transition>
    </div>

    <footer v-if="showStatusbar" class="workspace-statusbar">
      <slot name="statusbar" />
    </footer>
  </div>
</template>

<style scoped>
.workspace {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  flex-direction: column;
  background: var(--color-bg);
}
.workspace-body {
  display: flex;
  flex: 1;
  min-height: 0;
}
.workspace-rail {
  width: var(--rail-w);
  min-width: 0;
  flex-shrink: 0;
  transition: width var(--duration-slow) var(--ease);
}
.is-rail-collapsed .workspace-rail {
  width: var(--rail-collapsed-w);
}
.workspace-main {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  background: var(--color-bg);
}
.workspace-topbar {
  display: flex;
  min-height: 72px;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
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
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.breadcrumb-current {
  overflow: hidden;
  color: var(--color-fg-subtle);
  text-overflow: ellipsis;
  white-space: nowrap;
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
  font-size: var(--text-2xl);
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
  font-size: 10px;
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
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  white-space: nowrap;
}
.task-state.tone-info { border-color: color-mix(in srgb, var(--color-accent) 32%, var(--color-border)); background: var(--color-accent-soft); color: var(--color-accent-soft-fg); }
.task-state.tone-success { border-color: color-mix(in srgb, var(--color-success) 28%, var(--color-border)); background: var(--color-success-soft); color: var(--color-success-fg); }
.task-state.tone-warning { border-color: color-mix(in srgb, var(--color-warning) 28%, var(--color-border)); background: var(--color-warning-soft); color: var(--color-warning-fg); }
.task-state.tone-danger { border-color: color-mix(in srgb, var(--color-danger) 28%, var(--color-border)); background: var(--color-danger-soft); color: var(--color-danger-fg); }
.spin { animation: shell-spin .9s linear infinite; }
@keyframes shell-spin { to { transform: rotate(360deg); } }
.inspector-toggle.active { border-color: color-mix(in srgb, var(--color-accent) 42%, var(--color-border)); background: var(--color-accent-soft); color: var(--color-accent); }
.workspace-content {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}
.workspace-inspector {
  display: flex;
  width: var(--inspector-w);
  min-width: 0;
  flex-shrink: 0;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--color-border);
  background: var(--color-panel);
}
.workspace-statusbar {
  height: var(--statusbar-h);
  flex-shrink: 0;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}
.pa-zone-enter-active,
.pa-zone-leave-active {
  transition: opacity var(--duration) var(--ease), transform var(--duration) var(--ease);
}
.pa-zone-enter-from,
.pa-zone-leave-to {
  opacity: 0;
  transform: translateX(8px);
}
@media (max-width: 1420px) {
  .workspace-inspector { width: 320px; }
}
@media (max-width: 1319px) {
  .workspace-inspector { display: none; }
  .inspector-toggle { display: none; }
}
@media (max-width: 920px) {
  .workspace-rail { width: var(--rail-collapsed-w); }
  .workspace-topbar { padding-inline: var(--space-4); }
}
@media (prefers-reduced-motion: reduce) {
  .workspace-rail, .pa-zone-enter-active, .pa-zone-leave-active { transition: none; }
  .spin { animation: none; }
}
</style>
