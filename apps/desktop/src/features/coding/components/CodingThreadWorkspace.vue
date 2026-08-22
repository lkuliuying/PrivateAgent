<script setup lang="ts">
/**
 * CodingThreadWorkspace · v0.8.0 W2
 *
 * 任务页：ThreadHeader + RunTranscript + RunPlanPopover + 极简输入器。
 * run 生命周期由 useRunStream 管理（App.vue :key 按 thread 重建，切换任务
 * 即卸载清理流/定时器——零容忍 §10）。审批详情经 GET /agent-runs/{id}/approvals
 * 补全（事件只带 approval_id）。W3 将以 CodingComposer 取代极简输入器并扩展
 * Diff/命令输出。
 */
import { computed, ref, shallowRef, watch } from "vue";
import { PhChatsCircle, PhPaperPlaneRight, PhProhibit } from "@phosphor-icons/vue";
import type { View } from "../../../types";
import PaEmptyState from "../../../design/PaEmptyState.vue";
import PaButton from "../../../design/PaButton.vue";
import PaInlineNotice from "../../../design/PaInlineNotice.vue";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";
import { useRunStream } from "../composables/useRunStream";
import type { RunApprovalRecord } from "../model/runContracts";
import { isTerminalRunStatus } from "../model/runContracts";
import type { RunProjection } from "../model/runProjector";
import {
  approveRunApproval,
  fetchRunApprovals,
  rejectRunApproval,
} from "../api/runs";
import ThreadHeader from "./ThreadHeader.vue";
import RunTranscript from "./RunTranscript.vue";
import RunPlanPopover from "./RunPlanPopover.vue";

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
const cancelling = ref(false);
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
      previewProjection.value = module.createStaticProjection(
        previewKey as Parameters<typeof module.createStaticProjection>[0]
      ).projection;
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

// 未决审批 → 拉取审批详情（risk_level/capabilities/expires 只在 approvals API）
const pendingApprovalKey = computed(() => {
  const current = stream.projection.value;
  if (!current) return "";
  return current.entries
    .filter((entry) => entry.kind === "approval")
    .map((entry) => (entry.kind === "approval" ? `${entry.approvalId}:${entry.resolved ? 1 : 0}` : ""))
    .join(",");
});

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

watch(pendingApprovalKey, (next, previous) => {
  if (next && next !== previous && !previewMode.value) void refreshApprovals();
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

// ============ 极简输入器（W3 由 CodingComposer 取代：@上下文、/ 命令、权限/模型/推理） ============
const composerText = ref("");
const composerError = ref("");

const composerBusy = computed(
  () => !previewMode.value && ["starting", "streaming", "reconnecting"].includes(stream.phase.value)
);

async function send(): Promise<void> {
  const message = composerText.value.trim();
  if (!message || composerBusy.value || !thread.value) return;
  const projectId = props.store.selectedProjectId.value ?? thread.value.projectId;
  const workspaceId = props.store.selectedWorkspaceId.value ?? thread.value.workspaceId;
  if (projectId === null || workspaceId === null) {
    composerError.value = "项目或工作区不可用，无法发起任务";
    return;
  }
  composerError.value = "";
  await stream.startRun({
    session_id: thread.value.id,
    message,
    project_id: projectId,
    workspace_id: workspaceId,
  });
  if (stream.phase.value !== "error") composerText.value = "";
}

function onComposerKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void send();
  }
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
        :cancellable="runActive"
        :cancelling="cancelling"
        @back-home="backToHome"
        @cancel="cancelRun"
        @toggle-plan="planOpen = !planOpen"
      />

      <div class="thread-body" :class="{ 'has-plan': planOpen && projection?.plan }">
        <div class="thread-main">
          <RunTranscript
            :projection="projection"
            :phase="phase"
            :connection-error="connectionError"
            :approvals="approvalRecords"
            :preview-mode="previewMode"
            @approve="onApprove"
            @reject="onReject"
            @open-plan="openPlanFromTranscript"
            @retry-stream="stream.retryConnection()"
          />

          <div class="thread-composer" data-testid="coding-thread-composer">
            <PaInlineNotice
              v-if="composerError"
              tone="danger"
              title="无法发送"
              class="composer-notice"
            >
              {{ composerError }}
            </PaInlineNotice>
            <div class="composer-row">
              <textarea
                v-model="composerText"
                class="composer-input"
                data-testid="coding-thread-composer-input"
                rows="2"
                :disabled="composerBusy || previewMode"
                :placeholder="
                  previewMode
                    ? '预览模式：静态事件流演示'
                    : composerBusy
                      ? '任务执行中…可点击停止'
                      : '描述要执行的内容（Enter 发送 · Shift+Enter 换行）'
                "
                @keydown="onComposerKeydown"
              />
              <button
                v-if="!runActive"
                class="pa-btn pa-btn--primary composer-send"
                data-testid="coding-thread-composer-send"
                :disabled="composerBusy || previewMode || !composerText.trim()"
                @click="send()"
              >
                <PhPaperPlaneRight :size="15" />
                发送
              </button>
              <button
                v-else
                class="pa-btn pa-btn--ghost composer-stop"
                data-testid="coding-thread-composer-stop"
                :disabled="cancelling"
                @click="cancelRun()"
              >
                <PhProhibit :size="15" />
                {{ cancelling ? "停止中…" : "停止" }}
              </button>
            </div>
          </div>
        </div>

        <RunPlanPopover
          v-if="planOpen"
          :plan="projection?.plan ?? null"
          @close="planOpen = false"
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
.composer-notice {
  margin-bottom: var(--space-2);
}
.composer-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}
.composer-input {
  flex: 1;
  min-height: 44px;
  max-height: 160px;
  resize: none;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-fg);
  font-size: var(--text-sm);
  font-family: inherit;
  line-height: var(--leading-normal);
}
.composer-input:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 0;
}
.composer-input:disabled {
  color: var(--color-fg-faint);
}
.composer-send,
.composer-stop {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
}
.composer-stop {
  color: var(--color-danger-fg);
}
@media (max-width: 1080px) {
  .thread-body :deep(.plan-popover) {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: var(--z-raised);
    box-shadow: var(--shadow-lg);
  }
  .thread-body {
    position: relative;
  }
}
</style>
