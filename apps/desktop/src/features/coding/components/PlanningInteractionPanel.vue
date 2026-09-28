<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { PhListChecks, PhQuestion } from "@phosphor-icons/vue";
import { answerPlanQuestion, implementRunPlan, type PlanAnswerRequest, type PlanImplementRequest } from "../api/planning";
import { fetchRunSnapshot } from "../api/runs";
import type { RunProjection } from "../model/runProjector";

const props = defineProps<{ projection: RunProjection }>();
const emit = defineEmits<{ implemented: [runId: string]; revise: []; refresh: []; cancel: [] }>();
const answers = ref<Record<string, string>>({});
const busy = ref(false);
const error = ref("");
const pending = ref<{ kind: "answer"; data: PlanAnswerRequest } | { kind: "implement"; data: PlanImplementRequest } | null>(null);
let generation = 0;
const question = computed(() => props.projection.status === "waiting_input" ? props.projection.pendingInput : null);
const ready = computed(() => props.projection.collaborationMode === "plan" && props.projection.status === "completed"
  && props.projection.runOutcome.goal_outcome === "answered" && !!props.projection.plan && !props.projection.plan.needs_review);
const answered = computed(() => !!question.value && question.value.questions.every(item => answers.value[item.id]?.trim()));

watch(() => [props.projection.runId, question.value?.input_id] as const, () => {
  generation++;
  answers.value = {};
  pending.value = null;
  busy.value = false;
  error.value = "";
}, { immediate: true });
onBeforeUnmount(() => { generation++; });

async function submit(kind: "answer" | "implement") {
  if (busy.value || kind === "answer" && !answered.value || kind === "implement" && !ready.value) return;
  const mine = generation;
  const runId = props.projection.runId;
  const inputId = question.value?.input_id;
  const planVersion = props.projection.plan?.version;
  busy.value = true;
  error.value = "";
  try {
    if (!pending.value) {
      const snapshot = await fetchRunSnapshot(runId);
      if (mine !== generation) return;
      if (snapshot.state_version === undefined || (kind === "answer" ? snapshot.pending_input?.input_id !== inputId
          : snapshot.status !== "completed" || snapshot.plan?.version !== planVersion)) {
        emit("refresh");
        throw new Error("任务已变化，正在刷新；请核对后重试");
      }
      const base = { request_id: crypto.randomUUID(), expected_state_version: snapshot.state_version, checkpoint_id: snapshot.checkpoint_id };
      pending.value = kind === "answer"
        ? { kind, data: { ...base, input_id: inputId!, answers: { ...answers.value } } }
        : { kind, data: { ...base, expected_plan_version: planVersion! } };
    }
    // 不确定的网络结果保留原请求，重试不会重复回答或重复创建实施任务。
    const selected = pending.value;
    const result = selected.kind === "answer" ? await answerPlanQuestion(runId, selected.data) : await implementRunPlan(runId, selected.data);
    if (mine !== generation) return;
    pending.value = null;
    if (selected.kind === "implement") emit("implemented", result.result_run_id);
    else emit("refresh");
  } catch (cause) {
    if (mine !== generation) return;
    const detail = cause as { status?: number; message?: string };
    error.value = detail.message || "提交结果未确认，请重试";
    if (detail.status === 409 || detail.status === 422) {
      pending.value = null;
      emit("refresh");
    }
  } finally {
    if (mine === generation) busy.value = false;
  }
}
</script>

<template>
  <section v-if="question || ready" class="planning-panel" aria-label="计划协作" data-testid="planning-interaction">
    <form v-if="question" @submit.prevent="submit('answer')">
      <div class="planning-heading"><PhQuestion :size="18" aria-hidden="true" /><strong>需要你补充</strong><span>回答后继续规划</span></div>
      <fieldset v-for="item in question.questions" :key="item.id" :disabled="busy || !!pending" class="planning-question">
        <legend>{{ item.question }}</legend>
        <div v-if="item.options.length" class="planning-options">
          <button v-for="option in item.options" :key="option.label" type="button" class="pa-btn pa-btn--subtle planning-option"
            :aria-pressed="answers[item.id] === option.label" @click="answers[item.id] = option.label">
            <strong>{{ option.label }}</strong><span v-if="option.description">{{ option.description }}</span>
          </button>
        </div>
        <textarea v-model="answers[item.id]" class="pa-input" :aria-label="item.question" maxlength="4000" rows="2" placeholder="选择建议，或填写你的回答" />
      </fieldset>
      <div class="planning-actions">
        <button type="submit" class="pa-btn pa-btn--primary" :disabled="busy || !answered" data-testid="planning-answer">{{ busy ? '正在提交…' : pending ? '重试提交' : '提交回答' }}</button>
        <button type="button" class="pa-btn pa-btn--subtle" :disabled="busy" @click="emit('cancel')">取消任务</button>
      </div>
    </form>
    <template v-else-if="ready">
      <div class="planning-heading"><PhListChecks :size="18" aria-hidden="true" /><strong>计划已就绪</strong><span>尚未实施</span></div>
      <details class="planning-preview">
        <summary>查看实施步骤（{{ projection.plan?.items.filter(item => item.status === 'pending').length }} 项）</summary>
        <ol>
          <li v-for="item in projection.plan?.items.filter(item => item.status === 'pending')" :key="item.item_key">
            <strong>{{ item.title }}</strong><p v-if="item.detail">{{ item.detail }}</p>
          </li>
        </ol>
      </details>
      <p class="planning-hint">执行时沿用当前权限设置，需要审批的操作会单独确认。</p>
      <div class="planning-actions">
        <button class="pa-btn pa-btn--primary" :disabled="busy" data-testid="planning-implement" @click="submit('implement')">{{ busy ? '正在开始…' : pending ? '重试开始执行' : '按计划执行' }}</button>
        <button class="pa-btn pa-btn--subtle" :disabled="busy || !!pending" data-testid="planning-revise" @click="emit('revise')">修改计划</button>
      </div>
    </template>
    <p v-if="error" class="planning-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.planning-panel { flex-shrink: 0; max-height: 45vh; overflow-y: auto; margin: var(--space-2) var(--space-4); padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-panel); font-size: var(--text-sm); color: var(--color-fg); }
.planning-heading, .planning-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.planning-heading > span, .planning-hint, .planning-option span { color: var(--color-fg-muted); font-size: var(--pa-text-meta); }
.planning-question { margin: var(--space-3) 0; padding: 0; border: 0; min-width: 0; }
.planning-question legend { padding: 0; margin-bottom: var(--space-2); overflow-wrap: anywhere; }
.planning-options { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-2); }
.planning-option { flex: 1 1 160px; display: flex; align-items: flex-start; justify-content: center; flex-direction: column; height: auto; min-height: 56px; padding: var(--space-2) var(--space-3); white-space: normal; text-align: left; }
.planning-option[aria-pressed="true"] { outline: 2px solid var(--color-accent); outline-offset: -2px; }
textarea { display: block; box-sizing: border-box; width: 100%; resize: vertical; }
.planning-preview { margin: var(--space-2) 0; }
.planning-preview summary { cursor: pointer; }
.planning-preview ol { padding-left: var(--space-5); }
.planning-preview li { margin-bottom: var(--space-2); overflow-wrap: anywhere; }
.planning-preview p { margin: var(--space-1) 0; white-space: pre-wrap; color: var(--color-fg-muted); }
.planning-error { color: var(--color-danger); overflow-wrap: anywhere; }
@media (max-width: 600px) { .planning-panel { margin-inline: var(--space-2); } }
</style>
