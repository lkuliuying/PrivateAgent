<script setup lang="ts">
import { computed } from "vue";
import { PhCheck, PhShieldWarning, PhX } from "@phosphor-icons/vue";
import type { AgentRunApproval } from "../types";

const props = defineProps<{ approval: AgentRunApproval }>();
const emit = defineEmits<{
  approve: [runId: string, approvalId: string];
  reject: [runId: string, approvalId: string];
}>();

const pending = computed(() => props.approval.status === "pending");
const statusLabel = computed(() => ({
  pending: "等待审批",
  approved: "已批准，正在恢复",
  rejected: "已拒绝",
  consumed: "已执行",
  expired: "已过期",
  cancelled: "已取消",
}[props.approval.status]));
</script>

<template>
  <div class="approval-card" data-agent-card>
    <div class="approval-head">
      <div class="approval-title">
        <PhShieldWarning :size="18" weight="fill" />
        <div>
          <strong>外部 MCP 工具请求</strong>
          <code>{{ approval.tool_name }}@{{ approval.tool_version }}</code>
        </div>
      </div>
      <span :class="`status ${approval.status}`">{{ statusLabel }}</span>
    </div>
    <p>
      此调用来自显式白名单，但仍被按高风险外部能力逐次拦截。Server 返回内容不会改变本次权限。
    </p>
    <dl>
      <div>
        <dt>权限</dt>
        <dd>{{ approval.required_capabilities.join(" · ") || "无额外权限" }}</dd>
      </div>
      <div>
        <dt>参数指纹</dt>
        <dd><code>{{ approval.arguments_sha256.slice(0, 16) }}…</code></dd>
      </div>
      <div>
        <dt>审批过期</dt>
        <dd>{{ new Date(approval.expires_at).toLocaleString() }}</dd>
      </div>
    </dl>
    <div v-if="pending" class="approval-actions">
      <button
        class="approve"
        @click="emit('approve', approval.run_id, approval.id)"
      >
        <PhCheck :size="14" weight="bold" /> 批准一次
      </button>
      <button
        class="reject"
        @click="emit('reject', approval.run_id, approval.id)"
      >
        <PhX :size="14" weight="bold" /> 拒绝并终止
      </button>
    </div>
  </div>
</template>

<style scoped>
.approval-card { display: grid; gap: 12px; padding: 15px; border: 1px solid color-mix(in srgb, var(--color-warning) 46%, var(--color-border)); border-left: 3px solid var(--color-warning); border-radius: var(--radius-md); background: var(--color-surface); }
.approval-head, .approval-title, .approval-actions { display: flex; align-items: center; gap: 10px; }
.approval-head { justify-content: space-between; }
.approval-title { color: var(--color-warning); }
.approval-title > div { display: grid; gap: 2px; }
.approval-title strong { color: var(--color-fg); font-size: 13px; }
.approval-title code { color: var(--color-fg-muted); font-size: 10px; }
.status { padding: 3px 8px; border-radius: 999px; color: var(--color-fg-muted); background: var(--color-surface-muted); font-size: 10px; }
.status.pending, .status.approved { color: var(--color-warning); background: color-mix(in srgb, var(--color-warning) 12%, transparent); }
.status.consumed { color: var(--color-success-fg); }
p { margin: 0; color: var(--color-fg-muted); font-size: 12px; line-height: 1.55; }
dl { display: grid; gap: 7px; margin: 0; }
dl > div { display: grid; grid-template-columns: 74px minmax(0, 1fr); gap: 8px; font-size: 11px; }
dt { color: var(--color-fg-faint); }
dd { margin: 0; color: var(--color-fg-muted); overflow-wrap: anywhere; }
.approval-actions { justify-content: flex-end; }
button { display: inline-flex; align-items: center; gap: 5px; padding: 7px 10px; border-radius: 8px; cursor: pointer; font: inherit; font-size: 11px; }
button.approve { border: 0; color: white; background: var(--color-accent); }
button.reject { border: 1px solid var(--color-border); color: var(--color-fg); background: transparent; }
</style>
