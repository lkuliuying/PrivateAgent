<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhDatabase,
  PhPlus,
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
  { key: "due_cards", title: "到期复习", view: "learning", itemType: "review", pick: (s) => s.due_cards },
  { key: "attention_tasks", title: "待关注任务", view: "tasks", itemType: "approval", pick: (s) => s.attention_tasks },
  { key: "failed_activities", title: "失败活动", view: "kb", itemType: "failure", pick: (s) => s.failed_activities },
  { key: "draft_memories", title: "候选记忆", view: "memory", itemType: "memory", pick: (s) => s.draft_memories },
  { key: "due_reminders", title: "到期提醒", view: "today", itemType: "reminder", pick: (s) => s.due_reminders },
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

/** 桌面通知预研：到期提醒且设置开启时请求权限并提示；失败降级到今日页（已展示）。 */
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
    // 通知失败：今日页已展示到期提醒，无需额外处理
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
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}

/** 把一个今日卡片存为收件箱项（保留来源引用），完成后刷新收件箱列表。 */
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
    <div class="today-head">
      <div>
        <h1>今日</h1>
        <p class="hint">每天打开应用先看这里：到期复习、待审批任务、失败活动、候选记忆、提醒与收件箱。</p>
      </div>
      <button class="icon-btn" :disabled="loading" title="刷新" @click="load">
        <PhArrowClockwise :size="16" />
      </button>
    </div>

    <div v-if="error" class="error-line">{{ error }}</div>

    <!-- 摘要 chips -->
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

    <!-- 空状态 -->
    <div v-if="snap && allEmpty" class="empty-banner">
      <PhSun :size="36" weight="duotone" />
      <p>今天没有待处理事项，收件箱也空空如也。</p>
      <p class="hint">可在下方收件箱新建待办，或去各模块继续工作。</p>
    </div>

    <!-- 快照分区卡片 -->
    <div v-for="sec in visibleSections" :key="sec.key" class="section">
      <div class="section-head">
        <h3>{{ sec.title }} · {{ sec.items.length }}</h3>
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="emit('navigate', sec.view)">
          去查看
        </button>
      </div>
      <div class="card-list">
        <div v-for="it in sec.items" :key="`${sec.key}-${it.id}`" class="today-card">
          <div class="card-main">
            <div class="card-title">{{ cardTitle(it) }}</div>
            <div class="card-meta">{{ cardMeta(it) }}</div>
            <div v-if="it.error_message" class="card-err">{{ it.error_message }}</div>
          </div>
          <div class="card-actions">
            <button
              class="pa-btn pa-btn--subtle pa-btn--sm"
              :disabled="busy"
              title="存为收件箱"
              @click="saveToInbox(it, sec.itemType)"
            >
              <PhPlus :size="14" /> 收件箱
            </button>
            <button
              class="pa-btn pa-btn--ghost pa-btn--sm"
              title="跳转来源"
              @click="emit('navigate', sec.view)"
            >
              跳转
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 提醒 -->
    <div class="section">
      <ReminderPanel ref="reminderPanel" />
    </div>

    <!-- 收件箱 -->
    <div class="section">
      <InboxPanel ref="inboxPanel" />
    </div>

    <!-- 长期目标 -->
    <div class="section">
      <GoalsWorkspace />
    </div>

    <!-- 主动简报 -->
    <div class="section">
      <BriefingPanel />
    </div>

    <!-- 隐私与维护 -->
    <div class="section">
      <PrivacyAuditPanel />
    </div>

    <!-- 数据体检 -->
    <div v-if="snap" class="section">
      <div class="section-head">
        <h3>数据体检</h3>
      </div>
      <div class="health">
        <div class="health-row">
          <PhDatabase :size="16" />
          <span>最近备份：</span>
          <strong>{{ snap.backup.last_backup_at ? fmt(snap.backup.last_backup_at) : "暂无备份" }}</strong>
          <span class="hint">（共 {{ snap.backup.count }} 个备份包）</span>
        </div>
        <p class="hint">备份与数据清理建议在「设置」页操作；本页只做状态展示。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.today-shell {
  overflow: auto;
  padding: 28px 32px;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.today-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.today-head h1 {
  margin: 0;
  font-size: var(--text-2xl);
}
.hint {
  margin: 0;
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
.error-line {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius);
  padding: var(--space-2);
  font-size: var(--text-sm);
}
.chips {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--space-3);
}
.chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  cursor: pointer;
}
.chip:hover {
  border-color: var(--color-accent);
}
.chip.zero {
  opacity: 0.55;
}
.chip-value {
  font-size: var(--text-2xl);
  font-weight: var(--font-medium);
}
.chip-label {
  font-size: var(--text-sm);
  color: var(--color-fg-faint);
}
.empty-banner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-8);
  text-align: center;
  color: var(--color-fg-muted);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
}
.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.section-head h3 {
  margin: 0;
  font-size: var(--text-lg);
}
.card-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.today-card {
  display: flex;
  gap: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
}
.today-card:hover {
  border-color: var(--color-accent);
}
.card-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.card-title {
  font-weight: var(--font-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-meta {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.card-err {
  color: var(--color-danger-fg);
  font-size: var(--text-sm);
  white-space: pre-wrap;
}
.card-actions {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  flex-shrink: 0;
}
.health {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.health-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
</style>
