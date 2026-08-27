<script setup lang="ts">
/**
 * ContextUsageRing · v0.9.0 H1-A（计划 §5.4 / H0 §7.3）
 *
 * PrivateAgent 状态旁的紧凑上下文用量圆环：
 * - 数值只来自后端 typed budget（GET /sessions/{id}/context-budget），
 *   绝不按字符数/消息数伪造；不可用 → 「不可用 + 原因」，无虚假百分比；
 * - 颜色/进度之外提供文本替代、aria-label 与非颜色状态标记；
 * - hover 与键盘 focus 弹层显示 used/limit、百分比、保留输出预算、
 *   压缩阈值与最近压缩结果；
 * - 切换会话即重新读取（不显示上一会话旧值）；卸载清理轮询定时器。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { getContextBudget } from "../../api";
import { formatDateTime } from "../../services/timeDisplay";
import {
  CONTEXT_RING_NEAR_THRESHOLD,
  contextRingAriaLabel,
  contextRingLoading,
  contextRingSourceLabel,
  contextRingUnavailable,
  deriveContextRing,
  type ContextRingFacts,
} from "./model/contextRing";

const props = withDefaults(
  defineProps<{
    sessionId?: number | null;
    /** 能力位（/capabilities.coding_context_budget_enabled） */
    enabled?: boolean;
  }>(),
  { sessionId: null, enabled: false }
);

const facts = ref<ContextRingFacts>(contextRingLoading());
let pollTimer: number | null = null;
let fetchSeq = 0;

async function load(): Promise<void> {
  const mine = ++fetchSeq;
  if (!props.enabled) {
    facts.value = contextRingUnavailable("上下文计量能力未开启");
    return;
  }
  if (props.sessionId === null) {
    facts.value = contextRingUnavailable("尚无会话");
    return;
  }
  try {
    const body = await getContextBudget(props.sessionId);
    if (mine !== fetchSeq) return;
    facts.value = deriveContextRing(body);
  } catch {
    if (mine !== fetchSeq) return;
    facts.value = contextRingUnavailable("用量读取失败");
  }
}

function startPolling(): void {
  stopPolling();
  pollTimer = window.setInterval(() => void load(), 15_000);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

watch(
  () => [props.sessionId, props.enabled] as const,
  () => {
    facts.value = contextRingLoading();
    void load();
    startPolling();
  },
  { immediate: true }
);

// v0.9.0 H1-C（§5.7）：配置往返/Runtime 重连后回到窗口即原位重新探测，
// 无需新建对话或重启应用。
function onFocusReload(): void {
  void load();
}
window.addEventListener("focus", onFocusReload);

onBeforeUnmount(() => {
  stopPolling();
  window.removeEventListener("focus", onFocusReload);
});

const ariaLabel = computed(() => contextRingAriaLabel(facts.value));

// SVG 圆环进度（周长 = 2πr，r=8 → ≈50.27）
const RING_CIRCUMFERENCE = 2 * Math.PI * 8;
const dashOffset = computed(() => {
  const percent = facts.value.percent ?? 0;
  return RING_CIRCUMFERENCE * (1 - percent / 100);
});

const toneClass = computed(() => `tone-${facts.value.state}`);

/** 非颜色状态标记（形状/文字，色盲友好）。 */
const stateBadge = computed(() => {
  switch (facts.value.state) {
    case "unavailable":
      return "—";
    case "compacting":
      return "压缩中";
    case "failed":
      return "!";
    case "full":
      return "满";
    case "near":
      return "近";
    case "loading":
      return "…";
    default:
      return "";
  }
});

const popoverLines = computed(() => {
  const f = facts.value;
  if (f.state === "unavailable") {
    return [
      `不可用：${f.reason ?? "无法准确计量"}`,
      "恢复：完成模型/Provider 配置或更新 Runtime 后回到本页自动重新探测",
    ];
  }
  const lines = [
    `已用 / 上限：${f.usedTokens.toLocaleString()} / ${f.limitTokens.toLocaleString()} tokens`,
    `用量：${f.percent ?? 0}% · 压缩阈值：${CONTEXT_RING_NEAR_THRESHOLD}%`,
    `保留输出预算：${f.reservedTokens.toLocaleString()} tokens`,
  ];
  switch (f.compactionState) {
    case "compacting":
      lines.push("自动压缩：进行中");
      break;
    case "compacted":
      lines.push(
        `自动压缩：已完成${f.lastCompactedAt ? `（${formatDateTime(f.lastCompactedAt)}）` : ""}`
      );
      break;
    case "failed":
      lines.push(`自动压缩：失败${f.reason ? ` · ${f.reason}` : ""}`);
      break;
    default:
      lines.push("自动压缩：待触发");
  }
  // §5.7：详情显示数据来源与最近更新时间（可对账的真实事实）
  lines.push(`数据来源：${contextRingSourceLabel(f.source)}`);
  if (f.updatedAt !== null) {
    lines.push(`最近更新：${formatDateTime(new Date(f.updatedAt).toISOString())}`);
  }
  return lines;
});
</script>

<template>
  <div
    class="context-ring"
    :class="toneClass"
    tabindex="0"
    role="img"
    data-testid="context-usage-ring"
    :aria-label="ariaLabel"
    :title="ariaLabel"
  >
    <svg class="ring-svg" viewBox="0 0 20 20" aria-hidden="true">
      <circle class="ring-track" cx="10" cy="10" r="8" fill="none" stroke-width="3" />
      <circle
        v-if="facts.percent !== null"
        class="ring-progress"
        cx="10"
        cy="10"
        r="8"
        fill="none"
        stroke-width="3"
        stroke-linecap="round"
        :stroke-dasharray="RING_CIRCUMFERENCE"
        :stroke-dashoffset="dashOffset"
        transform="rotate(-90 10 10)"
      />
    </svg>
    <span v-if="stateBadge" class="ring-badge" aria-hidden="true">{{ stateBadge }}</span>
    <span class="visually-hidden">{{ ariaLabel }}</span>

    <!-- hover / 键盘 focus 弹层：真实数值与压缩事实 -->
    <div class="ring-popover" role="tooltip" data-testid="context-ring-popover">
      <p v-for="line in popoverLines" :key="line" class="popover-line">
        {{ line }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.context-ring {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  cursor: help;
  outline: none;
}
.context-ring:focus-visible {
  box-shadow: 0 0 0 2px var(--pa-input-ring, rgba(80, 140, 200, 0.55));
}
.ring-svg {
  width: 20px;
  height: 20px;
}
.ring-track {
  stroke: var(--color-surface-sunken);
}
.ring-progress {
  stroke: var(--color-success);
  transition: stroke-dashoffset var(--pa-motion-standard, 200ms) ease;
}
.tone-near .ring-progress {
  stroke: var(--color-warning);
}
.tone-full .ring-progress,
.tone-failed .ring-progress {
  stroke: var(--color-danger);
}
.tone-compacting .ring-progress {
  stroke: var(--color-accent);
}
.tone-unavailable .ring-track {
  stroke: var(--color-border);
  stroke-dasharray: 2 3;
}
.ring-badge {
  position: absolute;
  top: -4px;
  right: -8px;
  max-width: 32px;
  overflow: hidden;
  text-overflow: clip;
  white-space: nowrap;
  padding: 0 3px;
  border-radius: var(--radius-full);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  color: var(--color-fg-subtle);
  font-size: 9px;
  line-height: 12px;
}
.tone-full .ring-badge,
.tone-failed .ring-badge {
  background: var(--color-danger);
  border-color: var(--color-danger);
  color: #fff;
}
.tone-near .ring-badge {
  background: var(--color-warning);
  border-color: var(--color-warning);
  color: var(--color-warning-fg, #3a2a05);
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.ring-popover {
  position: absolute;
  bottom: calc(100% + 8px);
  right: -6px;
  z-index: 40;
  min-width: 220px;
  max-width: 300px;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-panel);
  box-shadow: var(--shadow-lg);
  display: none;
  pointer-events: none;
}
.context-ring:hover .ring-popover,
.context-ring:focus-visible .ring-popover,
.context-ring:focus-within .ring-popover {
  display: block;
}
.popover-line {
  margin: 0;
  padding: 1px 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta, 12px);
  line-height: 1.5;
}
@media (prefers-reduced-motion: reduce) {
  .ring-progress {
    transition: none;
  }
}
</style>
