<script setup lang="ts">
/**
 * RunTranscript · v0.8.0 W2
 *
 * 公开进展按模型请求保留，工具与命令默认折叠，待审批操作独立可见。
 * 最终回答保留确定性验收结论；新活动在用户位于底部时自动跟随。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  PhArrowCircleDown,
  PhCaretDown,
  PhCaretRight,
  PhCheckCircle,
  PhCircleNotch,
  PhClipboardText,
  PhClock,
  PhFilePlus,
  PhBookOpenText,
  PhGitDiff,
  PhLightning,
  PhPath,
  PhPencilSimple,
  PhMagnifyingGlass,
  PhWrench,
  PhShieldWarning,
  PhTerminalWindow,
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
import { isTerminalRunStatus } from "../model/runContracts";
import { parseExecutionResult, runResultMeta } from "../model/runOutcome";
import { redactCommandArgs, redactSecretText } from "../model/redaction";
import DiffArtifact from "./DiffArtifact.vue";
import CommandOutput from "./CommandOutput.vue";
import MarkdownContent from "./MarkdownContent.vue";
import { executionText } from "../api/executions";
import { parseWorkspaceFileTarget, type WorkspaceFileTarget } from "../model/outputFiles";

const props = withDefaults(
  defineProps<{
    projection: RunProjection | null;
    history?: Message[];
    searchTarget?: { messageId: number; seq: number } | null;
    phase?: RunConnectionPhase;
    connectionError?: string | null;
    approvals?: RunApprovalRecord[];
    /** W3：审批影响范围预览（父层按需加载；键为 approvalId） */
    approvalPreviews?: Record<string, RunApprovalPreviewRecord | null>;
    previewLoading?: string[];
    /** W3：工具执行结果（键为 toolCallId，按工具名+完成顺序关联） */
    executionByTool?: Record<string, RunExecutionRecord>;
    /** 全量执行记录提供调用次数与公开时序，不推断重试原因。 */
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
  "open-file": [target: WorkspaceFileTarget];
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
const failedParametersByTool = computed<Record<string, { field: string; received: string; hint: string }[]>>(() => {
  const result: Record<string, { field: string; received: string; hint: string }[]> = {};
  const fields = new Set(["query", "content", "rel_path", "glob", "regex", "case_sensitive", "cursor", "limit"]);
  for (const [toolCallId, execution] of Object.entries(props.executionByTool)) {
    if (execution.tool_name !== "search_project_files" || execution.status !== "failed") continue;
    const details = execution.output?.parameter_errors;
    if (!Array.isArray(details)) continue;
    result[toolCallId] = details.slice(0, 8).flatMap((item: unknown) => {
      if (!item || typeof item !== "object") return [];
      const detail = item as Record<string, unknown>;
      if (typeof detail.field !== "string" || !fields.has(detail.field)
        || typeof detail.received !== "string" || detail.received.length > 200
        || typeof detail.hint !== "string" || detail.hint.length > 400) return [];
      return [{ field: detail.field, received: redactSecretText(detail.received), hint: redactSecretText(detail.hint) }];
    });
  }
  return result;
});
const commandExecutionByTool = computed<Record<string, RunExecutionRecord>>(() => {
  const result: Record<string, RunExecutionRecord> = {};
  for (const [toolCallId, execution] of Object.entries(props.executionByTool)) {
    // 读取已有进程的退出码不产生新的命令验证；原始执行卡持续接收其终态。
    if (execution.tool_name === "read_execution") continue;
    const output = execution.output as Record<string, unknown> | null;
    const hasCommandFacts =
      Array.isArray(output?.args) ||
      typeof output?.returncode === "number" ||
      typeof output?.exit_code === "number";
    if (["run_whitelisted_command", "run_project_command", "run_powershell_command"].includes(execution.tool_name) || hasCommandFacts) {
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
const pendingApprovalIds = computed(() => new Set(pendingApprovals.value.map(item => item.id)));

// 长列表分段渲染（计划 §6.4：窗口化/分段，W5 5,000 条压力前提）：
// 默认仅渲染最近 RENDER_BATCH 条，「显示更早」按批次扩展；切换 run 重置。
const RENDER_BATCH = 200;
const visibleCount = ref(RENDER_BATCH);
const processOpen = ref<boolean | null>(null);
function isFinalCandidate(entry: Extract<TranscriptEntry, { kind: "model-output" }>): boolean {
  return entry.phase === "final_answer" || (entry.phase == null && entry.hasToolCalls !== true);
}
const displayEntries = computed(() => {
  const finalText = terminalEntry.value?.output ?? props.projection?.output;
  const normalized = (text: string) => executionText(text).replace(/\r\n?/g, "\n").trim();
  const visible = entries.value.filter(entry => {
    if (entry.kind === "context" || (entry.kind === "verification" && entry.state === "passed")) return false;
    if (entry.kind !== "model-output") return true;
    if (!entry.text.trim()) return false;
    if (!terminalEntry.value || !finalText || entry.state === "interrupted" || !isFinalCandidate(entry)) return true;
    const finalAttempt = props.projection?.finalOutputAttemptId;
    // 新记录用已提交正文的请求标识去重，不能把验收后的替换正文误当成原回答。
    if (finalAttempt !== undefined) return !(finalAttempt && entry.phase === "final_answer" && entry.attemptId === finalAttempt);
    return entry.truncated || normalized(entry.text) !== normalized(finalText);
  });
  const unique: TranscriptEntry[] = [];
  let narrative: { kind: TranscriptEntry["kind"]; text: string; index: number } | null = null;
  for (const entry of visible) {
    const text = entry.kind === "decision-summary" ? decisionNarrative(entry.method)
      : entry.kind === "model-output" && !isFinalCandidate(entry) ? entry.text : null;
    if (text) {
      const signature = normalized(text).replace(/\\([\\`*_{}\[\]()#+.!|>-])/g, "$1").replace(/\s+/g, " ");
      // 兼容事件可能同时携带公开正文与同文决策摘要，只合并相邻的两种来源。
      if (narrative && narrative.kind !== entry.kind && narrative.text === signature) {
        if (entry.kind === "decision-summary") continue;
        unique.splice(narrative.index, 1);
      }
      narrative = { kind: entry.kind, text: signature, index: unique.length };
    } else if (!["model-turn", "run-start", "decision-summary"].includes(entry.kind)) {
      narrative = null;
    }
    unique.push(entry);
  }
  // 重开任务时终态快照可能先于事件到达，最终回答始终排列在活动之后。
  return [...unique.filter(entry => entry.kind !== "terminal"), ...unique.filter(entry => entry.kind === "terminal")];
});
const visibleEntries = computed(() => {
  const start = Math.max(0, displayEntries.value.length - visibleCount.value);
  // 活动分段和整体折叠均不能藏起尚待处理的授权。
  const earlierApprovals = displayEntries.value.slice(0, start).filter(entry =>
    entry.kind === "approval" && !entry.resolved && pendingApprovalIds.value.has(entry.approvalId));
  return [...earlierApprovals, ...displayEntries.value.slice(start)];
});
const hiddenCount = computed(() => displayEntries.value.length - visibleEntries.value.length);
const terminalEntry = computed<Extract<TranscriptEntry, { kind: "terminal" }> | null>(() => {
  for (let index = entries.value.length - 1; index >= 0; index -= 1) {
    const entry = entries.value[index];
    if (entry.kind === "terminal") return entry;
  }
  return null;
});
const terminalContent = computed(() => {
  if (terminalEntry.value?.status === "completed" && props.projection?.structuredOutput) {
    return "```json\n" + JSON.stringify(props.projection.structuredOutput, null, 2) + "\n```";
  }
  return terminalEntry.value?.output ?? props.projection?.output ?? "";
});
const processExpanded = computed(() => processOpen.value ?? terminalEntry.value === null);

function loadEarlier(): void {
  visibleCount.value += RENDER_BATCH * 5;
}

watch(
  () => props.projection?.runId,
  () => {
    visibleCount.value = RENDER_BATCH;
    processOpen.value = null;
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

watch([entryCount, () => props.projection?.lastSequence], async () => {
  if (anchoredBottom.value) {
    await nextTick();
    void scrollToBottom();
  } else {
    newActivity.value = true;
  }
});

watch([() => props.searchTarget?.seq, () => props.history.length, () => props.projection?.runId], async () => {
  const request = props.searchTarget;
  if (!request) return;
  await nextTick();
  const message = props.history.find(item => item.id === request.messageId);
  const target = document.querySelector<HTMLElement>(`[data-message-id="${request.messageId}"]`)
    ?? (message ? document.querySelector<HTMLElement>(message.role === "user" ? '[data-testid="transcript-user-message"]' : '.terminal-output') : null);
  if (target) { anchoredBottom.value = false; target.scrollIntoView?.({ block: "center" }); target.setAttribute("tabindex", "-1"); target.focus({ preventScroll: true }); }
}, { immediate: true });
onMounted(() => { if (!props.searchTarget) void scrollToBottom(); });
onBeforeUnmount(() => {
  clearDurationTimer();
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
  invocation: number | null;
  invocationCount: number;
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
  const labels: Record<string, string> = {
    list_project_directory: "读取项目目录",
    search_project_files: "搜索项目文件",
    read_execution: "读取执行结果",
    propose_project_patch: "生成补丁预览",
    read_patch_preview: "查看补丁预览",
    apply_project_patch: "应用补丁",
  };
  if (labels[name]) return labels[name];
  const normalized = name.toLowerCase();
  if (normalized.includes("browser") || normalized.includes("web")) return "使用了浏览器";
  if (normalized.includes("image") || normalized.includes("screenshot")) return "查看了图像";
  if (normalized.includes("command") || normalized.includes("shell") || normalized.includes("terminal")) return "运行了命令";
  if (normalized.includes("patch") || normalized.includes("write") || normalized.includes("edit")) return "编辑了文件";
  if (normalized.includes("read") || normalized.includes("file")) return "读取了文件";
  if (normalized.includes("search") || normalized.includes("find")) return "搜索了内容";
  return "调用了工具";
}

function toolIcon(name: string) {
  if (/command|shell|terminal|execution/.test(name)) return PhTerminalWindow;
  if (/patch|write|edit/.test(name)) return PhPencilSimple;
  if (/search|find/.test(name)) return PhMagnifyingGlass;
  if (/read|file|directory/.test(name)) return PhBookOpenText;
  return PhWrench;
}

function decisionNarrative(method: string | null): string | null {
  if (!method) return null;
  const text = method.replace(/^本轮决策[：:]\s*/, "").trim();
  // 核心生成的工具名摘要不是模型进展正文，已有工具行承载这些执行事实。
  return /^(调用工具(?:\s|$)|给出最终回答$)/.test(text) ? null : text || null;
}

function shouldDisplayEntry(entry: TranscriptEntry): boolean {
  if (entry.kind === "terminal") return true;
  if (entry.kind === "approval" && !entry.resolved && pendingApprovalIds.value.has(entry.approvalId)) return true;
  if (!processExpanded.value) return false;
  if (entry.kind === "decision-summary") return decisionNarrative(entry.method) !== null;
  if (entry.kind === "verification" && entry.state === "passed") return false;
  return entry.kind !== "run-start" && entry.kind !== "model-turn" && entry.kind !== "context";
}

function toolSummaryState(entry: Extract<TranscriptEntry, { kind: "tool" }>): { label: string; tone: string } | null {
  const execution = props.executionByTool[entry.toolCallId];
  if (entry.state === "failed") {
    return { label: execution?.error_code === "local_tool_rejected" || entry.errorType === "local_tool_rejected"
      ? "请求被拒绝" : "失败", tone: "danger" };
  }
  if (entry.state !== "completed") return TOOL_STATE_LABEL[entry.state];
  if (!commandExecutionByTool.value[entry.toolCallId]) return null;
  const result = execution && parseExecutionResult(execution.execution_result, execution.id);
  if (!result) return { label: "结果未验证", tone: "warning" };
  if (result.outcome === "cancelled") return { label: "已取消", tone: "warning" };
  if (result.outcome === "timed_out") return { label: "命令超时", tone: "danger" };
  if (result.outcome === "failed") return { label: "启动或执行失败", tone: "danger" };
  if (result.outcome === "unknown") return { label: "结果未知", tone: "warning" };
  if (result.validation_outcome === "failed") return { label: result.command_kind === "test" ? "测试失败" : "命令失败", tone: "danger" };
  if (result.validation_outcome === "succeeded") return { label: result.command_kind === "test" ? "测试通过" : "命令通过", tone: "success" };
  return { label: "结果未验证", tone: "warning" };
}

function toolHasWarning(entry: Extract<TranscriptEntry, { kind: "tool" }>): boolean {
  const warnings = props.executionByTool[entry.toolCallId]?.output?.runtime_warnings;
  return Array.isArray(warnings) && warnings.some(warning => warning && typeof warning === "object"
    && warning.code === "python_path_resolution_warning");
}

/** 同名工具的调用序号不表示失败后的重试，也不推断参数相同。 */
function executionInvocation(execution: RunExecutionRecord): { invocation: number; total: number } {
  const sameName = props.executions.filter((item) => item.tool_name === execution.tool_name);
  if (sameName.length < 2) return { invocation: 1, total: sameName.length };
  const index = sameName.findIndex((item) => item.id === execution.id);
  return { invocation: index + 1, total: sameName.length };
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
      invocation: null,
      invocationCount: 0,
      commandText: null,
      resultSummary: null,
    };
  }
  const { invocation, total } = executionInvocation(execution);
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
    invocation: total >= 2 && invocation > 0 ? invocation : null,
    invocationCount: total,
    commandText: args.length ? redactCommandArgs(args) : null,
    resultSummary: executionResultSummary(execution),
  };
}

function terminalMeta(): { label: string; tone: string } | null {
  const status = props.projection?.status;
  if (!status) return null;
  const meta = runResultMeta(status, props.projection?.runOutcome, props.projection?.verifying);
  return { label: meta.label, tone: meta.tone };
}

const clockNow = ref(Date.now());
let durationTimer: number | null = null;
function clearDurationTimer(): void {
  if (durationTimer !== null) window.clearInterval(durationTimer);
  durationTimer = null;
}
watch(
  () => [props.projection?.runId, props.projection?.startedAt, props.projection?.status],
  () => {
    clearDurationTimer();
    clockNow.value = Date.now();
    const current = props.projection;
    if (current?.startedAt && Number.isFinite(Date.parse(current.startedAt)) && !isTerminalRunStatus(current.status)) {
      durationTimer = window.setInterval(() => { clockNow.value = Date.now(); }, 1000);
    }
  },
  { immediate: true }
);
const runDurationLabel = computed(() => {
  const current = props.projection;
  if (!current?.startedAt) return null;
  if (isTerminalRunStatus(current.status)) return formatDuration(current.startedAt, current.completedAt);
  return formatDurationMs(clockNow.value - Date.parse(current.startedAt));
});
const processDurationLabel = computed(() => {
  const ended = props.projection && isTerminalRunStatus(props.projection.status);
  if (!runDurationLabel.value) return ended ? "用时待同步" : "执行中 · 计时待同步";
  return `${ended ? "用时" : "已用时"} ${runDurationLabel.value}`;
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
      <div class="transcript-content">
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
            :data-message-id="message.id"
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
            <div class="history-copy" :class="{ 'assistant-response': message.role === 'assistant' }">
              <MarkdownContent v-if="message.role === 'assistant'" :content="message.content" copy-control="icon" @open-file="emit('open-file', $event)" />
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
          :aria-label="`${processExpanded ? '收起' : '展开'}执行过程，${processDurationLabel}`"
          @click="processOpen = !processExpanded"
        >
          <span class="process-duration" data-testid="run-duration">{{ processDurationLabel }}</span>
          <PhCaretRight :size="15" class="process-caret" :class="{ open: processExpanded }" aria-hidden="true" />
        </button>
        <div class="process-divider" aria-hidden="true" />

        <details v-if="projection.completionRequirements?.length" v-show="processExpanded" class="task-requirements" data-testid="completion-requirements">
          <summary>任务要求 · {{ projection.completionRequirements.length }} 项</summary>
          <ul><li v-for="requirement in projection.completionRequirements" :key="requirement.requirement_id">{{ requirement.description }}</li></ul>
          <span>自动提取的要求不代表额外操作授权；理解有误时可停止任务并补充说明。</span>
        </details>

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
              <span class="entry-detail">· {{ entry.estimatedTokens === null ? '估算暂不可用' : `约 ${entry.estimatedTokens.toLocaleString()} tokens` }}</span>
            </span>
          </template>

          <template v-else-if="entry.kind === 'context-compaction'">
            <PhClipboardText :size="17" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy" :class="{ 'tone-danger': entry.state === 'failed' }">
              {{ entry.state === 'started' ? '正在压缩上下文' : entry.state === 'completed' ? '上下文已压缩' : '上下文压缩失败' }}
              <span v-if="entry.message" class="entry-detail"> · {{ redactSecretText(entry.message) }}</span>
            </span>
          </template>

          <!-- 模型轮次（摘要折叠） -->
          <template v-else-if="entry.kind === 'model-turn'">
            <PhLightning :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              模型第 {{ entry.ordinal }} 轮
              <template v-if="entry.state === 'completed'">
                <template v-if="entry.usageComplete === false"> · 用量未知</template>
                <template v-else> · {{ entry.outputTokens.toLocaleString() }} 输出 tokens</template><template v-if="entry.latencyMs !== null"> · {{ Math.round(entry.latencyMs) }}ms</template>
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

          <!-- 逐轮公开正文与工具按原顺序呈现；候选回答不替代最终验收。 -->
          <template v-else-if="entry.kind === 'model-output'">
            <details v-if="terminalEntry && isFinalCandidate(entry) && entry.state !== 'interrupted'"
              class="model-candidate" data-testid="model-candidate-output">
              <summary>查看验收前的公开回答</summary>
              <p v-if="entry.truncated" class="model-output-notice" data-testid="model-output-truncated">公开输出较长，此处仅保留末尾 64,000 字符，内容不完整。</p>
              <MarkdownContent :content="executionText(entry.text)" copy-control="none" @open-file="emit('open-file', $event)" />
            </details>
            <section v-else class="model-public-output" data-testid="model-public-output">
              <span v-if="entry.state === 'interrupted'" class="model-output-interrupted">公开输出已中断，内容不完整</span>
              <p v-if="entry.truncated" class="model-output-notice" data-testid="model-output-truncated">公开输出较长，此处仅保留末尾 64,000 字符，内容不完整。</p>
              <MarkdownContent :content="executionText(entry.text)" copy-control="none" @open-file="emit('open-file', $event)" />
            </section>
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

          <!-- 工具摘要默认折叠；异常与待处理状态留在摘要，完整证据按需展开。 -->
          <template v-else-if="entry.kind === 'tool'">
            <details :key="`${projection.runId}:${entry.key}`" class="tool-disclosure">
              <summary data-testid="tool-toggle">
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
                <PhTerminalWindow v-else-if="commandExecutionByTool[entry.toolCallId]" :size="16" class="entry-icon" aria-hidden="true" />
                <component :is="toolIcon(entry.name)" v-else :size="17" class="entry-icon" aria-hidden="true" />
                <span class="entry-copy action-label">{{ entry.state === 'completed' && toolDetail(entry).commandText ? '已运行' : toolActionLabel(entry.name) }}</span>
                <span v-if="toolDetail(entry).commandText" class="tool-command-preview" data-testid="tool-command-preview" :title="toolDetail(entry).commandText ?? undefined">{{ toolDetail(entry).commandText }}</span>
                <span v-if="toolSummaryState(entry)" class="tool-summary-state" :class="`tone-${toolSummaryState(entry)?.tone}`">
                  {{ toolSummaryState(entry)?.label }}
                </span>
                <span v-if="toolHasWarning(entry)" class="tool-summary-warning">Python 路径解析警告</span>
                <PhCaretDown :size="13" class="tool-caret" aria-hidden="true" />
              </summary>
              <div class="tool-detail-body">
                <code class="tool-name mono">{{ entry.name }}</code>
                <span v-if="toolDetail(entry).invocation !== null" class="entry-invocation" data-testid="tool-invocation">
                  调用 {{ toolDetail(entry).invocation }}/{{ toolDetail(entry).invocationCount }}
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
                <details v-if="failedParametersByTool[entry.toolCallId]?.length" class="entry-parameters" data-testid="tool-parameters">
                  <summary>查看失败参数</summary>
                  <div v-for="parameter in failedParametersByTool[entry.toolCallId]" :key="parameter.field">
                    <p><code>{{ parameter.field }}</code>：{{ parameter.received }}</p>
                    <p>{{ parameter.hint }}</p>
                  </div>
                </details>
                <CommandOutput
                  v-if="commandExecutionByTool[entry.toolCallId]"
                  :execution="commandExecutionByTool[entry.toolCallId]"
                  :page="outputPages[commandExecutionByTool[entry.toolCallId].id] ?? null"
                  :loading="outputLoading.includes(commandExecutionByTool[entry.toolCallId].id)"
                  class="entry-execution"
                  @load="emit('load-output', commandExecutionByTool[entry.toolCallId].id)"
                />
              </div>
            </details>
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
              {{ entry.state === "started" ? "正在校验输出" : entry.state === "unverified" ? "核验结束，保留未验证项" : entry.state === "passed" ? "已完成输出校验" : entry.willRetry ? "输出校验未通过，准备重试" : "输出校验未通过" }}
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
            <p :class="{ 'terminal-result-ok': !['warning', 'danger'].includes(terminalMeta()?.tone ?? '') }"
              class="terminal-attention" :data-testid="entry.status !== 'completed' || ['warning', 'danger'].includes(terminalMeta()?.tone ?? '') ? 'terminal-attention' : 'terminal-result-label'" role="status">
              {{ terminalMeta()?.label }}
              <code v-if="entry.errorCode" class="mono terminal-code">{{ entry.errorCode }}</code>
            </p>
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
              v-if="terminalContent || latestPatchEntry || resultArtifactEntries.length || $slots['result-files']"
              class="terminal-output assistant-response"
              data-testid="terminal-output"
            ><MarkdownContent :content="terminalContent" copy-control="icon" @open-file="emit('open-file', $event)">
              <template #after-content>
                <slot name="result-files" />
                <div v-if="(!$slots['result-files'] && latestPatchEntry) || resultArtifactEntries.length" class="result-assets" aria-label="运行产物">
                  <div v-if="!$slots['result-files'] && latestPatchEntry" class="result-asset-card" data-testid="result-patch-card">
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
                    <button v-if="artifact.relPath && parseWorkspaceFileTarget(artifact.relPath)" type="button" class="pa-btn pa-btn--subtle result-open-file"
                      :aria-label="`查看产物 ${artifact.title}`" @click="emit('open-file', parseWorkspaceFileTarget(artifact.relPath)!)">查看文件</button>
                  </div>
                </div>
              </template>
            </MarkdownContent></div>
          </section>
        </div>

        <!-- 断线重连提示（仅存在 durable run 时；创建失败由阻塞卡片呈现，
             v0.9.0 H1-B §5.6：不显示无 run 的误导性重连提示） -->
        <div v-if="(phase === 'reconnecting' || connectionError) && projection" class="stream-notice" data-testid="stream-reconnect-notice">
          <PhClock :size="14" aria-hidden="true" />
          <span>连接中断，正在重连…（任务在本地继续执行，已完成步骤不会丢失）</span>
          <button class="notice-btn" @click="emit('retry-stream')">立即重试</button>
        </div>
        <div v-else-if="phase === 'streaming' && projection?.status !== 'paused'" class="stream-live" data-testid="stream-live">
          <PhCircleNotch :size="12" class="spin" aria-hidden="true" />
          <span>正在思考</span>
        </div>

        <!-- 静态预览标记 -->
        <div v-if="previewMode" class="preview-tag">RUN PREVIEW</div>
        </template>
      </template>
      <div v-if="$slots.default" class="transcript-panels" data-testid="transcript-panels"><slot /></div>
      </div>
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
  background: var(--color-surface);
}
.transcript-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-5) var(--space-5) var(--space-8);
}
.transcript-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 100%;
  box-sizing: border-box;
  width: min(var(--coding-content-width, 860px), 100%);
  margin-inline: auto;
}
.transcript-content > * { flex-shrink: 0; min-width: 0; max-width: 100%; }
.transcript-panels { display: grid; gap: var(--space-3); margin-top: var(--space-4); }
.task-requirements { margin: var(--space-3) 0; color: var(--color-fg-muted); font-size: var(--pa-text-meta); }
.task-requirements summary { padding-block: var(--space-2); cursor: pointer; }
.task-requirements ul { padding-left: var(--space-5); }
.model-public-output .markdown-content { color: var(--color-fg); }
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
  margin-bottom: var(--space-5);
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
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-accent-soft);
  color: var(--color-fg);
  font-size: var(--pa-text-body);
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
  margin-bottom: var(--space-5);
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
.history-copy:not(.assistant-response) {
  max-width: 76%;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
}
.history-system .history-copy {
  max-width: 100%;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
}
.history-user .history-copy { background: var(--color-accent-soft); }

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
.process-duration {
  font-variant-numeric: tabular-nums;
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
  transform: rotate(90deg);
}
.process-divider {
  width: 100%;
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
.entry-model-output {
  display: block;
  padding: var(--space-2) 0 var(--space-3);
  color: var(--color-fg);
}
.entry-model-output .model-public-output,
.model-candidate {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  color: var(--color-fg);
  font-size: 16px;
  line-height: 1.75;
  overflow-wrap: anywhere;
}
.model-candidate > summary {
  margin-bottom: var(--space-2);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.model-public-output > .model-output-interrupted,
.model-output-notice {
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
}
.model-output-notice { margin: 0 0 var(--space-2); }
.result-open-file { white-space: nowrap; }
.tool-disclosure {
  width: 100%;
  min-width: 0;
}
.tool-disclosure > summary {
  display: flex;
  width: fit-content;
  max-width: 100%;
  min-height: 30px;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--color-fg-muted);
  font-size: 16px;
  list-style: none;
  cursor: pointer;
}
.tool-disclosure > summary::-webkit-details-marker { display: none; }
.tool-disclosure > summary:hover { color: var(--color-fg); }
.tool-disclosure > summary:focus-visible,
.model-candidate > summary:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 3px;
}
.tool-caret { transition: transform var(--duration-fast, 120ms) ease; }
.tool-command-preview { flex: 1; min-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tool-disclosure:has(.tool-command-preview) > summary { width: 100%; flex-wrap: nowrap; }
.tool-disclosure[open] > summary .tool-caret { transform: rotate(180deg); }
.tool-summary-state,
.tool-summary-warning { font-size: var(--pa-text-meta); }
.tool-summary-state.tone-info { color: var(--color-accent); }
.tool-summary-state.tone-success { color: var(--color-success-fg); }
.tool-summary-state.tone-danger { color: var(--color-danger-fg); }
.tool-summary-state.tone-warning,
.tool-summary-warning { color: var(--color-warning-fg); }
.tool-detail-body {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin: var(--space-1) 0 var(--space-2) 7px;
  padding: var(--space-2) 0 var(--space-2) var(--space-3);
  border-left: 1px solid var(--color-border);
}
.tool-detail-body .entry-execution { width: 100%; margin-left: 0; }
.tool-detail-body :deep(.output-head) { flex-wrap: wrap; }
.tool-detail-body :deep(.output-status) { flex-shrink: 0; white-space: nowrap; }
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
.entry-invocation {
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
.entry-parameters {
  flex-basis: 100%;
  min-width: 0;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  overflow-wrap: anywhere;
}
.entry-parameters summary {
  color: var(--color-accent);
  cursor: pointer;
}
.entry-parameters p { margin: var(--space-2) 0; }
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
  gap: var(--space-3);
  margin: var(--space-2) 0;
  padding: var(--space-4);
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
  flex-wrap: wrap;
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
  width: 100%;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0 auto;
  padding: var(--space-2) 0 var(--space-3);
  border: 0;
  border-radius: 0;
  background: transparent;
}
.entry-terminal .assistant-response,
.history-assistant .assistant-response {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  max-height: none;
  overflow: visible;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--color-fg);
  font-size: 16px;
  line-height: 1.75;
  word-break: break-word;
  white-space: normal;
}
.terminal-attention { margin: 0; color: var(--color-warning-fg); font-size: 15px; }
.terminal-card.tone-danger .terminal-attention { color: var(--color-danger-fg); }
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
  .tool-caret { transition: none; }
  .process-caret { transition: none; }
}
@media (max-width: 760px) {
  .transcript-scroll { padding: var(--space-3) var(--space-3) var(--space-5); }
  .terminal-usage {
    margin-left: 0;
  }
  .audit-head {
    flex-direction: column;
  }
}
.terminal-result-ok { color: var(--color-fg-muted); font-size: 12px; }
</style>
