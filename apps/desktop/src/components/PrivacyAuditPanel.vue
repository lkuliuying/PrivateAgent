<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { PhArrowClockwise, PhShieldCheck } from "@phosphor-icons/vue";
import {
  getMaintenanceHealthReport,
  listPrivacyAudits,
  privacyPreview,
} from "../api";
import type { MaintenanceHealthReport, PrivacyPreview, ProviderCallAudit } from "../types";

const report = ref<MaintenanceHealthReport | null>(null);
const audits = ref<ProviderCallAudit[]>([]);
const preview = ref<PrivacyPreview | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");

const healthRows = computed(() => {
  if (!report.value) return [];
  const s = report.value.summary;
  return [
    ["备份", s.backup_count, s.last_backup_at ? `最近 ${fmt(s.last_backup_at)}` : "暂无"],
    ["失败活动", s.failed_activities, "需要复查"],
    ["草稿记忆", s.draft_memories, "待确认"],
    ["关注任务", s.attention_tasks, "暂停/失败/草稿"],
    ["收件箱", s.open_inbox, "未处理"],
    ["到期提醒", s.due_reminders, "待处理"],
  ];
});

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
    const [nextReport, nextAudits] = await Promise.all([
      getMaintenanceHealthReport(),
      listPrivacyAudits(),
    ]);
    report.value = nextReport;
    audits.value = nextAudits;
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function runPreview() {
  busy.value = true;
  error.value = "";
  try {
    preview.value = await privacyPreview({
      purpose: "manual-preview",
      include_kb: true,
      include_memories: true,
      include_messages: true,
      estimated_message_chars: 800,
    });
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
  <div class="privacy-panel">
    <div class="panel-head">
      <div>
        <h3>隐私与维护</h3>
        <p class="hint">预览远程 Provider 将接触的上下文，并检查本地维护风险。</p>
      </div>
      <div class="actions">
        <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="loading" @click="load">
          <PhArrowClockwise :size="14" /> 刷新
        </button>
        <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="busy" @click="runPreview">
          <PhShieldCheck :size="14" /> 隐私预览
        </button>
      </div>
    </div>

    <div v-if="error" class="error-line">{{ error }}</div>

    <div class="health-grid">
      <div v-for="row in healthRows" :key="row[0]" class="health-card">
        <strong>{{ row[1] }}</strong>
        <span>{{ row[0] }}</span>
        <small>{{ row[2] }}</small>
      </div>
    </div>

    <div v-if="report?.recommendations.length" class="recommend">
      <strong>建议</strong>
      <ul>
        <li v-for="r in report.recommendations" :key="r">{{ r }}</li>
      </ul>
    </div>

    <div v-if="preview" class="preview">
      <strong>最近一次预览 #{{ preview.audit_id }}</strong>
      <span>{{ preview.remote ? "远程 Provider" : "本地 Provider" }} · {{ preview.provider_type }}</span>
      <span>上下文：{{ preview.context_types.join(", ") || "无" }}</span>
      <span>排除敏感记忆：{{ preview.sensitive_memory_excluded }}</span>
      <span>估算输入字符：{{ preview.estimated_input_chars }}</span>
    </div>

    <div class="audit-list">
      <div class="audit-head">
        <strong>Provider 审计</strong>
        <span class="hint">最近 {{ audits.length }} 条</span>
      </div>
      <div v-for="a in audits.slice(0, 6)" :key="a.id" class="audit-item">
        <span>{{ a.purpose }} · {{ a.provider_type }} · {{ a.status }}</span>
        <small>{{ a.remote ? "remote" : "local" }} · {{ fmt(a.created_at) }}</small>
      </div>
      <div v-if="audits.length === 0" class="empty">暂无审计记录。</div>
    </div>
  </div>
</template>

<style scoped>
.privacy-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel-head,
.audit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.panel-head h3 {
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
.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: var(--space-2);
}
.health-card,
.recommend,
.preview,
.audit-list {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-3);
}
.health-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.health-card strong {
  font-size: var(--text-xl);
}
.health-card small,
.audit-item small {
  color: var(--color-fg-faint);
}
.recommend ul {
  margin: var(--space-2) 0 0;
  padding-left: 18px;
}
.preview,
.audit-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.audit-item {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  border-top: 1px solid var(--color-border);
  padding-top: var(--space-2);
  font-size: var(--text-sm);
}
</style>
