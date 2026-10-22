<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  controlRun, fetchRecovery, fetchResumePreview, fetchRunReview, reconcileRun,
  type BlockerDetail, type ControlPayload, type ReconcileDecision, type RecoveryControlKind,
  type RecoveryReport, type ResumePreview, type ResumeRequest, type RunReview,
} from "../api/recovery";
import { listCodingModelProfiles } from "../api/modelProfiles";
import type { CodingModelProfileDetail } from "../model/contracts";
import { readPendingControl, savePendingControl } from "../model/pendingControls";
import { isTerminalRunStatus, RUN_STATUS_META } from "../model/runContracts";
import PatchReviewPanel from "./PatchReviewPanel.vue";

/** 恢复面板：展示已提交现场，并把核对、续跑与模型交接集中在显式操作上。 */
const props = defineProps<{ runId: string; reconcileEnabled?: boolean; handoffEnabled?: boolean }>();
const emit = defineEmits<{ resumed: [runId: string]; changed: [] }>();
const state = ref<RecoveryReport | null>(null);
const review = ref<RunReview | null>(null);
const message = ref("");
const note = ref("");
const noteItem = ref("");
const error = ref("");
const busy = ref(false);
const loading = ref(false);
const profiles = ref<CodingModelProfileDetail[]>([]);
const targetProfile = ref("");
const preview = ref<ResumePreview | null>(null);
const timingAccepted = ref(false);
const pending = ref<{ kind: RecoveryControlKind; data: ControlPayload } | null>(null);
let generation = 0;
let controller: AbortController | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
const active = computed(() => !!state.value && state.value.supported !== false && !isTerminalRunStatus(state.value.status));
/** 可恢复的结束状态：暂停、中断、取消，以及明确的模型传输故障。 */
const resumable = computed(() => !!state.value && ["paused", "interrupted", "cancelled", "failed", "timed_out"].includes(state.value.status));
const needsTimingAcceptance = computed(() => state.value?.timing?.unconfirmed_tail === true);
const openItems = computed(() => (state.value?.blocker_details ?? []).filter(item => item.status === "open"));
const ancestors = computed(() => [...new Set(review.value?.task_changes.map(patch => patch.run_id).filter(id => id !== props.runId) ?? [])]);
const currentPatches = computed(() => (review.value?.task_changes ?? []).filter(patch => patch.run_id === props.runId));
const controlLabels: Record<string, string> = { pause: "暂停", resume: "继续", steer: "追加约束", cancel: "取消", reconcile: "核对现场", answer: "回答澄清", implement: "按计划执行" };
const decisionLabels: Record<ReconcileDecision, string> = {
  record_observation: "记录机器观察",
  externally_confirmed: "已核对完成",
  externally_failed: "已核对失败",
  abandon: "放弃后续恢复",
};
const budget = computed(() => state.value?.budget ?? {});

async function load() {
  if (loading.value) return;
  const mine = generation;
  controller = new AbortController();
  loading.value = true;
  try {
    const result = await fetchRecovery(props.runId, controller.signal);
    if (mine !== generation) return;
    state.value = result;
    if (state.value.timing && !needsTimingAcceptance.value) timingAccepted.value = true;
  } catch {
    if (mine === generation) error.value = "恢复现场读取失败，请刷新重试";
  } finally {
    if (mine === generation) {
      loading.value = false;
      clearTimeout(timer);
      if (state.value && !isTerminalRunStatus(state.value.status)) timer = setTimeout(() => void load(), 1500);
    }
  }
}
async function loadReview() {
  const mine = generation;
  try {
    const result = await fetchRunReview(props.runId, controller?.signal);
    if (mine === generation) review.value = result;
  } catch {
    if (mine === generation) error.value = "任务变更核对失败，请刷新重试";
  }
}
async function loadProfiles() {
  if (!props.handoffEnabled || profiles.value.length) return;
  try {
    profiles.value = (await listCodingModelProfiles()).filter(profile => profile.enabled);
  } catch {
    profiles.value = [];
  }
}
/** 组织一次写控制请求；结果未确认时保留 request_id，重试不会产生第二次操作。 */
function buildPayload(kind: RecoveryControlKind, extra: Partial<ControlPayload> = {}): ControlPayload {
  const report = state.value!;
  const payload: ControlPayload = { request_id: crypto.randomUUID(), expected_state_version: report.state_version, ...extra };
  if (kind === "resume" || kind === "reconcile") payload.checkpoint_id = report.checkpoint_id;
  return payload;
}
async function submit(kind: RecoveryControlKind, extra: Partial<ControlPayload> = {}, retry = false) {
  if (busy.value || !state.value) return;
  const mine = generation;
  const runId = props.runId;
  if (!retry) {
    const data = buildPayload(kind, extra);
    if (kind === "steer") data.message = message.value.trim();
    pending.value = { kind, data };
    savePendingControl(runId, { kind, data });
  }
  const selected = pending.value;
  if (!selected) return;
  busy.value = true;
  error.value = "";
  try {
    const result = selected.kind === "reconcile"
      ? await reconcileRun(runId, selected.data as never)
      : await controlRun(runId, selected.kind, selected.data);
    if (mine !== generation) return;
    pending.value = null;
    savePendingControl(runId, null);
    note.value = "";
    noteItem.value = "";
    preview.value = null;
    targetProfile.value = "";
    if (selected.kind === "steer") message.value = "";
    if (selected.kind === "resume" && result.result_run_id) emit("resumed", result.result_run_id);
    emit("changed");
    await load();
  } catch (cause) {
    if (mine !== generation) return;
    const detail = cause as { status?: number; message?: string };
    error.value = detail.message || "控制结果未确认；可使用同一请求标识重试";
    if (detail.status === 409 || detail.status === 422) { pending.value = null; savePendingControl(runId, null); }
    await load();
  } finally {
    if (mine === generation) busy.value = false;
  }
}
/** 续跑时一并提交计时确认；未勾选确认的旧客户端行为保持不变（不发送该字段）。 */
function resumePayload(): Partial<ResumeRequest> {
  return needsTimingAcceptance.value && timingAccepted.value ? { accept_unconfirmed_timing: true } : {};
}
function reconcile(item: BlockerDetail, decision: ReconcileDecision) {
  if (!item.resolvable) return;
  if (decision !== "record_observation" && decision !== "abandon" && note.value.trim().length < 4) {
    error.value = "请先写明外部核对依据（至少 4 个字），系统不会把人工说明当成机器验证";
    return;
  }
  if (decision === "abandon" && !note.value.trim()) note.value = "用户决定放弃后续恢复，保留已改文件与未知结果";
  noteItem.value = item.item_id;
  void submit("reconcile", { item_id: item.item_id, kind: item.kind as never, decision, note: note.value.trim() || undefined });
}
async function previewTarget() {
  if (!state.value || !targetProfile.value) return;
  error.value = "";
  busy.value = true;
  try {
    preview.value = await fetchResumePreview(props.runId, targetProfile.value, state.value.checkpoint_id);
  } catch (cause) {
    const detail = cause as { message?: string };
    error.value = detail.message || "模型差异预览失败，请刷新后重试";
    preview.value = null;
  } finally {
    busy.value = false;
  }
}
function resumeWithModel() {
  const chosen = preview.value;
  if (!chosen) return;
  const extra: Partial<ResumeRequest> = { model_profile_id: chosen.target.model_profile_id, preview_sha256: chosen.preview_sha256, accept_model_change: true, ...resumePayload() };
  void submit("resume", extra);
}
function setNote(item: BlockerDetail) {
  if (noteItem.value !== item.item_id) { noteItem.value = item.item_id; note.value = ""; }
}
watch(() => props.runId, () => {
  generation++;
  controller?.abort();
  clearTimeout(timer);
  state.value = null;
  review.value = null;
  pending.value = readPendingControl(props.runId) as { kind: RecoveryControlKind; data: ControlPayload } | null;
  preview.value = null;
  targetProfile.value = "";
  message.value = "";
  note.value = "";
  noteItem.value = "";
  error.value = "";
  timingAccepted.value = false;
  busy.value = false;
  loading.value = false;
  void load();
  void loadProfiles();
}, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); clearTimeout(timer); });
</script>

<template>
  <section class="recovery-panel" aria-label="任务恢复与协作">
    <details :open="!!active || !!error || !!pending || !!state?.blockers.length || !!state && ['paused', 'interrupted', 'cancelled', 'failed'].includes(state.status)">
    <summary>任务现场 · {{ state ? RUN_STATUS_META[state.status]?.label : '读取中' }}</summary>
    <div class="recovery-body">
    <div class="recovery-actions">
      <strong>{{ state ? RUN_STATUS_META[state.status]?.label : '正在读取任务现场…' }}</strong>
      <button class="pa-btn pa-btn--subtle" :disabled="loading || busy" @click="load">刷新现场</button>
      <button v-if="active && state?.status !== 'paused'" class="pa-btn pa-btn--subtle" :disabled="busy || !!pending" @click="submit('pause')">暂停</button>
      <button v-if="resumable" class="pa-btn pa-btn--primary" :disabled="busy || !state?.can_resume || !!pending || (needsTimingAcceptance && !timingAccepted)" @click="submit('resume', resumePayload())">保留当前代码并继续</button>
      <button v-if="active" class="pa-btn pa-btn--subtle" :disabled="busy || !!pending" @click="submit('cancel')">取消任务</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="pending && !busy" class="pa-btn pa-btn--subtle" @click="submit(pending.kind, {}, true)">重试上次控制</button>
    <template v-if="state">
      <p v-if="state.supported === false">旧运行缺少恢复检查点，请依据历史开始新任务。</p>
      <p v-if="state.queue_reason" role="status">排队 {{ state.queue_position }} · {{ state.queue_reason }}</p>
      <p v-if="state.resumed_from_run_id">已从中断记录继续；累计用量与历史失败保留。</p>
      <p>
        模型请求 {{ budget.model_requests ?? 0 }}<template v-if="budget.max_model_requests">/{{ budget.max_model_requests }}</template> 次 ·
        工具 {{ budget.tool_calls ?? 0 }}<template v-if="budget.max_tool_calls">/{{ budget.max_tool_calls }}</template> 次 ·
        活动 {{ Math.ceil(budget.active_seconds ?? 0) }}<template v-if="budget.max_active_seconds">/{{ budget.max_active_seconds }}</template> 秒
      </p>
      <p v-if="state.timing?.unconfirmed_tail" role="status">
        已记录活动 {{ Math.ceil(state.timing.confirmed_active_seconds ?? budget.active_seconds ?? 0) }} 秒；末段耗时未确认，继续不会补算离线间隔。
        <label v-if="resumable"><input v-model="timingAccepted" type="checkbox" /> 我了解末段耗时未确认</label>
      </p>
      <ul v-if="openItems.length" aria-label="待核对项">
        <li v-for="item in openItems" :key="item.item_id">
          <strong>{{ item.label }}</strong>
          <p v-if="item.reason">{{ item.reason }}</p>
          <template v-if="!!props.reconcileEnabled && item.actions.length">
            <textarea v-model="note" class="pa-input" rows="2" maxlength="2000" :disabled="busy" :placeholder="item.kind === 'mcp_write' ? '写明你在外部看到的远端结果；系统仍标记为未验证' : '写下核对依据（至少 4 个字）'" @focus="setNote(item)" />
            <button v-for="action in item.actions" :key="action" class="pa-btn pa-btn--subtle" :disabled="busy || !!pending || !item.resolvable" @click="reconcile(item, action)">{{ decisionLabels[action] }}</button>
          </template>
          <span v-else-if="item.resolvable === false">需要先按说明修复现场；不能忽略这项阻塞。</span>
        </li>
      </ul>
      <ul v-else-if="state.blockers.length"><li v-for="reason in state.blockers" :key="reason">{{ reason }}</li></ul>
      <template v-if="state.resolutions?.length">
        <p>已核对记录</p>
        <ul aria-label="已核对记录"><li v-for="item in state.resolutions" :key="item.resolution_id">{{ decisionLabels[item.decision] }} · {{ item.source === 'user_statement' ? '用户已核对，系统未验证' : '机器观察' }} · {{ item.created_at }}<span v-if="item.note"> · {{ item.note }}</span></li></ul>
      </template>
      <p v-if="state.expired_approvals.length">{{ state.expired_approvals.length }} 条旧审批已失效，继续时重新检查权限。</p>
      <section v-if="!!props.handoffEnabled && resumable && state.status !== 'paused'" class="recovery-handoff" aria-label="选择模型后继续">
        <strong>选择模型后继续</strong>
        <p>原运行与历史不改写；切换后只发送公开历史，已累计用量与失败记录继续沿用。</p>
        <select v-model="targetProfile" class="pa-input" :disabled="busy" @change="preview = null">
          <option value="">保持原模型</option>
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{ profile.displayName }}{{ profile.modelName ? ` · ${profile.modelName}` : '' }}</option>
        </select>
        <button class="pa-btn pa-btn--subtle" :disabled="busy || !targetProfile || targetProfile === state.model_profile_id" @click="previewTarget">预览差异</button>
        <template v-if="preview">
          <p>目标 {{ preview.target.model_name ?? preview.target.model_profile_id }} · {{ preview.switched ? '将切换模型' : '同模型' }}</p>
          <ul v-if="preview.capability_gaps.length"><li v-for="gap in preview.capability_gaps" :key="gap">{{ gap }}</li></ul>
          <p>{{ preview.budget_note }}</p>
          <button class="pa-btn pa-btn--primary" :disabled="busy || !preview.eligible || !!pending || (needsTimingAcceptance && !timingAccepted)" @click="resumeWithModel">用目标模型继续</button>
        </template>
      </section>
      <form v-if="active" class="recovery-steer" @submit.prevent="submit('steer')">
        <label :for="`steer-${runId}`">补充本任务约束</label>
        <textarea :id="`steer-${runId}`" v-model="message" class="pa-input" rows="2" maxlength="32000" :disabled="busy" placeholder="例如：停止写入，先解释当前结果" />
        <button class="pa-btn pa-btn--subtle" :disabled="busy || !message.trim() || !!pending">追加约束</button>
        <span>接收后在安全边界应用；正在发生的写入会保留真实结果。当前只收紧约束，解除限制或独立目标请开始新任务。</span>
      </form>
      <ul aria-label="控制进度"><li v-for="item in state.controls" :key="item.request_id">{{ controlLabels[item.kind] ?? item.kind }} · {{ item.status === 'applied' ? '已应用' : item.status === 'received' ? '等待应用' : '中断，未确认生效' }}<span v-if="item.message"> · {{ item.message }}</span><span v-if="item.note"> · {{ item.note }}</span><span v-if="item.source === 'user_statement'"> · 用户已核对，系统未验证</span><span v-if="item.cleanup_complete === false"> · 进程清理未确认</span></li></ul>
      <details><summary @click="loadReview">查看本轮修改与变更归属</summary>
        <template v-if="review">
          <p v-if="!review.snapshot_complete" role="alert">范围扫描不完整，以下列表不是完整仓库审计。</p>
          <p>任务记录 {{ review.task_changes.length }} 组补丁 · 本轮 {{ currentPatches.length }} 组 · 前序轮次 {{ ancestors.length }} 轮 · 开始前已有 {{ review.preexisting_changes.length }} 项改动</p>
          <ul><li v-for="item in review.preexisting_changes" :key="item.rel_path">已有改动 · {{ item.rel_path }} · {{ item.status }}</li></ul>
          <p>外部或无法归属的变化</p>
          <ul><li v-for="item in review.external_or_unattributed" :key="item.rel_path">{{ item.rel_path }} · {{ item.operation }} · {{ item.after_sha256?.slice(0, 12) ?? '不存在或不可读取' }}</li></ul>
          <details v-for="command in review.command_candidates" :key="command.execution_id"><summary>命令候选变化 · {{ command.items.length }} 项</summary><p>可能包含同时发生的外部编辑，归属未确认。</p><ul><li v-for="item in command.items" :key="item.rel_path">{{ item.rel_path }} · {{ item.operation }}</li></ul></details>
          <PatchReviewPanel :run-id="runId" :active="!!active" />
          <details v-if="ancestors.length"><summary>查看续跑链前序轮次 · {{ ancestors.length }} 轮</summary><PatchReviewPanel v-for="ancestor in ancestors" :key="ancestor" :run-id="ancestor" :active="!!active" /></details>
          <p v-for="limit in review.limitations" :key="limit">{{ limit }}</p>
        </template>
      </details>
    </template>
    </div>
    </details>
  </section>
</template>

<style scoped>
.recovery-panel { border: 1px solid var(--color-border); border-radius: var(--radius-lg); font-size: var(--pa-text-meta); min-height: 0; overflow-wrap: anywhere; container-type: inline-size; }
/* 宽按钮在窄容器内换行，避免固定 36px 高度配合 nowrap 造成文字裁切。 */
.recovery-panel :deep(.pa-btn), .recovery-panel .pa-btn { height: auto; min-height: 36px; padding: 8px 14px; white-space: normal; overflow-wrap: anywhere; max-width: 100%; }
.recovery-panel summary { padding: var(--space-3); cursor: pointer; color: var(--color-fg-muted); }
.recovery-body { padding: 0 var(--space-3) var(--space-3); max-height: 45vh; overflow: auto; }
.recovery-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.recovery-steer, .recovery-handoff { display: grid; gap: var(--space-2); }
.recovery-steer textarea, .recovery-handoff select { resize: vertical; min-width: 0; width: 100%; }
.recovery-panel details { max-height: 45vh; overflow: auto; }
.recovery-panel [role="alert"] { color: var(--color-danger-fg); }
/* 窄容器内动作按钮纵向铺满，保证确认文案完整可见且可点击。 */
@container (max-width: 380px) {
  .recovery-actions, .recovery-handoff, .recovery-steer { align-items: stretch; }
  .recovery-actions .pa-btn, .recovery-handoff .pa-btn, .recovery-steer .pa-btn { width: 100%; text-align: center; justify-content: center; }
}
</style>


