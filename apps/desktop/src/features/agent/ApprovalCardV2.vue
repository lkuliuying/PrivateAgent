<script setup lang="ts">
/**
 * ApprovalCardV2 · 统一审批卡（0.4.0 D3）
 * 同时承载 Runtime AgentRunApproval 与 legacy ToolCall 审批，遵循同一信息层级：
 * 动作 → 对象/范围 → 授权原因 → 风险/可撤销性 → 批准/拒绝/详情。
 * 批准后原位转为「已批准/执行中」，不从活动流消失后异地重现。
 */
import { computed, ref } from "vue";
import {
  PhCheck,
  PhClock,
  PhShieldWarning,
  PhX,
} from "@phosphor-icons/vue";
import type { AgentRunApproval, ToolCall } from "../../types";
import { TOOL_STATUS_META } from "../../models/agentWorkspace";
import PaBadge from "../../design/PaBadge.vue";
import PaButton from "../../design/PaButton.vue";
import PaDisclosure from "../../design/PaDisclosure.vue";
import PaInlineNotice from "../../design/PaInlineNotice.vue";
import PaSpinner from "../../design/PaSpinner.vue";

const props = defineProps<{
  /** Runtime 审批 */
  approval?: AgentRunApproval;
  /** legacy 工具审批 */
  toolCall?: ToolCall;
}>();

const emit = defineEmits<{
  "approve-tool": [id: number];
  "reject-tool": [id: number];
  "approve-agent": [runId: string, approvalId: string];
  "reject-agent": [runId: string, approvalId: string];
}>();

const detailsOpen = ref(false);

const status = computed(() => {
  if (props.approval) return props.approval.status;
  return props.toolCall?.status ?? "unknown";
});

const STATUS_LABEL: Record<string, string> = {
  pending: "等待审批",
  pending_approval: "等待审批",
  approved: "已批准 · 准备执行",
  running: "执行中",
  succeeded: "已完成",
  failed: "执行失败",
  rejected: "已拒绝",
  cancelled: "已取消",
  consumed: "已执行",
  expired: "已过期",
};
const statusLabel = computed(() => STATUS_LABEL[status.value] ?? status.value);

const tone = computed(() => {
  switch (status.value) {
    case "pending":
    case "pending_approval":
    case "approved":
      return "warning" as const;
    case "running":
      return "info" as const;
    case "succeeded":
    case "consumed":
      return "success" as const;
    case "failed":
    case "expired":
    case "cancelled":
      return "danger" as const;
    default:
      return "neutral" as const;
  }
});

const actionName = computed(() => {
  if (props.approval) return props.approval.tool_name;
  if (props.toolCall) return props.toolCall.tool_name;
  return "";
});

/** 人类可读的动作对象/范围 */
const scopeText = computed(() => {
  if (props.toolCall) {
    const input = props.toolCall.input_json ?? {};
    const value = Object.values(input).find(
      (v) => typeof v === "string" && v.trim().length > 0
    );
    return typeof value === "string" ? value : "（见参数详情）";
  }
  return props.approval?.required_capabilities.join(" · ") || "（见参数详情）";
});

const riskLabel = computed(() => {
  const risk = props.approval?.risk_level ?? props.toolCall?.risk_level ?? "safe";
  if (risk === "safe") return "安全 · 只读操作";
  if (risk === "confirm") return "需确认 · 会修改内容";
  return "高风险 · 影响范围较大";
});

const riskTone = computed<"success" | "warning" | "danger">(() => {
  const risk = props.approval?.risk_level ?? props.toolCall?.risk_level ?? "safe";
  if (risk === "safe") return "success";
  if (risk === "confirm") return "warning";
  return "danger";
});

const expiresText = computed(() => {
  if (!props.approval?.expires_at) return "";
  const date = new Date(props.approval.expires_at);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", { hour12: false });
});

const showActions = computed(
  () =>
    status.value === "pending" ||
    status.value === "pending_approval" ||
    status.value === "approved"
);

function approve() {
  if (props.approval) {
    emit("approve-agent", props.approval.run_id, props.approval.id);
  } else if (props.toolCall) {
    emit("approve-tool", props.toolCall.id);
  }
}

function reject() {
  if (props.approval) {
    emit("reject-agent", props.approval.run_id, props.approval.id);
  } else if (props.toolCall) {
    emit("reject-tool", props.toolCall.id);
  }
}
</script>

<template>
  <article class="approval-card" :class="`state-${status}`" data-agent-card>
    <header class="approval-head">
      <div class="approval-title">
        <PhShieldWarning :size="18" weight="fill" class="approval-icon" />
        <div class="approval-title-copy">
          <strong>授权请求</strong>
          <code class="approval-action">{{ actionName }}</code>
        </div>
      </div>
      <PaBadge :tone="tone">
        <span class="approval-status">
          <PaSpinner v-if="status === 'running'" :size="10" :label="statusLabel" />
          <PhClock v-else-if="status === 'pending' || status === 'pending_approval'" :size="11" />
          <PhCheck v-else-if="status === 'succeeded' || status === 'consumed'" :size="11" />
          <PhX v-else-if="status === 'rejected' || status === 'cancelled'" :size="11" />
          {{ statusLabel }}
        </span>
      </PaBadge>
    </header>

    <p class="approval-reason">
      Agent 准备执行 {{ actionName }}，作用于：<code class="approval-scope">{{ scopeText }}</code>。
      授权用于本次执行；范围外的读写仍需逐次确认。
    </p>

    <dl class="approval-meta">
      <div>
        <dt>风险等级</dt>
        <dd><PaBadge :tone="riskTone">{{ riskLabel }}</PaBadge></dd>
      </div>
      <div v-if="props.approval">
        <dt>参数指纹</dt>
        <dd><code>{{ props.approval.arguments_sha256.slice(0, 16) }}…</code></dd>
      </div>
      <div v-if="expiresText">
        <dt>审批过期</dt>
        <dd>{{ expiresText }}</dd>
      </div>
    </dl>

    <PaDisclosure
      v-if="props.toolCall"
      v-model:open="detailsOpen"
      title="查看参数与结果"
      :summary="TOOL_STATUS_META[props.toolCall.status]?.label"
    >
      <pre class="approval-json">{{
        JSON.stringify(props.toolCall.input_json, null, 2) ||
          JSON.stringify(props.toolCall.output_json, null, 2)
      }}</pre>
    </PaDisclosure>

    <div v-if="showActions" class="approval-actions">
      <PaButton variant="primary" size="sm" @click="approve">
        <PhCheck :size="14" weight="bold" /> 批准执行
      </PaButton>
      <PaButton variant="ghost" size="sm" @click="reject">
        <PhX :size="14" weight="bold" /> 拒绝
      </PaButton>
    </div>

    <PaInlineNotice v-if="status === 'expired'" tone="warning" title="审批已过期">
      本次请求已过期，未执行任何操作。可以让 Agent 重新发起。
    </PaInlineNotice>
    <PaInlineNotice v-else-if="status === 'cancelled'" tone="warning" title="请求已取消">
      该请求已被取消，未执行任何操作。
    </PaInlineNotice>
    <PaInlineNotice v-else-if="status === 'failed'" tone="danger" title="执行失败">
      {{ toolCall?.error_message || "工具执行未完成，可重试或查看诊断。" }}
    </PaInlineNotice>
  </article>
</template>

<style scoped>
.approval-card {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--pa-approval-border);
  border-left: 3px solid var(--color-warning);
  border-radius: var(--radius-md);
  background: var(--pa-approval-bg);
}
.approval-card.state-running {
  border-left-color: var(--color-accent);
}
.approval-card.state-succeeded,
.approval-card.state-consumed {
  border-left-color: var(--color-success);
}
.approval-card.state-rejected,
.approval-card.state-cancelled,
.approval-card.state-expired,
.approval-card.state-failed {
  border-left-color: var(--color-danger);
}
.approval-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.approval-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-warning);
}
.approval-title-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.approval-title strong {
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
}
.approval-action {
  overflow: hidden;
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.approval-status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
.approval-reason {
  margin: 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  line-height: var(--leading-normal);
}
.approval-scope {
  overflow-wrap: anywhere;
  color: var(--color-fg);
}
.approval-meta {
  display: grid;
  margin: 0;
  gap: var(--space-1);
}
.approval-meta > div {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: var(--space-2);
  font-size: var(--pa-t-12);
}
.approval-meta dt {
  color: var(--color-fg-faint);
}
.approval-meta dd {
  margin: 0;
  color: var(--color-fg-muted);
  overflow-wrap: anywhere;
}
.approval-json {
  margin: var(--space-2) 0 0;
  max-height: 220px;
  overflow: auto;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  line-height: 1.5;
  white-space: pre-wrap;
}
.approval-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
