<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhBell,
  PhCheck,
  PhClock,
  PhPlus,
  PhTrash,
} from "@phosphor-icons/vue";
import {
  createReminder,
  deleteReminder,
  doneReminder,
  listReminders,
  snoozeReminder,
} from "../api";
import type { RecurrenceFreq, Reminder } from "../types";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();

const reminders = ref<Reminder[]>([]);
const loading = ref(false);
const busy = ref(false);
const error = ref("");

const filterStatus = ref<string>("active");

const showCreate = ref(false);
const form = ref({
  title: "",
  due_at: "",
  freq: "none" as RecurrenceFreq,
  interval: 1,
  body_md: "",
});

const FREQS: RecurrenceFreq[] = ["none", "daily", "weekly", "monthly"];
const FREQ_LABEL: Record<string, string> = {
  none: "不重复",
  daily: "每天",
  weekly: "每周",
  monthly: "每月",
};

async function load() {
  loading.value = true;
  error.value = "";
  try {
    reminders.value = await listReminders(filterStatus.value || undefined);
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function reload() {
  await load();
}

async function save() {
  if (!form.value.title.trim() || !form.value.due_at) return;
  busy.value = true;
  error.value = "";
  try {
    // datetime-local 是本地时间，转 UTC ISO 发送，与后端 utcnow 比较基准一致。
    const due_at = new Date(form.value.due_at).toISOString();
    await createReminder({
      title: form.value.title.trim(),
      due_at,
      body_md: form.value.body_md.trim() || undefined,
      recurrence_rule:
        form.value.freq !== "none"
          ? { freq: form.value.freq, interval: form.value.interval }
          : undefined,
    });
    form.value = { title: "", due_at: "", freq: "none", interval: 1, body_md: "" };
    showCreate.value = false;
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function snooze(r: Reminder, minutes: number) {
  busy.value = true;
  error.value = "";
  try {
    await snoozeReminder(r.id, { minutes });
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function done(r: Reminder) {
  busy.value = true;
  error.value = "";
  try {
    await doneReminder(r.id);
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function remove(r: Reminder) {
  if (!await notify.confirm({ title: `确定删除提醒「${r.title}」？`, danger: true, impact: "该操作不可撤销，提醒将被永久删除" })) return;
  busy.value = true;
  error.value = "";
  try {
    await deleteReminder(r.id);
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

function statusLabel(s: string): string {
  return (
    {
      active: "进行中",
      snoozed: "稍后",
      done: "已完成",
      cancelled: "已取消",
    } as Record<string, string>
  )[s] || s;
}
function fmt(s: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}
function ruleLabel(r: Reminder): string {
  if (!r.recurrence_rule || r.recurrence_rule.freq === "none") return "";
  const f = FREQ_LABEL[r.recurrence_rule.freq];
  return r.recurrence_rule.interval > 1 ? `每 ${r.recurrence_rule.interval} ${f}` : f;
}

defineExpose({ reload });
onMounted(load);
</script>

<template>
  <section class="rem-panel">
    <div class="pane-head">
      <div>
        <h3>提醒</h3>
        <p class="hint">一次性/重复提醒；到期进入今日页，可稍后或完成。</p>
      </div>
      <div class="head-actions">
        <button class="icon-btn" :disabled="loading" title="刷新" @click="load">
          <PhArrowClockwise :size="16" />
        </button>
        <button class="pa-btn pa-btn--primary pa-btn--sm" @click="showCreate = !showCreate">
          <PhPlus :size="15" />
          <span>新建</span>
        </button>
      </div>
    </div>

    <div v-if="showCreate" class="create-form">
      <input v-model="form.title" class="pa-input" placeholder="提醒标题…" />
      <div class="form-row">
        <input v-model="form.due_at" type="datetime-local" class="pa-input" />
        <select v-model="form.freq" class="pa-input">
          <option v-for="f in FREQS" :key="f" :value="f">{{ FREQ_LABEL[f] }}</option>
        </select>
        <input
          v-if="form.freq !== 'none'"
          v-model.number="form.interval"
          type="number"
          min="1"
          class="pa-input"
          title="间隔"
        />
      </div>
      <textarea v-model="form.body_md" class="pa-input" rows="2" placeholder="详情（可选）…"></textarea>
      <div class="form-actions">
        <button
          class="pa-btn pa-btn--primary pa-btn--sm"
          :disabled="busy || !form.title.trim() || !form.due_at"
          @click="save"
        >
          <PhCheck :size="14" /> 保存
        </button>
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="showCreate = false">取消</button>
      </div>
    </div>

    <div class="filters">
      <select v-model="filterStatus" class="pa-input" @change="load">
        <option value="active">进行中</option>
        <option value="snoozed">稍后</option>
        <option value="done">已完成</option>
        <option value="cancelled">已取消</option>
        <option value="">全部</option>
      </select>
    </div>

    <div v-if="error" class="error-line">{{ error }}</div>

    <div v-if="!loading && reminders.length === 0" class="empty-list">暂无提醒</div>

    <div v-for="r in reminders" :key="r.id" class="rem-row">
      <div class="row-main">
        <div class="row-title">
          <PhBell :size="14" />
          <span class="title-text">{{ r.title }}</span>
          <span v-if="ruleLabel(r)" class="badge">{{ ruleLabel(r) }}</span>
        </div>
        <div class="row-meta">
          {{ statusLabel(r.status) }} · 到期 {{ fmt(r.due_at) }}
          <span v-if="r.next_fire_at && r.status === 'active'"> · 下次 {{ fmt(r.next_fire_at) }}</span>
          <span v-if="r.last_fired_at"> · 上次触发 {{ fmt(r.last_fired_at) }}</span>
        </div>
        <p v-if="r.body_md" class="row-body">{{ r.body_md }}</p>
      </div>
      <div v-if="r.status === 'active' || r.status === 'snoozed'" class="row-actions">
        <button class="icon-btn" title="稍后 10 分钟" :disabled="busy" @click="snooze(r, 10)">
          <PhClock :size="15" />
        </button>
        <button class="icon-btn" title="稍后到明天" :disabled="busy" @click="snooze(r, 1440)">
          <PhClock :size="15" />
        </button>
        <button class="icon-btn" title="完成（重复则生成下一次）" :disabled="busy" @click="done(r)">
          <PhCheck :size="15" />
        </button>
        <button class="icon-btn danger" title="删除" :disabled="busy" @click="remove(r)">
          <PhTrash :size="15" />
        </button>
      </div>
      <div v-else class="row-actions">
        <button class="icon-btn danger" title="删除" :disabled="busy" @click="remove(r)">
          <PhTrash :size="15" />
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.rem-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.pane-head h3 {
  margin: 0;
  font-size: var(--text-lg);
}
.pane-head p,
.hint {
  margin: 0;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.head-actions {
  display: flex;
  gap: var(--space-2);
  align-items: center;
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
.icon-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}
.icon-btn.danger:hover {
  border-color: var(--color-danger-fg);
  color: var(--color-danger-fg);
}
.create-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.form-row {
  display: flex;
  gap: var(--space-2);
}
.form-actions {
  display: flex;
  gap: var(--space-2);
}
.filters {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-2);
}
.error-line {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius);
  padding: var(--space-2);
  font-size: var(--text-sm);
}
.empty-list {
  text-align: center;
  color: var(--color-fg-faint);
  padding: 32px 0;
  font-size: var(--text-sm);
}
.rem-row {
  display: flex;
  gap: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
}
.rem-row:hover {
  border-color: var(--color-accent);
}
.row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.row-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: var(--font-medium);
}
.title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-meta {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.row-body {
  margin: 0;
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  white-space: pre-wrap;
}
.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-content: flex-start;
}
.badge {
  font-size: var(--text-xs);
  padding: 1px 6px;
  border-radius: var(--radius);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
}
</style>
