<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { PhArrowClockwise, PhCheckCircle, PhFileText, PhPlus } from "@phosphor-icons/vue";
import {
  addGoalLink,
  addGoalCheckin,
  createGoal,
  createGoalBriefing,
  createGoalTaskDraft,
  getGoal,
  listGoals,
  updateGoal,
} from "../api";
import type { GoalDetail, GoalPriority, GoalStatus, PersonalGoal } from "../types";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();

const goals = ref<PersonalGoal[]>([]);
const selected = ref<GoalDetail | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const title = ref("");
const domain = ref("custom");
const targetDate = ref("");
const progress = ref("");
const confidence = ref(0.7);
const linkType = ref("agent_task");
const linkId = ref<number | null>(null);
const linkRelation = ref("supports");

const activeGoals = computed(() => goals.value.filter((g) => g.status === "active"));

function fmtDate(s: string | null): string {
  return s ? s.slice(0, 10) : "未设置";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    goals.value = await listGoals();
    if (!selected.value && goals.value.length > 0) {
      await selectGoal(goals.value[0].id);
    } else if (selected.value) {
      await selectGoal(selected.value.goal.id);
    }
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function selectGoal(id: number) {
  selected.value = await getGoal(id);
}

async function onCreate() {
  const text = title.value.trim();
  if (!text) return;
  busy.value = true;
  error.value = "";
  try {
    const goal = await createGoal({
      title: text,
      domain: domain.value.trim() || "custom",
      target_date: targetDate.value || null,
      priority: "normal",
    });
    title.value = "";
    targetDate.value = "";
    await load();
    await selectGoal(goal.id);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function setStatus(goal: PersonalGoal, status: GoalStatus) {
  busy.value = true;
  try {
    await updateGoal(goal.id, { status });
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function setPriority(goal: PersonalGoal, priority: GoalPriority) {
  busy.value = true;
  try {
    await updateGoal(goal.id, { priority });
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function addCheckin() {
  if (!selected.value || !progress.value.trim()) return;
  busy.value = true;
  try {
    await addGoalCheckin(selected.value.goal.id, {
      progress_note_md: progress.value.trim(),
      confidence: confidence.value,
    });
    progress.value = "";
    await selectGoal(selected.value.goal.id);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function addLink() {
  if (!selected.value || !linkId.value) return;
  busy.value = true;
  try {
    await addGoalLink(selected.value.goal.id, {
      target_type: linkType.value,
      target_id: linkId.value,
      relation: linkRelation.value.trim() || "supports",
    });
    linkId.value = null;
    await selectGoal(selected.value.goal.id);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function makeBriefing() {
  if (!selected.value) return;
  busy.value = true;
  try {
    await createGoalBriefing(selected.value.goal.id);
    notify.success("目标简报已生成", "可在简报区查看。");
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function makeTaskDraft() {
  if (!selected.value) return;
  busy.value = true;
  try {
    const res = await createGoalTaskDraft(selected.value.goal.id);
    notify.success("任务草稿已生成", `任务草稿 #${res.task_id}`);
    await selectGoal(selected.value.goal.id);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="goal-panel">
    <div class="panel-head">
      <div>
        <h3>长期目标</h3>
        <p class="hint">活跃 {{ activeGoals.length }} 个，支持 check-in、转任务与目标简报。</p>
      </div>
      <button class="icon-btn" :disabled="loading" title="刷新" @click="load">
        <PhArrowClockwise :size="16" />
      </button>
    </div>

    <div v-if="error" class="error-line">{{ error }}</div>

    <form class="create-row" @submit.prevent="onCreate">
      <input v-model="title" class="pa-input" placeholder="新目标，例如：掌握 Agent 工作流" />
      <input v-model="domain" class="pa-input small" placeholder="领域" />
      <input v-model="targetDate" class="pa-input date" type="date" />
      <button class="pa-btn pa-btn--primary" :disabled="busy || !title.trim()">
        <PhPlus :size="14" /> 新建
      </button>
    </form>

    <div class="goal-grid">
      <div class="goal-list">
        <button
          v-for="g in goals"
          :key="g.id"
          class="goal-item"
          :class="{ active: selected?.goal.id === g.id }"
          @click="selectGoal(g.id)"
        >
          <span class="goal-title">{{ g.title }}</span>
          <span class="goal-meta">{{ g.status }} · {{ g.priority }} · {{ fmtDate(g.target_date) }}</span>
        </button>
        <div v-if="!loading && goals.length === 0" class="empty">还没有长期目标。</div>
      </div>

      <div v-if="selected" class="goal-detail">
        <div class="detail-head">
          <div>
            <h4>{{ selected.goal.title }}</h4>
            <p class="hint">{{ selected.goal.domain }} · 截止 {{ fmtDate(selected.goal.target_date) }}</p>
          </div>
          <div class="actions">
            <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="makeTaskDraft">
              <PhCheckCircle :size="14" /> 转任务
            </button>
            <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="makeBriefing">
              <PhFileText :size="14" /> 简报
            </button>
          </div>
        </div>

        <div class="inline-controls">
          <select class="pa-input" :value="selected.goal.status" @change="setStatus(selected.goal, ($event.target as HTMLSelectElement).value as GoalStatus)">
            <option value="active">active</option>
            <option value="paused">paused</option>
            <option value="done">done</option>
            <option value="archived">archived</option>
          </select>
          <select class="pa-input" :value="selected.goal.priority" @change="setPriority(selected.goal, ($event.target as HTMLSelectElement).value as GoalPriority)">
            <option value="low">low</option>
            <option value="normal">normal</option>
            <option value="high">high</option>
          </select>
        </div>

        <textarea v-model="progress" class="pa-input" rows="3" placeholder="记录本周进展、阻塞或下一步"></textarea>
        <div class="checkin-row">
          <label class="hint">信心 {{ confidence.toFixed(1) }}</label>
          <input v-model.number="confidence" type="range" min="0" max="1" step="0.1" />
          <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="busy || !progress.trim()" @click="addCheckin">
            Check-in
          </button>
        </div>

        <div class="link-box">
          <strong>关联对象</strong>
          <div class="link-row">
            <select v-model="linkType" class="pa-input">
              <option value="learning_topic">learning_topic</option>
              <option value="project">project</option>
              <option value="agent_task">agent_task</option>
              <option value="document_collection">document_collection</option>
            </select>
            <input v-model.number="linkId" class="pa-input id-input" type="number" min="1" placeholder="ID" />
            <input v-model="linkRelation" class="pa-input" placeholder="relation" />
            <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy || !linkId" @click="addLink">
              关联
            </button>
          </div>
          <div class="links">
            <span v-for="l in selected.links" :key="l.id" class="link-chip">
              {{ l.relation }} · {{ l.target_type }} #{{ l.target_id }}
            </span>
            <span v-if="selected.links.length === 0" class="empty">暂无关联对象。</span>
          </div>
        </div>

        <div class="history">
          <div v-for="c in selected.checkins" :key="c.id" class="history-item">
            <strong>{{ c.checkin_date }}</strong>
            <span>{{ c.progress_note_md || "无备注" }}</span>
          </div>
          <div v-if="selected.checkins.length === 0" class="empty">暂无 check-in。</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.goal-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel-head,
.detail-head,
.checkin-row,
.inline-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.panel-head h3,
.detail-head h4 {
  margin: 0;
}
.hint {
  margin: 0;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.error-line {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius);
  padding: var(--space-2);
  font-size: var(--text-sm);
}
.create-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 120px 150px auto;
  gap: var(--space-2);
}
.goal-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.9fr) minmax(300px, 1.4fr);
  gap: var(--space-3);
}
.goal-list,
.goal-detail {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
}
.goal-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.goal-item {
  text-align: left;
  border: 1px solid var(--color-border);
  background: var(--color-bg);
  border-radius: var(--radius);
  padding: var(--space-2);
  cursor: pointer;
}
.goal-item.active {
  border-color: var(--color-accent);
}
.goal-title,
.goal-meta {
  display: block;
}
.goal-title {
  font-weight: var(--font-medium);
}
.goal-meta {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  margin-top: 2px;
}
.goal-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.actions {
  display: flex;
  gap: var(--space-2);
}
.inline-controls {
  justify-content: flex-start;
}
.inline-controls .pa-input {
  max-width: 140px;
}
.checkin-row {
  justify-content: flex-start;
}
.link-box {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.link-row {
  display: grid;
  grid-template-columns: 1.2fr 90px 1fr auto;
  gap: var(--space-2);
}
.id-input {
  min-width: 0;
}
.links {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.link-chip {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  padding: 3px 8px;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
}
.history {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.history-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-top: 1px solid var(--color-border);
  padding-top: var(--space-2);
  font-size: var(--text-sm);
}
.empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
@media (max-width: 900px) {
  .create-row,
  .goal-grid,
  .link-row {
    grid-template-columns: 1fr;
  }
}
</style>
