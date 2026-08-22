<script setup lang="ts">
/**
 * ThreadHeader · v0.8.0 W2
 *
 * 任务页头部：标题 / 项目 · 分支 · HEAD · dirty / run 状态徽标 / 计划入口 /
 * 停止（run 运行中）/ 返回首页。全部信息来自公开事实（workspace DTO 与
 * run 快照的 base_* 字段），HEAD/dirty 未有快照时回退 workspace 登记值。
 */
import { computed, type Component } from "vue";
import {
  PhArrowLeft,
  PhCheckCircle,
  PhCircleNotch,
  PhClockClockwise,
  PhGitBranch,
  PhListChecks,
  PhProhibit,
  PhSidebarSimple,
  PhWarning,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { AgentRunStatus } from "../model/runContracts";
import { RUN_STATUS_META } from "../model/runContracts";

const props = withDefaults(
  defineProps<{
    title: string;
    projectName?: string;
    branchLabel?: string;
    headSha?: string | null;
    gitDirty?: boolean | null;
    runStatus?: AgentRunStatus | null;
    planAvailable?: boolean;
    planOpen?: boolean;
    contextOpen?: boolean;
    cancellable?: boolean;
    cancelling?: boolean;
  }>(),
  {
    projectName: "",
    branchLabel: "",
    headSha: null,
    gitDirty: null,
    runStatus: null,
    planAvailable: false,
    planOpen: false,
    contextOpen: false,
    cancellable: false,
    cancelling: false,
  }
);

const emit = defineEmits<{
  "back-home": [];
  cancel: [];
  "toggle-plan": [];
  "toggle-context": [];
}>();

const STATUS_ICONS: Record<AgentRunStatus, Component> = {
  created: PhClockClockwise,
  running: PhCircleNotch,
  waiting_approval: PhWarning,
  completed: PhCheckCircle,
  failed: PhWarningCircle,
  cancelled: PhProhibit,
  timed_out: PhClockClockwise,
  limit_exceeded: PhWarning,
};

const shortHead = computed(() => {
  const sha = props.headSha;
  return sha ? sha.slice(0, 8) : "";
});

const statusMeta = computed(() => (props.runStatus ? RUN_STATUS_META[props.runStatus] : null));
</script>

<template>
  <header class="thread-header" data-testid="coding-thread-header">
    <div class="header-actions">
      <button class="icon-btn" aria-label="回到首页" data-testid="thread-back-home" @click="emit('back-home')">
        <PhArrowLeft :size="16" />
      </button>
    </div>
    <div class="header-copy">
      <h1 :title="title">{{ title }}</h1>
      <p class="header-meta">
        <span v-if="projectName">{{ projectName }}</span>
        <template v-if="branchLabel">
          <span class="meta-sep" aria-hidden="true">/</span>
          <span class="meta-branch"><PhGitBranch :size="13" aria-hidden="true" />{{ branchLabel }}</span>
        </template>
        <template v-if="shortHead">
          <span class="meta-sep" aria-hidden="true">·</span>
          <span class="meta-sha" :title="'HEAD ' + shortHead">{{ shortHead }}</span>
        </template>
        <template v-if="gitDirty === true">
          <span class="meta-sep" aria-hidden="true">·</span>
          <span class="meta-dirty">有未提交更改</span>
        </template>
      </p>
    </div>
    <div class="header-trailing">
      <span
        v-if="statusMeta"
        class="run-status"
        :class="`tone-${statusMeta.tone}`"
        data-testid="thread-run-status"
        :aria-label="`任务状态：${statusMeta.label}`"
      >
        <component
          :is="STATUS_ICONS[runStatus!]"
          :size="14"
          :weight="runStatus === 'completed' ? 'fill' : 'regular'"
          :class="{ spin: runStatus === 'running' }"
        />
        {{ statusMeta.label }}
      </span>
      <button
        v-if="planAvailable"
        class="plan-toggle"
        :class="{ active: planOpen }"
        :aria-expanded="planOpen"
        data-testid="thread-plan-toggle"
        @click="emit('toggle-plan')"
      >
        <PhListChecks :size="15" />
        <span>计划</span>
      </button>
      <button
        class="plan-toggle"
        :class="{ active: contextOpen }"
        :aria-expanded="contextOpen"
        aria-label="任务上下文"
        data-testid="thread-context-toggle"
        :title="contextOpen ? '收起上下文' : '展开上下文'"
        @click="emit('toggle-context')"
      >
        <PhSidebarSimple :size="15" />
      </button>
      <button
        v-if="cancellable"
        class="cancel-btn"
        :disabled="cancelling"
        data-testid="thread-cancel"
        @click="emit('cancel')"
      >
        <PhProhibit :size="14" />
        <span>{{ cancelling ? "停止中…" : "停止" }}</span>
      </button>
    </div>
  </header>
</template>

<style scoped>
.thread-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.header-actions {
  display: flex;
  align-items: center;
}
.header-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}
.header-copy h1 {
  overflow: hidden;
  margin: 0;
  color: var(--color-fg);
  font-size: var(--pa-text-section);
  font-weight: var(--font-semibold);
  line-height: var(--leading-tight);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  margin: 2px 0 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.meta-branch {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.meta-sep {
  color: var(--color-fg-faint);
}
.meta-sha {
  font-family: var(--font-mono, monospace);
}
.meta-dirty {
  color: var(--color-accent-soft-fg);
}
.header-trailing {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-2);
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.run-status {
  display: inline-flex;
  height: 28px;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--pa-text-meta);
  font-weight: var(--font-medium);
  white-space: nowrap;
}
.run-status.tone-info {
  border-color: color-mix(in srgb, var(--color-accent) 32%, var(--color-border));
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.run-status.tone-success {
  border-color: color-mix(in srgb, var(--color-success) 28%, var(--color-border));
  background: var(--color-success-soft);
  color: var(--color-success-fg);
}
.run-status.tone-warning {
  border-color: color-mix(in srgb, var(--color-warning) 28%, var(--color-border));
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
}
.run-status.tone-danger {
  border-color: color-mix(in srgb, var(--color-danger) 28%, var(--color-border));
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
}
.plan-toggle,
.cancel-btn {
  display: inline-flex;
  height: 28px;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.plan-toggle:hover,
.plan-toggle.active {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.plan-toggle[aria-expanded="true"] {
  border-color: color-mix(in srgb, var(--color-accent) 40%, var(--color-border));
  color: var(--color-accent-soft-fg);
}
.cancel-btn {
  color: var(--color-danger-fg);
}
.cancel-btn:hover:not(:disabled) {
  background: var(--color-danger-soft);
}
.cancel-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
.spin {
  animation: header-spin 0.9s linear infinite;
}
@keyframes header-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
}
</style>
