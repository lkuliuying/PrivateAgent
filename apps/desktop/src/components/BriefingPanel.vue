<script setup lang="ts">
import { onMounted, ref } from "vue";
import { PhArrowClockwise, PhFileText, PhListChecks, PhPlus } from "@phosphor-icons/vue";
import {
  briefingToTask,
  createTodayBriefing,
  createWeeklyBriefing,
  listBriefings,
} from "../api";
import type { Briefing } from "../types";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const briefings = ref<Briefing[]>([]);
const selected = ref<Briefing | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");

function fmt(s: string): string {
  const d = new Date(s);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    briefings.value = await listBriefings();
    selected.value = selected.value
      ? briefings.value.find((b) => b.id === selected.value?.id) ?? briefings.value[0] ?? null
      : briefings.value[0] ?? null;
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function createToday() {
  busy.value = true;
  error.value = "";
  try {
    const briefing = await createTodayBriefing();
    await load();
    selected.value = briefing;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function createWeekly() {
  busy.value = true;
  error.value = "";
  try {
    const briefing = await createWeeklyBriefing();
    await load();
    selected.value = briefing;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function toTask() {
  if (!selected.value) return;
  busy.value = true;
  try {
    const res = await briefingToTask(selected.value.id);
    notify.success("任务草稿已生成", `#${res.task_id}`);
  } catch (e) {
    notify.error("生成任务草稿失败", String(e));
  } finally {
    busy.value = false;
  }
}

// 暴露给父组件（今日页「今日简报」按钮调用 load 刷新列表）。
defineExpose({ load });

onMounted(load);
</script>

<template>
  <div class="brief-panel">
    <div class="panel-head">
      <div>
        <h3>主动简报</h3>
        <p class="hint">把今日事项、目标回顾和后续动作沉淀为可追踪记录。</p>
      </div>
      <div class="actions">
        <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="loading" @click="load">
          <PhArrowClockwise :size="14" /> 刷新
        </button>
        <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="busy" @click="createToday">
          <PhPlus :size="14" /> 今日简报
        </button>
        <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="createWeekly">
          周回顾
        </button>
      </div>
    </div>

    <div v-if="error" class="error-line">{{ error }}</div>

    <div class="brief-grid">
      <div class="brief-list">
        <button
          v-for="b in briefings"
          :key="b.id"
          class="brief-item"
          :class="{ active: selected?.id === b.id }"
          @click="selected = b"
        >
          <PhFileText :size="16" />
          <span>
            <strong>{{ b.title }}</strong>
            <small>{{ b.kind }} · {{ fmt(b.created_at) }}</small>
          </span>
        </button>
        <div v-if="!loading && briefings.length === 0" class="empty">暂无简报。</div>
      </div>

      <div class="brief-preview">
        <template v-if="selected">
          <div class="preview-head">
            <div>
              <h4>{{ selected.title }}</h4>
              <p class="hint">{{ selected.kind }} · 来源 {{ selected.sources_json?.length || 0 }} 个</p>
            </div>
            <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="toTask">
              <PhListChecks :size="14" /> 转任务
            </button>
          </div>
          <pre>{{ selected.body_md }}</pre>
        </template>
        <div v-else class="empty">选择或生成一份简报。</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.brief-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel-head,
.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.panel-head h3,
.preview-head h4 {
  margin: 0;
}
.hint,
.empty {
  margin: 0;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.actions {
  display: flex;
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
.brief-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(320px, 1.5fr);
  gap: var(--space-3);
}
.brief-list,
.brief-preview {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
}
.brief-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.brief-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  text-align: left;
  border: 1px solid var(--color-border);
  background: var(--color-bg);
  border-radius: var(--radius);
  padding: var(--space-2);
  cursor: pointer;
}
.brief-item.active {
  border-color: var(--color-accent);
}
.brief-item strong,
.brief-item small {
  display: block;
}
.brief-item small {
  color: var(--color-fg-faint);
  margin-top: 2px;
}
.brief-preview {
  min-height: 220px;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
pre {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.55;
  font: inherit;
  color: var(--color-fg);
}
@media (max-width: 900px) {
  .brief-grid {
    grid-template-columns: 1fr;
  }
}
</style>
