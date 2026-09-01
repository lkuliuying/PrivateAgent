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
  PhCaretDown,
  PhCheckCircle,
  PhCircleNotch,
  PhClipboardText,
  PhClock,
  PhFilePlus,
  PhGitDiff,
  PhLightning,
  PhPath,
  PhShieldWarning,
  PhUser,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { TranscriptEntry, RunProjection } from "../model/runProjector";
import type { CodingInstructionMarker } from "../model/contracts";
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
    instructionTarget?: { id: string; seq: number } | null;
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
    instructionTarget: null,
  }
);

const emit = defineEmits<{
  approve: [approvalId: string];
  reject: [approvalId: string];
  "open-plan": [];
  "retry-stream": [];
  "load-output": [executionId: string];
  "instruction-markers-change": [markers: CodingInstructionMarker[]];
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
function historyInstructionId(messageId: number): string {
  return `message:${messageId}`;
}

const currentInstructionId = computed(() => {
  const current = props.projection;
  return current?.userMessage ? `run:${current.runId}` : null;
});

function instructionLabel(content: string): string {
  return content.replace(/\s+/g, " ").trim() || "未命名指令";
}

const instructionMarkers = computed<CodingInstructionMarker[]>(() => {
  const markers = historyEntries.value
    .filter((message) => message.role === "user" && message.content.trim().length > 0)
    .map((message) => ({
      id: historyInstructionId(message.id),
      label: instructionLabel(message.content),
    }));
  const currentId = currentInstructionId.value;
  const currentMessage = props.projection?.userMessage;
  if (currentId && currentMessage) {
    markers.push({ id: currentId, label: instructionLabel(currentMessage) });
  }
  return markers;
});

watch(
  instructionMarkers,
  (markers) => emit("instruction-markers-change", markers),
  { immediate: true }
);
const entryCount = computed(() => entries.value.length);
const pendingApprovals = computed(() => props.approvals.filter((item) => item.status === "pending"));

// 长列表分段渲染（计划 §6.4：窗口化/分段，W5 5,000 条压力前提）：
// 默认仅渲染最近 RENDER_BATCH 条，「显示更早」按批次扩展；切换 run 重置。
const RENDER_BATCH = 200;
const visibleCount = ref(RENDER_BATCH);
const processOpen = ref(true);
const visibleEntries = computed(() =>
  entries.value.slice(Math.max(0, entries.value.length - visibleCount.value))
);
const hiddenCount = computed(() => entries.value.length - visibleEntries.value.length);
const terminalEntry = computed<Extract<TranscriptEntry, { kind: "terminal" }> | null>(() => {
  for (let index = entries.value.length - 1; index >= 0; index -= 1) {
    const entry = entries.value[index];
    if (entry.kind === "terminal") return entry;
  }
  return null;
});
const processExpanded = computed(() => terminalEntry.value === null || processOpen.value);

function loadEarlier(): void {
  visibleCount.value += RENDER_BATCH * 5;
}

watch(
  () => props.projection?.runId,
  () => {
    visibleCount.value = RENDER_BATCH;
    processOpen.value = true;
  }
);

const scrollEl = ref<HTMLElement | null>(null);
const anchoredBottom = ref(true);
const newActivity = ref(false);
const activeInstructionId = ref<string | null>(null);
let instructionHighlightTimer: number | null = null;

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

async function scrollToInstruction(instructionId: string): Promise<void> {
  await nextTick();
  const el = scrollEl.value;
  if (!el) return;
  const target = Array.from(
    el.querySelectorAll<HTMLElement>("[data-instruction-id]")
  ).find((candidate) => candidate.dataset.instructionId === instructionId);
  if (!target) return;
  target.scrollIntoView?.({ behavior: "smooth", block: "center" });
  activeInstructionId.value = instructionId;
  if (instructionHighlightTimer !== null) window.clearTimeout(instructionHighlightTimer);
  instructionHighlightTimer = window.setTimeout(() => {
    activeInstructionId.value = null;
    instructionHighlightTimer = null;
  }, 1800);
}

watch(
  () => props.instructionTarget?.seq,
  () => {
    const target = props.instructionTarget;
    if (target) void scrollToInstruction(target.id);
  }
);

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
  if (instructionHighlightTimer !== null) {
    window.clearTimeout(instructionHighlightTimer);
    instructionHighlightTimer = null;
  }
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
  if (ms < 1000) return `${Math.round(ms)} 毫秒`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟 ${Math.round(seconds % 60)} 秒`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时 ${minutes % 60} 分钟`;
}

function toolActionLabel(name: string): string {
  const normalized = name.toLowerCase();
  if (normalized.includes("browser") || normalized.includes("web")) return "使用了浏览器";
  if (normalized.includes("image") || normalized.includes("screenshot")) return "查看了图像";
  if (normalized.includes("command") || normalized.includes("shell") || normalized.includes("terminal")) return "运行了命令";
  if (normalized.includes("patch") || normalized.includes("write") || normalized.includes("edit")) return "编辑了文件";
  if (normalized.includes("read") || normalized.includes("file")) return "读取了文件";
  if (normalized.includes("search") || normalized.includes("find")) return "搜索了内容";
  return "调用了工具";
}

function decisionNarrative(method: string | null): string | null {
  if (!method) return null;
  return method.replace(/^本轮决策[：:]\s*/, "");
}

function shouldDisplayEntry(entry: TranscriptEntry): boolean {
  if (entry.kind === "terminal") return true;
  if (!processExpanded.value) return false;
  return entry.kind !== "run-start" && entry.kind !== "model-turn";
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

const runDurationLabel = computed(() => {
  const current = props.projection;
  return current ? formatDuration(current.startedAt, current.completedAt) : null;
});

const processHeaderLabel = computed(() => {
  if (terminalEntry.value) {
    return runDurationLabel.value ? `用时 ${runDurationLabel.value}` : "执行过程";
  }
  return runDurationLabel.value ? `已用时 ${runDurationLabel.value}` : "正在执行";
});

const processSummaryLabels = computed(() => {
  const labels: string[] = [];
  for (const entry of entries.value) {
    if (entry.kind === "tool") labels.push(toolActionLabel(entry.name));
    if (entry.kind === "context" && entry.truncated) labels.push("压缩了上下文");
  }
  return [...new Set(labels)].slice(0, 6);
});

const latestPatchEntry = computed<Extract<TranscriptEntry, { kind: "patch-set" }> | null>(() => {
  for (let index = entries.value.length - 1; index >= 0; index -= 1) {
    const entry = entries.value[index];
    if (entry.kind === "patch-set") return entry;
  }
  return null;
});

const resultArtifactEntries = computed(() =>
  entries.value.filter((entry): entry is Extract<TranscriptEntry, { kind: "artifact" }> => entry.kind === "artifact")
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
            :class="[
              `history-${message.role}`,
              { 'instruction-targeted': message.role === 'user' && activeInstructionId === historyInstructionId(message.id) },
            ]"
            :data-testid="`transcript-history-${message.role}`"
            :data-instruction-id="message.role === 'user' ? historyInstructionId(message.id) : undefined"
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
        <div
          v-if="projection.userMessage"
          class="user-bubble"
          :class="{ 'instruction-targeted': activeInstructionId === currentInstructionId }"
          data-testid="transcript-user-message"
          :data-instruction-id="currentInstructionId ?? undefined"
        >
          <div class="user-avatar"><PhUser :size="14" weight="fill" aria-hidden="true" /></div>
          <div class="user-copy">{{ projection.userMessage }}</div>
        </div>

        <button
          type="button"
          class="process-toggle"
          data-testid="run-duration-toggle"
          :aria-expanded="processExpanded"
          @click="processOpen = !processOpen"
        >
          <PhClock :size="17" aria-hidden="true" />
          <span>{{ processHeaderLabel }}</span>
          <PhCaretDown :size="15" class="process-caret" :class="{ open: processExpanded }" aria-hidden="true" />
        </button>
        <div class="process-divider" aria-hidden="true" />

        <button
          v-if="hiddenCount > 0 && processExpanded"
          class="load-earlier"
          data-testid="transcript-load-earlier"
          @click="loadEarlier"
        >
          显示更早的活动（{{ hiddenCount.toLocaleString() }} 条）
        </button>

        <div
          v-for="entry in visibleEntries"
          :key="entry.key"
          v-show="shouldDisplayEntry(entry)"
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
              {{ entry.truncated ? "上下文已自动压缩" : "已整理上下文" }}
              <span class="entry-detail">· 约 {{ entry.estimatedTokens.toLocaleString() }} tokens</span>
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

          <!-- 仅展示公开行动摘要；具体命令、审批与结果由后续工具时间线呈现。 -->
          <template v-else-if="entry.kind === 'decision-summary'">
            <PhPath :size="14" class="entry-icon" aria-hidden="true" />
            <div class="narrative-message" data-testid="transcript-decision-summary">
              <p v-if="decisionNarrative(entry.method)">{{ decisionNarrative(entry.method) }}</p>
            </div>
          </template>

          <!-- 计划摘要 -->
          <button
            v-else-if="entry.kind === 'plan'"
            class="entry plan-entry"
            data-testid="transcript-plan-note"
            @click="emit('open-plan')"
          >
            <PhClipboardText :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              {{ entry.note === "created" ? "已建立执行计划" : "已更新执行计划" }}
              <span class="entry-detail">· {{ entry.itemCount }} 项 · 点击查看</span>
            </span>
          </button>

          <!-- 工具卡（摘要行 + W6-R 可追溯详情 + W3 执行输出按需加载） -->
          <template v-else-if="entry.kind === 'tool'">
            <PhCircleNotch
              v-if="entry.state === 'started' || entry.state === 'requested'"
              :size="14"
              class="entry-icon spin"
              aria-hidden="true"
            />
            <PhWarningCircle
              v-else-if="entry.state === 'failed' || entry.state === 'approval_required'"
              :size="14"
              class="entry-icon"
              :class="toolEntryClass(entry)"
              aria-hidden="true"
            />
            <PhCheckCircle v-else :size="14" class="entry-icon tone-success" aria-hidden="true" />
            <span class="entry-copy action-label">{{ toolActionLabel(entry.name) }}</span>
            <code class="tool-name mono">{{ entry.name }}</code>
            <span v-if="entry.state !== 'completed'" class="entry-state" :class="toolEntryClass(entry)">
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
          <template v-else-if="entry.kind === 'approval'">
            <div
              v-if="entry.resolved || approvalById(entry.approvalId)?.status !== 'pending'"
              class="approval-resolved-line"
              data-testid="approval-card"
            >
              <PhCheckCircle :size="14" class="tone-success" aria-hidden="true" />
              <span>已处理授权</span>
              <code class="mono tool-name">{{ approvalById(entry.approvalId)?.tool_name ?? entry.toolName }}</code>
            </div>
            <div v-else class="approval-card" data-testid="approval-card">
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
              <DiffArtifact
                v-if="approvalPreviews[entry.approvalId] !== undefined || previewLoading.includes(entry.approvalId)"
                :preview="approvalPreviews[entry.approvalId] ?? null"
                :loading="previewLoading.includes(entry.approvalId)"
              />
              <div class="approval-actions">
                <button class="pa-btn pa-btn--primary" :data-testid="`approval-approve-${entry.approvalId}`" @click="emit('approve', entry.approvalId)">
                  批准执行
                </button>
                <button class="pa-btn pa-btn--ghost" :data-testid="`approval-reject-${entry.approvalId}`" @click="emit('reject', entry.approvalId)">
                  拒绝
                </button>
              </div>
            </div>
          </template>

          <!-- 输出校验 -->
          <template v-else-if="entry.kind === 'verification'">
            <PhCheckCircle
              :size="14"
              class="entry-icon"
              :class="`tone-${entry.state === 'passed' ? 'success' : entry.state === 'failed' ? 'danger' : 'info'}`"
              aria-hidden="true"
            />
            <span class="entry-copy">
              {{ entry.state === "started" ? "正在校验输出" : entry.state === "passed" ? "已完成输出校验" : entry.willRetry ? "输出校验未通过，准备重试" : "输出校验未通过" }}
              <span class="entry-detail">· 第 {{ entry.attempt }} 次<template v-if="entry.message"> · {{ entry.message }}</template></span>
            </span>
          </template>

          <!-- 变更集（W2 摘要，W3 扩展 Diff） -->
          <template v-else-if="entry.kind === 'patch-set'">
            <PhGitDiff :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              {{ entry.state === "applied" ? "已应用文件修改" : entry.state === "previewed" ? "已生成文件修改预览" : `文件修改${PATCH_STATE_LABEL[entry.state]?.label ?? entry.state}` }}
              <span class="entry-detail"><template v-if="entry.fileCount !== null">· {{ entry.fileCount }} 个文件</template><template v-if="entry.verified === true"> · 已验证</template><template v-if="entry.reason"> · {{ entry.reason }}</template></span>
            </span>
          </template>

          <!-- 产出（W2 摘要，W3 按需加载内容） -->
          <template v-else-if="entry.kind === 'artifact'">
            <PhFilePlus :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">已生成 {{ entry.title }}<span class="entry-detail"> · {{ entry.artifactKind }}</span></span>
          </template>

          <!-- 完成结果：与执行过程分离，按文档而非状态卡呈现。 -->
          <section v-else-if="entry.kind === 'terminal'" class="terminal-card" data-testid="terminal-summary" :class="`tone-${terminalMeta()?.tone}`">
            <div v-if="processOpen && processSummaryLabels.length" class="process-footer" data-testid="process-footer">
              <PhPath :size="15" aria-hidden="true" />
              <span>已使用</span>
              <span v-for="label in processSummaryLabels" :key="label">{{ label }}</span>
            </div>

            <div v-if="entry.status !== 'completed'" class="result-state" :class="`tone-${terminalMeta()?.tone}`">
              <PhWarningCircle v-if="entry.status === 'failed' || entry.status === 'timed_out'" :size="18" aria-hidden="true" />
              <PhCheckCircle v-else :size="18" aria-hidden="true" />
              <strong>{{ terminalMeta()?.label }}</strong>
              <code v-if="entry.errorCode" class="mono terminal-code">{{ entry.errorCode }}</code>
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

            <div v-if="latestPatchEntry || resultArtifactEntries.length" class="result-assets" aria-label="运行产物">
              <div v-if="latestPatchEntry" class="result-asset-card" data-testid="result-patch-card">
                <span class="result-asset-icon"><PhGitDiff :size="20" aria-hidden="true" /></span>
                <div>
                  <strong>{{ latestPatchEntry.fileCount !== null ? `已编辑 ${latestPatchEntry.fileCount} 个文件` : "文件修改" }}</strong>
                  <span>{{ PATCH_STATE_LABEL[latestPatchEntry.state]?.label ?? latestPatchEntry.state }}</span>
                </div>
                <span v-if="latestPatchEntry.verified" class="result-verified">已验证</span>
              </div>
              <div
                v-for="artifact in resultArtifactEntries"
                :key="artifact.artifactId"
                class="result-asset-card"
                data-testid="result-artifact-card"
              >
                <span class="result-asset-icon"><PhFilePlus :size="20" aria-hidden="true" /></span>
                <div>
                  <strong>{{ artifact.title }}</strong>
                  <span>{{ artifact.artifactKind }}</span>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div v-if="!terminalEntry && processExpanded && processSummaryLabels.length" class="process-footer" data-testid="process-footer">
          <PhPath :size="15" aria-hidden="true" />
          <span>已使用</span>
          <span v-for="label in processSummaryLabels" :key="label">{{ label }}</span>
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
  padding: var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.transcript-scroll > * {
  box-sizing: border-box;
  width: min(1120px, 100%);
  margin-inline: auto;
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
.instruction-targeted .user-copy,
.history-user.instruction-targeted .history-copy {
  border-color: color-mix(in srgb, var(--color-accent) 58%, var(--color-border));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent);
}
.user-bubble[data-instruction-id],
.history-user[data-instruction-id] {
  scroll-margin-block: 72px;
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

.process-toggle {
  display: inline-flex;
  align-self: flex-start;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-fg-muted);
  font: inherit;
  font-size: 16px;
  cursor: pointer;
}
.process-toggle:hover {
  color: var(--color-fg);
}
.process-toggle:focus-visible {
  border-radius: var(--radius-sm);
  outline: var(--focus-ring);
  outline-offset: 3px;
}
.process-caret {
  transition: transform var(--duration-fast, 120ms) ease;
}
.process-caret.open {
  transform: rotate(180deg);
}
.process-divider {
  width: min(900px, 100%);
  height: 1px;
  margin-bottom: var(--space-3);
  background: var(--color-border);
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
  min-height: 36px;
  padding: 6px 0;
  color: var(--color-fg-muted);
  font-size: 15px;
  line-height: var(--leading-normal);
}
.transcript-scroll > .entry {
  width: min(1120px, 100%);
  margin-inline: auto;
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
.entry-detail {
  color: var(--color-fg-subtle);
  font-size: 13px;
}
/* v0.9.0 H0 §8：公开决策摘要（结构化公开事实；不呈现隐藏推理） */
.entry-decision-summary {
  align-items: flex-start;
  max-width: 920px;
  margin: var(--space-2) 0;
  padding: var(--space-2) 0;
  color: var(--color-fg);
}
.entry-decision-summary .entry-icon {
  margin-top: 5px;
  color: var(--color-accent);
}
.narrative-message {
  flex: 1;
  min-width: 0;
}
.narrative-message p {
  margin: 0 0 var(--space-2);
  color: var(--color-fg);
  font-size: 17px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}
.narrative-message p:last-child {
  margin-bottom: 0;
}
.narrative-message .narrative-next {
  color: var(--color-fg-muted);
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
.action-label {
  color: var(--color-fg-muted);
}
.tool-name {
  padding: 1px var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  color: var(--color-fg-subtle);
  font-size: 12px;
}
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
.approval-resolved-line {
  display: flex;
  min-height: 36px;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
  font-size: 15px;
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

/* 结果视图：参考文档式完成页，去除原“输出总结”状态卡。 */
.entry-terminal {
  display: block;
  min-height: 0;
  padding: 0;
}
.entry-terminal > .terminal-card {
  display: flex;
  width: min(900px, 100%);
  flex-direction: column;
  gap: var(--space-3);
  margin: 0 auto;
  padding: var(--space-2) 0 var(--space-8);
  border: 0;
  border-radius: 0;
  background: transparent;
}
.entry-terminal .terminal-output {
  max-height: none;
  overflow: visible;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--color-fg);
  font-size: 17px;
  line-height: 1.75;
  word-break: break-word;
}
.result-state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  color: var(--color-fg);
}
.result-state.tone-danger { color: var(--color-danger-fg); }
.result-state.tone-warning { color: var(--color-warning-fg); }
.process-footer {
  display: flex;
  width: min(900px, 100%);
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin: var(--space-2) 0 var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.process-footer span:not(:first-of-type) {
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-surface-muted);
}
.result-assets {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.result-asset-card {
  display: grid;
  min-height: 66px;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}
.result-asset-icon {
  display: inline-flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  color: var(--color-fg-muted);
}
.result-asset-card > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.result-asset-card strong {
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.result-asset-card div span {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.result-verified {
  padding: 2px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-success) 35%, var(--color-border));
  border-radius: var(--radius-full);
  color: var(--color-success-fg);
  font-size: var(--pa-text-meta);
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
  display: none;
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
