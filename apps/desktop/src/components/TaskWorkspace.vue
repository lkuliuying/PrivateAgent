<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhCheckCircle,
  PhListChecks,
  PhPlay,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import {
  approveAgentTaskStep,
  createAgentTask,
  listAgentTasks,
  listProjects,
  retryAgentTaskStep,
  runAgentTask,
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
let timer: ReturnType<typeof setInterval> | undefined;

const selected = computed(
  () => tasks.value.find((t) => t.id === selectedId.value) || tasks.value[0] || null
);

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
    const task = await createAgentTask({
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

function statusText(status: string): string {
  return (
    {
      planned: "Planned",
      waiting_approval: "Needs approval",
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
  if (status === "running" || status === "waiting_approval") return "warn";
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
          <span>Create plan</span>
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
              class="pa-btn pa-btn--primary pa-btn--sm"
              :disabled="busy || selected.status === 'succeeded'"
              @click="runTask(selected.id)"
            >
              <PhPlay :size="14" />
              <span>Run</span>
            </button>
          </div>
        </div>

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
            </div>

            <pre v-if="step.error_message" class="step-error">{{ step.error_message }}</pre>
            <details v-if="step.input_json || step.output_json" class="step-json">
              <summary>Input and output</summary>
              <pre>{{ JSON.stringify({ input: step.input_json, output: step.output_json }, null, 2) }}</pre>
            </details>
          </div>
        </div>

        <section class="evidence">
          <h3>Evidence</h3>
          <div v-if="selected.evidence.length === 0" class="hint">
            Evidence appears after steps run.
          </div>
          <article v-for="ev in selected.evidence" :key="ev.id" class="evidence-item">
            <div class="evidence-title">
              <PhWarningCircle v-if="ev.kind === 'error'" :size="15" />
              <span>{{ ev.title }}</span>
              <small>{{ fmt(ev.created_at) }}</small>
            </div>
            <pre>{{ ev.content_md }}</pre>
          </article>
        </section>

        <section v-if="selected.final_report_md" class="report">
          <h3>Markdown Report</h3>
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
.evidence,
.report {
  margin-top: var(--space-5);
}
.step,
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
.step-json {
  margin-top: var(--space-2);
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
