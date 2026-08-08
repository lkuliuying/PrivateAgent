<script setup lang="ts">
/**
 * AgentPlanV2 · 计划面板（0.4.0 D3）
 * 步骤与活动流关联：点击步骤定位对应活动（由父层映射步骤 id → 活动索引）。
 * 默认折叠低价值日志；计划状态来自 buildAgentPlan 统一推导。
 */
import {
  PhCheck,
  PhCircleNotch,
  PhHourglass,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { WorkspacePlanStep } from "../../types";

const props = withDefaults(
  defineProps<{
    steps: WorkspacePlanStep[];
    open?: boolean;
  }>(),
  { open: true }
);

const emit = defineEmits<{ locate: [stepId: string] }>();

const ICONS = {
  pending: PhCircleNotch,
  running: PhCircleNotch,
  completed: PhCheck,
  blocked: PhHourglass,
  failed: PhWarningCircle,
} as const;
</script>

<template>
  <section class="plan" :class="{ 'is-open': open }" aria-labelledby="plan-title">
    <div class="plan-heading">
      <h2 id="plan-title">执行计划</h2>
      <span class="plan-state">
        {{
          props.steps.some((s) => s.status === "running")
            ? "进行中"
            : props.steps.some((s) => s.status === "blocked")
              ? "等待确认"
              : props.steps.every((s) => s.status === "completed")
                ? "已完成"
                : "待开始"
        }}
      </span>
    </div>

    <ol class="plan-steps">
      <li
        v-for="step in steps"
        :key="step.id"
        class="plan-step"
        :class="`status-${step.status}`"
      >
        <button
          class="plan-step-hit"
          :aria-label="`定位到活动：${step.title}`"
          :title="step.title"
          @click="emit('locate', step.id)"
        >
          <span class="plan-step-icon">
            <component
              :is="ICONS[step.status]"
              :size="13"
              :weight="step.status === 'completed' ? 'fill' : 'regular'"
              :class="{ spin: step.status === 'running' }"
            />
          </span>
          <span class="plan-step-copy">
            <strong>{{ step.title }}</strong>
            <small>{{ step.detail }}</small>
          </span>
        </button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.plan {
  margin: var(--space-4) 0 0;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}
.plan-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}
.plan-heading h2 {
  margin: 0;
  font-size: var(--pa-text-compact);
  font-weight: var(--font-semibold);
}
.plan-state {
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.plan-steps {
  display: flex;
  margin: 0;
  padding: 0;
  flex-direction: column;
  list-style: none;
}
.plan-step {
  position: relative;
}
.plan-step:not(:last-child)::after {
  content: "";
  position: absolute;
  top: 26px;
  bottom: -2px;
  left: 13px;
  width: 1px;
  background: var(--color-border);
}
.plan-step-hit {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.plan-step-hit:hover .plan-step-copy strong {
  color: var(--color-accent);
}
.plan-step-hit:focus-visible {
  outline: none;
  box-shadow: inset var(--focus-ring);
  border-radius: var(--radius-sm);
}
.plan-step-icon {
  display: grid;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-fg-faint);
}
.plan-step.status-completed .plan-step-icon {
  background: var(--color-success-soft);
  color: var(--color-success-fg);
}
.plan-step.status-running .plan-step-icon {
  background: var(--color-accent-soft);
  color: var(--color-accent);
}
.plan-step.status-blocked .plan-step-icon {
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
}
.plan-step.status-failed .plan-step-icon {
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
}
.plan-step-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
}
.plan-step-copy strong {
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
}
.plan-step-copy small {
  overflow: hidden;
  color: var(--color-fg-subtle);
  font-size: var(--pa-t-11);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.spin {
  animation: plan-spin 0.9s linear infinite;
}
@keyframes plan-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}
</style>
