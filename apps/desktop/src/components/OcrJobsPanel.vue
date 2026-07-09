<script setup lang="ts">
/**
 * OCR 队列面板（第七阶段 M3）。展示引擎可用性、任务状态、失败重试。
 * 挂在诊断中心。引擎未装时给出明确原因与下一步。
 */
import { onMounted, ref } from "vue";
import { PhArrowClockwise, PhWarning, PhCheckCircle } from "@phosphor-icons/vue";
import { getOcrAvailability, listOcrJobs, retryOcrJob, type OcrAvailability, type OcrJob } from "../api";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const availability = ref<OcrAvailability | null>(null);
const jobs = ref<OcrJob[]>([]);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    availability.value = await getOcrAvailability();
    jobs.value = await listOcrJobs();
  } catch (e) {
    notify.error("加载 OCR 队列失败", String(e));
  } finally {
    loading.value = false;
  }
}

async function retry(id: number) {
  try {
    await retryOcrJob(id);
    notify.success("已重新排队", `OCR job #${id}`);
    await load();
  } catch (e) {
    notify.error("重试失败", String(e));
  }
}

function statusLabel(s: string): string {
  return { pending: "待处理", processing: "处理中", succeeded: "成功", failed: "失败", unavailable: "引擎不可用", cancelled: "已取消" }[s] || s;
}

onMounted(load);
</script>

<template>
  <article class="ocr-panel">
    <div class="panel-head">
      <h3>OCR 队列</h3>
      <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="loading" @click="load">
        <PhArrowClockwise :size="14" /> 刷新
      </button>
    </div>

    <div v-if="availability" class="ocr-avail" :class="{ unavailable: !availability.available }">
      <component
        :is="availability.available ? PhCheckCircle : PhWarning"
        :size="16"
        weight="fill"
      />
      <span v-if="availability.available">OCR 引擎可用（{{ availability.engine }}）</span>
      <span v-else>OCR 引擎不可用：{{ availability.reason }}</span>
    </div>

    <div v-if="jobs.length === 0" class="empty">暂无 OCR 任务</div>
    <ul v-else class="ocr-list">
      <li v-for="j in jobs" :key="j.id" class="ocr-item">
        <div class="ocr-item-head">
          <strong>job #{{ j.id }}</strong>
          <span class="ocr-status" :class="`st-${j.status}`">{{ statusLabel(j.status) }}</span>
        </div>
        <div class="ocr-item-meta">
          <span v-if="j.doc_id">文档 #{{ j.doc_id }}</span>
          <span v-if="j.engine">引擎 {{ j.engine }}</span>
          <span v-if="j.output_text">{{ j.output_text.length }} 字符</span>
        </div>
        <p v-if="j.error_message" class="ocr-err">{{ j.error_message }}</p>
        <button
          v-if="j.status === 'failed' || j.status === 'unavailable'"
          class="pa-btn pa-btn--subtle pa-btn--sm"
          @click="retry(j.id)"
        >
          <PhArrowClockwise :size="13" /> 重试
        </button>
      </li>
    </ul>
  </article>
</template>

<style scoped>
.ocr-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.panel-head h3 {
  margin: 0;
  font-size: var(--text-md);
}
.ocr-avail {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-success-fg);
}
.ocr-avail.unavailable {
  color: var(--color-warning-fg);
}
.empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.ocr-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.ocr-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.ocr-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ocr-item-head strong {
  font-size: var(--text-sm);
}
.ocr-status {
  font-size: var(--text-xs);
  padding: 1px var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
}
.st-succeeded {
  color: var(--color-success-fg);
  background: var(--color-success-soft);
}
.st-failed,
.st-unavailable {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
}
.st-processing {
  color: var(--color-accent);
  background: var(--color-accent-soft);
}
.ocr-item-meta {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}
.ocr-err {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-danger-fg);
  word-break: break-word;
}
</style>
