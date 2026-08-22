<script setup lang="ts">
/**
 * ContextUsageMeter · v0.8.0 W6-R3
 *
 * 上下文用量模块：只呈现公开 usage（used/limit token 数值与百分比）与
 * 压缩状态；数值来自 ContextUsageFacts（run 快照 + 公开配置上限），
 * 绝不按字符数/消息数估算。状态：读取中 / 不可用 / 正常 / 接近阈值 /
 * 已满（100% 钳制）；压缩状态未就绪时如实提示。
 */
import { computed } from "vue";
import type { ContextUsageFacts } from "./model/contextUsage";
import { contextUsageLabel } from "./model/contextUsage";

const props = defineProps<{
  facts: ContextUsageFacts;
}>();

const label = computed(() => contextUsageLabel(props.facts));

const barPercent = computed(() => {
  if (props.facts.state !== "ready" || props.facts.percentage === null) return 0;
  return Math.min(100, Math.max(0, props.facts.percentage));
});

const toneClass = computed(() => {
  if (props.facts.state !== "ready") return "tone-muted";
  switch (props.facts.threshold) {
    case "full":
      return "tone-danger";
    case "near":
      return "tone-warning";
    default:
      return "tone-ok";
  }
});

const compressionHint = computed(() => {
  const compression = props.facts.compression;
  switch (compression.kind) {
    case "unsupported":
      return "自动压缩：未就绪（后端未公开压缩状态）";
    case "idle":
      return "自动压缩：待触发";
    case "compressing":
      return "自动压缩：压缩中";
    case "compressed":
      return `自动压缩：已完成（${compression.detail}）`;
    case "failed":
      return compression.retryable ? "自动压缩：失败，可重试" : "自动压缩：失败";
  }
});
</script>

<template>
  <div
    class="usage-meter"
    :class="toneClass"
    data-testid="context-usage-meter"
    :title="`${label} · ${compressionHint}`"
    :aria-label="`上下文用量：${label}`"
    role="status"
  >
    <span class="usage-label">{{ label }}</span>
    <span class="usage-bar" aria-hidden="true">
      <span class="usage-bar-fill" :style="{ width: `${barPercent}%` }" />
    </span>
    <span class="usage-compression" data-testid="context-usage-compression">
      {{
        facts.compression.kind === "unsupported"
          ? "压缩未就绪"
          : facts.compression.kind === "compressing"
            ? "压缩中…"
            : facts.compression.kind === "compressed"
              ? "已压缩"
              : facts.compression.kind === "failed"
                ? "压缩失败"
                : ""
      }}
    </span>
  </div>
</template>

<style scoped>
.usage-meter {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 34px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  white-space: nowrap;
}
.usage-bar {
  display: inline-block;
  width: 56px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  overflow: hidden;
}
.usage-bar-fill {
  display: block;
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--color-success);
  transition: width var(--pa-motion-standard) var(--ease);
}
.tone-warning .usage-bar-fill {
  background: var(--color-warning);
}
.tone-warning .usage-label {
  color: var(--color-warning-fg);
}
.tone-danger .usage-bar-fill {
  background: var(--color-danger);
}
.tone-danger .usage-label {
  color: var(--color-danger-fg);
}
.tone-muted .usage-label {
  color: var(--color-fg-subtle);
}
.usage-compression:empty {
  display: none;
}
.usage-compression {
  color: var(--color-fg-subtle);
}
@media (max-width: 760px) {
  .usage-bar,
  .usage-compression {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .usage-bar-fill {
    transition: none;
  }
}
</style>
