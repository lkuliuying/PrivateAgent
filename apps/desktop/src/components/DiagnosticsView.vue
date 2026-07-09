<script setup lang="ts">
/**
 * 诊断中心（第七阶段 M5）。一屏排障：健康/版本/迁移/失败活动/Provider 失败/
 * 提醒 tick/导入队列/备份/数据体检/最近错误 + 导出脱敏诊断包。
 */
import { onMounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhDownloadSimple,
  PhCheckCircle,
  PhXCircle,
  PhWarning,
  PhDatabase,
  PhCpu,
} from "@phosphor-icons/vue";
import { exportDiagnostics, getDiagnostics, type DiagnosticsSnapshot } from "../api";
import { useNotifications } from "../stores/notifications";
import OcrJobsPanel from "./OcrJobsPanel.vue";
import IntegrityReportPanel from "./IntegrityReportPanel.vue";

const notify = useNotifications();
const snap = ref<DiagnosticsSnapshot | null>(null);
const loading = ref(false);
const exporting = ref(false);

function okOf(svc: unknown): boolean {
  return Boolean((svc as { ok?: boolean } | undefined)?.ok);
}

async function load() {
  loading.value = true;
  try {
    snap.value = await getDiagnostics();
  } catch (e) {
    notify.error("加载诊断失败", String(e));
  } finally {
    loading.value = false;
  }
}

async function doExport() {
  exporting.value = true;
  try {
    const res = await exportDiagnostics();
    notify.success("诊断包已生成", res.path);
  } catch (e) {
    notify.error("导出诊断包失败", String(e));
  } finally {
    exporting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="diag-shell">
    <header class="diag-head">
      <div>
        <h1>诊断中心</h1>
        <p class="hint" v-if="snap">
          版本 {{ snap.version }} · 迁移 {{ snap.migration_head || "未知" }} ·
          生成于 {{ new Date(snap.generated_at).toLocaleString() }}
        </p>
      </div>
      <div class="diag-actions">
        <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="loading" @click="load">
          <PhArrowClockwise :size="14" /> 刷新
        </button>
        <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="exporting" @click="doExport">
          <PhDownloadSimple :size="14" /> 导出诊断包
        </button>
      </div>
    </header>

    <div v-if="snap" class="diag-grid">
      <!-- 健康状态 -->
      <article class="diag-card">
        <h3>服务健康</h3>
        <div class="health-grid">
          <div v-for="svc in (['api','ollama','mysql','chroma'] as const)" :key="svc" class="health-item">
            <component
              :is="okOf(snap.health[svc]) ? PhCheckCircle : PhXCircle"
              :size="16"
              :class="okOf(snap.health[svc]) ? 'health-ok-icon' : 'health-bad-icon'"
              weight="fill"
            />
            <span class="health-label">{{ svc.toUpperCase() }}</span>
            <span class="health-state">{{ okOf(snap.health[svc]) ? "正常" : "异常" }}</span>
          </div>
        </div>
        <p v-if="(snap.health.mysql as any)?.error" class="err-line">
          MySQL: {{ (snap.health.mysql as any).error }}
        </p>
      </article>

      <!-- 失败活动 -->
      <article class="diag-card">
        <h3>失败活动 <span class="count">{{ snap.failed_activities.length }}</span></h3>
        <div v-if="snap.failed_activities.length === 0" class="empty">无失败活动</div>
        <ul v-else class="err-list">
          <li v-for="(a, i) in snap.failed_activities.slice(0, 10)" :key="i">
            <strong>{{ a.title }}</strong>
            <span>{{ a.error_message }}</span>
          </li>
        </ul>
      </article>

      <!-- Provider 失败 -->
      <article class="diag-card">
        <h3>Provider 调用失败 <span class="count">{{ snap.provider_failures.length }}</span></h3>
        <div v-if="snap.provider_failures.length === 0" class="empty">无失败调用</div>
        <ul v-else class="err-list">
          <li v-for="(p, i) in snap.provider_failures.slice(0, 10)" :key="i">
            <strong>{{ p.provider_type }} · {{ p.error_code || "未知" }}</strong>
            <span>{{ p.error_message }}{{ p.fallback_used ? "（已回退 Ollama）" : "" }}</span>
          </li>
        </ul>
      </article>

      <!-- 导入队列 / 提醒 / 备份 / 体检 -->
      <article class="diag-card">
        <h3>运行状态</h3>
        <div class="stat-row"><PhDatabase :size="15" /><span>导入队列</span>
          <strong>待{{ snap.import_queue.pending || 0 }} · 处理{{ snap.import_queue.processing || 0 }} · 需OCR{{ snap.import_queue.needs_ocr || 0 }} · 失败{{ snap.import_queue.failed || 0 }}</strong>
        </div>
        <div class="stat-row"><PhCpu :size="15" /><span>提醒 tick</span>
          <strong>{{ snap.reminder_tick.enabled ? "已启用" : "已关闭" }}</strong>
        </div>
        <div class="stat-row"><PhDatabase :size="15" /><span>备份</span>
          <strong>{{ snap.backup.count }} 个{{ snap.backup.last_backup_at ? " · " + new Date(snap.backup.last_backup_at).toLocaleDateString() : "" }}</strong>
        </div>
        <div class="stat-row"><PhWarning :size="15" /><span>孤儿证据</span>
          <strong :class="{ warn: snap.integrity_summary.orphan_evidence > 0 }">{{ snap.integrity_summary.orphan_evidence }}</strong>
        </div>
      </article>

      <!-- 最近错误日志 -->
      <article class="diag-card diag-card--wide">
        <h3>最近错误日志</h3>
        <pre v-if="snap.recent_errors.length" class="err-log">{{ snap.recent_errors.join("\n") }}</pre>
        <p v-else class="empty">无最近错误</p>
      </article>

      <!-- 脱敏配置摘要 -->
      <article class="diag-card diag-card--wide">
        <h3>脱敏配置摘要</h3>
        <p class="hint">DB: {{ snap.db_url_redacted }}</p>
        <div class="settings-grid">
          <div v-for="(v, k) in snap.settings_redacted" :key="k" class="settings-row">
            <span class="settings-key">{{ k }}</span>
            <span class="settings-val">{{ v }}</span>
          </div>
        </div>
      </article>
    </div>

    <!-- OCR 队列 + 数据完整性体检 -->
    <div class="diag-grid">
      <OcrJobsPanel />
      <IntegrityReportPanel />
    </div>
  </section>
</template>

<style scoped>
.diag-shell {
  overflow-y: auto;
  padding: var(--space-8);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  max-width: 1180px;
  margin: 0 auto;
  width: 100%;
}
.diag-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}
.diag-head h1 {
  margin: 0;
  font-size: var(--text-2xl);
  font-weight: var(--font-semibold);
}
.hint {
  margin: var(--space-1) 0 0;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.diag-actions {
  display: flex;
  gap: var(--space-2);
}
.diag-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}
.diag-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.diag-card--wide {
  grid-column: 1 / -1;
}
.diag-card h3 {
  margin: 0;
  font-size: var(--text-md);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.count {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  background: var(--color-surface-sunken);
  border-radius: var(--radius-full);
  padding: 1px var(--space-2);
}
.health-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
}
.health-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
.health-ok-icon {
  color: var(--color-success);
}
.health-bad-icon {
  color: var(--color-danger);
}
.health-label {
  font-weight: var(--font-medium);
}
.health-state {
  margin-left: auto;
  color: var(--color-fg-muted);
}
.err-line {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-danger-fg);
  word-break: break-word;
}
.err-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.err-list li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--text-sm);
}
.err-list strong {
  font-weight: var(--font-medium);
}
.err-list span {
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  word-break: break-word;
}
.stat-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
.stat-row span {
  color: var(--color-fg-muted);
}
.stat-row strong {
  margin-left: auto;
}
.stat-row strong.warn {
  color: var(--color-danger-fg);
}
.empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.err-log {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  background: var(--color-surface-sunken);
  border-radius: var(--radius);
  padding: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--color-fg-muted);
}
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-1) var(--space-4);
}
.settings-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--text-xs);
}
.settings-key {
  color: var(--color-fg-muted);
}
.settings-val {
  color: var(--color-fg);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 900px) {
  .diag-grid {
    grid-template-columns: 1fr;
  }
}
</style>
