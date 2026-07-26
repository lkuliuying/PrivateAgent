<script setup lang="ts">
const props = defineProps<{ error?: Error }>();

function reload() {
  window.location.reload();
}
</script>

<template>
  <section
    class="async-workspace"
    :class="{ 'is-error': props.error }"
    :role="props.error ? 'alert' : 'status'"
    :aria-live="props.error ? 'assertive' : 'polite'"
    :aria-busy="props.error ? undefined : 'true'"
  >
    <div class="async-mark" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
    <div class="async-copy">
      <strong>{{ props.error ? "工作区加载失败" : "正在准备工作区" }}</strong>
      <p>
        {{
          props.error
            ? "本地资源暂时不可用，重新加载后可继续当前工作。"
            : "正在装配视图、状态与本地能力…"
        }}
      </p>
    </div>
    <button
      v-if="props.error"
      class="pa-btn pa-btn--primary"
      type="button"
      @click="reload"
    >
      重新加载工作区
    </button>
    <div v-else class="async-skeleton" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  </section>
</template>

<style scoped>
.async-workspace {
  position: relative;
  flex: 1;
  align-self: stretch;
  min-width: 0;
  min-height: 280px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: var(--space-3);
  padding: var(--space-8);
  overflow: hidden;
  color: var(--color-fg-subtle);
  text-align: center;
  background:
    radial-gradient(circle at 50% 44%, color-mix(in srgb, var(--color-accent) 8%, transparent), transparent 30%),
    var(--color-bg);
}
.async-workspace::before {
  content: "";
  position: absolute;
  width: min(520px, 72%);
  height: 1px;
  top: calc(50% - 86px);
  background: linear-gradient(90deg, transparent, var(--color-border-strong), transparent);
}
.async-mark {
  width: 54px;
  height: 54px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px solid var(--color-border);
  border-radius: 18px;
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}
.async-mark span {
  width: 4px;
  height: 18px;
  border-radius: var(--radius-full);
  background: var(--color-accent);
  animation: async-pulse 900ms var(--ease-out) infinite alternate;
}
.async-mark span:nth-child(2) { animation-delay: 120ms; }
.async-mark span:nth-child(3) { animation-delay: 240ms; }
.async-copy { display: grid; gap: var(--space-1); }
.async-copy strong { color: var(--color-fg); font-size: var(--text-base); }
.async-copy p { max-width: 420px; margin: 0; font-size: var(--text-sm); line-height: 1.6; }
.async-skeleton {
  width: min(360px, 70vw);
  display: grid;
  gap: 7px;
}
.async-skeleton span {
  height: 7px;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--color-surface-sunken), var(--color-border), var(--color-surface-sunken));
  background-size: 220% 100%;
  animation: async-shimmer 1.35s linear infinite;
}
.async-skeleton span:nth-child(2) { width: 82%; }
.async-skeleton span:nth-child(3) { width: 58%; }
.async-workspace.is-error .async-mark span {
  height: 4px;
  animation: none;
  background: var(--color-danger-fg);
}
@keyframes async-pulse {
  from { transform: scaleY(.45); opacity: .45; }
  to { transform: scaleY(1); opacity: 1; }
}
@keyframes async-shimmer {
  to { background-position: -220% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .async-mark span,
  .async-skeleton span { animation: none; }
}
</style>
