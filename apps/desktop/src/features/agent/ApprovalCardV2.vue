<script setup lang="ts">
/**
 * ApprovalCardV2 · 统一审批卡（0.4.0 D3）
 * 同时承载 Runtime AgentRunApproval 与 legacy ToolCall 审批，遵循同一信息层级：
 * 动作 → 对象/范围 → 授权原因 → 风险/可撤销性 → 批准/拒绝/详情。
 * 批准后原位转为「已批准/执行中」，不从活动流消失后异地重现。
 */
import { computed, onUnmounted, ref, watch } from "vue";
import {
  PhCheck,
  PhClock,
  PhDatabase,
  PhFilePlus,
  PhShieldWarning,
  PhTerminal,
  PhX,
} from "@phosphor-icons/vue";
import type {
  AgentApprovalPreview,
  AgentRunApproval,
  AgentToolExecution,
  AgentToolOutputLine,
  ToolCall,
} from "../../types";
import {
  getAgentApprovalPreview,
  getAgentToolOutput,
  listAgentRunExecutions,
} from "../../api/agentRuns";
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

/**
 * v0.5.0 B1：文件变更类工具（apply_patch_to_workspace / propose_patch）在审批时
 * 加载只读 diff 预览。预览失败或不可预览时静默降级，不阻塞审批。
 */
const PATCH_TOOLS = new Set(["apply_patch_to_workspace", "propose_patch"]);
const preview = ref<AgentApprovalPreview | null>(null);
const previewLoading = ref(false);
let previewRequest = 0;

watch(
  () => [props.approval?.id, props.approval?.status, props.approval?.tool_name],
  async ([approvalId, approvalStatus, toolName]) => {
    preview.value = null;
    const isPatchTool = typeof toolName === "string" && PATCH_TOOLS.has(toolName);
    if (
      !isPatchTool ||
      !approvalId ||
      !props.approval ||
      approvalStatus !== "pending"
    ) {
      return;
    }
    const requestId = ++previewRequest;
    previewLoading.value = true;
    try {
      const result = await getAgentApprovalPreview(
        props.approval.run_id,
        approvalId
      );
      if (requestId === previewRequest) preview.value = result;
    } catch {
      if (requestId === previewRequest) {
        preview.value = {
          tool_name: String(toolName),
          previewable: false,
          rel_path: null,
          creates_file: null,
          old_sha256: null,
          new_sha256: null,
          diff: null,
          truncated: null,
          reason: "无法加载变更预览",
        };
      }
    } finally {
      if (requestId === previewRequest) previewLoading.value = false;
    }
  },
  { immediate: true }
);

onUnmounted(() => {
  previewRequest += 1;
});

/**
 * v0.5.0 B2：命令工具的实时输出——审批通过/执行中时轮询已脱敏的流式行
 * （executions + tool_execution_output），展示 argv/cwd/退出码/进程树清理结果。
 */
const isCommandTool = computed(
  () => props.approval?.tool_name === "run_whitelisted_command"
);
const commandExec = ref<AgentToolExecution | null>(null);
const outputLines = ref<AgentToolOutputLine[]>([]);
const outputLastSeq = ref(-1);
const outputFinished = ref(false);
const outputError = ref("");
let outputTimer: ReturnType<typeof setTimeout> | null = null;

function stopOutputPolling() {
  if (outputTimer !== null) {
    clearTimeout(outputTimer);
    outputTimer = null;
  }
}

async function pollCommandOutput() {
  if (!props.approval) return;
  const runId = props.approval.run_id;
  try {
    if (!commandExec.value) {
      const executions = await listAgentRunExecutions(runId);
      const candidates = executions.filter(
        (execution) => execution.tool_name === "run_whitelisted_command"
      );
      if (!candidates.length) return;
      const running = candidates.find((execution) => execution.status === "running");
      commandExec.value = running ?? candidates[candidates.length - 1];
    }
    const page = await getAgentToolOutput(
      runId,
      commandExec.value.id,
      outputLastSeq.value
    );
    if (page.lines.length) {
      outputLines.value.push(...page.lines);
      outputLastSeq.value = page.last_seq;
    }
    outputFinished.value = page.finished;
    if (!page.finished) {
      outputTimer = setTimeout(pollCommandOutput, 600);
    }
  } catch {
    outputError.value = "无法加载命令输出";
  }
}

function resetCommandOutput() {
  commandExec.value = null;
  outputLines.value = [];
  outputLastSeq.value = -1;
  outputFinished.value = false;
  outputError.value = "";
  stopOutputPolling();
}

watch(
  () => [props.approval?.id, props.approval?.status],
  ([, status]) => {
    resetCommandOutput();
    if (
      isCommandTool.value &&
      props.approval &&
      (status === "approved" || status === "consumed")
    ) {
      void pollCommandOutput();
    }
  },
  { immediate: true }
);

onUnmounted(() => {
  previewRequest += 1;
  stopOutputPolling();
});

const commandExitMeta = computed(() => {
  const output = commandExec.value?.output ?? {};
  const returncode = output.returncode;
  const succeeded = output.succeeded === true;
  const remaining = output.processes_remaining;
  return { returncode, succeeded, remaining };
});

const commandArgv = computed(() => {
  const args = commandExec.value?.output?.args;
  return Array.isArray(args) ? args.join(" ") : props.approval?.tool_name ?? "";
});

/**
 * v0.5.0 B4：只读 SQL 查询结果表格（已脱敏列/有界行；executions output 事实源）。
 */
const isSqlTool = computed(
  () => props.approval?.tool_name === "query_readonly_sql"
);
const sqlExec = ref<AgentToolExecution | null>(null);
let sqlTimer: ReturnType<typeof setTimeout> | null = null;

function stopSqlPolling() {
  if (sqlTimer !== null) {
    clearTimeout(sqlTimer);
    sqlTimer = null;
  }
}

async function pollSqlResult() {
  if (!props.approval) return;
  try {
    if (!sqlExec.value) {
      const executions = await listAgentRunExecutions(props.approval.run_id);
      const candidates = executions.filter(
        (execution) => execution.tool_name === "query_readonly_sql"
      );
      if (!candidates.length) return;
      const running = candidates.find((execution) => execution.status === "running");
      sqlExec.value = running ?? candidates[candidates.length - 1];
    }
    if (["succeeded", "failed", "timed_out", "cancelled"].includes(sqlExec.value.status)) {
      return;
    }
    sqlTimer = setTimeout(pollSqlResult, 600);
  } catch {
    // 静默降级：结果缺失不影响审批流程
  }
}

function resetSqlResult() {
  sqlExec.value = null;
  stopSqlPolling();
}

watch(
  () => [props.approval?.id, props.approval?.status],
  ([, status]) => {
    resetSqlResult();
    if (isSqlTool.value && props.approval && (status === "approved" || status === "consumed")) {
      void pollSqlResult();
    }
  },
  { immediate: true }
);

const sqlResultTable = computed(() => {
  const output = sqlExec.value?.output ?? {};
  const columns = Array.isArray(output.columns) ? (output.columns as string[]) : [];
  const rows = Array.isArray(output.rows) ? (output.rows as unknown[][]) : [];
  return {
    columns,
    rows,
    rowCount: typeof output.row_count === "number" ? output.row_count : rows.length,
    truncated: output.truncated === true,
    readOnly: output.read_only_confirmed === true,
  };
});

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

    <!-- v0.5.0 B1：文件变更预览（审批时展示，基于磁盘事实只读重算） -->
    <section
      v-if="previewLoading"
      class="preview-section"
      aria-label="正在生成变更预览"
    >
      <PaSpinner :size="12" label="生成中" /> 正在生成变更预览…
    </section>
    <section
      v-else-if="preview?.previewable && preview.diff != null"
      class="preview-section"
      aria-label="文件变更预览"
    >
      <header class="preview-head">
        <strong>变更预览</strong>
        <span class="preview-file">{{ preview.rel_path }}</span>
        <PaBadge v-if="preview.creates_file" tone="info">
          <PhFilePlus :size="11" /> 新建文件
        </PaBadge>
      </header>
      <dl class="preview-sha">
        <div><dt>旧 SHA</dt><dd><code>{{ preview.old_sha256?.slice(0, 12) }}…</code></dd></div>
        <div><dt>新 SHA</dt><dd><code>{{ preview.new_sha256?.slice(0, 12) }}…</code></dd></div>
      </dl>
      <pre class="preview-diff">{{ preview.diff }}</pre>
      <PaInlineNotice
        v-if="preview.truncated"
        tone="warning"
        title="预览已被截断"
      >
        预览内容不完整；批准后只会应用本次审批绑定参数的原始内容，不会直接应用截断视图。
      </PaInlineNotice>
    </section>
    <PaInlineNotice
      v-else-if="preview && !preview.previewable && approval?.tool_name"
      tone="info"
      :title="`无法预览（${approval.tool_name}）`"
    >
      {{ preview.reason || "该工具不产生文件变更预览，可查看参数指纹后决定。" }}
    </PaInlineNotice>

    <!-- v0.5.0 B2：命令实时输出（已脱敏流式行 + 退出码/进程树清理证据） -->
    <section
      v-if="isCommandTool && commandExec && (outputLines.length || outputError)"
      class="command-section"
      aria-label="命令实时输出"
    >
      <header class="command-head">
        <PhTerminal :size="14" />
        <code class="command-argv">{{ commandArgv }}</code>
        <PaBadge v-if="outputFinished" :tone="commandExitMeta.succeeded ? 'success' : 'danger'">
          <PhCheck v-if="commandExitMeta.succeeded" :size="11" />
          <PhX v-else :size="11" />
          {{ commandExitMeta.succeeded ? "成功" : `退出码 ${commandExitMeta.returncode ?? "?"}` }}
        </PaBadge>
        <PaBadge v-else tone="info"><PhClock :size="11" /> 执行中</PaBadge>
      </header>
      <p class="command-meta">
        <code>{{ commandExec.output?.cwd ?? "" }}</code>
        <template v-if="commandExitMeta.remaining != null">
          · 进程树残留 {{ commandExitMeta.remaining }}
        </template>
      </p>
      <pre class="command-output" data-testid="command-output">{{
        outputError || outputLines.map((line) => line.text).join("\n")
      }}</pre>
    </section>

    <!-- v0.5.0 B4：只读 SQL 查询结果（脱敏列/有界行表格） -->
    <section
      v-if="isSqlTool && sqlExec && sqlResultTable.columns.length"
      class="sql-section"
      aria-label="只读查询结果"
    >
      <header class="sql-head">
        <PaBadge tone="info">
          <PhDatabase :size="11" />
          {{ sqlResultTable.readOnly ? "只读事务" : "未确认" }}
        </PaBadge>
        <span class="sql-meta">
          {{ sqlResultTable.rowCount }} 行
          <template v-if="sqlResultTable.truncated">（已截断）</template>
        </span>
      </header>
      <div class="sql-table-wrap">
        <table class="sql-table" data-testid="sql-result-table">
          <thead>
            <tr>
              <th v-for="column in sqlResultTable.columns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in sqlResultTable.rows" :key="index">
              <td v-for="(value, cell) in row" :key="cell">{{ String(value) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

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
.preview-section {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-sunken);
}
.preview-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
  font-size: var(--pa-t-12);
}
.preview-head strong {
  color: var(--color-fg);
  font-weight: var(--font-semibold);
}
.preview-file {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.preview-sha {
  display: grid;
  margin: 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
  font-size: var(--pa-t-12);
}
.preview-sha dt {
  color: var(--color-fg-faint);
}
.preview-sha dd {
  margin: 0;
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
}
.preview-diff {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  line-height: 1.55;
  white-space: pre;
}
.command-section {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-sunken);
}
.command-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
  font-size: var(--pa-t-12);
}
.command-argv {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--color-fg);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.command-meta {
  margin: 0;
  color: var(--color-fg-faint);
  font-size: var(--pa-t-12);
  overflow-wrap: anywhere;
}
.command-output {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  line-height: 1.5;
  white-space: pre-wrap;
}
.sql-section {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-sunken);
}
.sql-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.sql-meta {
  color: var(--color-fg-faint);
  font-size: var(--pa-t-12);
}
.sql-table-wrap {
  max-height: 220px;
  overflow: auto;
  border-radius: var(--radius-sm);
}
.sql-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--color-surface);
  font-size: var(--pa-t-12);
}
.sql-table th,
.sql-table td {
  max-width: 220px;
  overflow: hidden;
  padding: 4px 8px;
  border: 1px solid var(--color-border);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sql-table th {
  position: sticky;
  top: 0;
  background: var(--color-surface-muted);
  color: var(--color-fg);
  font-weight: var(--font-semibold);
}
</style>
