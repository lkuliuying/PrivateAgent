<script setup lang="ts">
/**
 * CodingThreadWorkspace · v0.8.0 W3
 *
 * 任务页组装：ThreadHeader + RunTranscript + RunPlanPopover + CodingComposer
 * + ContextDrawer。run 生命周期由 useRunStream 管理（App.vue :key 按 thread
 * 重建，切换任务即卸载清理）。W3 增补：审批影响范围预览自动加载（Diff），
 * 工具执行输出按需加载与轮询（finished 后停表，卸载清理），@ 上下文发现
 * 经注入 searchFiles 传入 Composer（API 不进组件）。
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { PhChatsCircle, PhWarningCircle } from "@phosphor-icons/vue";
import { pickFile } from "../../../api";
import type { View } from "../../../types";
import type { Message } from "../../../types";
import PaEmptyState from "../../../design/PaEmptyState.vue";
import PaButton from "../../../design/PaButton.vue";
import { useNotifications } from "../../../stores/notifications";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";
import { useRunStream } from "../composables/useRunStream";
import { describeRunBlocker } from "../model/runBlocking";
import type {
  RunApprovalPreviewRecord,
  RunApprovalRecord,
  RunExecutionOutputPage,
  RunExecutionRecord,
} from "../model/runContracts";
import { isTerminalRunStatus } from "../model/runContracts";
import type { RunProjection } from "../model/runProjector";
import type { CodingInstructionMarker } from "../model/contracts";
import {
  approveRunApproval,
  fetchRunApprovalPreview,
  fetchRunApprovals,
  fetchRunExecutionOutput,
  fetchRunExecutions,
  rejectRunApproval,
} from "../api/runs";
import {
  attachCodingProjectFile,
  fetchCodingWorkspacePath,
  searchCodingProjectFiles,
} from "../api/projects";
import {
  createFullAccessGrant,
  fetchFullAccessGrant,
} from "../api/fullAccess";
import {
  fetchCodingThreadMessages,
  fetchLatestCodingThreadRunId,
} from "../api/threads";
import ThreadHeader from "./ThreadHeader.vue";
import RunTranscript from "./RunTranscript.vue";
import RunPlanPopover from "./RunPlanPopover.vue";
import ContextDrawer from "./ContextDrawer.vue";
import CodingComposer, { type CodingComposerSendPayload } from "./CodingComposer.vue";

const props = withDefaults(
  defineProps<{
    store?: CodingWorkspaceStore;
  }>(),
  {
    store: () => useCodingWorkspace(),
  }
);

const emit = defineEmits<{
  navigate: [view: View];
  /** v0.9.0 H1-D（§5.8）：模型类阻塞 → 进入同一模型管理区（带 returnTo） */
  "configure-provider": [];
}>();
const notify = useNotifications();

const thread = computed(() => props.store.selectedThread.value);
const project = computed(() => props.store.selectedProject.value);
const workspace = computed(() => props.store.selectedWorkspace.value);
const workspacePath = ref<string | null>(null);
const workspacePathLoading = ref(false);
const workspacePathRequested = ref(false);
let workspacePathSeq = 0;
let workspacePathForId: number | null = null;

const branchLabel = computed(() => {
  const current = workspace.value;
  if (!current) return "";
  return current.branchName ?? (current.kind === "root" ? "根工作区" : "工作区");
});

watch(
  () => workspace.value?.id ?? null,
  () => {
    workspacePathSeq += 1;
    workspacePath.value = null;
    workspacePathLoading.value = false;
    workspacePathRequested.value = false;
    workspacePathForId = null;
  }
);

async function requestWorkspacePath(): Promise<void> {
  const currentProject = project.value;
  const currentWorkspace = workspace.value;
  workspacePathRequested.value = true;
  if (!currentProject || !currentWorkspace || workspacePathLoading.value) return;
  if (workspacePathForId === currentWorkspace.id && workspacePath.value) return;
  const mine = ++workspacePathSeq;
  workspacePathLoading.value = true;
  try {
    const path = await fetchCodingWorkspacePath(currentProject.id, currentWorkspace.id);
    if (mine !== workspacePathSeq || workspace.value?.id !== currentWorkspace.id) return;
    workspacePath.value = path;
    workspacePathForId = currentWorkspace.id;
  } catch {
    if (mine !== workspacePathSeq) return;
    workspacePath.value = null;
  } finally {
    if (mine === workspacePathSeq) workspacePathLoading.value = false;
  }
}

// ============ run 流（真实计划/工具/审批/终态均来自 durable 事件） ============
const stream = useRunStream();
const durableHistory = shallowRef<Message[]>([]);
let hydrationSeq = 0;
const planOpen = ref(false);
const contextOpen = ref(false);
const cancelling = ref(false);
const lastPermissionMode = ref<string | null>(null);
const approvalRecords = shallowRef<RunApprovalRecord[]>([]);
const instructionMarkers = ref<CodingInstructionMarker[]>([]);
const instructionTarget = ref<{ id: string; seq: number } | null>(null);
let instructionTargetSeq = 0;

// ?coding-run-preview=<state>：任务页事件流静态预览（W0 矩阵 L2，生产不进入）
const previewKey = import.meta.env.DEV
  ? new URLSearchParams(window.location.search).get("coding-run-preview")
  : null;
const previewProjection = shallowRef<RunProjection | null>(null);
const previewMode = ref(false);
if (previewKey) {
  void import("../dev/codingRunPreview").then((module) => {
    const keys: readonly string[] = module.CODING_RUN_PREVIEW_KEYS;
    if (keys.includes(previewKey)) {
      const fixture = module.createStaticProjection(
        previewKey as Parameters<typeof module.createStaticProjection>[0]
      );
      previewProjection.value = fixture.projection;
      approvalPreviews.value = fixture.approvalPreviews ?? {};
      executions.value = fixture.executions ?? [];
      outputPages.value = fixture.outputPages ?? {};
      previewMode.value = true;
    }
  });
}

const projection = computed(() => previewProjection.value ?? stream.projection.value);
const phase = computed(() => (previewMode.value ? "idle" : stream.phase.value));
const connectionError = computed(() => (previewMode.value ? null : stream.connectionError.value));
const composerInputHistory = computed(() => {
  const messages = durableHistory.value
    .filter((message) => message.role === "user" && message.content.trim().length > 0)
    .map((message) => message.content);
  const current = projection.value?.userMessage;
  // 当前 run 创建后消息可能尚未重新拉入 durableHistory；按值只补尾项，
  // 重开任务时则避免把同一轮输入重复放进 ↑/↓ 历史。
  if (current && messages[messages.length - 1] !== current) messages.push(current);
  return messages;
});

/**
 * 消息表拉取的安全包装：后端/模拟层返回非数组时回落空数组，
 * 不得把非法载荷写进 durableHistory（否则击穿 RunTranscript 渲染）。
 */
async function fetchThreadMessagesSafe(threadId: number): Promise<Message[]> {
  const messages = await fetchCodingThreadMessages(threadId);
  return Array.isArray(messages) ? messages : [];
}

/**
 * 任务重开：消息表恢复更早对话，last_run_id（或旧版事实表兜底）恢复最近
 * run 的详细活动。世代令牌防止切换任务后的迟到请求污染新页面。
 */
async function hydrateSelectedThread(): Promise<void> {
  const current = thread.value;
  if (!current || previewMode.value) return;
  const mine = ++hydrationSeq;
  const messagesPromise = fetchCodingThreadMessages(current.id);
  const runIdPromise = current.lastRunId
    ? Promise.resolve(current.lastRunId)
    : fetchLatestCodingThreadRunId(current.id);
  const [messagesResult, runIdResult] = await Promise.allSettled([
    messagesPromise,
    runIdPromise,
  ]);
  if (mine !== hydrationSeq || thread.value?.id !== current.id) return;
  const rawMessages =
    messagesResult.status === "fulfilled" ? messagesResult.value : [];
  durableHistory.value = Array.isArray(rawMessages) ? rawMessages : [];
  const runId = runIdResult.status === "fulfilled" ? runIdResult.value : null;
  if (!runId) return;
  // 旧版任务没有 messages 行时，任务标题就是首轮输入的可靠 UI 事实源。
  const lastUserMessage = [...durableHistory.value]
    .reverse()
    .find((message) => message.role === "user")?.content;
  props.store.recordThreadRun(current.id, runId);
  await stream.attachRun(runId, lastUserMessage ?? current.title);
}

watch(
  () => thread.value?.id ?? null,
  async (threadId) => {
    hydrationSeq += 1;
    durableHistory.value = [];
    instructionMarkers.value = [];
    instructionTarget.value = null;
    stream.detach();
    if (threadId === null) return;
    await hydrateSelectedThread();
    if (thread.value?.id !== threadId) return;
    const firstTurn = props.store.takePendingFirstTurn(threadId);
    if (!firstTurn) return;
    const allowed = await guardFullAccess(firstTurn);
    if (allowed) {
      await send(firstTurn);
      return;
    }
    restoreSeq += 1;
    restoreRequest.value = { message: firstTurn.message, seq: restoreSeq };
  },
  { immediate: true }
);

// ============ v0.9.0 H1-B（计划 §5.6）：创建失败关闭与恢复入口 ============
// 阻塞项不得静默隐藏：创建失败时原位展示具体阻塞项 + 可操作恢复入口；
// 同时把未成功的输入回填草稿（不丢失），重试/配置往返不产生假完成记录。
const createBlocker = computed(() => {
  if (previewMode.value || stream.phase.value !== "error") return null;
  return describeRunBlocker(stream.createErrorCode.value);
});
const lastSentPayload = ref<CodingComposerSendPayload | null>(null);
const restoreRequest = ref<{ message: string; seq: number } | null>(null);
let restoreSeq = 0;

watch(
  () => stream.phase.value,
  (next, previous) => {
    if (next === "error" && previous === "starting" && lastSentPayload.value) {
      restoreSeq += 1;
      restoreRequest.value = {
        message: lastSentPayload.value.message,
        seq: restoreSeq,
      };
    }
  }
);

async function retryBlockedSend(): Promise<void> {
  const payload = lastSentPayload.value;
  if (!payload) return;
  await send(payload);
}

function recoverFromBlocker(): void {
  const blocker = createBlocker.value;
  if (!blocker) return;
  switch (blocker.recovery) {
    case "configure-model":
      // 配置往返保留当前会话与草稿（回填已在上述 watch 完成）；
      // H1-D：模型类阻塞定位到同一模型管理区，保存后原位解除阻塞。
      emit("configure-provider");
      return;
    case "select-project":
    case "reauthorize":
      backToHome();
      return;
    default:
      void retryBlockedSend();
  }
}

const runStatus = computed(() => projection.value?.status ?? null);
const runActive = computed(() => {
  const status = runStatus.value;
  return !previewMode.value && status !== null && !isTerminalRunStatus(status);
});

// ============ 审批：详情 + 影响范围预览（W3：审批显示完整影响范围） ============
async function refreshApprovals(): Promise<void> {
  const runId = stream.projection.value?.runId;
  if (!runId) {
    approvalRecords.value = [];
    return;
  }
  try {
    approvalRecords.value = await fetchRunApprovals(runId);
  } catch {
    // 审批详情拉取失败不阻断事件流；按钮仍可用（approve/reject 幂等收敛）
  }
}

const approvalPreviews = ref<Record<string, RunApprovalPreviewRecord | null>>({});
const previewLoading = ref<string[]>([]);

async function ensureApprovalPreviews(): Promise<void> {
  const runId = stream.projection.value?.runId;
  if (!runId) return;
  const pending = approvalRecords.value.filter(
    (item) =>
      (item.status === "pending" || item.status === "consumed") &&
      !(item.id in approvalPreviews.value)
  );
  for (const item of pending) {
    previewLoading.value = [...previewLoading.value, item.id];
    try {
      approvalPreviews.value = {
        ...approvalPreviews.value,
        [item.id]: await fetchRunApprovalPreview(runId, item.id),
      };
    } catch {
      approvalPreviews.value = { ...approvalPreviews.value, [item.id]: null };
    } finally {
      previewLoading.value = previewLoading.value.filter((id) => id !== item.id);
    }
  }
}

const pendingApprovalKey = computed(() => {
  const current = stream.projection.value;
  if (!current) return "";
  return current.entries
    .filter((entry) => entry.kind === "approval")
    .map((entry) => (entry.kind === "approval" ? `${entry.approvalId}:${entry.resolved ? 1 : 0}` : ""))
    .join(",");
});

watch(pendingApprovalKey, (next, previous) => {
  if (next && next !== previous && !previewMode.value) {
    void refreshApprovals().then(() => ensureApprovalPreviews());
  }
});

async function onApprove(approvalId: string): Promise<void> {
  const runId = stream.projection.value?.runId;
  if (!runId) return;
  try {
    await approveRunApproval(runId, approvalId);
  } finally {
    void refreshApprovals();
  }
}

async function onReject(approvalId: string): Promise<void> {
  const runId = stream.projection.value?.runId;
  if (!runId) return;
  try {
    await rejectRunApproval(runId, approvalId);
  } finally {
    void refreshApprovals();
  }
}

// ============ 工具执行输出（W3：按需加载 + finished 前轮询，卸载清理） ============
const executions = shallowRef<RunExecutionRecord[]>([]);
const executionsLoadedForRun = ref<string | null>(null);
const outputPages = shallowRef<Record<string, RunExecutionOutputPage | null>>({});
const outputLoading = ref<string[]>([]);
let outputPollTimer: number | null = null;

/** executions 无 tool_call_id：按工具名 + 完成顺序与 transcript 工具条目关联 */
const executionByTool = computed<Record<string, RunExecutionRecord>>(() => {
  const current = projection.value;
  const map: Record<string, RunExecutionRecord> = {};
  if (!current) return map;
  const byName = new Map<string, number>();
  for (const execution of executions.value) {
    const nextIndex = byName.get(execution.tool_name) ?? 0;
    byName.set(execution.tool_name, nextIndex + 1);
    const matches = current.entries.filter(
      (entry) => entry.kind === "tool" && entry.name === execution.tool_name
    );
    const target = matches[nextIndex];
    if (target && target.kind === "tool") {
      map[target.toolCallId] = execution;
    }
  }
  return map;
});

async function loadExecutions(): Promise<void> {
  const runId = stream.projection.value?.runId;
  if (!runId || executionsLoadedForRun.value === runId) return;
  executionsLoadedForRun.value = runId;
  try {
    executions.value = await fetchRunExecutions(runId);
  } catch {
    executions.value = [];
  }
}

// 终态或出现已完成工具时拉取一次执行结果（脱敏持久层，不依赖流）
watch(
  () => [projection.value?.status, projection.value?.entries.filter((e) => e.kind === "tool" && e.state === "completed").length] as const,
  () => {
    if (!previewMode.value && projection.value?.runId) void loadExecutions();
  },
  { immediate: true }
);

async function loadOutput(executionId: string): Promise<void> {
  const runId = stream.projection.value?.runId;
  if (!runId || outputLoading.value.includes(executionId)) return;
  outputLoading.value = [...outputLoading.value, executionId];
  try {
    const previous = outputPages.value[executionId];
    const after = previous ? previous.last_seq : -1;
    const page = await fetchRunExecutionOutput(runId, executionId, after);
    outputPages.value = { ...outputPages.value, [executionId]: page };
  } catch {
    // 输出拉取失败保留已加载页；用户可再次触发
  } finally {
    outputLoading.value = outputLoading.value.filter((id) => id !== executionId);
    scheduleOutputPoll();
  }
}

function scheduleOutputPoll(): void {
  const unfinished = Object.entries(outputPages.value)
    .filter(([, page]) => page && !page.finished)
    .map(([id]) => id);
  if (!unfinished.length) {
    if (outputPollTimer !== null) {
      window.clearTimeout(outputPollTimer);
      outputPollTimer = null;
    }
    return;
  }
  if (outputPollTimer !== null) return;
  outputPollTimer = window.setTimeout(() => {
    outputPollTimer = null;
    for (const id of unfinished) void loadOutput(id);
  }, 1500);
}

onBeforeUnmount(() => {
  hydrationSeq += 1;
  workspacePathSeq += 1;
  if (outputPollTimer !== null) {
    window.clearTimeout(outputPollTimer);
    outputPollTimer = null;
  }
});

// ============ 输入器（W3 CodingComposer：权限/模型/推理/@ 上下文/草稿） ============
const composerBusy = computed(
  () => !previewMode.value && ["starting", "streaming", "reconnecting"].includes(stream.phase.value)
);

/**
 * v0.9.0 H1-A：full_access 二次确认守卫（H0 §6.3）。
 * - 已有有效授予 → 直接放行；
 * - 无授予 → 向用户显式说明范围/有效期/边界并二次确认；确认后创建授予；
 * - 拒绝或授予失败 → 中止发送（保留草稿），不得静默降级执行。
 */
async function guardFullAccess(payload: CodingComposerSendPayload): Promise<boolean> {
  if (payload.permissionMode !== "full_access") return true;
  const current = thread.value;
  if (!current) return false;
  try {
    const state = await fetchFullAccessGrant(current.id);
    if (state.active) return true;
    const confirmed = await notify.confirm({
      title: "为当前会话启用完全访问？",
      message:
        "有效期 4 小时；切换项目、退出应用或手动撤销后立即失效。不获得管理员权限，也不绕过系统权限。",
      impact:
        "当前系统用户可访问的本机文件与常规命令将免逐次审批；凭据、秘密与远程外发仍受硬边界约束并保留审计。",
      confirmLabel: "启用完全访问",
      danger: true,
    });
    if (!confirmed) return false;
    const granted = await createFullAccessGrant(current.id);
    return granted.active;
  } catch {
    // 能力位关闭/授予失败：失败关闭，不静默以更高权限执行
    return false;
  }
}

async function send(payload: CodingComposerSendPayload): Promise<void> {
  const currentThread = thread.value;
  if (!currentThread) return;
  const projectId = props.store.selectedProjectId.value ?? currentThread.projectId;
  const workspaceId = props.store.selectedWorkspaceId.value ?? currentThread.workspaceId;
  if (projectId === null || workspaceId === null) return;
  lastPermissionMode.value = payload.permissionMode;
  lastSentPayload.value = payload;
  // 新一轮会替换当前 run 投影；先收进已完成的上一轮对话，保证同一任务内
  // 连续发送时旧问答仍留在 transcript。读取失败不阻断本轮执行。
  if (stream.projection.value) {
    try {
      durableHistory.value = await fetchThreadMessagesSafe(currentThread.id);
    } catch {
      // 保留现有历史；运行创建仍按后端事实收敛。
    }
  }
  await stream.startRun({
    session_id: currentThread.id,
    message: payload.message,
    project_id: projectId,
    workspace_id: workspaceId,
    permission_mode: payload.permissionMode,
    model_profile_id: payload.modelProfileId ?? undefined,
    reasoning_effort: payload.reasoningEffort ?? undefined,
  });
  const createdRunId = stream.projection.value?.runId;
  if (createdRunId && thread.value?.id === currentThread.id) {
    props.store.recordThreadRun(
      currentThread.id,
      createdRunId,
      new Date().toISOString()
    );
    // run 创建会持久化本轮 user 消息。创建成功后立即重新同步消息表，让
    // transcript 能明确区分“更早对话”和当前活动流；RunTranscript 只裁掉
    // 当前 run 的最后一份持久化副本，不再依赖发送前的旧快照。
    try {
      durableHistory.value = await fetchThreadMessagesSafe(currentThread.id);
    } catch {
      // 事件流仍是当前 run 的事实源；消息同步失败留待下次重开恢复。
    }
  }
}

function searchFiles(query: string) {
  const projectId = props.store.selectedProjectId.value;
  if (projectId === null) return Promise.resolve([]);
  return searchCodingProjectFiles(projectId, query);
}

async function pickAttachment() {
  const sourcePath = await pickFile();
  if (!sourcePath) return null;
  const currentThread = thread.value;
  const projectId = props.store.selectedProjectId.value ?? currentThread?.projectId ?? null;
  const workspaceId =
    props.store.selectedWorkspaceId.value ?? currentThread?.workspaceId ?? null;
  if (projectId === null || workspaceId === null) {
    throw new Error("当前任务尚未绑定可用工作区");
  }
  return attachCodingProjectFile(projectId, workspaceId, sourcePath);
}

async function cancelRun(): Promise<void> {
  cancelling.value = true;
  try {
    await stream.cancelActive();
  } finally {
    cancelling.value = false;
  }
}

function backToHome(): void {
  props.store.startNewTask();
  emit("navigate", "coding");
}

function openPlanFromTranscript(): void {
  planOpen.value = true;
  contextOpen.value = false;
}

function togglePlan(): void {
  planOpen.value = !planOpen.value;
  if (planOpen.value) contextOpen.value = false;
}

function toggleContext(): void {
  contextOpen.value = !contextOpen.value;
  if (contextOpen.value) planOpen.value = false;
}

function onInstructionMarkersChange(markers: CodingInstructionMarker[]): void {
  instructionMarkers.value = markers;
}

function navigateToInstruction(instructionId: string): void {
  instructionTargetSeq += 1;
  instructionTarget.value = { id: instructionId, seq: instructionTargetSeq };
}
</script>

<template>
  <section class="coding-thread" data-testid="coding-thread-workspace">
    <PaEmptyState
      v-if="!thread"
      :icon="PhChatsCircle"
      title="未选择任务"
      description="从侧栏选择一个对话，或回到首页新建对话。"
    >
      <PaButton variant="primary" @click="backToHome">回到首页</PaButton>
    </PaEmptyState>

    <template v-else>
      <ThreadHeader
        :title="thread.title"
        :project-name="project?.name ?? ''"
        :branch-label="branchLabel"
        :workspace-path="workspacePath"
        :workspace-path-loading="workspacePathLoading"
        :workspace-path-requested="workspacePathRequested"
        :head-sha="workspace?.headSha ?? null"
        :git-dirty="workspace ? workspace.status === 'dirty' : null"
        :run-status="runStatus"
        :plan-available="projection?.plan != null"
        :plan-open="planOpen"
        :context-open="contextOpen"
        :cancellable="runActive"
        :cancelling="cancelling"
        @back-home="backToHome"
        @cancel="cancelRun"
        @toggle-plan="togglePlan"
        @toggle-context="toggleContext"
        @request-workspace-path="void requestWorkspacePath()"
      />

      <div class="thread-body">
        <aside
          v-if="instructionMarkers.length > 0"
          class="instruction-index"
          aria-label="用户指令索引"
          data-testid="coding-instruction-index"
        >
          <div class="instruction-index__list">
            <button
              v-for="(marker, index) in instructionMarkers"
              :key="marker.id"
              type="button"
              class="instruction-index__item"
              :class="{ active: instructionTarget?.id === marker.id }"
              :title="marker.label"
              :aria-label="`定位到用户指令：${marker.label}`"
              :data-testid="`coding-instruction-${index}`"
              @click="navigateToInstruction(marker.id)"
            >
              <span class="instruction-index__tick" aria-hidden="true" />
            </button>
          </div>
        </aside>

        <div class="thread-main">
          <RunTranscript
            :projection="projection"
            :history="durableHistory"
            :phase="phase"
            :connection-error="connectionError"
            :approvals="approvalRecords"
            :approval-previews="approvalPreviews"
            :preview-loading="previewLoading"
            :execution-by-tool="executionByTool"
            :executions="executions"
            :output-pages="outputPages"
            :output-loading="outputLoading"
            :preview-mode="previewMode"
            :instruction-target="instructionTarget"
            @approve="onApprove"
            @reject="onReject"
            @open-plan="openPlanFromTranscript"
            @retry-stream="stream.retryConnection()"
            @load-output="loadOutput"
            @instruction-markers-change="onInstructionMarkersChange"
          />

          <!-- v0.9.0 H1-B（§5.6）：创建失败阻塞卡片（具体阻塞项 + 恢复入口） -->
          <div
            v-if="createBlocker"
            class="create-blocker"
            role="alert"
            data-testid="run-create-blocker"
          >
            <PhWarningCircle :size="16" aria-hidden="true" />
            <div class="blocker-copy">
              <strong>{{ createBlocker.title }}</strong>
              <span class="blocker-hint">{{ createBlocker.hint }}</span>
              <span v-if="connectionError" class="blocker-detail">{{ connectionError }}</span>
            </div>
            <div class="blocker-actions">
              <PaButton
                size="sm"
                variant="primary"
                data-testid="run-blocker-recover"
                @click="recoverFromBlocker"
              >{{ createBlocker.recoveryLabel }}</PaButton>
              <PaButton
                v-if="createBlocker.recovery !== 'retry' && lastSentPayload"
                size="sm"
                variant="ghost"
                data-testid="run-blocker-retry"
                @click="void retryBlockedSend()"
              >重试</PaButton>
            </div>
          </div>

          <div class="thread-composer">
            <CodingComposer
              :store="store"
              :thread-id="thread.id"
              :busy="composerBusy"
              :stopping="cancelling"
              :running="runActive"
              :preview-mode="previewMode"
              :search-files="searchFiles"
              :pick-attachment="pickAttachment"
              :before-send="guardFullAccess"
              :input-history="composerInputHistory"
              :restore-request="restoreRequest"
              @send="send"
              @stop="cancelRun"
            />
          </div>
        </div>

        <RunPlanPopover
          v-if="planOpen"
          :plan="projection?.plan ?? null"
          @close="planOpen = false"
        />

        <ContextDrawer
          v-if="contextOpen"
          :projection="projection"
          :previews="approvalPreviews"
          :permission-mode="lastPermissionMode"
          @close="contextOpen = false"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
.coding-thread {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}
.thread-body {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
}
.thread-main {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}
.instruction-index {
  display: flex;
  width: 30px;
  min-width: 30px;
  flex-direction: column;
  justify-content: center;
  overflow: hidden;
  background: transparent;
}
.instruction-index__list {
  display: flex;
  width: 100%;
  max-height: 64%;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  overflow-y: auto;
  scrollbar-width: none;
}
.instruction-index__list::-webkit-scrollbar {
  display: none;
}
.instruction-index__item {
  display: flex;
  width: 28px;
  height: 8px;
  align-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
}
.instruction-index__item:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 2px;
}
.instruction-index__tick {
  width: 8px;
  height: 2px;
  border-radius: var(--radius-full);
  background: var(--color-border-strong);
  transition: width 120ms ease, background-color 120ms ease;
}
.instruction-index__item:nth-child(3n + 2) .instruction-index__tick {
  width: 14px;
}
.instruction-index__item:nth-child(3n) .instruction-index__tick {
  width: 6px;
}
.instruction-index__item:hover .instruction-index__tick,
.instruction-index__item.active .instruction-index__tick {
  width: 22px;
  height: 3px;
  background: var(--color-fg);
}
.thread-composer {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 0;
  background: var(--color-bg);
}
.create-blocker {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-shrink: 0;
  margin: 0 var(--space-4);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.create-blocker > svg {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--color-warning);
}
.blocker-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: row;
  align-items: baseline;
  gap: var(--space-2);
}
.blocker-hint {
  overflow: hidden;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta, 12px);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.blocker-detail {
  display: none;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta, 12px);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.blocker-actions {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-shrink: 0;
}
@media (max-width: 1080px) {
  .instruction-index {
    width: 26px;
    min-width: 26px;
  }
  .thread-body :deep(.plan-popover),
  .thread-body :deep(.context-drawer) {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: var(--z-raised);
    box-shadow: var(--shadow-lg);
  }
  .blocker-copy {
    flex-direction: column;
    align-items: flex-start;
    gap: 1px;
  }
}
</style>
