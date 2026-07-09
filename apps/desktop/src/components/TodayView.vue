<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  PhArrowClockwise,
  PhArrowRight,
  PhBell,
  PhBooks,
  PhChatCircle,
  PhCheckCircle,
  PhDatabase,
  PhFileText,
  PhPlus,
  PhSparkle,
  PhSun,
  PhTarget,
  PhUploadSimple,
  PhLightning,
} from "@phosphor-icons/vue";
import { createInbox, createTodayBriefing, getToday } from "../api";
import type {
  InboxItemType,
  TodayFilters,
  TodayItem,
  TodayRecentItem,
  TodaySnapshot,
  View,
} from "../types";
import { useNotifications } from "../stores/notifications";
import BriefingPanel from "./BriefingPanel.vue";
import GoalsWorkspace from "./GoalsWorkspace.vue";
import InboxPanel from "./InboxPanel.vue";
import PrivacyAuditPanel from "./PrivacyAuditPanel.vue";
import ReminderPanel from "./ReminderPanel.vue";
import CapturePanel from "./CapturePanel.vue";

const emit = defineEmits<{ navigate: [view: View] }>();
const notify = useNotifications();

const snap = ref<TodaySnapshot | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const inboxPanel = ref<InstanceType<typeof InboxPanel> | null>(null);
const reminderPanel = ref<InstanceType<typeof ReminderPanel> | null>(null);
const briefingPanel = ref<InstanceType<typeof BriefingPanel> | null>(null);
const capturePanel = ref<InstanceType<typeof CapturePanel> | null>(null);

const filters = reactive<TodayFilters>({});

const TYPE_OPTIONS: { value: TodayFilters["type"]; label: string }[] = [
  { value: undefined, label: "全部类型" },
  { value: "learning", label: "学习" },
  { value: "task", label: "任务" },
  { value: "doc", label: "文档" },
  { value: "memory", label: "记忆" },
  { value: "reminder", label: "提醒" },
  { value: "goal", label: "目标" },
  { value: "inbox", label: "收件箱" },
  { value: "system", label: "系统" },
];
const PRIORITY_OPTIONS: { value: TodayFilters["priority"]; label: string }[] = [
  { value: undefined, label: "全部优先级" },
  { value: "urgent", label: "紧急" },
  { value: "high", label: "高" },
  { value: "normal", label: "普通" },
  { value: "low", label: "低" },
];
const TIME_OPTIONS: { value: TodayFilters["time"]; label: string }[] = [
  { value: undefined, label: "全部时间" },
  { value: "today", label: "今天" },
  { value: "overdue", label: "逾期" },
  { value: "this-week", label: "本周" },
  { value: "future", label: "未来" },
];
const STATUS_OPTIONS: { value: TodayFilters["status"]; label: string }[] = [
  { value: undefined, label: "全部状态" },
  { value: "open", label: "待处理" },
  { value: "snoozed", label: "已暂缓" },
  { value: "done", label: "已完成" },
  { value: "ignored", label: "已忽略" },
];

interface SectionDef {
  key: string;
  title: string;
  view: View;
  itemType: InboxItemType;
  pick: (s: TodaySnapshot) => TodayItem[];
}

const SECTIONS: SectionDef[] = [
  {
    key: "due_cards",
    title: "到期复习",
    view: "learning",
    itemType: "review",
    pick: (s) => s.due_cards,
  },
  {
    key: "attention_tasks",
    title: "待关注任务",
    view: "tasks",
    itemType: "approval",
    pick: (s) => s.attention_tasks,
  },
  {
    key: "failed_activities",
    title: "失败活动",
    view: "kb",
    itemType: "failure",
    pick: (s) => s.failed_activities,
  },
  {
    key: "draft_memories",
    title: "候选记忆",
    view: "memory",
    itemType: "memory",
    pick: (s) => s.draft_memories,
  },
  {
    key: "due_reminders",
    title: "到期提醒",
    view: "today",
    itemType: "reminder",
    pick: (s) => s.due_reminders,
  },
];

const visibleSections = computed(() => {
  if (!snap.value) return [];
  return SECTIONS.map((s) => ({ ...s, items: s.pick(snap.value!) })).filter(
    (s) => s.items.length > 0
  );
});

const allEmpty = computed(() => {
  if (!snap.value) return false;
  const sm = snap.value.summary;
  return (
    sm.due_cards === 0 &&
    sm.attention_tasks === 0 &&
    sm.failed_activities === 0 &&
    sm.draft_memories === 0 &&
    sm.due_reminders === 0 &&
    sm.open_inbox === 0
  );
});

const chips = computed(() => {
  if (!snap.value) return [];
  const sm = snap.value.summary;
  return [
    { label: "到期复习", value: sm.due_cards, view: "learning" as View },
    { label: "待关注任务", value: sm.attention_tasks, view: "tasks" as View },
    { label: "失败活动", value: sm.failed_activities, view: "kb" as View },
    { label: "候选记忆", value: sm.draft_memories, view: "memory" as View },
    { label: "到期提醒", value: sm.due_reminders, view: "today" as View },
    { label: "收件箱", value: sm.open_inbox, view: "today" as View },
  ];
});

const todayLabel = computed(() => {
  const d = new Date();
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
});

const weekdayLabel = computed(() =>
  new Intl.DateTimeFormat("zh-CN", { weekday: "long" }).format(new Date())
);

const hasFilters = computed(
  () => !!(filters.type || filters.priority || filters.time || filters.status)
);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    snap.value = await getToday(hasFilters.value ? { ...filters } : undefined);
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

function onFilterChange() {
  void load();
}

function clearFilters() {
  filters.type = undefined;
  filters.priority = undefined;
  filters.time = undefined;
  filters.status = undefined;
  void load();
}

async function generateBriefing() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await createTodayBriefing();
    await briefingPanel.value?.load();
    notify.success("今日简报已生成", "已添加到下方简报列表");
    await load();
  } catch (e) {
    notify.error("生成今日简报失败", String(e));
  } finally {
    busy.value = false;
  }
}

function newReminder() {
  // 滚动到下方提醒面板的创建表单。
  reminderPanel.value?.$el?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function quickCapture() {
  // 滚动到下方快速捕获面板。
  capturePanel.value?.$el?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function importDocument() {
  emit("navigate", "kb");
}

function cardTitle(it: TodayItem): string {
  return it.title || it.front || `#${it.id}`;
}

function cardMeta(it: TodayItem): string {
  const parts: string[] = [];
  if (it.status) parts.push(it.status);
  if (it.kind) parts.push(it.kind);
  if (it.item_type) parts.push(it.item_type);
  if (it.due_at) parts.push(`到期 ${fmt(it.due_at)}`);
  if (it.next_fire_at) parts.push(`下次 ${fmt(it.next_fire_at)}`);
  if (it.recurring) parts.push("重复");
  return parts.join(" · ");
}

function fmt(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(
    2,
    "0"
  )}:${String(d.getMinutes()).padStart(2, "0")}`;
}

async function saveToInbox(it: TodayItem, itemType: InboxItemType) {
  busy.value = true;
  error.value = "";
  try {
    await createInbox({
      title: cardTitle(it).slice(0, 255),
      item_type: itemType,
      source_type: it.source_type,
      source_id: it.source_id,
    });
    await inboxPanel.value?.reload();
    notify.success("已存为收件箱", cardTitle(it));
    await load();
  } catch (e) {
    notify.error("保存收件箱失败", String(e));
  } finally {
    busy.value = false;
  }
}

/** 最近来源条目点击跳转。 */
function onRecentClick(it: TodayRecentItem) {
  switch (it.source_type) {
    case "chat_session":
      emit("navigate", "chat");
      break;
    case "document":
      emit("navigate", "kb");
      break;
    case "briefing":
      briefingPanel.value?.$el?.scrollIntoView({ behavior: "smooth", block: "start" });
      break;
    case "goal_checkin":
      emit("navigate", "today");
      break;
    default:
      break;
  }
}

onMounted(load);
</script>

<template>
  <section class="today-shell">
    <div class="today-grid">
      <main class="today-main">
        <div class="today-head">
          <div>
            <p class="eyebrow">{{ todayLabel }} · {{ weekdayLabel }}</p>
            <h1>今日</h1>
          </div>
          <div class="head-actions">
            <button class="soft-action" :disabled="busy" @click="generateBriefing">
              <PhSparkle :size="16" />
              <span>今日简报</span>
            </button>
            <button class="icon-btn" :disabled="loading" title="刷新" @click="load">
              <PhArrowClockwise :size="16" />
            </button>
          </div>
        </div>

        <div v-if="error" class="error-line">{{ error }}</div>

        <!-- 第七阶段 M1：筛选栏（type/priority/time/status） -->
        <div v-if="snap" class="filter-bar">
          <select
            v-model="filters.type"
            class="filter-select"
            aria-label="类型筛选"
            @change="onFilterChange"
          >
            <option v-for="o in TYPE_OPTIONS" :key="String(o.value)" :value="o.value">
              {{ o.label }}
            </option>
          </select>
          <select
            v-model="filters.priority"
            class="filter-select"
            aria-label="优先级筛选"
            @change="onFilterChange"
          >
            <option v-for="o in PRIORITY_OPTIONS" :key="String(o.value)" :value="o.value">
              {{ o.label }}
            </option>
          </select>
          <select
            v-model="filters.time"
            class="filter-select"
            aria-label="时间筛选"
            @change="onFilterChange"
          >
            <option v-for="o in TIME_OPTIONS" :key="String(o.value)" :value="o.value">
              {{ o.label }}
            </option>
          </select>
          <select
            v-model="filters.status"
            class="filter-select"
            aria-label="状态筛选"
            @change="onFilterChange"
          >
            <option v-for="o in STATUS_OPTIONS" :key="String(o.value)" :value="o.value">
              {{ o.label }}
            </option>
          </select>
          <button v-if="hasFilters" class="filter-clear" @click="clearFilters">
            清除筛选
          </button>
        </div>

        <div v-if="snap" class="chips">
          <button
            v-for="c in chips"
            :key="c.label"
            class="chip"
            :class="{ zero: c.value === 0 }"
            @click="emit('navigate', c.view)"
          >
            <span class="chip-value">{{ c.value }}</span>
            <span class="chip-label">{{ c.label }}</span>
          </button>
        </div>

        <!-- 空状态：真实可执行动作 -->
        <div v-if="snap && allEmpty && !hasFilters" class="empty-banner">
          <PhSun :size="34" weight="duotone" />
          <div class="empty-body">
            <p>今天没有必须处理的事项。</p>
            <p class="hint">选择一个动作开始：</p>
            <div class="empty-actions">
              <button class="empty-action" @click="newReminder">
                <PhBell :size="15" /> 新建提醒
              </button>
              <button class="empty-action" @click="quickCapture">
                <PhLightning :size="15" /> 快速捕获
              </button>
              <button class="empty-action" @click="importDocument">
                <PhUploadSimple :size="15" /> 导入文档
              </button>
              <button class="empty-action" :disabled="busy" @click="generateBriefing">
                <PhSparkle :size="15" /> 生成简报
              </button>
            </div>
          </div>
        </div>

        <section class="focus-section">
          <div class="section-head">
            <h3>优先事项</h3>
            <button class="text-action" @click="emit('navigate', 'tasks')">
              <span>添加任务</span>
              <PhPlus :size="14" />
            </button>
          </div>

          <div v-if="visibleSections.length" class="priority-list">
            <div v-for="sec in visibleSections.slice(0, 3)" :key="sec.key">
              <div
                v-for="it in sec.items.slice(0, 3)"
                :key="`${sec.key}-${it.id}`"
                class="priority-row"
              >
                <span class="fake-check" />
                <div class="priority-copy">
                  <strong>{{ cardTitle(it) }}</strong>
                  <span>{{ sec.title }} · {{ cardMeta(it) || "需要处理" }}</span>
                  <em v-if="it.error_message">{{ it.error_message }}</em>
                </div>
                <button
                  class="row-action"
                  :disabled="busy"
                  title="存为收件箱"
                  @click="saveToInbox(it, sec.itemType)"
                >
                  收件箱
                </button>
              </div>
            </div>
          </div>

          <div v-else class="quiet-empty">
            <PhCheckCircle :size="18" weight="fill" />
            <span>当前没有必须马上处理的事项。</span>
          </div>
        </section>

        <!-- 最近会话（真实数据，替代固定日程） -->
        <section class="schedule-section">
          <div class="section-head">
            <h3>最近会话</h3>
            <button class="text-action" @click="emit('navigate', 'chat')">
              <span>查看全部</span>
              <PhArrowRight :size="14" />
            </button>
          </div>
          <div class="schedule-list">
            <button
              v-for="s in snap?.recent_sessions ?? []"
              :key="s.id"
              class="schedule-row"
              @click="onRecentClick(s)"
            >
              <PhChatCircle :size="15" class="schedule-icon" />
              <strong>{{ s.title || `会话 #${s.id}` }}</strong>
              <span>{{ fmt(s.updated_at) }}</span>
            </button>
            <div v-if="!snap || snap.recent_sessions.length === 0" class="schedule-empty">
              暂无会话，点击「查看全部」开始对话。
            </div>
          </div>
        </section>

        <section class="reminder-strip">
          <div class="section-head compact">
            <h3>提醒</h3>
            <button class="text-action" @click="newReminder">
              全部提醒 {{ snap?.summary.due_reminders ?? 0 }}
            </button>
          </div>
          <div class="reminder-chips">
            <button
              v-for="r in snap?.due_reminders.slice(0, 3) ?? []"
              :key="r.id"
              class="reminder-chip"
            >
              <PhBell :size="14" />
              <span>{{ cardTitle(r) }}</span>
            </button>
            <button v-if="!snap || snap.due_reminders.length === 0" class="reminder-chip muted">
              <PhBell :size="14" />
              <span>没有到期提醒</span>
            </button>
          </div>
        </section>

        <section class="today-composer">
          <textarea
            readonly
            rows="3"
            placeholder="有什么问题或需要我帮忙的吗？"
            @focus="emit('navigate', 'chat')"
          />
          <div class="composer-actions">
            <button @click="emit('navigate', 'kb')">搜索知识库</button>
            <button @click="emit('navigate', 'tasks')">生成计划</button>
            <button @click="emit('navigate', 'projects')">代码助手</button>
            <button class="send" @click="emit('navigate', 'chat')" title="进入对话">
              <PhChatCircle :size="17" />
            </button>
          </div>
          <p>本地优先处理，所有数据只保存在你的设备上。</p>
        </section>
      </main>

      <aside class="today-context">
        <div class="context-tabs">
          <button class="active">上下文</button>
          <button @click="emit('navigate', 'tasks')">工具</button>
        </div>

        <!-- 最近目标进展（真实 check-in，替代固定记忆洞察） -->
        <section class="context-card">
          <div class="context-head">
            <h3>最近目标进展</h3>
            <button @click="emit('navigate', 'today')">查看全部</button>
          </div>
          <div class="insight-list">
            <button
              v-for="c in snap?.recent_checkins ?? []"
              :key="c.id"
              class="insight-row"
              @click="onRecentClick(c)"
            >
              <PhTarget :size="15" class="insight-icon" />
              <div class="insight-copy">
                <strong>{{ c.goal_title }}</strong>
                <span>{{ fmt(c.checkin_date) }}{{ c.confidence != null ? ` · 信心 ${Math.round(c.confidence * 100)}%` : "" }}</span>
                <em v-if="c.progress_note_md">{{ c.progress_note_md }}</em>
              </div>
            </button>
            <div v-if="!snap || snap.recent_checkins.length === 0" class="context-empty">
              暂无目标回顾。
            </div>
          </div>
        </section>

        <!-- 最近文档（真实数据，替代固定来源） -->
        <section class="context-card">
          <div class="context-head">
            <h3>最近文档</h3>
            <button @click="emit('navigate', 'kb')">查看全部</button>
          </div>
          <div class="source-list">
            <button
              v-for="d in snap?.recent_docs ?? []"
              :key="d.id"
              class="source-row"
              @click="onRecentClick(d)"
            >
              <PhDatabase :size="14" />
              <span class="source-name">{{ d.name }}</span>
              <span class="source-meta">{{ d.doc_type || "文档" }}</span>
            </button>
            <div v-if="!snap || snap.recent_docs.length === 0" class="context-empty">
              暂无文档，点击「查看全部」导入。
            </div>
          </div>
        </section>

        <!-- 最近简报（真实数据） -->
        <section class="context-card">
          <div class="context-head">
            <h3>最近简报</h3>
            <button @click="generateBriefing" :disabled="busy">生成</button>
          </div>
          <div class="source-list">
            <button
              v-for="b in snap?.recent_briefings ?? []"
              :key="b.id"
              class="source-row"
              @click="onRecentClick(b)"
            >
              <PhFileText :size="14" />
              <span class="source-name">{{ b.title }}</span>
              <span class="source-meta">{{ b.kind }}</span>
            </button>
            <div v-if="!snap || snap.recent_briefings.length === 0" class="context-empty">
              暂无简报，点击「生成」创建今日简报。
            </div>
          </div>
        </section>

        <!-- 系统健康（真实维护摘要） -->
        <section v-if="snap" class="context-card">
          <div class="context-head">
            <h3>系统健康</h3>
            <button @click="emit('navigate', 'diagnostics')">查看详情</button>
          </div>
          <div class="health-row">
            <PhDatabase :size="16" />
            <span>最近备份</span>
            <strong>{{ snap.maintenance.last_backup_at ? fmt(snap.maintenance.last_backup_at) : "暂无" }}</strong>
          </div>
          <div class="health-row">
            <PhBooks :size="16" />
            <span>备份包</span>
            <strong>{{ snap.maintenance.backup_count }} 个</strong>
          </div>
          <div class="health-row">
            <PhCheckCircle :size="16" />
            <span>失败活动</span>
            <strong :class="{ warn: snap.maintenance.failed_activities > 0 }">{{ snap.maintenance.failed_activities }}</strong>
          </div>
          <div class="health-row">
            <PhTarget :size="16" />
            <span>孤儿证据</span>
            <strong :class="{ warn: snap.maintenance.orphan_evidence > 0 }">{{ snap.maintenance.orphan_evidence }}</strong>
          </div>
          <p class="health-ok" :class="{ warn: snap.maintenance.failed_activities > 0 || snap.maintenance.orphan_evidence > 0 }">
            {{ snap.maintenance.failed_activities > 0 || snap.maintenance.orphan_evidence > 0 ? "存在需要关注的项目" : "服务运行正常" }}
          </p>
        </section>
      </aside>
    </div>

    <div class="workbench-modules">
      <ReminderPanel ref="reminderPanel" />
      <InboxPanel ref="inboxPanel" />
      <GoalsWorkspace />
      <BriefingPanel ref="briefingPanel" />
      <CapturePanel ref="capturePanel" />
      <PrivacyAuditPanel />
    </div>
  </section>
</template>

<style scoped>
.today-shell {
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--space-8) var(--space-8) var(--space-10);
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}
.today-grid {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--space-8);
}
.today-main,
.today-context {
  min-width: 0;
}
.today-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}
.today-head h1 {
  margin: 0;
  color: var(--color-fg);
  font-size: 34px;
  font-weight: 650;
  line-height: 1.1;
}
.eyebrow {
  margin: 0 0 var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--text-base);
}
.hint {
  margin: 0;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.soft-action,
.icon-btn {
  height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-panel);
  color: var(--color-fg);
  cursor: pointer;
}
.soft-action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
}
.soft-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.icon-btn {
  width: 36px;
  display: grid;
  place-items: center;
}
.soft-action:hover,
.icon-btn:hover {
  color: var(--color-accent);
  border-color: var(--color-accent);
}
.error-line {
  margin-top: var(--space-4);
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
  border: 1px solid color-mix(in srgb, var(--color-danger) 20%, transparent);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
}
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
.filter-select {
  height: 32px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-fg);
  font-size: var(--text-sm);
  padding: 0 var(--space-2);
  cursor: pointer;
}
.filter-select:focus {
  outline: none;
  border-color: var(--color-accent);
}
.filter-clear {
  height: 32px;
  border: none;
  background: transparent;
  color: var(--color-danger-fg);
  font-size: var(--text-sm);
  cursor: pointer;
  padding: 0 var(--space-2);
}
.chips {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-6);
}
.chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--space-3) var(--space-2);
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--color-fg);
  cursor: pointer;
}
.chip:hover {
  background: var(--color-accent-soft);
}
.chip.zero {
  opacity: 0.52;
}
.chip-value {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  font-variant-numeric: tabular-nums;
}
.chip-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.empty-banner {
  margin-top: var(--space-6);
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-4);
  color: var(--color-fg-muted);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.46);
}
.empty-banner p {
  margin: 0;
}
.empty-body {
  flex: 1;
}
.empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
.empty-action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-fg);
  font-size: var(--text-sm);
  cursor: pointer;
  padding: 0 var(--space-3);
}
.empty-action:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}
.empty-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.focus-section,
.schedule-section,
.reminder-strip {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-top: var(--space-8);
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.section-head h3 {
  margin: 0;
  font-size: var(--text-lg);
}
.text-action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  border: none;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  cursor: pointer;
}
.text-action:hover {
  color: var(--color-accent);
}
.priority-list,
.schedule-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.62);
  overflow: hidden;
}
.priority-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}
.priority-row:last-child {
  border-bottom: none;
}
.fake-check {
  width: 16px;
  height: 16px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}
.priority-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.priority-copy strong {
  color: var(--color-fg);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.priority-copy span,
.priority-copy em {
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
  font-style: normal;
}
.priority-copy em {
  color: var(--color-danger-fg);
}
.row-action {
  height: 26px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-panel);
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  cursor: pointer;
  padding: 0 var(--space-2);
}
.quiet-empty {
  min-height: 72px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-success-fg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.62);
  padding: var(--space-4);
}
.schedule-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 50px;
  padding: 0 var(--space-4);
  border: none;
  border-bottom: 1px solid var(--color-border);
  background: transparent;
  cursor: pointer;
  text-align: left;
  width: 100%;
}
.schedule-row:last-child {
  border-bottom: none;
}
.schedule-icon {
  color: var(--color-fg-subtle);
  flex-shrink: 0;
}
.schedule-row strong {
  flex: 1;
  min-width: 0;
  font-weight: var(--font-normal);
  color: var(--color-fg);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.schedule-row > span {
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
  flex-shrink: 0;
}
.schedule-empty {
  padding: var(--space-4);
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.reminder-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.reminder-chip {
  height: 36px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.62);
  color: var(--color-fg-muted);
  padding: 0 var(--space-3);
  font-size: var(--text-sm);
}
.reminder-chip.muted {
  color: var(--color-fg-faint);
}
.today-composer {
  margin-top: var(--space-8);
  border: 2px solid var(--color-accent);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: 0 8px 28px rgba(7, 135, 163, 0.08);
  overflow: hidden;
}
.today-composer textarea {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  padding: var(--space-5);
  font-family: inherit;
  color: var(--color-fg);
  background: transparent;
  cursor: text;
}
.composer-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
}
.composer-actions button {
  height: 32px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
  padding: 0 var(--space-3);
}
.composer-actions .send {
  margin-left: auto;
  width: 40px;
  padding: 0;
  display: grid;
  place-items: center;
  background: var(--color-accent);
  color: #fff;
  border-color: var(--color-accent);
}
.today-composer p {
  margin: 0 0 var(--space-3);
  text-align: center;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.today-context {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.context-tabs {
  display: flex;
  gap: var(--space-5);
  border-bottom: 1px solid var(--color-border);
}
.context-tabs button {
  height: 38px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.context-tabs button.active {
  color: var(--color-fg);
  border-bottom-color: var(--color-accent);
}
.context-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.66);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.context-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.context-head h3 {
  margin: 0;
  font-size: var(--text-md);
}
.context-head button {
  border: none;
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
  font-size: var(--text-sm);
}
.insight-list,
.source-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.insight-row,
.source-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  padding: var(--space-1) 0;
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.insight-row {
  flex-direction: row;
  align-items: flex-start;
}
.insight-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.insight-copy strong {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.insight-copy span {
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.insight-copy em {
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  font-style: normal;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.insight-icon,
.source-row :deep(svg) {
  color: var(--color-fg-subtle);
  flex-shrink: 0;
}
.source-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-meta {
  margin-left: auto;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
  flex-shrink: 0;
}
.context-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  padding: var(--space-1) 0;
}
.health-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
.health-row :deep(svg) {
  color: var(--color-fg-subtle);
}
.health-row strong {
  margin-left: auto;
}
.health-row strong.warn {
  color: var(--color-danger-fg);
}
.health-ok {
  margin: 0;
  color: var(--color-success-fg);
  font-size: var(--text-sm);
}
.health-ok.warn {
  color: var(--color-warning-fg);
}
.workbench-modules {
  max-width: 1180px;
  width: 100%;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-5);
  align-items: start;
}

@media (max-width: 1180px) {
  .today-grid {
    grid-template-columns: 1fr;
  }
  .today-context {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .context-tabs {
    grid-column: 1 / -1;
  }
}

@media (max-width: 1440px) {
  .today-grid {
    gap: var(--space-6);
  }
  .context-card {
    padding: var(--space-3);
  }
  .chips {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .today-shell {
    padding: var(--space-5);
  }
  .chips,
  .workbench-modules,
  .today-context {
    grid-template-columns: 1fr;
  }
  .composer-actions {
    flex-wrap: wrap;
  }
}
</style>
