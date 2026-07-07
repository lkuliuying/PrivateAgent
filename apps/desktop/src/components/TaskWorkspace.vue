<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  PhArrowClockwise,
  PhBrain,
  PhCheckCircle,
  PhListChecks,
  PhPlay,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import {
  approveAgentTaskStep,
  approveAgentTaskPlan,
  candidateMemories,
  cancelAgentTask,
  createAgentTaskPlan,
  listAgentTasks,
  listProjects,
  pauseAgentTask,
  resumeAgentTask,
  resumeAgentTaskFrom,
  retryAgentTaskStep,
  runAgentTask,
  updateAgentTaskPlan,
} from "../api";
import type { AgentTask, AgentTaskStep, Project } from "../types";

const tasks = ref<AgentTask[]>([]);
const projects = ref<Project[]>([]);
const selectedId = ref<number | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const title = ref("Fix or verify project");
const goal = ref("Run checks, apply approved changes, and collect evidence.");
const projectId = ref<number | "">("");
const planText = ref("");
const evidenceKind = ref("");
const evidenceText = ref("");
let timer: ReturnType<typeof setInterval> | undefined;

const candBusy = ref(false);
const candMsg = ref("");

async function genCandidates(taskId: number) {
  candBusy.value = true;
  candMsg.value = "";
  try {
    const list = await candidateMemories({
      source_type: "agent_task",
      source_id: taskId,
    });
    candMsg.value = `已生成 ${list.length} 条候选记忆（draft，请在记忆页确认）`;
  } catch (e) {
    candMsg.value = String(e);
  } finally {
    candBusy.value = false;
  }
}

const selected = computed(
  () => tasks.value.find((t) => t.id === selectedId.value) || tasks.value[0] || null
);
const displayedEvidence = computed(() => {
  const evs = selected.value?.evidence || [];
  return evs.filter((ev) => {
    if (evidenceKind.value && ev.kind !== evidenceKind.value) return false;
    if (evidenceText.value) {
      const needle = evidenceText.value.toLowerCase();
      return (
        ev.title.toLowerCase().includes(needle) ||
        ev.content_md.toLowerCase().includes(needle)
      );
    }
    return true;
  });
});

function syncPlanEditor(task: AgentTask | null) {
  if (!task) {
    planText.value = "";
    return;
  }
  planText.value = JSON.stringify(
    task.steps.map((s) => ({
      title: s.title,
      tool_name: s.tool_name || "",
      input_json: s.input_json || {},
    })),
    null,
    2
  );
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [taskRows, projectRows] = await Promise.all([
      listAgentTasks(),
      listProjects(),
    ]);
    tasks.value = taskRows;
    projects.value = projectRows.filter((p) => p.status === "active");
    if (!selectedId.value && taskRows.length) selectedId.value = taskRows[0].id;
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function createTask() {
  if (!title.value.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    const task = await createAgentTaskPlan({
      title: title.value.trim(),
      goal: goal.value.trim(),
      project_id: projectId.value === "" ? undefined : Number(projectId.value),
    });
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function savePlan() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    const steps = JSON.parse(planText.value);
    if (!Array.isArray(steps)) throw new Error("计划必须是步骤数组");
    const task = await updateAgentTaskPlan(selected.value.id, {
      title: selected.value.title,
      goal: selected.value.goal || "",
      steps: steps.map((s) => ({
        title: String(s.title || ""),
        tool_name: String(s.tool_name || ""),
        input_json: s.input_json || {},
      })),
    });
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = "保存计划失败：" + String(e);
  } finally {
    busy.value = false;
  }
}

async function approvePlan(id: number) {
  busy.value = true;
  error.value = "";
  try {
    const task = await approveAgentTaskPlan(id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function runTask(id: number) {
  busy.value = true;
  error.value = "";
  try {
    const task = await runAgentTask(id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function pauseTask(id: number) {
  busy.value = true;
  error.value = "";
  try {
    const task = await pauseAgentTask(id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function cancelTask(id: number) {
  busy.value = true;
  error.value = "";
  try {
    const task = await cancelAgentTask(id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function resumeTask(id: number) {
  busy.value = true;
  error.value = "";
  try {
    const task = await resumeAgentTask(id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function approveStep(step: AgentTaskStep) {
  busy.value = true;
  error.value = "";
  try {
    const task = await approveAgentTaskStep(step.id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function retryStep(step: AgentTaskStep) {
  busy.value = true;
  error.value = "";
  try {
    const task = await retryAgentTaskStep(step.id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function resumeFromStep(step: AgentTaskStep) {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    const task = await resumeAgentTaskFrom(selected.value.id, step.id);
    await load();
    selectedId.value = task.id;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

function statusText(status: string): string {
  return (
    {
      planned: "Planned",
      plan_draft: "Plan draft",
      plan_approved: "Plan approved",
      waiting_approval: "Needs approval",
      paused: "Paused",
      running: "Running",
      succeeded: "Succeeded",
      failed: "Failed",
      skipped: "Skipped",
      cancelled: "Cancelled",
    } as Record<string, string>
  )[status] || status;
}

function statusClass(status: string): string {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "bad";
  if (
    status === "running" ||
    status === "waiting_approval" ||
    status === "plan_draft" ||
    status === "plan_approved" ||
    status === "paused"
  )
    return "warn";
  return "muted";
}

function fmt(s: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(
    2,
    "0"
  )}:${String(d.getMinutes()).padStart(2, "0")}`;
}

onMounted(() => {
  load();
  timer = setInterval(load, 5000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
watch(selected, (task) => syncPlanEditor(task), { immediate: true });
</script>

<template>
  <section class="tasks-shell">
    <aside class="task-list">
      <div class="pane-head">
        <div>
          <h1>Agent Tasks</h1>
          <p>Plan, approve, run, and review evidence.</p>
        </div>
        <button class="icon-btn" :disabled="loading" title="Refresh" @click="load">
          <PhArrowClockwise :size="16" />
        </button>
      </div>

      <div class="new-task">
        <input v-model="title" class="pa-input" placeholder="Task title" />
        <textarea v-model="goal" class="pa-input" rows="3" placeholder="Goal" />
        <select v-model="projectId" class="pa-input">
          <option value="">No project</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">
            {{ p.name }}
          </option>
        </select>
        <button class="pa-btn pa-btn--primary" :disabled="busy" @click="createTask">
          <PhListChecks :size="15" />
          <span>Generate draft</span>
        </button>
      </div>

      <div v-if="error" class="error-line">{{ error }}</div>

      <button
        v-for="t in tasks"
        :key="t.id"
        class="task-row"
        :class="{ active: selected?.id === t.id }"
        @click="selectedId = t.id"
      >
        <span class="task-title">{{ t.title }}</span>
        <span class="task-meta">
          <span class="status-dot" :class="statusClass(t.status)" />
          {{ statusText(t.status) }} · {{ fmt(t.updated_at) }}
        </span>
      </button>
    </aside>

    <main class="task-main">
      <div v-if="!selected" class="empty">
        <PhListChecks :size="44" weight="duotone" />
        <p>No tasks yet</p>
      </div>

      <template v-else>
        <div class="detail-head">
          <div>
            <h2>{{ selected.title }}</h2>
            <p>{{ selected.goal || "No goal" }}</p>
          </div>
          <div class="head-actions">
            <span class="task-status" :class="statusClass(selected.status)">
              {{ statusText(selected.status) }}
            </span>
            <button
              v-if="selected.status === 'plan_draft' || selected.status === 'planned'"
              class="pa-btn pa-btn--primary pa-btn--sm"
              :disabled="busy"
              @click="approvePlan(selected.id)"
            >
              <PhCheckCircle :size="14" />
              <span>Approve plan</span>
            </button>
            <button
              class="pa-btn pa-btn--primary pa-btn--sm"
              :disabled="
                busy ||
                selected.status === 'succeeded' ||
                selected.status === 'cancelled' ||
                selected.status === 'plan_draft' ||
                selected.status === 'paused'
              "
              @click="runTask(selected.id)"
            >
              <PhPlay :size="14" />
              <span>Run</span>
            </button>
            <button
              v-if="selected.status === 'running' || selected.status === 'waiting_approval'"
              class="pa-btn pa-btn--subtle pa-btn--sm"
              :disabled="busy"
              @click="pauseTask(selected.id)"
            >
              Pause
            </button>
            <button
              v-if="selected.status === 'paused' || selected.status === 'failed'"
              class="pa-btn pa-btn--subtle pa-btn--sm"
              :disabled="busy"
              @click="resumeTask(selected.id)"
            >
              Resume
            </button>
            <button
              v-if="selected.status !== 'succeeded' && selected.status !== 'cancelled'"
              class="pa-btn pa-btn--subtle pa-btn--sm"
              :disabled="busy"
              @click="cancelTask(selected.id)"
            >
              Cancel
            </button>
          </div>
        </div>

        <section
          v-if="selected.status === 'plan_draft' || selected.status === 'planned'"
          class="plan-editor"
        >
          <div class="plan-head">
            <h3>Editable Plan</h3>
            <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="savePlan">
              Save plan
            </button>
          </div>
          <textarea v-model="planText" class="plan-text" spellcheck="false" />
          <p class="hint">每个步骤包含 title / tool_name / input_json。保存后需要批准计划才会执行。</p>
        </section>

        <div class="steps">
          <div v-for="step in selected.steps" :key="step.id" class="step">
            <div class="step-top">
              <span class="step-num">{{ step.ordinal }}</span>
              <div class="step-main">
                <div class="step-title">{{ step.title }}</div>
                <div class="step-sub">
                  {{ step.tool_name || "manual" }}
                  <span v-if="step.tool_call_id"> · tool #{{ step.tool_call_id }}</span>
                </div>
              </div>
              <span class="step-status" :class="statusClass(step.status)">
                {{ statusText(step.status) }}
              </span>
              <button
                v-if="step.status === 'waiting_approval'"
                class="pa-btn pa-btn--primary pa-btn--sm"
                :disabled="busy"
                @click="approveStep(step)"
              >
                <PhCheckCircle :size="14" />
                <span>Approve</span>
              </button>
              <button
                v-if="step.status === 'failed'"
                class="pa-btn pa-btn--subtle pa-btn--sm"
                :disabled="busy"
                @click="retryStep(step)"
              >
                <PhArrowClockwise :size="14" />
                <span>Retry</span>
              </button>
              <button
                v-if="step.status === 'failed' || step.status === 'cancelled'"
                class="pa-btn pa-btn--subtle pa-btn--sm"
                :disabled="busy"
                @click="resumeFromStep(step)"
              >
                <span>Resume from here</span>
              </button>
            </div>

            <pre v-if="step.error_message" class="step-error">{{ step.error_message }}</pre>
            <details v-if="step.input_json || step.output_json" class="step-json">
              <summary>Input and output</summary>
              <pre>{{ JSON.stringify({ input: step.input_json, output: step.output_json }, null, 2) }}</pre>
            </details>
          </div>
        </div>

        <section class="evidence">
          <div class="evidence-head">
            <h3>Evidence</h3>
            <select v-model="evidenceKind" class="pa-input evidence-filter">
              <option value="">All kinds</option>
              <option value="tool_output">Tool output</option>
              <option value="error">Error</option>
              <option value="note">Note</option>
              <option value="report">Report</option>
            </select>
            <input
              v-model="evidenceText"
              class="pa-input evidence-search"
              placeholder="Filter evidence"
            />
          </div>
          <div v-if="displayedEvidence.length === 0" class="hint">
            Evidence appears after steps run.
          </div>
          <article v-for="ev in displayedEvidence" :key="ev.id" class="evidence-item">
            <div class="evidence-title">
              <PhWarningCircle v-if="ev.kind === 'error'" :size="15" />
              <span>{{ ev.title }}</span>
              <small>{{ fmt(ev.created_at) }}</small>
            </div>
            <pre>{{ ev.content_md }}</pre>
          </article>
        </section>

        <section v-if="selected.final_report_md" class="report">
          <div class="report-head">
            <h3>Markdown Report</h3>
            <button
              class="pa-btn pa-btn--subtle pa-btn--sm"
              :disabled="candBusy"
              @click="genCandidates(selected.id)"
            >
              <PhBrain :size="14" />
              <span>生成候选记忆</span>
            </button>
          </div>
          <p v-if="candMsg" class="cand-msg">{{ candMsg }}</p>
          <pre>{{ selected.final_report_md }}</pre>
        </section>
      </template>
    </main>
  </section>
</template>

<style scoped>
.tasks-shell {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  min-height: 0;
  flex: 1;
}
.task-list {
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
  overflow: auto;
  padding: var(--space-4);
}
.pane-head,
.detail-head,
.step-top,
.evidence-title,
.head-actions {
  display: flex;
  align-items: center;
}
.pane-head,
.detail-head {
  justify-content: space-between;
  gap: var(--space-3);
}
h1,
h2,
h3,
p {
  margin: 0;
}
h1 {
  font-size: var(--text-xl);
}
h2 {
  font-size: var(--text-2xl);
}
h3 {
  font-size: var(--text-lg);
  margin-bottom: var(--space-2);
}
.pane-head p,
.detail-head p,
.hint,
.step-sub,
.task-meta {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.icon-btn {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
}
.new-task {
  display: grid;
  gap: var(--space-2);
  margin: var(--space-4) 0;
}
.new-task textarea {
  resize: vertical;
  min-height: 74px;
}
.error-line,
.step-error {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius);
  padding: var(--space-2);
  white-space: pre-wrap;
}
.task-row {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  display: grid;
  gap: 4px;
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  text-align: left;
  cursor: pointer;
}
.task-row.active,
.task-row:hover {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}
.task-title {
  font-weight: var(--font-medium);
}
.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-fg-faint);
}
.status-dot.ok {
  background: var(--color-success-fg);
}
.status-dot.bad {
  background: var(--color-danger-fg);
}
.status-dot.warn {
  background: var(--color-warning-fg);
}
.task-main {
  overflow: auto;
  padding: 28px 32px;
}
.head-actions {
  gap: var(--space-2);
}
.task-status,
.step-status {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.ok {
  color: var(--color-success-fg);
}
.bad {
  color: var(--color-danger-fg);
}
.warn {
  color: var(--color-warning-fg);
}
.muted {
  color: var(--color-fg-faint);
}
.steps,
.plan-editor,
.evidence,
.report {
  margin-top: var(--space-5);
}
.step,
.plan-editor,
.evidence-item,
.report {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
  margin-bottom: var(--space-2);
}
.step-top {
  gap: var(--space-3);
}
.step-num {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
}
.step-main {
  flex: 1;
  min-width: 0;
}
.step-title {
  font-weight: var(--font-medium);
}
.plan-head,
.evidence-head,
.step-json {
  margin-top: var(--space-2);
}
.plan-head,
.evidence-head,
.report-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.plan-head h3,
.evidence-head h3,
.report-head h3 {
  margin: 0;
}
.plan-text {
  width: 100%;
  min-height: 220px;
  resize: vertical;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.5;
  color: var(--color-fg);
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.evidence-filter {
  width: 150px;
}
.evidence-search {
  width: min(260px, 100%);
}
.cand-msg {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
}
pre {
  margin: var(--space-2) 0 0;
  max-height: 360px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}
.evidence-title {
  gap: var(--space-2);
  font-weight: var(--font-medium);
}
.evidence-title small {
  margin-left: auto;
  color: var(--color-fg-faint);
  font-weight: var(--font-regular);
}
.empty {
  min-height: 420px;
  display: grid;
  place-items: center;
  color: var(--color-fg-faint);
}

@media (max-width: 900px) {
  .tasks-shell {
    grid-template-columns: 1fr;
  }
  .task-list {
    border-right: 0;
    border-bottom: 1px solid var(--color-border);
    max-height: 420px;
  }
}
</style>
