<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { PhArrowCounterClockwise, PhCaretDown, PhLightning } from "@phosphor-icons/vue";

const props = defineProps<{ modelValue: string; modelLabel: string; efforts?: string[] | null; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const root = ref<HTMLElement>();
const trigger = ref<HTMLButtonElement>();
const slider = ref<HTMLInputElement>();
const open = ref(false);
const order = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];
const labels: Record<string, string> = { none: "关闭", minimal: "最低", low: "低", medium: "中", high: "高", xhigh: "最高", max: "最高", ultra: "极高" };
const options = computed(() => {
  const values = [...new Set((props.efforts ?? []).filter(value => value.trim()))];
  values.sort((left, right) => (order.indexOf(left) < 0 ? order.length : order.indexOf(left)) - (order.indexOf(right) < 0 ? order.length : order.indexOf(right)));
  return [{ value: "", label: "默认" }, ...values.map(value => ({ value, label: labels[value] ?? value }))];
});
const index = computed(() => Math.max(0, options.value.findIndex(option => option.value === props.modelValue)));
const currentLabel = computed(() => options.value[index.value].label);
const progress = computed(() => options.value.length > 1 ? index.value / (options.value.length - 1) * 100 : 0);

function close(restoreFocus = false): void {
  open.value = false;
  if (restoreFocus) trigger.value?.focus();
}
async function toggle(): Promise<void> {
  if (props.disabled) return;
  if (open.value) return close();
  open.value = true;
  await nextTick();
  if (open.value) slider.value?.focus();
}
function select(event: Event): void {
  const option = options.value[Number((event.target as HTMLInputElement).value)];
  if (option && !props.disabled) emit("update:modelValue", option.value);
}
async function reset(): Promise<void> {
  emit("update:modelValue", "");
  await nextTick();
  if (open.value) (slider.value ?? trigger.value)?.focus();
}
function outside(event: Event): void {
  if (!root.value?.contains(event.target as Node)) close();
}
function blur(event: FocusEvent): void {
  if (event.relatedTarget && !root.value?.contains(event.relatedTarget as Node)) close();
}
watch(open, value => {
  if (value) window.addEventListener("pointerdown", outside);
  else window.removeEventListener("pointerdown", outside);
});
watch(() => [props.modelLabel, props.efforts, props.disabled], () => close());
onBeforeUnmount(() => window.removeEventListener("pointerdown", outside));
</script>

<template>
  <div ref="root" class="model-strength" @focusout="blur" @keydown.esc.stop.prevent="close(true)">
    <button ref="trigger" type="button" class="strength-trigger" data-testid="composer-effort" :disabled="disabled" :aria-label="`模型强度：${currentLabel}`" aria-haspopup="dialog" :aria-expanded="open" @click="toggle">
      <span>{{ currentLabel }}</span><PhCaretDown :size="12" aria-hidden="true" />
    </button>
    <div v-if="open" class="strength-popover" role="dialog" aria-label="模型强度" data-testid="model-strength-popover">
      <div class="strength-heading">
        <PhLightning :size="19" class="strength-icon" aria-hidden="true" />
        <div class="strength-caption"><strong>{{ currentLabel }}</strong><span :title="modelLabel">{{ modelLabel }}</span></div>
        <button type="button" class="strength-reset" aria-label="恢复默认强度" title="恢复默认强度" :disabled="!modelValue" @click="reset"><PhArrowCounterClockwise :size="18" aria-hidden="true" /></button>
      </div>
      <div v-if="options.length > 1" class="strength-track" :style="{ '--strength-progress': `${progress}%` }">
        <div class="strength-dots" aria-hidden="true"><span v-for="option in options" :key="option.value" /></div>
        <input ref="slider" class="strength-slider" type="range" min="0" :max="options.length - 1" step="1" :value="index" aria-label="模型强度" :aria-valuetext="currentLabel" data-testid="model-strength-slider" @input="select" />
      </div>
      <p v-else class="strength-unavailable">此模型未提供可调节的推理强度。</p>
    </div>
  </div>
</template>

<style scoped>
.model-strength { position: relative; flex: 0 0 auto; }
.strength-trigger { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 30px; padding: 4px; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--color-fg-subtle); font: inherit; font-size: var(--pa-text-body); cursor: pointer; }
.strength-trigger:hover:not(:disabled) { background: var(--color-surface-hover); color: var(--color-fg); }
.strength-trigger:disabled { color: var(--color-fg-disabled); cursor: not-allowed; }
.strength-trigger:focus-visible, .strength-reset:focus-visible, .strength-slider:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.strength-popover { position: absolute; z-index: var(--z-overlay); right: 0; bottom: calc(100% + 12px); width: min(280px, calc(100vw - 32px)); padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-lg); }
.strength-heading { display: flex; gap: var(--space-2); align-items: flex-start; margin-bottom: 14px; }
.strength-icon { flex: 0 0 auto; color: var(--color-fg-subtle); margin-top: 2px; }
.strength-caption { display: grid; flex: 1; min-width: 0; gap: 2px; text-align: center; }
.strength-caption strong { color: var(--color-accent); font-size: var(--text-sm); font-weight: 600; }
.strength-caption span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-fg-subtle); font-size: var(--text-xs); }
.strength-reset { display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; flex: 0 0 auto; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--color-fg-subtle); cursor: pointer; }
.strength-reset:disabled { opacity: .4; cursor: default; }
.strength-reset:hover:not(:disabled) { background: var(--color-surface-hover); }
.strength-track { position: relative; height: 32px; border-radius: var(--radius-full); background: linear-gradient(to right, var(--color-accent) 0%, var(--color-accent) var(--strength-progress), var(--color-surface-sunken) var(--strength-progress), var(--color-surface-sunken) 100%); }
.strength-dots { position: absolute; inset: 0 16px; display: flex; align-items: center; justify-content: space-between; pointer-events: none; }
.strength-dots span { width: 4px; height: 4px; border-radius: 50%; background: var(--color-fg-faint); }
.strength-slider { appearance: none; position: relative; width: 100%; height: 32px; padding: 0; margin: 0; background: transparent; border-radius: inherit; cursor: pointer; }
.strength-slider::-webkit-slider-runnable-track { height: 32px; background: transparent; }
.strength-slider::-webkit-slider-thumb { appearance: none; width: 30px; height: 30px; margin-top: 1px; border: 1px solid var(--color-border); border-radius: 50%; background: var(--color-surface); box-shadow: var(--shadow-sm); }
.strength-slider::-moz-range-thumb { width: 28px; height: 28px; border: 1px solid var(--color-border); border-radius: 50%; background: var(--color-surface); box-shadow: var(--shadow-sm); }
.strength-unavailable { margin: 0; color: var(--color-fg-subtle); font-size: var(--text-xs); line-height: 1.6; }
</style>
