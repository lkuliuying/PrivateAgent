<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

const tooltipId = "pa-button-tooltip";
const selector = 'button, [role="button"], [role="tab"], [role="menuitem"], [role="switch"], summary, select, input[type="button"], input[type="submit"], input[type="reset"], [data-tooltip]';
const text = ref("");
const position = ref({ left: "0px", top: "0px" });
const tooltip = ref<HTMLElement | null>(null);
let target: HTMLElement | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let observer: MutationObserver | undefined;
let generation = 0;

function hintFor(element: HTMLElement): string {
  // 原生 title 和已有的专用提示继续生效，避免出现两层说明。
  if (element.closest(".pa-tooltip") || element.closest("[title]")?.getAttribute("title")?.trim()) return "";
  const descriptions = element.getAttribute("aria-describedby")?.split(/\s+/) ?? [];
  if (descriptions.some(id => id !== tooltipId && document.getElementById(id)?.getAttribute("role") === "tooltip")) return "";
  const labelledBy = element.getAttribute("aria-labelledby")?.split(/\s+/)
    .map(id => document.getElementById(id)?.textContent ?? "").join(" ");
  let label = element.getAttribute("data-tooltip") || labelledBy || element.getAttribute("aria-label");
  if (!label) {
    if (element instanceof HTMLInputElement) label = element.value;
    else if (element instanceof HTMLSelectElement) label = Array.from(element.labels ?? []).map(item => item.textContent).join(" ");
    else {
      const copy = element.cloneNode(true) as HTMLElement;
      copy.querySelectorAll('svg, [aria-hidden="true"], kbd').forEach(node => node.remove());
      label = copy.textContent;
    }
  }
  const cleaned = label?.replace(/\s+/g, " ").trim() ?? "";
  if (!cleaned) return "";
  const disabled = element.matches(":disabled") || element.getAttribute("aria-disabled") === "true";
  return `${cleaned}${disabled ? "（当前不可用）" : ""}`;
}

function clear(): void {
  generation++;
  clearTimeout(timer);
  timer = undefined;
  observer?.disconnect();
  observer = undefined;
  if (target) {
    const ids = (target.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(id => id && id !== tooltipId);
    if (ids.length) target.setAttribute("aria-describedby", ids.join(" "));
    else target.removeAttribute("aria-describedby");
  }
  target = null;
  text.value = "";
}

async function show(element: HTMLElement, mine: number): Promise<void> {
  if (mine !== generation) return;
  if (!element.isConnected || element.closest('[hidden], [aria-hidden="true"]')) return clear();
  const hint = hintFor(element);
  if (!hint) return clear();
  text.value = hint;
  await nextTick();
  if (mine !== generation || !tooltip.value || !element.isConnected) return;
  const anchor = element.getBoundingClientRect();
  const size = tooltip.value.getBoundingClientRect();
  const margin = 8;
  const left = Math.max(margin, Math.min(anchor.left + (anchor.width - size.width) / 2, window.innerWidth - size.width - margin));
  const top = anchor.top >= size.height + margin * 2
    ? anchor.top - size.height - margin
    : Math.min(anchor.bottom + margin, window.innerHeight - size.height - margin);
  position.value = { left: `${left}px`, top: `${Math.max(margin, top)}px` };
  const ids = new Set((element.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean));
  ids.add(tooltipId);
  element.setAttribute("aria-describedby", [...ids].join(" "));
}

function enter(event: Event): void {
  if (typeof PointerEvent !== "undefined" && event instanceof PointerEvent && event.pointerType === "touch") return;
  const element = event.target instanceof Element ? event.target.closest<HTMLElement>(selector) : null;
  if (element === target) return;
  clear();
  if (!element || !hintFor(element)) return;
  target = element;
  const mine = generation;
  timer = setTimeout(() => { timer = undefined; void show(element, mine); }, 350);
  // 只在提示候选存在时观察，处理菜单卸载和按钮状态变化；不扫描整棵页面。
  observer = new MutationObserver(records => {
    if (!element.isConnected || element.closest('[hidden], [aria-hidden="true"]')) return clear();
    if (text.value && records.some(record => element.contains(record.target))) void show(element, mine);
  });
  observer.observe(document.body, { childList: true, subtree: true });
  observer.observe(element, {
    attributes: true, attributeFilter: ["aria-label", "aria-labelledby", "data-tooltip", "title", "disabled", "aria-disabled", "hidden"],
    childList: true, characterData: true, subtree: true,
  });
}

function leave(event: Event): void {
  if (!target) return;
  const next = (event as FocusEvent | PointerEvent).relatedTarget;
  if (!(next instanceof Node) || !target.contains(next)) clear();
}

function keydown(event: KeyboardEvent): void {
  if (event.key === "Escape") clear();
}

onMounted(() => {
  document.addEventListener("pointerover", enter, true);
  document.addEventListener("pointerout", leave, true);
  document.addEventListener("focusin", enter, true);
  document.addEventListener("focusout", leave, true);
  document.addEventListener("pointerdown", clear, true);
  document.addEventListener("keydown", keydown, true);
  document.addEventListener("scroll", clear, true);
  window.addEventListener("resize", clear);
  window.addEventListener("blur", clear);
});

onBeforeUnmount(() => {
  clear();
  document.removeEventListener("pointerover", enter, true);
  document.removeEventListener("pointerout", leave, true);
  document.removeEventListener("focusin", enter, true);
  document.removeEventListener("focusout", leave, true);
  document.removeEventListener("pointerdown", clear, true);
  document.removeEventListener("keydown", keydown, true);
  document.removeEventListener("scroll", clear, true);
  window.removeEventListener("resize", clear);
  window.removeEventListener("blur", clear);
});
</script>

<template>
  <Teleport to="body">
    <div v-if="text" :id="tooltipId" ref="tooltip" class="pa-button-tooltip" role="tooltip" :style="position">{{ text }}</div>
  </Teleport>
</template>

<style scoped>
.pa-button-tooltip {
  position: fixed;
  z-index: calc(var(--z-toast) + 1);
  width: max-content;
  max-width: min(320px, calc(100vw - 16px));
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-fg);
  color: var(--color-surface);
  box-shadow: var(--shadow-sm);
  font-size: var(--pa-text-meta);
  line-height: 1.5;
  overflow-wrap: anywhere;
  pointer-events: none;
}
</style>
