<script setup lang="ts">
/**
 * RunTranscript · v0.8.0 W2
 *
 * 文档式活动流：用户请求 → 运行/上下文 → 模型轮次 → 计划摘要 → 工具卡 →
 * 审批卡 → 验证 → 变更集/产出 → 终态摘要（最终输出按安全 Markdown 渲染）。
 * 工具活动默认摘要折叠；新活动自动跟随（离开底部时出现「查看新活动」）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  PhArrowCircleDown,
  PhCheckCircle,
  PhCircleNotch,
  PhClipboardText,
  PhClock,
  PhFilePlus,
  PhGitDiff,
  PhLightning,
  PhPath,
  PhProhibit,
  PhShieldWarning,
  PhUser,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { TranscriptEntry, RunProjection } from "../model/runProjector";
import type { Message } from "../../../types";
import type {
  RunApprovalPreviewRecord,
  RunApprovalRecord,
  RunConnectionPhase,
  RunExecutionOutputPage,
  RunExecutionRecord,
} from "../model/runContracts";
import { RUN_STATUS_META } from "../model/runContracts";
import { redactCommandArgs, redactSecretText } from "../model/redaction";
import DiffArtifact from "./DiffArtifact.vue";
import CommandOutput from "./CommandOutput.vue";
import MarkdownContent from "./MarkdownContent.vue";

const props = withDefaults(
  defineProps<{
    projection: RunProjection | null;
    history?: Message[];
    phase?: RunConnectionPhase;
    connectionError?: string | null;
    approvals?: RunApprovalRecord[];
    /** W3：审批影响范围预览（父层按需加载；键为 approvalId） */
    approvalPreviews?: Record<string, RunApprovalPreviewRecord | null>;
    previewLoading?: string[];
    /** W3：工具执行结果（键为 toolCallId，按工具名+完成顺序关联） */
    executionByTool?: Record<string, RunExecutionRecord>;
    /** W6-R：全量执行记录（重试计数/公开时序事实源） */
    executions?: RunExecutionRecord[];
    /** W3：流式输出页（键为 executionId） */
    outputPages?: Record<string, RunExecutionOutputPage | null>;
    outputLoading?: string[];
    previewMode?: boolean;
  }>(),
  {
    phase: "idle" as RunConnectionPhase,
    history: () => [],
    connectionError: null,
    approvals: () => [],
    approvalPreviews: () => ({}),
    previewLoading: () => [],
    executionByTool: () => ({}),
    executions: () => [],
    outputPages: () => ({}),
    outputLoading: () => [],
    previewMode: false,
  }
);

const emit = defineEmits<{
  approve: [approvalId: string];
  reject: [approvalId: string];
  "open-plan": [];
  "retry-stream": [];
  "load-output": [executionId: string];
}>();

const TOOL_STATE_LABEL: Record<string, { label: string; tone: string }> = {
  requested: { label: "已请求", tone: "neutral" },
  started: { label: "执行中", tone: "info" },
  approval_required: { label: "等待审批", tone: "warning" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
};

const PATCH_STATE_LABEL: Record<string, { label: string; tone: string }> = {
  previewed: { label: "已预览", tone: "info" },
  applied: { label: "已应用", tone: "success" },
  rolled_back: { label: "已回滚", tone: "neutral" },
  failed: { label: "应用失败", tone: "danger" },
  unknown: { label: "状态未知（人工处置）", tone: "warning" },
};

const entries = computed(() => props.projection?.entries ?? []);
const commandExecutionByTool = computed<Record<string, RunExecutionRecord>>(() => {
  const result: Record<string, RunExecutionRecord> = {};
  for (const [toolCallId, execution] of Object.entries(props.executionByTool)) {
    const output = execution.output as Record<string, unknown> | null;
    const hasCommandFacts =
      Array.isArray(output?.args) ||
      typeof output?.returncode === "number" ||
      typeof output?.exit_code === "number";
    if (execution.tool_name === "run_whitelisted_command" || hasCommandFacts) {
      result[toolCallId] = execution;
    }
  }
  return result;
});
const historyEntries = computed(() => {
  const items = [...props.history];
  const current = props.projection;
  if (!current) return items;
  // 消息表与 run 事件分别持久化，完成时序不保证 assistant/user 恰好位于数组
  // 最尾端。按角色从后向前只裁掉最后一个当前 run 副本，并规范 CRLF/尾部空白；
  // 更早轮次即使问题文本相同也会保留。
  const normalized = (value: string) => value.replace(/\r\n?/g, "\n").trimEnd();
  const findLastMatch = (role: Message["role"], content: string, after = -1) => {
    const expected = normalized(content);
    for (let index = items.length - 1; index > after; index -= 1) {
      const message = items[index];
      if (message.role === role && normalized(message.content) === expected) return index;
    }
    return -1;
  };
  const userIndex = current.userMessage
    ? findLastMatch("user", current.userMessage)
    : -1;
  const assistantIndex = current.output
    ? findLastMatch("assistant", current.output, userIndex)
    : -1;
  if (assistantIndex >= 0) items.splice(assistantIndex, 1);
  if (userIndex >= 0) items.splice(userIndex, 1);
  return items;
});
const entryCount = computed(() => entries.value.length);
const pendingApprovals = computed(() => props.approvals.filter((item) => item.status === "pending"));

// 长列表分段渲染（计划 §6.4：窗口化/分段，W5 5,000 条压力前提）：
// 默认仅渲染最近 RENDER_BATCH 条，「显示更早」按批次扩展；切换 run 重置。
const RENDER_BATCH = 200;
const visibleCount = ref(RENDER_BATCH);
const auditOpen = ref(false);
const visibleEntries = computed(() =>
  entries.value.slice(Math.max(0, entries.value.length - visibleCount.value))
);
const hiddenCount = computed(() => entries.value.length - visibleEntries.value.length);

function loadEarlier(): void {
  visibleCount.value += RENDER_BATCH * 5;
}

watch(
  () => props.projection?.runId,
  () => {
    visibleCount.value = RENDER_BATCH;
    auditOpen.value = false;
  }
);

const scrollEl = ref<HTMLElement | null>(null);
const anchoredBottom = ref(true);
const newActivity = ref(false);

function onScroll(): void {
  const el = scrollEl.value;
  if (!el) return;
  anchoredBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  if (anchoredBottom.value) newActivity.value = false;
}

async function scrollToBottom(): Promise<void> {
  const el = scrollEl.value;
  if (!el) return;
  // jsdom 无滚动实现：可选调用，锚定状态由逻辑保证
  el.scrollTo?.({ top: el.scrollHeight });
  anchoredBottom.value = true;
  newActivity.value = false;
}

watch(entryCount, async () => {
  if (anchoredBottom.value) {
    await nextTick();
    void scrollToBottom();
  } else {
    newActivity.value = true;
  }
});

onMounted(() => void scrollToBottom());
onBeforeUnmount(() => {
  // 无定时器/监听器需要拆除（scroll 绑定随 DOM 卸载）
});

function approvalById(approvalId: string): RunApprovalRecord | undefined {
  return props.approvals.find((item) => item.id === approvalId);
}

function riskLabel(risk: string): string {
  return risk === "safe" ? "低风险" : risk === "confirm" ? "需确认" : risk === "restricted" ? "受限" : risk;
}

function toolEntryClass(entry: Extract<TranscriptEntry, { kind: "tool" }>): string {
  return `tone-${TOOL_STATE_LABEL[entry.state]?.tone ?? "neutral"}`;
}

// ============ W6-R：工具卡可追溯详情（公开事实，不猜测） ============

type ToolDetail = {
  startedAt: string | null;
  completedAt: string | null;
  durationLabel: string | null;
  attempt: number | null;
  attemptCount: number;
  commandText: string | null;
  resultSummary: string | null;
};

function formatClock(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatDuration(startIso: string | null, endIso: string | null): string | null {
  if (!startIso || !endIso) return null;
  const start = new Date(startIso).getTime();
  const end = new Date(endIso).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  return formatDurationMs(end - start);
}

function formatDurationMs(ms: number): string | null {
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/** 同名执行 ≥2 次时呈现重试序号（按创建顺序；公开事实，不推测原因） */
function executionAttempt(execution: RunExecutionRecord): { attempt: number; total: number } {
  const sameName = props.executions.filter((item) => item.tool_name === execution.tool_name);
  if (sameName.length < 2) return { attempt: 1, total: sameName.length };
  const index = sameName.findIndex((item) => item.id === execution.id);
  return { attempt: index >= 0 ? index + 1 : 1, total: sameName.length };
}

/** 结果摘要：仅从脱敏持久层 output 里提取有限字段（不展示完整输出） */
function executionResultSummary(execution: RunExecutionRecord): string | null {
  const output = execution.output;
  if (!output || typeof output !== "object") return null;
  const record = output as Record<string, unknown>;
  const parts: string[] = [];
  const parsed = record.parsed as Record<string, unknown> | undefined;
  if (parsed && typeof parsed === "object" && typeof parsed.summary === "string") {
    parts.push(parsed.summary);
  }
  if (record.verified === true) parts.push("已验证");
  if (typeof record.profile === "string") parts.push(`profile: ${record.profile}`);
  if (typeof record.file_count === "number") parts.push(`${record.file_count} 个文件`);
  if (!parts.length) return null;
  return redactSecretText(parts.join(" · "));
}

function toolDetail(entry: Extract<TranscriptEntry, { kind: "tool" }>): ToolDetail {
  const execution = props.executionByTool[entry.toolCallId];
  if (!execution) {
    return {
      startedAt: null,
      completedAt: null,
      durationLabel: null,
      attempt: null,
      attemptCount: 0,
      commandText: null,
      resultSummary: null,
    };
  }
  const { attempt, total } = executionAttempt(execution);
  const output =
    execution.output && typeof execution.output === "object"
      ? (execution.output as Record<string, unknown>)
      : null;
  const args =
    output && Array.isArray(output.args)
      ? output.args.filter((item): item is string => typeof item === "string")
      : [];
  return {
    startedAt: formatClock(execution.created_at),
    completedAt: formatClock(execution.completed_at),
    durationLabel: formatDuration(execution.created_at, execution.completed_at),
    attempt: total >= 2 ? attempt : null,
    attemptCount: total,
    commandText: args.length ? redactCommandArgs(args) : null,
    resultSummary: executionResultSummary(execution),
  };
}

function terminalMeta(): { label: string; tone: string } | null {
  const status = props.projection?.status;
  if (!status) return null;
  const meta = RUN_STATUS_META[status];
  return { label: meta.label, tone: meta.tone };
}

type RunAuditRow = {
  key: string;
  title: string;
  detail: string;
  duration: string | null;
};

const runDurationLabel = computed(() => {
  const current = props.projection;
  return current ? formatDuration(current.startedAt, current.completedAt) : null;
});

const runTimeRange = computed(() => {
  const current = props.projection;
  if (!current) return null;
  const started = formatClock(current.startedAt);
  const completed = formatClock(current.completedAt);
  if (!started && !completed) return null;
  return `${started ?? "--"} → ${completed ?? "--"}`;
});

function auditRow(entry: TranscriptEntry): RunAuditRow {
  switch (entry.kind) {
    case "run-start":
      return {
        key: entry.key,
        title: "任务开始",
        detail: `上限 ${entry.maxSteps} 步、${entry.maxToolCalls} 次工具${entry.maxWallTimeSeconds !== null ? `、${Math.round(entry.maxWallTimeSeconds)} 秒` : ""}`,
        duration: null,
      };
    case "context":
      return {
        key: entry.key,
        title: "上下文准备",
        detail: `约 ${entry.estimatedTokens.toLocaleString()} tokens${entry.truncated ? "，已截断" : ""}`,
        duration: null,
      };
    case "model-turn":
      return {
        key: entry.key,
        title: `模型第 ${entry.ordinal} 轮`,
        detail:
          entry.state === "completed"
            ? `${entry.inputTokens.toLocaleString()} 输入 / ${entry.outputTokens.toLocaleString()} 输出 tokens${entry.finishReason ? `，结束原因：${entry.finishReason}` : ""}`
            : "生成中",
        duration: entry.latencyMs === null ? null : formatDurationMs(entry.latencyMs),
      };
    case "decision-summary":
      return {
        key: entry.key,
        title: "公开决策摘要",
        detail: [
          `目标：${entry.goal}`,
          entry.method ? `方法：${entry.method}` : null,
          entry.nextSteps.length ? `后续：${entry.nextSteps.join("、")}` : null,
        ].filter(Boolean).join("；"),
        duration: null,
      };
    case "plan":
      return {
        key: entry.key,
        title: entry.note === "created" ? "建立执行计划" : "更新执行计划",
        detail: `v${entry.version}，${entry.itemCount} 项`,
        duration: null,
      };
    case "tool": {
      const detail = toolDetail(entry);
      const facts = [
        `状态：${TOOL_STATE_LABEL[entry.state]?.label ?? entry.state}`,
        detail.attempt !== null ? `第 ${detail.attempt}/${detail.attemptCount} 次执行` : null,
        detail.commandText ? `命令：${detail.commandText}` : null,
        detail.resultSummary ? `结果：${detail.resultSummary}` : null,
        entry.errorMessage ? `错误：${entry.errorType ?? "tool_error"} · ${entry.errorMessage}` : null,
      ];
      return {
        key: entry.key,
        title: `工具 · ${entry.name || "未命名工具"}`,
        detail: redactSecretText(facts.filter(Boolean).join("；")),
        duration: detail.durationLabel,
      };
    }
    case "approval": {
      const approval = approvalById(entry.approvalId);
      return {
        key: entry.key,
        title: `授权 · ${approval?.tool_name ?? entry.toolName}`,
        detail:
          entry.resolved || (approval !== undefined && approval.status !== "pending")
            ? `已处理（${approval?.status ?? "resolved"}）`
            : "等待用户确认",
        duration: null,
      };
    }
    case "verification":
      return {
        key: entry.key,
        title: `输出校验 · ${entry.verifier}`,
        detail: `第 ${entry.attempt} 次，${entry.state === "passed" ? "通过" : entry.state === "started" ? "进行中" : entry.willRetry ? "未通过，将重试" : "未通过"}${entry.message ? `；${entry.message}` : ""}`,
        duration: null,
      };
    case "patch-set":
      return {
        key: entry.key,
        title: "变更集",
        detail: `${PATCH_STATE_LABEL[entry.state]?.label ?? entry.state}${entry.fileCount !== null ? `，${entry.fileCount} 个文件` : ""}${entry.verified === true ? "，已验证" : ""}${entry.reason ? `；${entry.reason}` : ""}`,
        duration: null,
      };
    case "artifact":
      return {
        key: entry.key,
        title: `产出 · ${entry.artifactKind}`,
        detail: entry.title,
        duration: null,
      };
    case "terminal":
      return {
        key: entry.key,
        title: "任务结束",
        detail: `${RUN_STATUS_META[entry.status].label}${entry.errorCode ? `，错误码：${entry.errorCode}` : ""}`,
        duration: runDurationLabel.value,
      };
  }
}

const auditRows = computed(() => entries.value.map(auditRow));
const modelRoundCount = computed(
  () => entries.value.filter((entry) => entry.kind === "model-turn").length
);
</script>

<template>
  <div class="run-transcript" data-testid="run-transcript">
    <div ref="scrollEl" class="transcript-scroll" @scroll.passive="onScroll">
      <!-- 未开始任务 -->
      <div v-if="!projection && historyEntries.length === 0" class="transcript-empty" data-testid="transcript-empty">
        <PhLightning :size="26" weight="duotone" />
        <p>还没有开始任务</p>
        <p class="hint">在下方输入要执行的内容；执行计划、工具与审批都会在这里展示。</p>
      </div>

      <template v-else>
        <!-- 已持久化的更早对话；当前 run 继续使用下方详细活动流呈现。 -->
        <section v-if="historyEntries.length" class="history-section" data-testid="transcript-history-section">
          <div class="transcript-divider"><span>更早对话</span></div>
          <div
            v-for="message in historyEntries"
            :key="`history:${message.id}`"
            class="history-message"
            :class="`history-${message.role}`"
            :data-testid="`transcript-history-${message.role}`"
          >
            <div v-if="message.role === 'user'" class="user-avatar">
              <PhUser :size="14" weight="fill" aria-hidden="true" />
            </div>
            <div class="history-copy">
              <MarkdownContent v-if="message.role === 'assistant'" :content="message.content" />
              <template v-else>{{ message.content }}</template>
            </div>
          </div>
        </section>

        <template v-if="projection">
        <div v-if="historyEntries.length" class="transcript-divider current"><span>当前执行</span></div>
        <!-- 用户请求 -->
        <div v-if="projection.userMessage" class="user-bubble" data-testid="transcript-user-message">
          <div class="user-avatar"><PhUser :size="14" weight="fill" aria-hidden="true" /></div>
          <div class="user-copy">{{ projection.userMessage }}</div>
        </div>

        <button
          v-if="hiddenCount > 0"
          class="load-earlier"
          data-testid="transcript-load-earlier"
          @click="loadEarlier"
        >
          显示更早的活动（{{ hiddenCount.toLocaleString() }} 条）
        </button>

        <div
          v-for="entry in visibleEntries"
          :key="entry.key"
          class="entry"
          :class="`entry-${entry.kind}`"
          :data-testid="`transcript-${entry.kind}`"
        >
          <!-- 运行开始 -->
          <template v-if="entry.kind === 'run-start'">
            <PhCircleNotch :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              任务开始 · 最多 {{ entry.maxSteps }} 步 / {{ entry.maxToolCalls }} 次工具<template v-if="entry.maxWallTimeSeconds !== null"> / {{ Math.round(entry.maxWallTimeSeconds) }}s</template>
            </span>
          </template>

          <!-- 上下文就绪 -->
          <template v-else-if="entry.kind === 'context'">
            <PhClipboardText :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              上下文就绪 · 约 {{ entry.estimatedTokens.toLocaleString() }} tokens<template v-if="entry.truncated">（已截断）</template>
            </span>
          </template>

          <!-- 模型轮次（摘要折叠） -->
          <template v-else-if="entry.kind === 'model-turn'">
            <PhLightning :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              模型第 {{ entry.ordinal }} 轮
              <template v-if="entry.state === 'completed'">
                · {{ entry.outputTokens.toLocaleString() }} 输出 tokens<template v-if="entry.latencyMs !== null"> · {{ Math.round(entry.latencyMs) }}ms</template>
              </template>
              <template v-else> · 生成中</template>
            </span>
          </template>

          <!-- v0.9.0 H0 §8：逐轮公开决策摘要（结构化公开事实，不含隐藏推理） -->
          <div
            v-else-if="entry.kind === 'decision-summary'"
            class="entry decision-entry"
            data-testid="transcript-decision-summary"
          >
            <PhPath :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              决策：{{ entry.goal }}
              <template v-if="entry.method"> · {{ entry.method }}</template>
            </span>
            <span v-if="entry.nextSteps.length" class="decision-steps">
              后续：{{ entry.nextSteps.join("、") }}
            </span>
          </div>

          <!-- 计划摘要 -->
          <button
            v-else-if="entry.kind === 'plan'"
            class="entry plan-entry"
            data-testid="transcript-plan-note"
            @click="emit('open-plan')"
          >
            <PhClipboardText :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              {{ entry.note === "created" ? "执行计划已建立" : "执行计划已更新" }} · v{{ entry.version }} · {{ entry.itemCount }} 项 · 点击查看
            </span>
          </button>

          <!-- 工具卡（摘要行 + W6-R 可追溯详情 + W3 执行输出按需加载） -->
          <template v-else-if="entry.kind === 'tool'">
            <span class="entry-icon" :class="toolEntryClass(entry)" aria-hidden="true">●</span>
            <span class="entry-copy mono">{{ entry.name }}</span>
            <span class="entry-state" :class="toolEntryClass(entry)">
              <PhCircleNotch v-if="entry.state === 'started' || entry.state === 'requested'" :size="12" class="spin" />
              {{ TOOL_STATE_LABEL[entry.state]?.label ?? entry.state }}
            </span>
            <span v-if="toolDetail(entry).attempt !== null" class="entry-retry" data-testid="tool-retry">
              重试 {{ toolDetail(entry).attempt }}/{{ toolDetail(entry).attemptCount }}
            </span>
            <span
              v-if="toolDetail(entry).startedAt"
              class="entry-time"
              data-testid="tool-time"
            >
              {{ toolDetail(entry).startedAt }}<template v-if="toolDetail(entry).completedAt"> → {{ toolDetail(entry).completedAt }}</template>
              <template v-if="toolDetail(entry).durationLabel"> · {{ toolDetail(entry).durationLabel }}</template>
            </span>
            <code
              v-if="toolDetail(entry).commandText"
              class="entry-command mono"
              data-testid="tool-command"
            >$ {{ toolDetail(entry).commandText }}</code>
            <span v-if="toolDetail(entry).resultSummary" class="entry-result" data-testid="tool-result">
              {{ toolDetail(entry).resultSummary }}
            </span>
            <span v-if="entry.errorMessage" class="entry-error" :title="entry.errorMessage">
              {{ entry.errorType || "错误" }}：{{ entry.errorMessage }}
            </span>
            <CommandOutput
              v-if="commandExecutionByTool[entry.toolCallId]"
              :execution="commandExecutionByTool[entry.toolCallId]"
              :page="outputPages[commandExecutionByTool[entry.toolCallId].id] ?? null"
              :loading="outputLoading.includes(commandExecutionByTool[entry.toolCallId].id)"
              class="entry-execution"
              @load="emit('load-output', commandExecutionByTool[entry.toolCallId].id)"
            />
          </template>

          <!-- 审批卡 -->
          <div v-else-if="entry.kind === 'approval'" class="approval-card" data-testid="approval-card">
            <div class="approval-head">
              <PhShieldWarning :size="16" class="approval-icon" aria-hidden="true" />
              <strong>授权请求</strong>
              <span class="mono approval-tool">{{ approvalById(entry.approvalId)?.tool_name ?? entry.toolName }}</span>
            </div>
            <div v-if="approvalById(entry.approvalId)" class="approval-meta">
              <span class="risk" :class="`risk-${approvalById(entry.approvalId)!.risk_level}`">
                {{ riskLabel(approvalById(entry.approvalId)!.risk_level) }}
              </span>
              <span>能力：{{ approvalById(entry.approvalId)!.required_capabilities.join("、") || "—" }}</span>
              <span class="mono">{{ approvalById(entry.approvalId)!.tool_version }}</span>
            </div>
            <div v-if="entry.resolved || approvalById(entry.approvalId)?.status !== 'pending'" class="approval-resolved">
              已处理（{{ approvalById(entry.approvalId)?.status ?? "resolved" }}）
            </div>
            <DiffArtifact
              v-if="approvalPreviews[entry.approvalId] !== undefined || previewLoading.includes(entry.approvalId)"
              :preview="approvalPreviews[entry.approvalId] ?? null"
              :loading="previewLoading.includes(entry.approvalId)"
            />
            <div
              v-if="!entry.resolved && approvalById(entry.approvalId)?.status === 'pending'"
              class="approval-actions"
            >
              <button class="pa-btn pa-btn--primary" :data-testid="`approval-approve-${entry.approvalId}`" @click="emit('approve', entry.approvalId)">
                批准执行
              </button>
              <button class="pa-btn pa-btn--ghost" :data-testid="`approval-reject-${entry.approvalId}`" @click="emit('reject', entry.approvalId)">
                拒绝
              </button>
            </div>
          </div>

          <!-- 输出校验 -->
          <template v-else-if="entry.kind === 'verification'">
            <PhCheckCircle
              :size="14"
              class="entry-icon"
              :class="`tone-${entry.state === 'passed' ? 'success' : entry.state === 'failed' ? 'danger' : 'info'}`"
              aria-hidden="true"
            />
            <span class="entry-copy">
              输出校验 · {{ entry.verifier }} · 第 {{ entry.attempt }} 次 · {{ entry.state === "started" ? "进行中" : entry.state === "passed" ? "通过" : entry.willRetry ? "未通过（将重试）" : "未通过" }}
              <template v-if="entry.message"> · {{ entry.message }}</template>
            </span>
          </template>

          <!-- 变更集（W2 摘要，W3 扩展 Diff） -->
          <template v-else-if="entry.kind === 'patch-set'">
            <PhGitDiff :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              变更集 · {{ PATCH_STATE_LABEL[entry.state]?.label ?? entry.state }}
              <template v-if="entry.fileCount !== null"> · {{ entry.fileCount }} 个文件</template>
              <template v-if="entry.verified === true"> · 已验证</template>
              <template v-if="entry.reason"> · {{ entry.reason }}</template>
            </span>
          </template>

          <!-- 产出（W2 摘要，W3 按需加载内容） -->
          <template v-else-if="entry.kind === 'artifact'">
            <PhFilePlus :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">产出 · {{ entry.artifactKind }} · {{ entry.title }}</span>
          </template>

          <!-- 终态摘要 -->
          <div v-else-if="entry.kind === 'terminal'" class="terminal-card" :data-testid="'terminal-summary'" :class="`tone-${terminalMeta()?.tone}`">
            <div class="terminal-head">
              <PhCheckCircle v-if="entry.status === 'completed'" :size="16" weight="fill" aria-hidden="true" />
              <PhWarningCircle v-else-if="entry.status === 'failed' || entry.status === 'timed_out'" :size="16" aria-hidden="true" />
              <PhProhibit v-else :size="16" aria-hidden="true" />
              <strong>输出总结</strong>
              <span class="terminal-status" :class="`tone-${terminalMeta()?.tone}`">{{ terminalMeta()?.label }}</span>
              <span v-if="entry.errorCode" class="mono terminal-code">{{ entry.errorCode }}</span>
              <span class="terminal-usage">
                {{ projection.usage.toolCallCount }} 次工具 · {{ projection.usage.outputTokens.toLocaleString() }} 输出 tokens
              </span>
              <button
                type="button"
                class="terminal-duration"
                data-testid="run-duration-toggle"
                :aria-expanded="auditOpen"
                aria-controls="run-audit-panel"
                title="查看执行过程与结果"
                @click="auditOpen = !auditOpen"
              >
                <PhClock :size="13" aria-hidden="true" />
                {{ runDurationLabel ? `耗时 ${runDurationLabel}` : "耗时待同步" }}
                <span class="duration-caret" :class="{ open: auditOpen }" aria-hidden="true">⌄</span>
              </button>
            </div>
            <!-- v0.9.0 H1-B（§5.5/§5.6）：无工具/命令事件的完成态如实标注，
                 不把无执行证据的回答呈现为“已完成的可执行任务”。 -->
            <p
              v-if="entry.status === 'completed' && projection.usage.toolCallCount === 0"
              class="terminal-no-evidence"
              data-testid="terminal-no-evidence"
            >
              本轮未执行工具/命令；以上为文字回答，不含执行证据。
            </p>
            <p
              v-if="entry.status === 'failed' && projection.error?.message"
              class="terminal-failure-reason"
              data-testid="terminal-failure-reason"
            >
              <strong>失败原因：</strong>{{ projection.error.message }}
            </p>
            <div
              v-if="entry.output || projection.output"
              class="terminal-output"
              data-testid="terminal-output"
            ><MarkdownContent :content="entry.output ?? projection.output ?? ''" /></div>

            <div
              v-if="auditOpen"
              id="run-audit-panel"
              class="run-audit-panel"
              data-testid="run-audit-panel"
            >
              <div class="audit-head">
                <div>
                  <strong>执行过程与结果</strong>
                  <p>按持久化事件展示公开决策、模型轮次、工具调用与验证；不包含模型隐藏推理。</p>
                </div>
                <span v-if="runTimeRange" class="audit-time mono">{{ runTimeRange }}</span>
              </div>

              <div class="audit-stats" aria-label="运行统计">
                <span>{{ modelRoundCount }} 轮模型</span>
                <span>{{ projection.usage.toolCallCount }} 次工具</span>
                <span>{{ projection.usage.inputTokens.toLocaleString() }} 输入 tokens</span>
                <span>{{ projection.usage.outputTokens.toLocaleString() }} 输出 tokens</span>
              </div>

              <ol class="audit-list">
                <li v-for="row in auditRows" :key="`audit:${row.key}`" class="audit-row">
                  <span class="audit-marker" aria-hidden="true"></span>
                  <div class="audit-copy">
                    <div class="audit-row-head">
                      <strong>{{ row.title }}</strong>
                      <span v-if="row.duration" class="mono">{{ row.duration }}</span>
                    </div>
                    <p>{{ row.detail }}</p>
                  </div>
                </li>
              </ol>

              <div v-if="entry.output || projection.output" class="audit-result">
                <strong>最终结果</strong>
                <MarkdownContent :content="entry.output ?? projection.output ?? ''" />
              </div>
            </div>
          </div>
        </div>

        <!-- 断线重连提示（仅存在 durable run 时；创建失败由阻塞卡片呈现，
             v0.9.0 H1-B §5.6：不显示无 run 的误导性重连提示） -->
        <div v-if="(phase === 'reconnecting' || connectionError) && projection" class="stream-notice" data-testid="stream-reconnect-notice">
          <PhClock :size="14" aria-hidden="true" />
          <span>连接中断，正在重连…（任务在本地继续执行，已完成步骤不会丢失）</span>
          <button class="notice-btn" @click="emit('retry-stream')">立即重试</button>
        </div>
        <div v-else-if="phase === 'streaming'" class="stream-live" data-testid="stream-live">
          <PhCircleNotch :size="12" class="spin" aria-hidden="true" />
          <span>实时更新中</span>
        </div>

        <!-- 静态预览标记 -->
        <div v-if="previewMode" class="preview-tag">RUN PREVIEW</div>
        </template>
      </template>
    </div>

    <Transition name="pa-zone">
      <button
        v-if="newActivity"
        class="follow-pill"
        data-testid="new-activity-pill"
        @click="scrollToBottom"
      >
        <PhArrowCircleDown :size="14" />
        查看新活动
      </button>
    </Transition>

    <span
      v-if="pendingApprovals.length > 0"
      class="sr-only"
      role="status"
    >有 {{ pendingApprovals.length }} 个待审批请求</span>
  </div>
</template>

<style scoped>
.run-transcript {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}
.transcript-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.transcript-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-2);
  color: var(--color-fg-subtle);
  text-align: center;
}
.transcript-empty p {
  margin: 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
}
.transcript-empty .hint {
  max-width: 420px;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}

.user-bubble {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.user-avatar {
  order: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.user-copy {
  max-width: 76%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-fg);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
}

.history-message {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.history-section {
  display: flex;
  flex-direction: column;
}
.transcript-divider {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.transcript-divider::before,
.transcript-divider::after {
  height: 1px;
  flex: 1;
  background: var(--color-border);
  content: "";
}
.transcript-divider.current {
  margin-top: var(--space-1);
}
.history-user {
  justify-content: flex-end;
}
.history-user .user-avatar {
  order: 2;
}
.history-copy {
  max-width: 76%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-fg);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
}
.history-assistant .history-copy {
  width: min(760px, 76%);
  border-color: transparent;
  background: var(--color-surface-muted);
  white-space: normal;
}
.history-system .history-copy {
  max-width: 100%;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
}

.load-earlier {
  align-self: center;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.load-earlier:hover {
  color: var(--color-fg);
}

.entry {
  position: relative;
  display: flex;
  width: 100%;
  box-sizing: border-box;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-2);
  min-height: 23px;
  padding: 2px var(--space-1);
  border-left: 2px solid transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
}
.entry-icon {
  flex-shrink: 0;
  color: var(--color-fg-subtle);
}
.entry-icon.tone-info { color: var(--color-accent); }
.entry-icon.tone-success { color: var(--color-success); }
.entry-icon.tone-warning { color: var(--color-warning); }
.entry-icon.tone-danger { color: var(--color-danger); }
.entry-copy {
  min-width: 0;
}
/* v0.9.0 H0 §8：公开决策摘要（结构化公开事实；不呈现隐藏推理） */
.decision-entry .entry-icon {
  color: var(--color-accent);
}
.decision-steps {
  flex-basis: 100%;
  padding-left: 22px;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.entry-state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--pa-text-meta);
}
.entry-state.tone-info { color: var(--color-accent-soft-fg); }
.entry-state.tone-success { color: var(--color-success-fg); }
.entry-state.tone-warning { color: var(--color-warning-fg); }
.entry-state.tone-danger { color: var(--color-danger-fg); }
.entry-error {
  flex-basis: 100%;
  color: var(--color-danger-fg);
  font-size: var(--pa-text-meta);
  word-break: break-word;
}
.entry-retry {
  padding: 1px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-warning) 40%, var(--color-border));
  border-radius: var(--radius-full);
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
}
.entry-time {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.entry-command {
  flex-basis: 100%;
  max-height: 84px;
  overflow-y: auto;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
  white-space: pre-wrap;
  word-break: break-all;
}
.entry-result {
  flex-basis: 100%;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  word-break: break-word;
}
.entry-execution {
  flex-basis: 100%;
  width: min(760px, calc(100% - 22px));
  margin-left: 22px;
}
.plan-entry {
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.plan-entry:hover {
  color: var(--color-accent-soft-fg);
}
.mono {
  font-family: var(--font-mono, monospace);
}

.approval-card {
  display: flex;
  flex-direction: column;
  width: min(680px, 100%);
  box-sizing: border-box;
  gap: var(--space-1);
  margin: 2px 0;
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-warning) 40%, var(--color-border));
  border-radius: var(--radius-lg);
  background: var(--color-warning-soft);
}
.entry-approval {
  display: block;
  min-height: 0;
  padding: 0 var(--space-1);
}
.approval-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.approval-icon {
  color: var(--color-warning-fg);
}
.approval-tool {
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.approval-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.risk {
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
}
.risk-safe { color: var(--color-success-fg); }
.risk-confirm { color: var(--color-warning-fg); }
.risk-restricted { color: var(--color-danger-fg); }
.approval-actions {
  display: flex;
  gap: var(--space-2);
}
.approval-resolved {
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}

.terminal-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: var(--space-1);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}
.terminal-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.terminal-card.tone-success .terminal-head svg { color: var(--color-success); }
.terminal-card.tone-danger .terminal-head svg { color: var(--color-danger); }
.terminal-card.tone-warning .terminal-head svg { color: var(--color-warning); }
.terminal-status {
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.terminal-status.tone-success {
  border-color: color-mix(in srgb, var(--color-success) 38%, var(--color-border));
  color: var(--color-success-fg);
}
.terminal-status.tone-warning {
  border-color: color-mix(in srgb, var(--color-warning) 42%, var(--color-border));
  color: var(--color-warning-fg);
}
.terminal-status.tone-danger {
  border-color: color-mix(in srgb, var(--color-danger) 38%, var(--color-border));
  color: var(--color-danger-fg);
}
.terminal-code {
  color: var(--color-danger-fg);
  font-size: var(--pa-text-meta);
}
.terminal-usage {
  margin-left: auto;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.terminal-duration {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface-muted);
  color: var(--color-fg-muted);
  font: inherit;
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.terminal-duration:hover {
  border-color: color-mix(in srgb, var(--color-accent) 48%, var(--color-border));
  color: var(--color-accent-soft-fg);
}
.terminal-duration:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 2px;
}
.duration-caret {
  display: inline-block;
  transition: transform var(--duration-fast, 120ms) ease;
}
.duration-caret.open {
  transform: rotate(180deg);
}
.terminal-no-evidence {
  margin: var(--space-2) 0 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-warning-soft);
  border-radius: var(--radius-md);
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
}
.terminal-failure-reason {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-left: 3px solid var(--color-danger);
  border-radius: var(--radius-sm);
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
  overflow-wrap: anywhere;
}
.terminal-output {
  max-height: 420px;
  overflow-y: auto;
  margin: 0;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-fg);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  word-break: break-word;
}

.run-audit-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}
.audit-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}
.audit-head strong,
.audit-result > strong {
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.audit-head p {
  max-width: 660px;
  margin: var(--space-1) 0 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
}
.audit-time {
  flex-shrink: 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.audit-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.audit-stats span {
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface-muted);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.audit-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  max-height: 440px;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}
.audit-row {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: var(--space-2);
  padding: 0 0 var(--space-3);
}
.audit-row:not(:last-child)::before {
  position: absolute;
  top: 10px;
  bottom: -2px;
  left: 4px;
  width: 1px;
  background: var(--color-border);
  content: "";
}
.audit-marker {
  position: relative;
  z-index: 1;
  width: 9px;
  height: 9px;
  margin-top: 5px;
  border: 2px solid var(--color-surface);
  border-radius: var(--radius-full);
  background: var(--color-accent);
  box-shadow: 0 0 0 1px var(--color-border);
}
.audit-copy {
  min-width: 0;
}
.audit-row-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
}
.audit-row-head span {
  flex-shrink: 0;
  color: var(--color-fg-subtle);
}
.audit-copy p {
  margin: 2px 0 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
}
.audit-result {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.audit-result > :last-child {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-fg);
  font: inherit;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  word-break: break-word;
}

.stream-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--color-warning) 36%, var(--color-border));
  border-radius: var(--radius-md);
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
}
.notice-btn {
  margin-left: auto;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.stream-live {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.preview-tag {
  align-self: flex-start;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-fg-subtle);
  font-size: var(--pa-t-11);
  letter-spacing: 0.1em;
}

.follow-pill {
  position: absolute;
  bottom: var(--space-3);
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.spin {
  animation: transcript-spin 0.9s linear infinite;
}
@keyframes transcript-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
  .duration-caret { transition: none; }
}
@media (max-width: 760px) {
  .terminal-usage {
    margin-left: 0;
  }
  .audit-head {
    flex-direction: column;
  }
}
</style>
