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
import { PhChatsCircle } from "@phosphor-icons/vue";
import type { View } from "../../../types";
import PaEmptyState from "../../../design/PaEmptyState.vue";
import PaButton from "../../../design/PaButton.vue";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";
import { useRunStream } from "../composables/useRunStream";
import type {
  RunApprovalPreviewRecord,
  RunApprovalRecord,
  RunExecutionOutputPage,
  RunExecutionRecord,
} from "../model/runContracts";
import { isTerminalRunStatus } from "../model/runContracts";
import type { RunProjection } from "../model/runProjector";
import {
  approveRunApproval,
  fetchRunApprovalPreview,
  fetchRunApprovals,
  fetchRunExecutionOutput,
  fetchRunExecutions,
  rejectRunApproval,
} from "../api/runs";
import { searchCodingProjectFiles } from "../api/projects";
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
}>();

const thread = computed(() => props.store.selectedThread.value);
const project = computed(() => props.store.selectedProject.value);
const workspace = computed(() => props.store.selectedWorkspace.value);

const branchLabel = computed(() => {
  const current = workspace.value;
  if (!current) return "";
  return current.branchName ?? (current.kind === "root" ? "根工作区" : "工作区");
});

// ============ run 流（真实计划/工具/审批/终态均来自 durable 事件） ============
const stream = useRunStream();
const planOpen = ref(false);
const contextOpen = ref(false);
const cancelling = ref(false);
const lastPermissionMode = ref<string | null>(null);
const approvalRecords = shallowRef<RunApprovalRecord[]>([]);

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
  if (outputPollTimer !== null) {
    window.clearTimeout(outputPollTimer);
    outputPollTimer = null;
  }
});

// ============ 输入器（W3 CodingComposer：权限/模型/推理/@ 上下文/草稿） ============
const composerBusy = computed(
  () => !previewMode.value && ["starting", "streaming", "reconnecting"].includes(stream.phase.value)
);

async function send(payload: CodingComposerSendPayload): Promise<void> {
  if (!thread.value) return;
  const projectId = props.store.selectedProjectId.value ?? thread.value.projectId;
  const workspaceId = props.store.selectedWorkspaceId.value ?? thread.value.workspaceId;
  if (projectId === null || workspaceId === null) return;
  lastPermissionMode.value = payload.permissionMode;
  await stream.startRun({
    session_id: thread.value.id,
    message: payload.message,
    project_id: projectId,
    workspace_id: workspaceId,
    permission_mode: payload.permissionMode,
    model_profile_id: payload.modelProfileId ?? undefined,
    reasoning_effort: payload.reasoningEffort ?? undefined,
  });
}

function searchFiles(query: string) {
  const projectId = props.store.selectedProjectId.value;
  if (projectId === null) return Promise.resolve([]);
  return searchCodingProjectFiles(projectId, query);
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
</script>

<template>
  <section class="coding-thread" data-testid="coding-thread-workspace">
    <PaEmptyState
      v-if="!thread"
      :icon="PhChatsCircle"
      title="未选择任务"
      description="从侧栏选择一个任务，或回到首页新建任务。"
    >
      <PaButton variant="primary" @click="backToHome">回到首页</PaButton>
    </PaEmptyState>

    <template v-else>
      <ThreadHeader
        :title="thread.title"
        :project-name="project?.name ?? ''"
        :branch-label="branchLabel"
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
      />

      <div class="thread-body">
        <div class="thread-main">
          <RunTranscript
            :projection="projection"
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
            @approve="onApprove"
            @reject="onReject"
            @open-plan="openPlanFromTranscript"
            @retry-stream="stream.retryConnection()"
            @load-output="loadOutput"
          />

          <div class="thread-composer">
            <CodingComposer
              :store="store"
              :thread-id="thread.id"
              :busy="composerBusy"
              :stopping="cancelling"
              :running="runActive"
              :preview-mode="previewMode"
              :search-files="searchFiles"
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
.thread-composer {
  flex-shrink: 0;
  padding: var(--space-3) var(--space-5) var(--space-4);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}
@media (max-width: 1080px) {
  .thread-body :deep(.plan-popover),
  .thread-body :deep(.context-drawer) {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: var(--z-raised);
    box-shadow: var(--shadow-lg);
  }
}
</style>
