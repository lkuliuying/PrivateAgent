<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";
import { getContextBudget } from "../../api";
import { contextRingAriaLabel, contextRingLoading, contextRingUnavailable, deriveContextRing, type ContextRingFacts } from "./model/contextRing";

defineOptions({ inheritAttrs: false });
const props = withDefaults(defineProps<{
  sessionId?: number | null;
  modelProfileId?: string | null;
  contextTokens?: number | null;
  enabled?: boolean;
}>(), { sessionId: null, modelProfileId: null, contextTokens: null, enabled: false });
const facts = ref<ContextRingFacts>(contextRingLoading());
const trigger = ref<HTMLButtonElement>();
const tooltipId = useId();
const open = ref(false);
const placement = ref({ left: "0px", top: "0px", width: "232px" });
let pollTimer: number | null = null;
let fetchSeq = 0;

async function load(): Promise<void> {
  const mine = ++fetchSeq;
  if (props.sessionId === null) {
    facts.value = contextRingUnavailable("开始对话后显示用量");
    if (props.contextTokens && Number.isFinite(props.contextTokens) && props.contextTokens > 0) facts.value.limitTokens = props.contextTokens;
    return;
  }
  if (!props.enabled) {
    facts.value = contextRingUnavailable("上下文计量能力未开启");
    return;
  }
  try {
    const body = await getContextBudget(props.sessionId, props.modelProfileId);
    if (mine === fetchSeq) facts.value = deriveContextRing(body);
  } catch {
    if (mine === fetchSeq) facts.value = contextRingUnavailable("用量读取失败");
  }
}
function stopPolling(): void {
  if (pollTimer !== null) window.clearInterval(pollTimer);
  pollTimer = null;
}
watch(() => [props.sessionId, props.modelProfileId, props.contextTokens, props.enabled], () => {
  facts.value = contextRingLoading();
  void load();
  stopPolling();
  if (props.enabled && props.sessionId !== null) pollTimer = window.setInterval(() => void load(), 15_000);
}, { immediate: true });
function onFocusReload(): void { void load(); }
window.addEventListener("focus", onFocusReload);

function show(): void {
  const rect = trigger.value?.getBoundingClientRect();
  if (!rect) return;
  const width = Math.min(232, window.innerWidth - 24);
  placement.value = { left: `${Math.max(12, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 12))}px`, top: `${rect.top - 10}px`, width: `${width}px` };
  open.value = true;
}
function hide(): void { open.value = false; }
function escape(event: KeyboardEvent): void { if (event.key === "Escape") hide(); }
function outside(event: Event): void { if (!trigger.value?.contains(event.target as Node)) hide(); }
function removeTooltipListeners(): void {
  window.removeEventListener("scroll", hide, true);
  window.removeEventListener("resize", hide);
  window.removeEventListener("keydown", escape);
  window.removeEventListener("pointerdown", outside);
}
watch(open, visible => {
  removeTooltipListeners();
  if (!visible) return;
  window.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
  window.addEventListener("keydown", escape);
  window.addEventListener("pointerdown", outside);
});
onBeforeUnmount(() => {
  fetchSeq++;
  stopPolling();
  removeTooltipListeners();
  window.removeEventListener("focus", onFocusReload);
});

const ariaLabel = computed(() => contextRingAriaLabel(facts.value));
const circumference = 2 * Math.PI * 8;
const dashOffset = computed(() => circumference * (1 - (facts.value.percent ?? 0) / 100));
const badge = computed(() => ({ unavailable: "—", compacting: "压缩中", failed: "!", full: "满", near: "近", loading: "…", ok: "" })[facts.value.state]);
const percent = computed(() => facts.value.percent === null || facts.value.limitTokens <= 0 ? null : Math.min(100, Math.max(0, Math.round(facts.value.usedTokens * 100 / facts.value.limitTokens))));
function tokens(value: number): string {
  return value >= 1000 ? `${Number((value / 1000).toFixed(1))}k` : Math.round(value).toLocaleString("zh-CN");
}
const usageLabel = computed(() => `已用 ${tokens(facts.value.usedTokens)} 标记，共 ${tokens(facts.value.limitTokens)}`);
</script>

<template>
  <button ref="trigger" v-bind="$attrs" type="button" class="context-ring" :class="`tone-${facts.state}`" data-testid="context-usage-ring" :aria-label="ariaLabel" :aria-describedby="open ? tooltipId : undefined" @mouseenter="show" @mouseleave="hide" @focus="show" @blur="hide" @click="show">
    <svg class="ring-svg" viewBox="0 0 20 20" aria-hidden="true">
      <circle class="ring-track" cx="10" cy="10" r="8" fill="none" stroke-width="2.5" />
      <circle v-if="facts.percent !== null" class="ring-progress" cx="10" cy="10" r="8" fill="none" stroke-width="2.5" stroke-linecap="round" :stroke-dasharray="circumference" :stroke-dashoffset="dashOffset" transform="rotate(-90 10 10)" />
    </svg>
    <span v-if="badge" class="ring-badge" aria-hidden="true">{{ badge }}</span>
  </button>
  <Teleport to="body">
    <div v-if="open" :id="tooltipId" class="ring-popover" :style="placement" role="tooltip" data-testid="context-ring-popover">
      <strong class="ring-heading">上下文窗口</strong>
      <template v-if="percent !== null">
        <span class="ring-percent" data-testid="context-usage-percent">{{ facts.source === "estimated" ? "估算 " : "" }}{{ percent }}% 已用</span>
        <strong class="ring-usage" data-testid="context-capacity-value">{{ usageLabel }}</strong>
        <span v-if="facts.state === 'compacting'" class="ring-status">正在压缩上下文…</span>
        <span v-else-if="facts.reason" class="ring-status">{{ facts.reason }}</span>
      </template>
      <template v-else>
        <span v-if="facts.state === 'loading'">正在读取用量…</span>
        <template v-else>
          <span v-if="facts.limitTokens > 0" data-testid="context-capacity-pending">总容量 {{ tokens(facts.limitTokens) }} 标记</span>
          <span class="ring-status">{{ facts.reason ?? "用量未知" }}</span>
        </template>
      </template>
    </div>
  </Teleport>
</template>

<style scoped>
.context-ring { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 30px; padding: 3px; flex: 0 0 auto; border: 0; border-radius: var(--radius-full); background: transparent; cursor: help; }
.context-ring:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.ring-svg { width: 16px; height: 16px; }
.ring-track { stroke: var(--color-border); }
.ring-progress { stroke: var(--color-fg-subtle); transition: stroke-dashoffset var(--pa-motion-standard, 200ms) ease; }
.tone-near .ring-progress { stroke: var(--color-warning); }
.tone-full .ring-progress, .tone-failed .ring-progress { stroke: var(--color-danger); }
.tone-compacting .ring-progress { stroke: var(--color-accent); }
.tone-unavailable .ring-track { stroke-dasharray: 2 3; }
.ring-badge { position: absolute; top: 0; right: -3px; padding: 0 2px; border-radius: var(--radius-full); background: var(--color-surface); color: var(--color-fg-subtle); font-size: 9px; line-height: 11px; white-space: nowrap; }
.tone-full .ring-badge, .tone-failed .ring-badge { color: var(--color-danger); }
.ring-popover { position: fixed; z-index: var(--z-toast); transform: translateY(-100%); display: grid; gap: 4px; padding: 11px 14px; border-radius: var(--radius-lg); background: var(--pa-p-gray-900); color: var(--pa-p-gray-0); box-shadow: var(--shadow-lg); font-size: 13px; line-height: 1.4; text-align: center; pointer-events: none; }
.ring-heading, .ring-percent { opacity: .68; }
.ring-heading { font-size: 13px; font-weight: 600; }
.ring-usage { font-size: 14px; font-weight: 600; }
.ring-status { opacity: .8; overflow-wrap: anywhere; }
@media (prefers-reduced-motion: reduce) { .ring-progress { transition: none; } }
</style>
