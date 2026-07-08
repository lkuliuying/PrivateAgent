<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  PhArchive,
  PhArrowClockwise,
  PhArrowFatRight,
  PhBell,
  PhCheck,
  PhClock,
  PhEyeSlash,
  PhPlus,
  PhTrash,
} from "@phosphor-icons/vue";
import {
  createInbox,
  deleteInbox,
  inboxToReminder,
  inboxToTask,
  listInbox,
  updateInbox,
} from "../api";
import type { InboxItem, InboxItemType, InboxPriority, InboxStatus } from "../types";

const items = ref<InboxItem[]>([]);
const loading = ref(false);
const busy = ref(false);
const error = ref("");

const filterStatus = ref<string>("open");
const filterType = ref<string>("");
const filterPriority = ref<string>("");

const showCreate = ref(false);
const form = ref({
  title: "",
  item_type: "todo" as InboxItemType,
  priority: "normal" as InboxPriority,
  body_md: "",
});

const TYPES: InboxItemType[] = [
  "todo",
  "reminder",
  "review",
  "approval",
  "failure",
  "memory",
  "note",
  "system",
];
const TYPE_LABEL: Record<string, string> = {
  todo: "待办",
  reminder: "提醒",
  review: "回顾",
  approval: "待审批",
  failure: "失败",
  memory: "记忆",
  note: "笔记",
  system: "系统",
};
const PRIORITIES: InboxPriority[] = ["low", "normal", "high", "urgent"];
const PRIORITY_LABEL: Record<string, string> = {
  low: "低",
  normal: "普通",
  high: "高",
  urgent: "紧急",
};

async function load() {
  loading.value = true;
  error.value = "";
  try {
    items.value = await listInbox({
      status: filterStatus.value || undefined,
      item_type: filterType.value || undefined,
      priority: filterPriority.value || undefined,
    });
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
  if (!form.value.title.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    await createInbox({
      title: form.value.title.trim(),
      item_type: form.value.item_type,
      priority: form.value.priority,
      body_md: form.value.body_md.trim() || undefined,
    });
    form.value = { title: "", item_type: "todo", priority: "normal", body_md: "" };
    showCreate.value = false;
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function setStatus(item: InboxItem, status: InboxStatus) {
  busy.value = true;
  error.value = "";
  try {
    const due_at =
      status === "snoozed"
        ? new Date(Date.now() + 86400000).toISOString()
        : undefined;
    await updateInbox(item.id, { status, due_at });
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function toTask(item: InboxItem) {
  busy.value = true;
  error.value = "";
  try {
    await inboxToTask(item.id);
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function toReminder(item: InboxItem) {
  busy.value = true;
  error.value = "";
  try {
    await inboxToReminder(item.id);
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function remove(item: InboxItem) {
  if (!window.confirm(`确定删除收件箱项「${item.title}」？`)) return;
  busy.value = true;
  error.value = "";
  try {
    await deleteInbox(item.id);
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
      open: "待处理",
      snoozed: "稍后",
      done: "已完成",
      ignored: "已忽略",
      archived: "已归档",
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

defineExpose({ reload });
onMounted(load);
</script>

<template>
  <section class="inbox-panel">
    <div class="pane-head">
      <div>
        <h3>收件箱</h3>
        <p class="hint">统一待处理事项：手动创建或从聊天/任务/活动/记忆保存。</p>
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
      <input v-model="form.title" class="pa-input" placeholder="标题…" />
      <div class="form-row">
        <select v-model="form.item_type" class="pa-input">
          <option v-for="t in TYPES" :key="t" :value="t">{{ TYPE_LABEL[t] }}</option>
        </select>
        <select v-model="form.priority" class="pa-input">
          <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABEL[p] }}</option>
        </select>
      </div>
      <textarea v-model="form.body_md" class="pa-input" rows="2" placeholder="详情（可选）…"></textarea>
      <div class="form-actions">
        <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="busy || !form.title.trim()" @click="save">
          <PhCheck :size="14" /> 保存
        </button>
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="showCreate = false">取消</button>
      </div>
    </div>

    <div class="filters">
      <select v-model="filterStatus" class="pa-input" @change="load">
        <option value="open">待处理</option>
        <option value="snoozed">稍后</option>
        <option value="done">已完成</option>
        <option value="ignored">已忽略</option>
        <option value="archived">已归档</option>
        <option value="">全部</option>
      </select>
      <select v-model="filterType" class="pa-input" @change="load">
        <option value="">全部类型</option>
        <option v-for="t in TYPES" :key="t" :value="t">{{ TYPE_LABEL[t] }}</option>
      </select>
      <select v-model="filterPriority" class="pa-input" @change="load">
        <option value="">全部优先级</option>
        <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABEL[p] }}</option>
      </select>
    </div>

    <div v-if="error" class="error-line">{{ error }}</div>

    <div v-if="!loading && items.length === 0" class="empty-list">暂无收件箱项</div>

    <div v-for="it in items" :key="it.id" class="inbox-row">
      <div class="row-main">
        <div class="row-title">
          <span class="status-dot" :class="it.status" />
          <span class="title-text">{{ it.title }}</span>
          <span v-if="it.priority === 'urgent'" class="badge urgent">紧急</span>
          <span v-else-if="it.priority === 'high'" class="badge high">高</span>
        </div>
        <div class="row-meta">
          {{ TYPE_LABEL[it.item_type] }} · {{ statusLabel(it.status) }}
          <span v-if="it.due_at"> · 截止 {{ fmt(it.due_at) }}</span>
          <span v-if="it.source_type"> · 来源 {{ it.source_type }}#{{ it.source_id }}</span>
          <span v-if="it.target_type"> · 已转 {{ it.target_type }}#{{ it.target_id }}</span>
        </div>
        <p v-if="it.body_md" class="row-body">{{ it.body_md }}</p>
      </div>
      <div class="row-actions">
        <button v-if="it.status !== 'done'" class="icon-btn" title="完成" :disabled="busy" @click="setStatus(it, 'done')">
          <PhCheck :size="15" />
        </button>
        <button v-if="it.status !== 'snoozed'" class="icon-btn" title="稍后（明天）" :disabled="busy" @click="setStatus(it, 'snoozed')">
          <PhClock :size="15" />
        </button>
        <button v-if="it.status !== 'ignored'" class="icon-btn" title="忽略" :disabled="busy" @click="setStatus(it, 'ignored')">
          <PhEyeSlash :size="15" />
        </button>
        <button v-if="it.status !== 'archived'" class="icon-btn" title="归档" :disabled="busy" @click="setStatus(it, 'archived')">
          <PhArchive :size="15" />
        </button>
        <button class="icon-btn" title="转任务草稿" :disabled="busy" @click="toTask(it)">
          <PhArrowFatRight :size="15" />
        </button>
        <button class="icon-btn" title="转提醒" :disabled="busy" @click="toReminder(it)">
          <PhBell :size="15" />
        </button>
        <button class="icon-btn danger" title="删除" :disabled="busy" @click="remove(it)">
          <PhTrash :size="15" />
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.inbox-panel {
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
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}
.form-actions {
  display: flex;
  gap: var(--space-2);
}
.filters {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
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
.inbox-row {
  display: flex;
  gap: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
}
.inbox-row:hover {
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
.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-warning-fg);
  flex-shrink: 0;
}
.status-dot.done,
.status-dot.archived {
  background: var(--color-success-fg);
}
.status-dot.ignored {
  background: var(--color-fg-faint);
}
.status-dot.snoozed {
  background: var(--color-warning-fg);
}
.badge {
  font-size: var(--text-xs);
  padding: 1px 6px;
  border-radius: var(--radius);
}
.badge.urgent {
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
}
.badge.high {
  background: var(--color-warning-soft, var(--color-surface-sunken));
  color: var(--color-warning-fg);
}
@media (max-width: 720px) {
  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
