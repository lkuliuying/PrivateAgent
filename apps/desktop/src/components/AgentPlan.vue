<script setup lang="ts">
import type { Component } from "vue";
import {
  PhCheckCircle,
  PhCircle,
  PhCircleNotch,
  PhHourglassMedium,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { WorkspacePlanStep, WorkspaceStepStatus } from "../types";
import { STEP_STATUS_META } from "../models/agentWorkspace";

defineProps<{ steps: WorkspacePlanStep[] }>();

const STATUS_ICONS: Record<WorkspaceStepStatus, Component> = {
  pending: PhCircle,
  running: PhCircleNotch,
  completed: PhCheckCircle,
  blocked: PhHourglassMedium,
  failed: PhWarningCircle,
};
</script>

<template>
  <section class="agent-plan" aria-labelledby="agent-plan-title">
    <div class="plan-heading">
      <div>
        <span class="plan-kicker">TASK PLAN</span>
        <h2 id="agent-plan-title">执行计划</h2>
      </div>
      <span class="plan-progress">
        {{ steps.filter((step) => step.status === "completed").length }} / {{ steps.length }}
      </span>
    </div>

    <ol class="plan-steps">
      <li
        v-for="(step, index) in steps"
        :key="step.id"
        class="plan-step"
        :class="`is-${STEP_STATUS_META[step.status].tone}`"
        :aria-current="step.status === 'running' ? 'step' : undefined"
      >
        <div class="step-marker" :class="{ pulse: step.status === 'running' }">
          <component :is="STATUS_ICONS[step.status]" :size="20" :weight="step.status === 'completed' ? 'fill' : 'regular'" />
        </div>
        <div class="step-copy">
          <div class="step-topline">
            <span class="step-index">{{ index + 1 }}</span>
            <strong>{{ step.title }}</strong>
          </div>
          <span class="step-detail">{{ step.detail }}</span>
          <span class="step-state">{{ STEP_STATUS_META[step.status].label }}</span>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.agent-plan {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  padding: var(--space-4) var(--space-5);
  box-shadow: var(--shadow-sm);
}
.plan-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.plan-kicker {
  display: block;
  margin-bottom: 2px;
  color: var(--color-fg-faint);
  font-size: 10px;
  font-weight: var(--font-semibold);
  letter-spacing: 0.11em;
}
.plan-heading h2 {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--text-lg);
  line-height: var(--leading-tight);
}
.plan-progress {
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}
.plan-steps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.plan-step {
  position: relative;
  display: flex;
  min-width: 0;
  gap: var(--space-3);
  padding-right: var(--space-4);
}
.plan-step:not(:last-child)::after {
  content: "";
  position: absolute;
  top: 10px;
  left: 31px;
  right: 8px;
  height: 1px;
  background: var(--color-border-strong);
}
.step-marker {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border-radius: var(--radius-full);
  color: var(--color-fg-faint);
  background: var(--color-surface);
}
.step-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
  padding-top: 1px;
}
.step-topline {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-1);
}
.step-topline strong {
  overflow: hidden;
  color: var(--color-fg);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step-index {
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}
.step-detail,
.step-state {
  overflow: hidden;
  color: var(--color-fg-faint);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step-state {
  color: var(--color-fg-subtle);
  font-weight: var(--font-medium);
}
.is-info .step-marker,
.is-info .step-state {
  color: var(--color-accent);
}
.is-success .step-marker,
.is-success .step-state {
  color: var(--color-success);
}
.is-warning .step-marker,
.is-warning .step-state {
  color: var(--color-warning);
}
.is-danger .step-marker,
.is-danger .step-state {
  color: var(--color-danger);
}
.pulse {
  animation: plan-pulse 1.8s var(--ease) infinite;
}
@keyframes plan-pulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-accent) 0%, transparent); }
  50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--color-accent) 12%, transparent); }
}
@media (max-width: 900px) {
  .plan-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
  .plan-step:nth-child(2)::after { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .pulse { animation: none; }
}
</style>
