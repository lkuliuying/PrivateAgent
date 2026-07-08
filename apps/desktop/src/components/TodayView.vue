<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhArrowRight,
  PhBell,
  PhCalendarBlank,
  PhChatCircle,
  PhCheckCircle,
  PhDatabase,
  PhPlus,
  PhShieldCheck,
  PhSparkle,
  PhSun,
} from "@phosphor-icons/vue";
import { createInbox, getSettings, getToday } from "../api";
import type { InboxItemType, TodayItem, TodaySnapshot } from "../types";
import BriefingPanel from "./BriefingPanel.vue";
import GoalsWorkspace from "./GoalsWorkspace.vue";
import InboxPanel from "./InboxPanel.vue";
import PrivacyAuditPanel from "./PrivacyAuditPanel.vue";
import ReminderPanel from "./ReminderPanel.vue";

type View =
  | "chat"
  | "today"
  | "kb"
  | "projects"
  | "learning"
  | "tasks"
  | "memory"
  | "settings";

const emit = defineEmits<{ navigate: [view: View] }>();

const snap = ref<TodaySnapshot | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const inboxPanel = ref<InstanceType<typeof InboxPanel> | null>(null);
const reminderPanel = ref<InstanceType<typeof ReminderPanel> | null>(null);

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

async function load() {
  loading.value = true;
  error.value = "";
  try {
    snap.value = await getToday();
    void maybeNotify();
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function maybeNotify() {
  if (!snap.value || snap.value.due_reminders.length === 0) return;
  try {
    const s = await getSettings();
    if (!s.desktop_notifications_enabled) return;
    if (!("Notification" in window)) return;
    let perm = Notification.permission;
    if (perm === "default") perm = await Notification.requestPermission();
    if (perm !== "granted") return;
    new Notification("私人助手：到期提醒", {
      body: `你有 ${snap.value.due_reminders.length} 条到期提醒，请在今日页处理。`,
    });
  } catch {
    // 今日页已展示到期提醒。
  }
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

function fmt(s: string | null): string {
  if (!s) return "";
  const d = new Date(s);
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
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
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
            <button class="soft-action" @click="emit('navigate', 'chat')">
              <PhSparkle :size="16" />
              <span>今日简报</span>
            </button>
            <button class="icon-btn" :disabled="loading" title="刷新" @click="load">
              <PhArrowClockwise :size="16" />
            </button>
          </div>
        </div>

        <div v-if="error" class="error-line">{{ error }}</div>

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

        <div v-if="snap && allEmpty" class="empty-banner">
          <PhSun :size="34" weight="duotone" />
          <div>
            <p>今天没有必须处理的事项。</p>
            <p class="hint">你可以从下方收件箱新建待办，或直接向助手提问。</p>
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

        <section class="schedule-section">
          <div class="section-head">
            <h3>日程安排</h3>
            <button class="text-action" @click="emit('navigate', 'tasks')">
              <span>查看日历</span>
              <PhArrowRight :size="14" />
            </button>
          </div>
          <div class="schedule-list">
            <div class="schedule-row active">
              <span class="time">09:30</span>
              <span class="schedule-dot" />
              <strong>整理今日简报与计划</strong>
              <span>30 分钟</span>
            </div>
            <div class="schedule-row">
              <span class="time">11:00</span>
              <span class="schedule-dot" />
              <strong>处理收件箱与任务审批</strong>
              <span>45 分钟</span>
            </div>
            <div class="schedule-row">
              <span class="time">15:00</span>
              <span class="schedule-dot" />
              <strong>复习学习卡片和候选记忆</strong>
              <span>60 分钟</span>
            </div>
            <div class="schedule-row">
              <span class="time">20:00</span>
              <span class="schedule-dot" />
              <strong>个人时间：阅读与回顾</strong>
              <span>90 分钟</span>
            </div>
          </div>
        </section>

        <section class="reminder-strip">
          <div class="section-head compact">
            <h3>提醒</h3>
            <button class="text-action" @click="emit('navigate', 'today')">
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

        <section class="context-card">
          <div class="context-head">
            <h3>记忆洞察</h3>
            <button @click="emit('navigate', 'memory')">查看全部</button>
          </div>
          <div class="insight-list">
            <div>
              <strong>你正在推进个人助手项目</strong>
              <span>基于最近会话与任务上下文</span>
            </div>
            <div>
              <strong>本周重点偏向发布与 UI</strong>
              <span>安装包、更新与界面改造</span>
            </div>
            <div>
              <strong>学习复习需要持续跟进</strong>
              <span>{{ snap?.summary.due_cards ?? 0 }} 张卡片到期</span>
            </div>
          </div>
          <button class="wide-action" @click="emit('navigate', 'memory')">
            <span>更新记忆</span>
            <PhArrowClockwise :size="14" />
          </button>
        </section>

        <section class="context-card">
          <div class="context-head">
            <h3>相关来源</h3>
            <button @click="emit('navigate', 'kb')">查看全部</button>
          </div>
          <div class="source-list">
            <div><PhDatabase :size="14" /> PRD_智能笔记应用_v1.3.md <span>文档</span></div>
            <div><PhDatabase :size="14" /> 用户反馈汇总_202505.md <span>文档</span></div>
            <div><PhDatabase :size="14" /> 系统设计_存储模块.md <span>文档</span></div>
          </div>
          <p class="hint">基于当前上下文推荐</p>
        </section>

        <section class="context-card">
          <div class="context-head">
            <h3>隐私与安全</h3>
            <button @click="emit('navigate', 'settings')">隐私审计</button>
          </div>
          <div class="privacy-list">
            <div><PhShieldCheck :size="16" weight="fill" /> 本地优先 <span>正常</span></div>
            <div><PhShieldCheck :size="16" weight="fill" /> 数据未外传 <span>正常</span></div>
            <div><PhShieldCheck :size="16" weight="fill" /> 模型本地运行 <span>Qwen3 14B</span></div>
          </div>
        </section>

        <section v-if="snap" class="context-card">
          <div class="context-head">
            <h3>系统健康</h3>
            <button @click="emit('navigate', 'settings')">查看详情</button>
          </div>
          <div class="health-row">
            <PhDatabase :size="16" />
            <span>最近备份</span>
            <strong>{{ snap.backup.last_backup_at ? fmt(snap.backup.last_backup_at) : "暂无" }}</strong>
          </div>
          <div class="health-row">
            <PhCalendarBlank :size="16" />
            <span>备份包</span>
            <strong>{{ snap.backup.count }} 个</strong>
          </div>
          <p class="health-ok">服务运行正常</p>
        </section>
      </aside>
    </div>

    <div class="workbench-modules">
      <ReminderPanel ref="reminderPanel" />
      <InboxPanel ref="inboxPanel" />
      <GoalsWorkspace />
      <BriefingPanel />
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
  align-items: center;
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
  min-height: 54px;
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--color-border);
}
.schedule-row:last-child {
  border-bottom: none;
}
.schedule-row .time {
  width: 48px;
  color: var(--color-fg);
  font-variant-numeric: tabular-nums;
}
.schedule-dot {
  width: 9px;
  height: 9px;
  border: 2px solid var(--color-border-strong);
  border-radius: var(--radius-full);
  background: var(--color-panel);
  flex-shrink: 0;
}
.schedule-row.active .schedule-dot {
  border-color: var(--color-accent);
  background: var(--color-accent);
}
.schedule-row strong {
  flex: 1;
  min-width: 0;
  font-weight: var(--font-normal);
}
.schedule-row > span:last-child {
  color: var(--color-fg-subtle);
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
.source-list,
.privacy-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.insight-list div,
.source-list div,
.privacy-list div,
.health-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.insight-list div {
  align-items: flex-start;
  flex-direction: column;
  gap: 2px;
}
.insight-list strong,
.source-list div,
.privacy-list div,
.health-row {
  font-size: var(--text-sm);
}
.insight-list span,
.source-list span,
.privacy-list span {
  margin-left: auto;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}
.wide-action {
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-panel);
  color: var(--color-fg);
  cursor: pointer;
}
.privacy-list svg {
  color: var(--color-success);
}
.health-row strong {
  margin-left: auto;
}
.health-ok {
  margin: 0;
  color: var(--color-success-fg);
  font-size: var(--text-sm);
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
