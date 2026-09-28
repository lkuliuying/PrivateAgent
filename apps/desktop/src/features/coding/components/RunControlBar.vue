<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { controlRun, fetchRecovery, type RecoveryReport, type RunControlKind } from "../api/recovery";
import { enqueueTurn, fetchTurnQueue, removeQueuedTurn, type QueuedTurn } from "../api/turnQueue";
import { readPendingControl, savePendingControl, type PendingControl } from "../model/pendingControls";
import { isTerminalRunStatus } from "../model/runContracts";
const props = defineProps<{ runId: string; sessionId: number }>();
const emit = defineEmits<{ resumed: [id: string] }>();
const state = ref<RecoveryReport | null>(null);
const queued = ref<QueuedTurn | null>(null);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const pending = ref<PendingControl | null>(null);
let generation = 0, loadSequence = 0;
let launchedNotified = "";
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;
const active = computed(() => state.value && !isTerminalRunStatus(state.value.status));
const paused = computed(() => state.value?.status === "paused");
const pausePending = computed(() => pending.value?.kind === "pause" || !!state.value?.controls.some(item => item.kind === "pause" && item.status === "received"));
const canPause = computed(() => !!active.value && !paused.value && !busy.value && !pending.value && !pausePending.value);
async function load(clearError = false) {
  const mine = generation, request = ++loadSequence;
  controller?.abort(); const current = controller = new AbortController();
  try {
    const [report, queue] = await Promise.all([fetchRecovery(props.runId, current.signal), fetchTurnQueue(props.sessionId, current.signal)]);
    if (mine !== generation || request !== loadSequence) return;
    state.value = report; queued.value = queue.item;
    if (clearError) error.value = "";
    if (queue.item?.state === "launched" && queue.item.after_run_id === props.runId && queue.item.result_run_id && launchedNotified !== queue.item.result_run_id) { launchedNotified = queue.item.result_run_id; emit("resumed", queue.item.result_run_id); }
  } catch (cause) { if (mine === generation && request === loadSequence && !current.signal.aborted) error.value = (cause as { message?: string }).message || "运行状态读取失败"; }
  finally { if (mine === generation && request === loadSequence) { clearTimeout(timer); if (active.value || queued.value?.state === "pending") timer = setTimeout(() => void load(), 1500); } }
}
async function act(kind: RunControlKind | "queue", message?: string, retry = false): Promise<boolean> {
  if (busy.value || pending.value && !retry) return false;
  busy.value = true; error.value = ""; notice.value = "";
  const mine = generation, runId = props.runId, sessionId = props.sessionId;
  try {
    if (!state.value) await load();
    if (mine !== generation || !state.value) return false;
    if (!retry) pending.value = { kind, data: { request_id: crypto.randomUUID(), expected_state_version: state.value.state_version,
      ...(message ? { message } : {}), ...(kind === "resume" ? { checkpoint_id: state.value.checkpoint_id } : {}) } };
    savePendingControl(runId, pending.value);
    const request = pending.value;
    if (!request) return false;
    if (request.kind === "queue") await enqueueTurn(sessionId, runId, request.data.request_id, request.data.message!);
    else {
      const result = await controlRun(runId, request.kind, request.data);
      if (mine === generation && request.kind === "resume") emit("resumed", result.result_run_id);
    }
    savePendingControl(runId, null);
    if (mine !== generation) return false;
    notice.value = request.kind === "steer" ? "已接收补充要求，将在安全边界应用" : request.kind === "queue" ? "下一条已保存，本轮正常结束后自动发送" : "控制请求已接收";
    pending.value = null; await load(); return true;
  } catch (cause) {
    if (mine !== generation) return false;
    const failure = cause as { status?: number; message?: string };
    error.value = failure.message || "请求结果未确认，请重试上次请求";
    if (failure.status && failure.status < 500) { pending.value = null; savePendingControl(runId, null); }
    await load(); return false;
  } finally { if (mine === generation) busy.value = false; }
}
async function dequeue() {
  if (!queued.value || busy.value) return;
  const mine = generation; busy.value = true;
  try { const item = await removeQueuedTurn(props.sessionId, queued.value.request_id); if (mine === generation) queued.value = item; }
  catch (cause) { if (mine === generation) error.value = (cause as { message?: string }).message || "撤回失败"; }
  finally { if (mine === generation) busy.value = false; }
}
defineExpose({ pause: () => canPause.value ? act("pause") : Promise.resolve(false), paused, pausePending, canPause });
watch(() => props.runId, () => { generation++; controller?.abort(); clearTimeout(timer); state.value = null; queued.value = null; pending.value = readPendingControl(props.runId); busy.value = false; error.value = ""; notice.value = ""; void load(); }, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); clearTimeout(timer); });
</script>
<template>
  <section v-if="paused || state?.can_resume || notice || error || pending || queued && ['pending', 'blocked'].includes(queued.state)" class="run-control-bar" aria-label="运行控制">
    <div class="control-actions">
      <span v-if="paused">已暂停</span>
      <button v-if="state?.can_resume" class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy || !!pending" @click="act('resume')">继续任务</button>
      <button v-if="error && !pending" class="pa-btn pa-btn--ghost pa-btn--sm" :disabled="busy" @click="load(true)">刷新状态</button>
    </div>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="pending && !busy" class="pa-btn pa-btn--subtle" @click="act(pending.kind, undefined, true)">重试上次请求</button>
    <div v-if="queued && ['pending', 'blocked'].includes(queued.state)" class="queued-turn"><span>下一条：{{ queued.message }}</span><small v-if="queued.error">{{ queued.error }}</small><button class="pa-btn pa-btn--ghost pa-btn--sm" :disabled="busy" @click="dequeue">撤回排队</button></div>
  </section>
</template>
<style scoped>
.run-control-bar { width: min(var(--coding-content-width), 100%); margin: 0 auto 6px; font-size: 12px; color: var(--color-fg-muted); }
.control-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
p { margin: 5px 0; } [role="alert"] { color: var(--color-danger-fg); }
.queued-turn { padding: 8px 12px; background: var(--color-surface-sunken); border-radius: var(--radius); display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.queued-turn span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
.queued-turn small { flex-basis: 100%; }
</style>
