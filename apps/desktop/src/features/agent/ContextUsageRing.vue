<script setup lang="ts">
/**
 * ContextUsageRing · v0.9.0 H1-A（计划 §5.4 / H0 §7.3）
 *
 * PrivateAgent 状态旁的紧凑上下文用量圆环：
 * - 数值只来自后端 typed budget（GET /sessions/{id}/context-budget），
 *   绝不按字符数/消息数伪造；不可用 → 「不可用 + 原因」，无虚假百分比；
 * - 颜色/进度之外提供文本替代、aria-label 与非颜色状态标记；
 * - hover 与键盘 focus 弹层只显示上下文容量、进度与平均缓存命中率；
 * - 切换会话即重新读取（不显示上一会话旧值）；卸载清理轮询定时器。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { getContextBudget } from "../../api";
import {
  contextRingAriaLabel,
  contextRingLoading,
  contextRingUnavailable,
  deriveContextRing,
  formatCompactTokens,
  type ContextRingFacts,
} from "./model/contextRing";

const props = withDefaults(
  defineProps<{
    sessionId?: number | null;
    modelProfileId?: string | null;
    /** 能力位（/capabilities.coding_context_budget_enabled） */
    enabled?: boolean;
  }>(),
  { sessionId: null, modelProfileId: null, enabled: false }
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
    const body = await getContextBudget(props.sessionId, props.modelProfileId);
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
  () => [props.sessionId, props.modelProfileId, props.enabled] as const,
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

const preciseUsagePercent = computed(() => {
  const f = facts.value;
  if (f.percent === null || f.limitTokens <= 0) return null;
  return Math.min(100, Math.max(0, f.usedTokens * 100 / f.limitTokens));
});

const capacityLabel = computed(() => {
  const f = facts.value;
  const percent = preciseUsagePercent.value;
  if (percent === null) return f.limitTokens > 0 ? `容量 ${formatCompactTokens(f.limitTokens)}，用量待上报` : "不可用";
  return `${formatCompactTokens(f.usedTokens)}/${formatCompactTokens(f.limitTokens)}（${percent.toFixed(1)}%）`;
});

const cacheHitLabel = computed(() => {
  const value = facts.value.cacheHitPercent;
  return value === null ? "--" : `${value.toFixed(1)}%`;
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

    <!-- hover / 键盘 focus 弹层：按产品口径仅呈现容量与缓存命中率 -->
    <div class="ring-popover" role="tooltip" data-testid="context-ring-popover">
      <template v-if="facts.state !== 'unavailable' && preciseUsagePercent !== null">
        <div class="capacity-row">
          <span class="capacity-title">上下文容量</span>
          <span class="capacity-value" data-testid="context-capacity-value">{{ capacityLabel }}</span>
        </div>
        <div
          class="capacity-track"
          role="progressbar"
          aria-label="上下文容量"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="preciseUsagePercent"
        >
          <span class="capacity-progress" :style="{ width: `${preciseUsagePercent}%` }" />
        </div>
        <div class="popover-divider" />
        <div class="cache-row">
          <span>平均缓存命中率</span>
          <strong data-testid="context-cache-hit">{{ cacheHitLabel }}</strong>
        </div>
      </template>
      <template v-else>
        <p v-if="facts.limitTokens > 0" data-testid="context-capacity-pending">{{ capacityLabel }}</p>
        <p class="unavailable-copy">{{ facts.limitTokens > 0 ? "上下文用量" : "上下文容量" }}不可用：{{ facts.reason ?? "无法准确计量" }}</p>
      </template>
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
  width: 300px;
  padding: 14px 16px;
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
.capacity-row,
.cache-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  color: var(--color-fg);
  font-size: var(--pa-text-meta, 12px);
}
.capacity-title {
  font-weight: 600;
}
.capacity-value {
  color: var(--color-fg-muted);
  white-space: nowrap;
}
.capacity-track {
  height: 8px;
  margin-top: 12px;
  overflow: hidden;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
}
.capacity-progress {
  display: block;
  height: 100%;
  min-width: 2px;
  border-radius: inherit;
  background: var(--color-fg);
}
.popover-divider {
  height: 1px;
  margin: 14px 0 10px;
  background: var(--color-border);
}
.cache-row {
  color: var(--color-fg-muted);
}
.cache-row strong {
  color: var(--color-fg);
  font-weight: 600;
}
.unavailable-copy {
  margin: 0;
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
