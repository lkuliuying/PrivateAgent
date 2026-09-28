<script setup lang="ts">
/**
 * RunPlanPopover · v0.8.0 W2
 *
 * 后端真实计划浮层：仅消费 plan.created/plan.updated/plan.item_changed 投影与
 * run 快照 plan（W2 退出条件：不使用 buildAgentPlan() 启发式）。
 * 当前 in_progress 项高亮；Esc/关闭按钮收起。
 */
import { onBeforeUnmount, onMounted } from "vue";
import {
  PhCheckCircle,
  PhCircle,
  PhCircleNotch,
  PhProhibit,
  PhWarning,
  PhX,
} from "@phosphor-icons/vue";
import type { RunPlanItemStatus, RunPlanState } from "../model/runContracts";
import { PLAN_ITEM_META } from "../model/runContracts";

defineProps<{
  plan: RunPlanState | null;
}>();

const emit = defineEmits<{
  close: [];
}>();

const ITEM_ICON_TONE: Record<RunPlanItemStatus, string> = {
  pending: "neutral",
  in_progress: "info",
  completed: "success",
  blocked: "warning",
  failed: "danger",
  cancelled: "neutral",
};

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") emit("close");
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <aside class="plan-popover" data-testid="run-plan-popover" aria-label="执行计划" role="complementary">
    <header class="plan-head">
      <strong>执行计划<template v-if="plan"> · v{{ plan.version }}</template></strong>
      <button class="icon-btn" aria-label="关闭计划" data-testid="plan-close" @click="emit('close')">
        <PhX :size="15" />
      </button>
    </header>

    <div v-if="!plan || plan.items.length === 0" class="plan-empty">
      后端尚未建立计划；计划生成后会实时更新。
    </div>

    <template v-else>
      <p v-if="plan.needs_review" class="plan-notice" role="status">目标已变化，计划待核对。</p>
      <p v-if="plan.explanation" class="plan-explanation">{{ plan.explanation }}</p>
      <ol class="plan-list">
        <li
          v-for="item in plan.items"
          :key="item.item_key"
          class="plan-item"
          :class="{ current: item.status === 'in_progress' }"
          :data-testid="`plan-item-${item.item_key}`"
          :data-status="item.status"
          :aria-label="`${item.title}：${PLAN_ITEM_META[item.status]?.label ?? item.status}`"
        >
          <span class="item-icon" :class="`tone-${ITEM_ICON_TONE[item.status]}`">
            <PhCheckCircle v-if="item.status === 'completed'" :size="14" weight="fill" aria-hidden="true" />
            <PhCircleNotch v-else-if="item.status === 'in_progress'" :size="14" class="spin" aria-hidden="true" />
            <PhWarning v-else-if="item.status === 'blocked' || item.status === 'failed'" :size="14" aria-hidden="true" />
            <PhProhibit v-else-if="item.status === 'cancelled'" :size="14" aria-hidden="true" />
            <PhCircle v-else :size="14" aria-hidden="true" />
          </span>
          <div class="item-copy">
            <p class="item-title">
              <span class="item-ordinal">{{ item.ordinal }}</span>
              {{ item.title }}
            </p>
            <p v-if="item.detail" class="item-detail">{{ item.detail }}</p>
            <p v-if="item.supersedes?.length" class="item-detail">补救步骤：{{ item.supersedes.map(key => plan?.items.find(previous => previous.item_key === key)?.title ?? key).join('、') }}</p>
            <p v-if="item.evidence_calls?.length" class="item-detail">关联 {{ item.evidence_calls.length }} 次工具调用</p>
          </div>
        </li>
      </ol>
      <p class="plan-explanation">步骤进度不代表验证通过，结果以任务验收为准。</p>
    </template>
  </aside>
</template>

<style scoped>
.plan-popover {
  display: flex;
  width: 300px;
  flex-shrink: 0;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--color-border);
  background: var(--color-panel);
}
.plan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border);
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.plan-empty {
  padding: var(--space-4) var(--space-3);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.plan-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0;
  padding: var(--space-2);
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.plan-notice, .plan-explanation {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
  overflow-wrap: anywhere;
}
.plan-notice {
  color: var(--color-warning);
}
.plan-item {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
}
.plan-item.current {
  border-color: color-mix(in srgb, var(--color-accent) 36%, var(--color-border));
  background: var(--color-accent-soft);
}
.item-icon {
  display: inline-flex;
  margin-top: 1px;
}
.item-icon.tone-info { color: var(--color-accent); }
.item-icon.tone-success { color: var(--color-success); }
.item-icon.tone-warning { color: var(--color-warning); }
.item-icon.tone-danger { color: var(--color-danger); }
.item-icon.tone-neutral { color: var(--color-fg-subtle); }
.item-copy {
  min-width: 0;
}
.item-title {
  display: flex;
  gap: var(--space-1);
  margin: 0;
  color: var(--color-fg);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  line-height: var(--leading-normal);
}
.plan-item.current .item-title {
  color: var(--color-accent-soft-fg);
}
.item-ordinal {
  color: var(--color-fg-subtle);
  font-weight: var(--font-normal);
}
.item-detail {
  margin: var(--space-1) 0 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
  word-break: break-word;
}
.spin {
  animation: plan-spin 0.9s linear infinite;
}
@keyframes plan-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
}
</style>
