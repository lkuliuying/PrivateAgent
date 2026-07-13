<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import {
  PhArrowClockwise,
  PhArrowRight,
  PhBell,
  PhChatCircle,
  PhCheckCircle,
  PhDatabase,
  PhFileText,
  PhPlus,
  PhSparkle,
  PhTarget,
  PhUploadSimple,
  PhLightning,
  PhMagnifyingGlass,
  PhListBullets,
  PhCode,
  PhPaperPlaneTilt,
  PhShieldCheck,
  PhSlidersHorizontal,
  PhCaretDown,
  PhWrench,
  PhWarningCircle,
  PhDotsThree,
  PhUserCircle,
  PhCloudCheck,
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

type ComposerMode = "chat" | "knowledge" | "plan" | "code";

const emit = defineEmits<{
  navigate: [view: View];
  submit: [text: string, mode: ComposerMode];
  "open-command": [];
}>();
const notify = useNotifications();

const snap = ref<TodaySnapshot | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const inboxPanel = ref<InstanceType<typeof InboxPanel> | null>(null);
const reminderPanel = ref<InstanceType<typeof ReminderPanel> | null>(null);
const briefingPanel = ref<InstanceType<typeof BriefingPanel> | null>(null);
const capturePanel = ref<InstanceType<typeof CapturePanel> | null>(null);
const composerInput = ref<HTMLTextAreaElement | null>(null);
const composerText = ref("");
const composerMode = ref<ComposerMode>("chat");
const composerModeOpen = ref(false);
const contextTab = ref<"memory" | "sources" | "status">("memory");

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
  return `${d.getMonth() + 1}月${d.getDate()}日`;
});

const overviewItems = computed(() => {
  const summary = snap.value?.summary;
  return [
    { label: "待处理", value: (summary?.attention_tasks ?? 0) + (summary?.open_inbox ?? 0), hint: "任务与收件箱", view: "tasks" as View },
    { label: "今日计划", value: (summary?.due_cards ?? 0) + (summary?.due_reminders ?? 0), hint: "复习与提醒", view: "today" as View },
    { label: "运行关注", value: summary?.failed_activities ?? 0, hint: "失败活动", view: "diagnostics" as View, tone: "danger" },
    { label: "新增上下文", value: (summary?.draft_memories ?? 0) + (snap.value?.recent_docs.length ?? 0), hint: "记忆与资料", view: "memory" as View },
  ];
});

const recentActivities = computed(() => {
  if (!snap.value) return [];
  return [
    ...snap.value.failed_activities.map((item) => ({ id: `error-${item.id}`, type: "error", title: cardTitle(item), summary: item.error_message || item.summary || "运行活动需要处理", time: item.due_at, status: "需要关注", view: "diagnostics" as View })),
    ...snap.value.recent_sessions.map((item) => ({ id: `chat-${item.id}`, type: "chat", title: item.title || `会话 #${item.id}`, summary: "本地 Agent 对话", time: item.updated_at, status: "已同步", view: "chat" as View })),
    ...snap.value.recent_docs.map((item) => ({ id: `doc-${item.id}`, type: "document", title: item.name || item.title || `文档 #${item.id}`, summary: item.doc_type || "本地资料", time: item.created_at || item.updated_at, status: item.status || "可用", view: "kb" as View })),
    ...snap.value.recent_briefings.map((item) => ({ id: `brief-${item.id}`, type: "tool", title: item.title || "Agent 简报", summary: "已生成本地简报", time: item.created_at, status: "已完成", view: "today" as View })),
    ...snap.value.recent_checkins.map((item) => ({ id: `checkin-${item.id}`, type: "complete", title: item.goal_title || item.title || "目标回顾", summary: item.progress_note_md || "已记录进展", time: item.checkin_date, status: "已完成", view: "today" as View })),
  ]
    .sort((a, b) => new Date(b.time || 0).getTime() - new Date(a.time || 0).getTime())
    .slice(0, 6);
});

const topPriorityItems = computed(() =>
  visibleSections.value
    .flatMap((section) =>
      section.items.map((item) => ({
        item,
        sectionKey: section.key,
        sectionTitle: section.title,
        itemType: section.itemType,
      }))
    )
    .slice(0, 2)
);

const weekdayLabel = computed(() =>
  new Intl.DateTimeFormat("zh-CN", { weekday: "short" })
    .format(new Date())
    .replace("星期", "周")
);

const composerPlaceholder = computed(() => {
  switch (composerMode.value) {
    case "knowledge":
      return "输入要从本地知识库中查找的问题…";
    case "plan":
      return "描述目标、期限或约束，我来生成计划…";
    case "code":
      return "描述代码问题、仓库或期望改动…";
    default:
      return "输入问题、想法或指令…";
  }
});

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

function selectComposerMode(mode: ComposerMode) {
  composerMode.value = mode;
  void nextTick(() => composerInput.value?.focus());
}

function submitComposer() {
  const value = composerText.value.trim();
  if (!value) {
    composerInput.value?.focus();
    return;
  }
  emit("submit", value, composerMode.value);
  composerText.value = "";
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitComposer();
  }
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
  <section class="today-shell" :aria-busy="loading">
    <div class="today-grid">
      <main class="today-main">
        <header class="today-head" data-motion-hero>
          <div class="title-block">
            <h1>今日工作台</h1>
            <p class="eyebrow">{{ todayLabel }} · {{ weekdayLabel }} · 聚焦当前最重要的工作</p>
          </div>
          <div class="head-actions">
            <button class="command-entry" @click="emit('open-command')">
              <PhMagnifyingGlass :size="16" />
              <span>搜索或输入命令</span><kbd>Ctrl K</kbd>
            </button>
            <button class="soft-action primary-action" :disabled="busy" @click="generateBriefing">
              <PhSparkle :size="16" weight="fill" />
              <span>{{ busy ? "生成中…" : "今日简报" }}</span>
            </button>
            <button class="icon-btn" aria-label="通知" title="通知"><PhBell :size="17" /></button>
            <button class="runtime-pill" title="本地运行状态" @click="emit('navigate', 'diagnostics')">
              <span class="runtime-dot" />本地运行
            </button>
            <button class="user-entry" aria-label="用户设置" title="用户设置" @click="emit('navigate', 'settings')"><PhUserCircle :size="22" /></button>
          </div>
        </header>

        <div v-if="error" class="error-line" role="alert">{{ error }}</div>

        <section v-if="snap" class="today-overview" aria-label="今日概览">
          <button v-for="item in overviewItems" :key="item.label" :class="['overview-item', item.tone]" data-agent-card @click="emit('navigate', item.view)">
            <span class="overview-label">{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.hint }}</small>
          </button>
        </section>

        <section class="focus-section priority-card">
          <div class="section-head">
            <h2>优先事项</h2>
            <button class="text-action" @click="emit('navigate', 'tasks')">
              <span>添加任务</span>
              <PhPlus :size="14" />
            </button>
          </div>

          <div v-if="topPriorityItems.length" class="priority-list">
              <div
                v-for="entry in topPriorityItems"
                :key="`${entry.sectionKey}-${entry.item.id}`"
                class="priority-row"
              >
                <span class="fake-check" aria-hidden="true" />
                <div class="priority-copy">
                  <strong>{{ cardTitle(entry.item) }}</strong>
                  <span>{{ entry.sectionTitle }} · {{ cardMeta(entry.item) || "需要处理" }}</span>
                  <em v-if="entry.item.error_message">{{ entry.item.error_message }}</em>
                </div>
                <button
                  class="row-action"
                  :disabled="busy"
                  title="保存到收件箱"
                  @click="saveToInbox(entry.item, entry.itemType)"
                >
                  收件箱
                </button>
              </div>
          </div>

          <div v-else class="quiet-empty">
            <PhCheckCircle :size="20" weight="fill" />
            <div>
              <strong>当前没有必须马上处理的事项。</strong>
              <span>你可以从提醒、捕获或简报开始今天。</span>
            </div>
            <div class="quiet-actions">
              <button title="新建提醒" @click="newReminder"><PhBell :size="15" />提醒</button>
              <button title="快速捕获" @click="quickCapture"><PhLightning :size="15" />捕获</button>
              <button title="导入文档" @click="importDocument"><PhUploadSimple :size="15" />文档</button>
            </div>
          </div>
        </section>

        <details v-if="snap" class="overview-disclosure">
          <summary>
            <span><PhSlidersHorizontal :size="16" /> 筛选工作项</span>
            <em>{{ chips.reduce((sum, chip) => sum + chip.value, 0) }} 项</em>
          </summary>
          <div class="overview-body">
            <div class="filter-bar">
              <select v-model="filters.type" class="filter-select" aria-label="类型筛选" @change="onFilterChange">
                <option v-for="o in TYPE_OPTIONS" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
              </select>
              <select v-model="filters.priority" class="filter-select" aria-label="优先级筛选" @change="onFilterChange">
                <option v-for="o in PRIORITY_OPTIONS" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
              </select>
              <select v-model="filters.time" class="filter-select" aria-label="时间筛选" @change="onFilterChange">
                <option v-for="o in TIME_OPTIONS" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
              </select>
              <select v-model="filters.status" class="filter-select" aria-label="状态筛选" @change="onFilterChange">
                <option v-for="o in STATUS_OPTIONS" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
              </select>
              <button v-if="hasFilters" class="filter-clear" @click="clearFilters">清除筛选</button>
            </div>
            <div class="chips">
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
          </div>
        </details>

        <section class="schedule-section activity-section">
          <div class="section-head">
            <div><h2>最近活动</h2><p>来自对话、工具、资料和运行记录</p></div>
            <button class="text-action" @click="emit('navigate', 'chat')">
              <span>查看全部</span>
              <PhArrowRight :size="14" />
            </button>
          </div>
          <div class="activity-list">
            <button
              v-for="activity in recentActivities"
              :key="activity.id"
              class="activity-row"
              @click="emit('navigate', activity.view)"
            >
              <span :class="['activity-icon', `is-${activity.type}`]">
                <PhWarningCircle v-if="activity.type === 'error'" :size="17" />
                <PhChatCircle v-else-if="activity.type === 'chat'" :size="17" />
                <PhFileText v-else-if="activity.type === 'document'" :size="17" />
                <PhWrench v-else-if="activity.type === 'tool'" :size="17" />
                <PhCheckCircle v-else :size="17" />
              </span>
              <span class="activity-copy"><strong>{{ activity.title }}</strong><small>{{ activity.summary }}</small></span>
              <time>{{ fmt(activity.time) }}</time>
              <span :class="['activity-status', { warn: activity.type === 'error' }]">{{ activity.status }}</span>
              <PhDotsThree :size="18" class="activity-more" />
            </button>
            <div v-if="recentActivities.length === 0" class="schedule-empty">
              暂无最近活动。开始一次对话或导入资料后会显示在这里。
              <button @click="emit('navigate', 'chat')">开始对话</button>
            </div>
          </div>
        </section>

        <section class="reminder-strip">
          <div class="section-head compact">
            <h2>提醒</h2>
            <button class="text-action" @click="newReminder">查看全部（{{ snap?.summary.due_reminders ?? 0 }}）</button>
          </div>
          <div class="reminder-chips">
            <button
              v-for="r in snap?.due_reminders.slice(0, 3) ?? []"
              :key="r.id"
              class="reminder-chip"
              @click="newReminder"
            >
              <PhBell :size="14" />
              <span>{{ cardTitle(r) }}</span>
            </button>
            <button v-if="!snap || snap.due_reminders.length === 0" class="reminder-chip muted" @click="newReminder">
              <PhBell :size="14" />
              <span>暂无到期提醒</span>
            </button>
          </div>
        </section>

        <section class="today-composer" aria-label="快速开始">
          <label for="today-composer-input">让 Agent 帮你推进下一步</label>
          <textarea
            id="today-composer-input"
            ref="composerInput"
            v-model="composerText"
            rows="2"
            :placeholder="composerPlaceholder"
            @keydown="onComposerKeydown"
          />
          <div class="composer-actions">
            <button class="attachment-button" title="添加附件" aria-label="添加附件"><PhPlus :size="17" /></button>
            <div class="mode-menu-wrap">
              <button class="mode-trigger" :aria-expanded="composerModeOpen" @click="composerModeOpen = !composerModeOpen">
                <PhSparkle v-if="composerMode === 'chat'" :size="16" />
                <PhMagnifyingGlass v-else-if="composerMode === 'knowledge'" :size="16" />
                <PhListBullets v-else-if="composerMode === 'plan'" :size="16" />
                <PhCode v-else :size="16" />
                {{ { chat: '智能对话', knowledge: '知识检索', plan: '计划模式', code: '代码助手' }[composerMode] }}
                <PhCaretDown :size="13" />
              </button>
              <div v-if="composerModeOpen" class="mode-menu" role="menu">
                <button v-for="mode in ([['chat','智能对话'],['knowledge','搜索知识库'],['plan','生成计划'],['code','代码助手']] as const)" :key="mode[0]" role="menuitem" @click="selectComposerMode(mode[0]); composerModeOpen = false">{{ mode[1] }}</button>
              </div>
            </div>
            <span class="composer-runtime"><PhCloudCheck :size="15" />本地</span>
            <button class="send" :disabled="!composerText.trim()" aria-label="发送" title="发送（Enter）" @click="submitComposer">
              <PhPaperPlaneTilt :size="18" weight="fill" />
            </button>
          </div>
          <div class="composer-meta">
            <span><PhShieldCheck :size="14" />本地优先处理</span>
            <span>输入 / 可调用更多能力</span><kbd>Enter</kbd><span>发送</span>
          </div>
        </section>
      </main>

      <aside class="today-context" aria-label="上下文中心">
        <section class="context-card context-center" data-agent-card>
          <div class="context-head"><div><span class="context-kicker">CONTEXT</span><h2>上下文中心</h2></div><button class="icon-btn compact" :disabled="loading" title="刷新" @click="load"><PhArrowClockwise :size="15" /></button></div>
          <div class="context-tabs" role="tablist" aria-label="上下文类型">
            <button :class="{ active: contextTab === 'memory' }" role="tab" @click="contextTab = 'memory'">记忆</button>
            <button :class="{ active: contextTab === 'sources' }" role="tab" @click="contextTab = 'sources'">资料</button>
            <button :class="{ active: contextTab === 'status' }" role="tab" @click="contextTab = 'status'">状态</button>
          </div>
          <div v-if="contextTab === 'memory'" class="context-pane">
          <div class="insight-list">
            <button
              v-for="c in snap?.recent_checkins.slice(0, 3) ?? []"
              :key="`checkin-${c.id}`"
              class="insight-row"
              @click="onRecentClick(c)"
            >
              <PhTarget :size="16" class="insight-icon" weight="duotone" />
              <span class="insight-copy">
                <strong>{{ c.goal_title }}</strong>
                <small>{{ c.progress_note_md || "来自最近的目标回顾" }}</small>
                <em>{{ fmt(c.checkin_date) }}</em>
              </span>
            </button>
            <button
              v-for="b in snap?.recent_briefings.slice(0, 2) ?? []"
              :key="`briefing-${b.id}`"
              class="insight-row"
              @click="onRecentClick(b)"
            >
              <PhFileText :size="16" class="insight-icon" weight="duotone" />
              <span class="insight-copy">
                <strong>{{ b.title }}</strong>
                <small>来自最近生成的本地简报</small>
                <em>{{ b.kind }}</em>
              </span>
            </button>
            <div v-if="!snap || (snap.recent_checkins.length === 0 && snap.recent_briefings.length === 0)" class="context-empty">
              暂无线索。完成一次目标回顾或生成今日简报后会显示在这里。
            </div>
          </div>
          <button class="context-footer" @click="emit('navigate', 'memory')">查看全部记忆 <PhArrowRight :size="13" /></button>
          </div>
          <div v-else-if="contextTab === 'sources'" class="context-pane source-list">
            <button
              v-for="d in snap?.recent_docs.slice(0, 4) ?? []"
              :key="d.id"
              class="source-row"
              @click="onRecentClick(d)"
            >
              <PhFileText :size="15" />
              <span class="source-name">{{ d.name }}</span>
              <span class="source-meta">{{ d.doc_type || "文档" }}</span>
            </button>
            <div v-if="!snap || snap.recent_docs.length === 0" class="context-empty">
              暂无资料。导入文档后，我会结合当前上下文推荐相关内容。
            </div>
            <button class="context-footer" @click="emit('navigate', 'kb')">打开资料库 <PhArrowRight :size="13" /></button>
          </div>
          <div v-else-if="snap" class="context-pane health-card">
            <div class="health-summary">
              <span>运行状态</span>
            <span class="health-state" :class="{ warn: snap.maintenance.failed_activities > 0 || snap.maintenance.orphan_evidence > 0 }">
              <i />{{ snap.maintenance.failed_activities > 0 || snap.maintenance.orphan_evidence > 0 ? "需要关注" : "运行正常" }}
            </span>
            </div>
          <button class="health-row" @click="emit('navigate', 'diagnostics')">
            <PhShieldCheck :size="16" weight="duotone" />
            <span>本地优先</span><strong>正常</strong>
          </button>
          <button class="health-row" @click="emit('navigate', 'diagnostics')">
            <PhDatabase :size="16" />
            <span>本地备份</span><strong>{{ snap.maintenance.backup_count }} 个</strong>
          </button>
          <button class="health-row" @click="emit('navigate', 'diagnostics')">
            <PhCheckCircle :size="16" />
            <span>失败活动</span><strong :class="{ warn: snap.maintenance.failed_activities > 0 }">{{ snap.maintenance.failed_activities }}</strong>
          </button>
          <button class="health-row" @click="emit('navigate', 'diagnostics')">
            <PhTarget :size="16" />
            <span>孤儿证据</span><strong :class="{ warn: snap.maintenance.orphan_evidence > 0 }">{{ snap.maintenance.orphan_evidence }}</strong>
          </button>
            <button class="context-footer" @click="emit('navigate', 'diagnostics')">查看诊断详情 <PhArrowRight :size="13" /></button>
          </div>
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

/* 2026 redesign · warm editorial workbench */
.today-shell {
  padding: 38px 40px 64px;
  gap: 48px;
  background: var(--color-bg);
}
.today-grid {
  max-width: 1280px;
  grid-template-columns: minmax(560px, 1fr) 300px;
  gap: 36px;
  align-items: start;
}
.today-head {
  min-height: 72px;
  align-items: flex-start;
}
.today-head h1 {
  font-family: var(--font-sans);
  font-size: 40px;
  font-weight: 720;
  line-height: 1;
  letter-spacing: -0.055em;
}
.eyebrow {
  margin: 12px 0 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-lg);
  letter-spacing: 0.015em;
}
.head-actions {
  margin-top: 2px;
}
.soft-action,
.icon-btn {
  height: 40px;
  border-color: var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-surface) 84%, transparent);
  box-shadow: var(--shadow-sm);
  transition: color var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease),
    transform var(--duration-fast) var(--ease-out);
}
.soft-action:hover,
.icon-btn:hover {
  color: var(--color-accent-hover);
  border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
  background: var(--color-surface);
  transform: translateY(-1px);
}
.soft-action:focus-visible,
.icon-btn:focus-visible,
.text-action:focus-visible,
.context-head button:focus-visible,
.source-row:focus-visible,
.insight-row:focus-visible,
.health-row:focus-visible,
.context-refresh:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.icon-btn {
  width: 40px;
}
.focus-section,
.schedule-section,
.reminder-strip {
  margin-top: 28px;
  gap: 12px;
}
.section-head h2,
.context-head h2 {
  margin: 0;
  color: var(--color-fg);
  font-size: 18px;
  font-weight: 650;
  letter-spacing: -0.015em;
}
.text-action {
  min-height: 30px;
  padding: 0 2px;
  border-radius: var(--radius-sm);
  color: var(--color-fg-muted);
  transition: color var(--duration-fast) var(--ease);
}
.priority-list,
.schedule-list {
  border-color: var(--color-border);
  border-radius: 12px;
  background: color-mix(in srgb, var(--color-surface) 76%, transparent);
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.75);
}
.priority-row {
  min-height: 64px;
  padding: 12px 16px;
}
.priority-row:hover {
  background: color-mix(in srgb, var(--color-accent-soft) 52%, transparent);
}
.fake-check {
  width: 18px;
  height: 18px;
  border-radius: 50%;
}
.priority-copy strong {
  font-size: var(--text-md);
}
.row-action {
  border-radius: 7px;
  transition: color var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease);
}
.row-action:hover {
  color: var(--color-accent-hover);
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}
.quiet-empty {
  min-height: 72px;
  padding: 14px 16px;
  border-style: solid;
  border-color: var(--color-border);
  border-radius: 12px;
  color: var(--color-accent-hover);
  background: color-mix(in srgb, var(--color-surface) 72%, transparent);
}
.quiet-empty > div:first-of-type {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}
.quiet-empty strong {
  color: var(--color-fg);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
}
.quiet-empty span {
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
}
.quiet-actions {
  display: flex;
  gap: 6px;
}
.quiet-actions button {
  height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--color-border);
  border-radius: 7px;
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
  font-size: var(--text-sm);
}
.quiet-actions button:hover {
  color: var(--color-accent-hover);
  border-color: var(--color-accent);
}
.overview-disclosure {
  margin-top: 12px;
  border-bottom: 1px solid var(--color-border);
}
.overview-disclosure summary {
  min-height: 34px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--color-fg-subtle);
  cursor: pointer;
  list-style: none;
  font-size: var(--text-sm);
}
.overview-disclosure summary::-webkit-details-marker {
  display: none;
}
.overview-disclosure summary > span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.overview-disclosure summary em {
  font-style: normal;
  color: var(--color-fg-faint);
}
.overview-body {
  padding: 8px 0 16px;
}
.filter-bar {
  margin-top: 0;
}
.filter-select {
  height: 34px;
  border-color: var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}
.filter-select:focus {
  box-shadow: 0 0 0 3px var(--color-accent-soft);
}
.chips {
  margin-top: 12px;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  border-top: 1px solid var(--color-border);
  padding-top: 10px;
}
.chip {
  border-radius: 8px;
}
.chip:hover,
.chip:focus-visible {
  background: var(--color-accent-soft);
  outline: none;
}
.schedule-section {
  margin-top: 24px;
}
.schedule-row {
  position: relative;
  min-height: 58px;
  gap: 12px;
  padding: 0 16px;
  transition: background var(--duration-fast) var(--ease);
}
.schedule-row:hover,
.schedule-row:focus-visible {
  background: color-mix(in srgb, var(--color-accent-soft) 54%, transparent);
  outline: none;
}
.schedule-time {
  width: 50px;
  color: var(--color-fg);
  font-family: var(--font-display);
  font-size: var(--text-md);
  font-variant-numeric: tabular-nums;
}
.schedule-marker {
  position: relative;
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
  border: 1.5px solid var(--color-fg-faint);
  border-radius: 50%;
  background: var(--color-surface);
}
.schedule-row:not(:last-of-type) .schedule-marker::after {
  content: "";
  position: absolute;
  left: 3px;
  top: 11px;
  width: 1px;
  height: 47px;
  background: var(--color-border-strong);
}
.schedule-row.current .schedule-marker {
  border-color: var(--color-accent);
  background: var(--color-accent);
  box-shadow: 0 0 0 4px var(--color-accent-soft);
}
.schedule-copy {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  text-align: left;
}
.schedule-copy strong {
  color: var(--color-fg);
  font-size: var(--text-md);
  font-weight: var(--font-normal);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.schedule-copy small {
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.schedule-icon {
  color: var(--color-fg-faint);
}
.schedule-empty {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.schedule-empty button {
  border: none;
  background: transparent;
  color: var(--color-accent-hover);
  cursor: pointer;
}
.reminder-strip {
  margin-top: 20px;
}
.reminder-chip {
  height: 34px;
  border-radius: 9px;
  background: color-mix(in srgb, var(--color-surface) 70%, transparent);
  cursor: pointer;
}
.reminder-chip:hover {
  color: var(--color-accent-hover);
  border-color: var(--color-accent);
}
.today-composer {
  margin-top: 24px;
  border: 1px solid color-mix(in srgb, var(--color-accent) 30%, var(--color-border));
  border-radius: 16px;
  background: color-mix(in srgb, var(--color-surface) 90%, transparent);
  box-shadow: 0 14px 38px rgba(48, 42, 32, 0.07), inset 0 1px rgba(255, 255, 255, 0.7);
}
.today-composer:focus-within {
  border-color: var(--color-accent);
  box-shadow: 0 16px 40px rgba(47, 123, 105, 0.1),
    0 0 0 3px color-mix(in srgb, var(--color-accent-soft) 72%, transparent);
}
.today-composer label {
  display: block;
  padding: 18px 18px 0;
  color: var(--color-fg);
  font-size: 17px;
  font-weight: var(--font-medium);
}
.today-composer textarea {
  min-height: 70px;
  padding: 16px 18px 12px;
  font-size: var(--text-md);
  line-height: 1.55;
}
.today-composer textarea::placeholder {
  color: var(--color-fg-faint);
}
.composer-actions {
  gap: 8px;
  padding: 12px 16px;
  border-top-color: var(--color-border);
}
.composer-actions button {
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border-radius: 8px;
  background: transparent;
  transition: color var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease),
    transform var(--duration-fast) var(--ease-out);
}
.composer-actions button:hover {
  color: var(--color-accent-hover);
  border-color: var(--color-accent);
  transform: translateY(-1px);
}
.composer-actions button.active {
  color: var(--color-accent-hover);
  border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
  background: var(--color-accent-soft);
}
.composer-actions .send {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--color-accent);
  color: white;
  box-shadow: 0 8px 18px color-mix(in srgb, var(--color-accent) 24%, transparent);
}
.composer-actions .send:disabled {
  opacity: 0.42;
  cursor: not-allowed;
  transform: none;
}
.composer-meta {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 16px 10px;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.composer-meta > span:first-child {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: auto;
  color: var(--color-fg-subtle);
}
.composer-meta > span:first-child svg {
  color: var(--color-accent);
}
.composer-meta kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  border: 1px solid var(--color-border-strong);
  border-radius: 5px;
  background: var(--color-surface-sunken);
  padding: 2px 5px;
}
.today-context {
  gap: 14px;
  padding-top: 92px;
}
.context-card {
  gap: 13px;
  padding: 18px;
  border-color: var(--color-border);
  border-radius: 14px;
  background: color-mix(in srgb, var(--color-surface) 76%, transparent);
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.7);
}
.context-head h2 {
  font-size: 17px;
}
.context-head button,
.health-detail {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
  font-size: var(--text-sm);
}
.context-head button:hover,
.health-detail:hover {
  color: var(--color-accent-hover);
}
.insight-list,
.source-list {
  gap: 0;
}
.insight-row,
.source-row {
  border-radius: 8px;
  padding: 9px 4px;
  transition: background var(--duration-fast) var(--ease);
}
.insight-row + .insight-row,
.source-row + .source-row {
  border-top: 1px solid var(--color-border);
  border-radius: 0;
}
.insight-row:hover,
.source-row:hover {
  background: color-mix(in srgb, var(--color-accent-soft) 48%, transparent);
}
.insight-icon,
.source-row :deep(svg) {
  color: var(--color-accent);
}
.insight-copy {
  gap: 3px;
}
.insight-copy strong {
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.insight-copy small {
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.insight-copy em {
  color: var(--color-fg-faint);
  font-size: 10px;
}
.source-row {
  min-height: 38px;
}
.source-meta {
  color: var(--color-fg-faint);
}
.context-empty {
  line-height: 1.6;
}
.health-card {
  gap: 6px;
}
.health-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-success-fg);
  font-size: var(--text-sm);
}
.health-state i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-success);
}
.health-state.warn {
  color: var(--color-warning-fg);
}
.health-state.warn i {
  background: var(--color-warning);
}
.health-row {
  width: 100%;
  min-height: 34px;
  padding: 0 2px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
  text-align: left;
}
.health-row:hover {
  background: color-mix(in srgb, var(--color-accent-soft) 48%, transparent);
}
.health-row :deep(svg) {
  color: var(--color-accent);
}
.health-row strong {
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
  font-weight: var(--font-normal);
}
.health-detail {
  align-self: flex-end;
  margin-top: 4px;
}
.context-refresh {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.context-refresh:hover {
  color: var(--color-accent-hover);
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}
.workbench-modules {
  max-width: 1280px;
  gap: 24px;
}
@media (max-width: 1280px) {
  .today-shell {
    padding: 30px 28px 56px;
  }
  .today-grid {
    grid-template-columns: minmax(500px, 1fr) 280px;
    gap: 26px;
  }
  .composer-actions {
    flex-wrap: wrap;
  }
  .composer-actions .send {
    margin-left: auto;
  }
}
@media (max-width: 1050px) {
  .today-grid {
    grid-template-columns: 1fr;
  }
  .today-context {
    padding-top: 0;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .today-context .health-card,
  .today-context .context-refresh {
    grid-column: 1 / -1;
  }
}
@media (max-height: 820px) and (min-width: 1051px) {
  .today-shell {
    padding: 24px 28px 44px;
    gap: 32px;
  }
  .today-head {
    min-height: 58px;
  }
  .today-head h1 {
    font-size: 34px;
  }
  .eyebrow {
    margin-top: 7px;
    font-size: var(--text-md);
  }
  .focus-section,
  .schedule-section {
    margin-top: 16px;
  }
  .priority-row {
    min-height: 56px;
    padding-block: 9px;
  }
  .priority-row:nth-child(n + 2) {
    display: none;
  }
  .overview-disclosure summary {
    min-height: 30px;
  }
  .schedule-row {
    min-height: 46px;
  }
  .schedule-list .schedule-row:nth-of-type(n + 4) {
    display: none;
  }
  .schedule-row:not(:last-of-type) .schedule-marker::after {
    height: 35px;
  }
  .reminder-strip {
    margin-top: 12px;
    gap: 8px;
  }
  .reminder-chip {
    height: 30px;
  }
  .today-composer {
    margin-top: 14px;
  }
  .today-composer label {
    padding: 14px 16px 0;
    font-size: var(--text-lg);
  }
  .today-composer textarea {
    min-height: 48px;
    padding: 10px 16px 8px;
  }
  .composer-actions {
    padding: 10px 14px;
  }
  .composer-actions .send {
    width: 40px;
    height: 40px;
  }
  .composer-meta {
    min-height: 30px;
    padding: 0 14px 8px;
  }
  .today-context {
    padding-top: 72px;
    gap: 10px;
  }
  .context-card {
    gap: 9px;
    padding: 14px;
  }
  .insight-row,
  .source-row {
    padding-block: 6px;
  }
  .health-row {
    min-height: 29px;
  }
}
@media (max-width: 760px) {
  .today-shell {
    padding: 24px 18px 48px;
  }
  .today-head h1 {
    font-size: 34px;
  }
  .soft-action span,
  .composer-meta kbd,
  .composer-meta > span:not(:first-child) {
    display: none;
  }
  .quiet-empty {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .quiet-actions {
    width: 100%;
  }
  .chips {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .composer-actions button:not(.send) {
    flex: 1 1 calc(50% - 8px);
    justify-content: center;
  }
  .today-context {
    grid-template-columns: 1fr;
  }
  .today-context .health-card,
  .today-context .context-refresh {
    grid-column: auto;
  }
}
@media (prefers-reduced-motion: reduce) {
  .soft-action,
  .icon-btn,
  .composer-actions button {
    transition-duration: 0.01ms;
  }
}

/* 2026 enterprise workbench refinement */
.today-grid { max-width: 1360px; grid-template-columns: minmax(0, 1fr) 332px; gap: 24px; }
.today-head { min-height: 64px; padding-bottom: 18px; border-bottom: 1px solid var(--color-border); }
.today-head h1 { font-size: 24px; font-weight: 650; letter-spacing: -0.02em; }
.eyebrow { margin-top: 5px; font-size: var(--text-sm); }
.head-actions { margin-left: auto; height: 36px; }
.head-actions button, .runtime-pill { white-space: nowrap; }
.command-entry { width: min(250px, 20vw); height: 36px; display: flex; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-md); background: var(--color-surface-sunken); color: var(--color-fg-subtle); cursor: pointer; }
.command-entry span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.command-entry kbd { margin-left: auto; font: 10px var(--font-mono); color: var(--color-fg-faint); }
.command-entry:hover, .command-entry:focus-visible { border-color: var(--color-accent); background: var(--color-surface); outline: none; }
.primary-action { min-width: 96px; color: var(--color-accent-fg); border-color: var(--color-accent); background: var(--color-accent); }
.primary-action:hover { color: var(--color-accent-fg); border-color: var(--color-accent-hover); background: var(--color-accent-hover); }
.runtime-pill { height: 32px; display: flex; align-items: center; gap: 7px; padding: 0 9px; border: 0; border-radius: var(--radius-md); background: var(--color-surface-hover); color: var(--color-fg-muted); cursor: pointer; font-size: var(--text-xs); }
.runtime-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-success); }
.user-entry { width: 34px; height: 34px; display: grid; place-items: center; border: 0; border-radius: 50%; background: transparent; color: var(--color-fg-muted); cursor: pointer; }
.user-entry:hover, .user-entry:focus-visible { background: var(--color-surface-hover); color: var(--color-fg); outline: none; }
.today-overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 20px; padding: 4px 0; border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.overview-item { min-width: 0; display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; padding: 13px 16px; border: 0; border-right: 1px solid var(--color-border); background: transparent; color: var(--color-fg); text-align: left; cursor: pointer; }
.overview-item:last-child { border-right: 0; }
.overview-item:hover, .overview-item:focus-visible { background: var(--color-surface-hover); outline: none; }
.overview-label { font-size: var(--text-sm); color: var(--color-fg-muted); }
.overview-item strong { grid-row: 1 / 3; grid-column: 2; align-self: center; font-size: 22px; font-variant-numeric: tabular-nums; }
.overview-item small { color: var(--color-fg-faint); }
.overview-item.danger strong { color: var(--color-danger-fg); }
.priority-card { margin-top: 20px; padding: 18px 20px 12px; border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.priority-card .section-head { margin-bottom: 8px; }
.priority-row { padding-inline: 4px; }
.activity-section { margin-top: 20px; padding: 18px 20px 10px; border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.activity-section .section-head p { margin: 3px 0 0; color: var(--color-fg-faint); font-size: var(--text-xs); }
.activity-list { margin-top: 8px; }
.activity-row { position: relative; width: 100%; min-height: 58px; display: grid; grid-template-columns: 34px minmax(0, 1fr) 86px auto 22px; align-items: center; gap: 10px; padding: 8px 4px; border: 0; border-radius: var(--radius-md); background: transparent; color: var(--color-fg); text-align: left; cursor: pointer; }
.activity-row:not(:last-child)::after { content: ""; position: absolute; left: 17px; top: 46px; bottom: -12px; width: 1px; background: var(--color-border); }
.activity-row:hover, .activity-row:focus-visible { background: var(--color-surface-hover); outline: none; }
.activity-icon { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 9px; background: var(--color-accent-soft); color: var(--color-accent); z-index: 1; }
.activity-icon.is-error { background: var(--color-danger-soft); color: var(--color-danger-fg); }
.activity-icon.is-complete { background: var(--color-success-soft); color: var(--color-success-fg); }
.activity-copy { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.activity-copy strong, .activity-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-copy strong { font-size: var(--text-sm); }
.activity-copy small, .activity-row time { color: var(--color-fg-faint); font-size: var(--text-xs); }
.activity-status { padding: 4px 7px; border-radius: var(--radius-full); background: var(--color-surface-sunken); color: var(--color-fg-subtle); font-size: 10px; }
.activity-status.warn { background: var(--color-danger-soft); color: var(--color-danger-fg); }
.activity-more { color: var(--color-fg-faint); }
.today-composer { position: sticky; bottom: 14px; z-index: var(--z-raised); border-color: var(--color-border-strong); background: var(--color-surface); box-shadow: var(--shadow); }
.composer-actions { position: relative; flex-wrap: nowrap; }
.attachment-button { width: 34px; padding: 0; justify-content: center; }
.mode-menu-wrap { position: relative; }
.mode-trigger { min-width: 126px; justify-content: flex-start; }
.mode-menu { position: absolute; left: 0; bottom: 42px; width: 180px; padding: 6px; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); box-shadow: var(--shadow-lg); }
.mode-menu button { width: 100%; justify-content: flex-start; border: 0; }
.composer-runtime { margin-left: auto; display: inline-flex; align-items: center; gap: 5px; color: var(--color-fg-subtle); font-size: var(--text-xs); }
.context-center { min-height: 410px; padding: 18px; background: var(--color-surface); box-shadow: var(--shadow-sm); }
.context-kicker { color: var(--color-fg-faint); font: 10px var(--font-mono); letter-spacing: .12em; }
.context-tabs { display: grid; grid-template-columns: repeat(3, 1fr); padding: 3px; border-radius: var(--radius-md); background: var(--color-surface-sunken); }
.context-tabs button { height: 30px; border: 0; border-radius: 7px; background: transparent; color: var(--color-fg-subtle); cursor: pointer; }
.context-tabs button.active { background: var(--color-surface); color: var(--color-fg); box-shadow: var(--shadow-sm); }
.context-pane { min-height: 280px; display: flex; flex-direction: column; }
.context-footer { align-self: flex-start; margin-top: auto; display: inline-flex; align-items: center; gap: 4px; border: 0; background: transparent; color: var(--color-accent); cursor: pointer; font-size: var(--text-xs); }
.health-summary { display: flex; align-items: center; justify-content: space-between; padding: 8px 2px; }
.compact { width: 30px; height: 30px; }
@media (max-width: 1320px) { .command-entry { width: 44px; } .command-entry span, .command-entry kbd, .runtime-pill { display: none; } .today-grid { grid-template-columns: minmax(0, 1fr) 300px; } }
@media (max-width: 1050px) { .today-grid { grid-template-columns: 1fr; } .today-context { padding-top: 0; display: block; } .today-overview { grid-template-columns: repeat(2, 1fr); } .overview-item:nth-child(2) { border-right: 0; } .overview-item:nth-child(-n+2) { border-bottom: 1px solid var(--color-border); } }
@media (max-width: 720px) { .today-head { align-items: flex-start; } .head-actions { flex-wrap: wrap; justify-content: flex-end; } .primary-action span { display: none; } .activity-row { grid-template-columns: 34px minmax(0, 1fr) auto; } .activity-row time, .activity-more { display: none; } }
</style>
