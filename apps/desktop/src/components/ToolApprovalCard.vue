<script setup lang="ts">
import { computed } from "vue";
import {
  PhShieldCheck,
  PhCheck,
  PhX,
  PhCircleNotch,
  PhWarning,
  PhFileText,
} from "@phosphor-icons/vue";
import type { ToolCall, ToolCallStatus, RiskLevel } from "../types";

/** 工具调用审批卡片：展示工具/参数/风险/状态，pending 时可批准/拒绝。 */
const props = defineProps<{ toolCall: ToolCall }>();
const emit = defineEmits<{
  approve: [id: number];
  reject: [id: number];
}>();

const statusMeta: Record<ToolCallStatus, { label: string; tone: string }> = {
  pending_approval: { label: "等待审批", tone: "warning" },
  approved: { label: "执行中", tone: "info" },
  running: { label: "执行中", tone: "info" },
  succeeded: { label: "成功", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  rejected: { label: "已拒绝", tone: "muted" },
  cancelled: { label: "已取消", tone: "muted" },
};

const riskMeta: Record<RiskLevel, { label: string; tone: string }> = {
  safe: { label: "安全", tone: "info" },
  confirm: { label: "需审批", tone: "warning" },
  restricted: { label: "受限", tone: "danger" },
};

const status = computed(() => statusMeta[props.toolCall.status]);
const risk = computed(() => riskMeta[props.toolCall.risk_level]);
const isPending = computed(() => props.toolCall.status === "pending_approval");
const isRunning = computed(
  () =>
    props.toolCall.status === "running" || props.toolCall.status === "approved"
);

// read_file 输出摘要
const readFileOutput = computed(() => {
  if (props.toolCall.tool_name !== "read_file") return null;
  const o = props.toolCall.output_json;
  if (!o) return null;
  const content = String(o.content ?? "");
  return {
    path: String(o.path ?? ""),
    size: Number(o.size_bytes ?? 0),
    truncated: Boolean(o.truncated),
    preview: content.slice(0, 300),
    full: content,
    overflow: content.length > 300,
  };
});
</script>

<template>
  <div class="tool-card" :class="`tone-${status.tone}`">
    <div class="card-head">
      <div class="head-left">
        <PhFileText class="tool-icon" :size="16" weight="regular" />
        <span class="tool-name">{{ toolCall.tool_name }}</span>
        <span class="pa-badge" :class="`pa-badge--${risk.tone}`">
          <PhShieldCheck :size="11" weight="bold" />
          {{ risk.label }}
        </span>
      </div>
      <span class="status" :class="`status-${status.tone}`">
        <PhCircleNotch
          v-if="isRunning"
          :size="12"
          weight="bold"
          class="spin"
        />
        {{ status.label }}
      </span>
    </div>

    <!-- 输入参数 -->
    <div v-if="toolCall.input_json" class="card-section">
      <div class="section-label">参数</div>
      <dl class="params">
        <div v-for="(v, k) in toolCall.input_json" :key="k" class="param-row">
          <dt>{{ k }}</dt>
          <dd class="pa-ellipsis" :title="String(v)">{{ v }}</dd>
        </div>
      </dl>
    </div>

    <!-- 成功输出 -->
    <div v-if="readFileOutput" class="card-section">
      <div class="section-label">
        结果 · {{ readFileOutput.size }} 字节<template v-if="readFileOutput.truncated">
          · 已截断</template>
      </div>
      <details class="output-details">
        <summary>查看文件内容</summary>
        <pre class="output-pre">{{ readFileOutput.full }}</pre>
      </details>
    </div>
    <div
      v-else-if="toolCall.output_json && toolCall.status === 'succeeded'"
      class="card-section"
    >
      <div class="section-label">结果</div>
      <pre class="output-pre">{{ JSON.stringify(toolCall.output_json, null, 2) }}</pre>
    </div>

    <!-- 失败错误 -->
    <div v-if="toolCall.error_message && toolCall.status === 'failed'" class="error-box">
      <PhWarning :size="13" weight="bold" />
      <span>{{ toolCall.error_message }}</span>
    </div>

    <!-- 审批按钮 -->
    <div v-if="isPending" class="card-actions">
      <button
        class="pa-btn pa-btn--primary pa-btn--sm"
        :disabled="isRunning"
        @click="emit('approve', toolCall.id)"
      >
        <PhCheck :size="14" weight="bold" />
        <span>批准执行</span>
      </button>
      <button
        class="pa-btn pa-btn--ghost pa-btn--sm"
        :disabled="isRunning"
        @click="emit('reject', toolCall.id)"
      >
        <PhX :size="14" weight="bold" />
        <span>拒绝</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.tool-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-left: 3px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 560px;
}
.tool-card.tone-warning {
  border-left-color: var(--color-warning);
}
.tool-card.tone-success {
  border-left-color: var(--color-success);
}
.tool-card.tone-danger {
  border-left-color: var(--color-danger);
}
.tool-card.tone-info {
  border-left-color: var(--color-accent);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.head-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.tool-icon {
  color: var(--color-fg-muted);
  flex-shrink: 0;
}
.tool-name {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  white-space: nowrap;
  flex-shrink: 0;
}
.status-warning {
  color: var(--color-warning-fg);
}
.status-info {
  color: var(--color-accent-soft-fg);
}
.status-success {
  color: var(--color-success-fg);
}
.status-danger {
  color: var(--color-danger-fg);
}
.status-muted {
  color: var(--color-fg-faint);
}
.spin {
  animation: toolcard-spin 0.9s linear infinite;
}
@keyframes toolcard-spin {
  to {
    transform: rotate(360deg);
  }
}

.card-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.section-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  font-weight: var(--font-medium);
}
.params {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.param-row {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-sm);
  align-items: baseline;
}
.param-row dt {
  color: var(--color-fg-faint);
  margin: 0;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
.param-row dd {
  margin: 0;
  color: var(--color-fg);
  min-width: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.output-details summary {
  cursor: pointer;
  font-size: var(--text-xs);
  color: var(--color-accent-soft-fg);
  user-select: none;
}
.output-pre {
  margin: var(--space-2) 0 0;
  padding: var(--space-2);
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}

.error-box {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
  border-radius: var(--radius);
  padding: var(--space-2);
}

.card-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-1);
}
</style>
