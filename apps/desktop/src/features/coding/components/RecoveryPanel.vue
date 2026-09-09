<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { controlRun, fetchRecovery, fetchRunReview, type ControlRecord, type ControlRequest, type RecoveryReport, type RunReview } from "../api/recovery";
import { isTerminalRunStatus, RUN_STATUS_META } from "../model/runContracts";
import PatchReviewPanel from "./PatchReviewPanel.vue";

const props = defineProps<{ runId: string }>();
const emit = defineEmits<{ resumed: [runId: string]; changed: [] }>();
const state = ref<RecoveryReport | null>(null);
const review = ref<RunReview | null>(null);
const message = ref("");
const error = ref("");
const busy = ref(false);
const loading = ref(false);
const pending = ref<{ kind: ControlRecord["kind"]; data: ControlRequest } | null>(null);
let generation = 0;
let controller: AbortController | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
const active = computed(() => state.value && state.value.supported !== false && !isTerminalRunStatus(state.value.status));
const ancestors = computed(() => [...new Set(review.value?.task_changes.map(patch => patch.run_id).filter(id => id !== props.runId) ?? [])]);
const controlLabels = { pause: "暂停", resume: "继续", steer: "追加约束", cancel: "取消" };

async function load() {
  if (loading.value) return;
  const mine = generation;
  controller = new AbortController();
  loading.value = true;
  try {
    const result = await fetchRecovery(props.runId, controller.signal);
    if (mine === generation) state.value = result;
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
async function send(kind: ControlRecord["kind"], retry = false) {
  if (busy.value || !state.value) return;
  const mine = generation;
  const runId = props.runId;
  if (!retry) pending.value = { kind, data: { request_id: crypto.randomUUID(), expected_state_version: state.value.state_version,
    ...(kind === "resume" ? { checkpoint_id: state.value.checkpoint_id } : {}), ...(kind === "steer" ? { message: message.value.trim() } : {}) } };
  const selected = pending.value;
  if (!selected) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await controlRun(runId, selected.kind, selected.data);
    if (mine !== generation) return;
    pending.value = null;
    if (selected.kind === "steer") message.value = "";
    if (selected.kind === "resume") emit("resumed", result.result_run_id);
    emit("changed");
    await load();
  } catch (cause) {
    if (mine !== generation) return;
    const detail = cause as { status?: number; message?: string };
    error.value = detail.message || "控制结果未确认；可使用同一请求标识重试";
    if (detail.status === 409 || detail.status === 422) pending.value = null;
    await load();
  } finally {
    if (mine === generation) busy.value = false;
  }
}
watch(() => props.runId, () => {
  generation++;
  controller?.abort();
  clearTimeout(timer);
  state.value = null;
  review.value = null;
  pending.value = null;
  message.value = "";
  error.value = "";
  busy.value = false;
  loading.value = false;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); clearTimeout(timer); });
</script>

<template>
  <section class="recovery-panel" aria-label="任务恢复与协作">
    <div class="recovery-actions">
      <strong>{{ state ? RUN_STATUS_META[state.status]?.label : '正在读取任务现场…' }}</strong>
      <button class="pa-btn pa-btn--subtle" :disabled="loading || busy" @click="load">刷新现场</button>
      <button v-if="active && state?.status !== 'paused'" class="pa-btn pa-btn--subtle" :disabled="busy || !!pending" @click="send('pause')">暂停</button>
      <button v-if="state && ['paused', 'interrupted', 'cancelled'].includes(state.status)" class="pa-btn pa-btn--primary" :disabled="busy || !state.can_resume || !!pending" @click="send('resume')">核对并继续</button>
      <button v-if="active" class="pa-btn pa-btn--subtle" :disabled="busy || !!pending" @click="send('cancel')">取消任务</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="pending && !busy" class="pa-btn pa-btn--subtle" @click="send(pending.kind, true)">重试上次控制</button>
    <template v-if="state">
      <p v-if="state.supported === false">旧运行缺少恢复检查点，请依据历史开始新任务。</p>
      <p v-if="state.queue_reason" role="status">排队 {{ state.queue_position }} · {{ state.queue_reason }}</p>
      <p v-if="state.resumed_from_run_id">已从中断记录继续；累计用量与历史失败保留。</p>
      <p>累计模型请求 {{ state.budget.model_requests ?? 0 }} 次 · 工具 {{ state.budget.tool_calls ?? 0 }} 次 · 活动 {{ Math.ceil(state.budget.active_seconds ?? 0) }} 秒</p>
      <ul v-if="state.blockers.length"><li v-for="reason in state.blockers" :key="reason">{{ reason }}</li></ul>
      <p v-if="state.expired_approvals.length">{{ state.expired_approvals.length }} 条旧审批已失效，继续时重新检查权限。</p>
      <form v-if="active" class="recovery-steer" @submit.prevent="send('steer')">
        <label :for="`steer-${runId}`">补充本任务约束</label>
        <textarea :id="`steer-${runId}`" v-model="message" class="pa-input" rows="2" maxlength="32000" :disabled="busy" placeholder="例如：停止写入，先解释当前结果" />
        <button class="pa-btn pa-btn--subtle" :disabled="busy || !message.trim() || !!pending">追加约束</button>
        <span>接收后在安全边界应用；正在发生的写入会保留真实结果。当前只收紧约束，解除限制或独立目标请开始新任务。</span>
      </form>
      <ul aria-label="控制进度"><li v-for="item in state.controls" :key="item.request_id">{{ controlLabels[item.kind] }} · {{ item.status === 'applied' ? '已应用' : item.status === 'received' ? '等待应用' : '中断，未确认生效' }}<span v-if="item.message"> · {{ item.message }}</span><span v-if="item.cleanup_complete === false"> · 进程清理未确认</span></li></ul>
      <details><summary @click="loadReview">核对变更归属</summary>
        <template v-if="review">
          <p v-if="!review.snapshot_complete" role="alert">范围扫描不完整，以下列表不是完整仓库审计。</p>
          <p>任务记录 {{ review.task_changes.length }} 组补丁 · 开始前已有 {{ review.preexisting_changes.length }} 项改动</p>
          <ul><li v-for="item in review.preexisting_changes" :key="item.rel_path">已有改动 · {{ item.rel_path }} · {{ item.status }}</li></ul>
          <p>外部或无法归属的变化</p>
          <ul><li v-for="item in review.external_or_unattributed" :key="item.rel_path">{{ item.rel_path }} · {{ item.operation }} · {{ item.after_sha256?.slice(0, 12) ?? '不存在或不可读取' }}</li></ul>
          <details v-for="command in review.command_candidates" :key="command.execution_id"><summary>命令候选变化 · {{ command.items.length }} 项</summary><p>可能包含同时发生的外部编辑，归属未确认。</p><ul><li v-for="item in command.items" :key="item.rel_path">{{ item.rel_path }} · {{ item.operation }}</li></ul></details>
          <PatchReviewPanel v-for="ancestor in ancestors" :key="ancestor" :run-id="ancestor" :active="!!active" />
          <p v-for="limit in review.limitations" :key="limit">{{ limit }}</p>
        </template>
      </details>
    </template>
  </section>
</template>

<style scoped>
.recovery-panel { border-top: 1px solid var(--color-border); padding: var(--space-3); font-size: var(--pa-text-meta); min-height: 0; max-height: 45vh; overflow: auto; overflow-wrap: anywhere; }
.recovery-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.recovery-steer { display: grid; gap: var(--space-2); }
.recovery-steer textarea { resize: vertical; min-width: 0; width: 100%; }
.recovery-panel details { max-height: 45vh; overflow: auto; }
.recovery-panel [role="alert"] { color: var(--color-danger-fg); }
</style>
