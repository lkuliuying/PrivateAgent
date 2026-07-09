<script setup lang="ts">
/**
 * 快速捕获面板（第七阶段 M3）。文本/剪贴板捕获，转 inbox/reminder/memory candidate。
 * 挂在今日页工作区模块。OCR 队列见 OcrJobsPanel（诊断中心）。
 */
import { onMounted, ref } from "vue";
import {
  PhClipboard,
  PhPlus,
  PhTray,
  PhBell,
  PhBrain,
  PhArrowClockwise,
} from "@phosphor-icons/vue";
import {
  captureToInbox,
  captureToMemory,
  captureToReminder,
  createCapture,
  listCapture,
  type CaptureItem,
} from "../api";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const content = ref("");
const title = ref("");
const candidate = ref<string>("inbox");
const items = ref<CaptureItem[]>([]);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    items.value = await listCapture({ status: "pending" });
  } catch {
    items.value = [];
  } finally {
    loading.value = false;
  }
}

async function readClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      content.value = text;
      notify.success("已读取剪贴板", `${text.length} 字符`);
    } else {
      notify.info("剪贴板为空");
    }
  } catch {
    notify.warning("无法读取剪贴板", "请手动粘贴文本");
  }
}

async function save() {
  const text = content.value.trim();
  if (!text) {
    notify.warning("请输入捕获内容");
    return;
  }
  try {
    await createCapture({
      content_md: text,
      title: title.value.trim() || undefined,
      source: "manual",
      candidate_type: candidate.value,
    });
    content.value = "";
    title.value = "";
    notify.success("已保存捕获草稿");
    await load();
  } catch (e) {
    notify.error("保存失败", String(e));
  }
}

async function convert(item: CaptureItem, target: "inbox" | "reminder" | "memory") {
  try {
    if (target === "inbox") await captureToInbox(item.id);
    else if (target === "reminder") await captureToReminder(item.id);
    else await captureToMemory(item.id);
    notify.success(`已转为${target === "inbox" ? "收件箱" : target === "reminder" ? "提醒" : "记忆候选"}`);
    await load();
  } catch (e) {
    notify.error("转化失败", String(e));
  }
}

onMounted(load);
defineExpose({ load });
</script>

<template>
  <div class="cap-panel">
    <div class="panel-head">
      <div>
        <h3>快速捕获</h3>
        <p class="hint">把零散文本统一成可处理对象，再转为收件箱/提醒/记忆。</p>
      </div>
      <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="loading" @click="load">
        <PhArrowClockwise :size="14" /> 刷新
      </button>
    </div>

    <div class="cap-form">
      <input
        v-model="title"
        class="cap-title"
        placeholder="标题（可选）"
      />
      <textarea
        v-model="content"
        class="cap-text"
        rows="3"
        placeholder="粘贴或输入要捕获的文本…"
      />
      <div class="cap-actions">
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="readClipboard">
          <PhClipboard :size="14" /> 读剪贴板
        </button>
        <select v-model="candidate" class="cap-select" aria-label="候选类型">
          <option value="inbox">收件箱</option>
          <option value="reminder">提醒</option>
          <option value="memory">记忆候选</option>
          <option value="learning_note">学习笔记</option>
          <option value="task_draft">任务草稿</option>
        </select>
        <button class="pa-btn pa-btn--primary pa-btn--sm" @click="save">
          <PhPlus :size="14" /> 保存草稿
        </button>
      </div>
    </div>

    <div v-if="items.length" class="cap-list">
      <div v-for="it in items" :key="it.id" class="cap-item">
        <div class="cap-item-body">
          <strong>{{ it.title || it.content_md.slice(0, 40) }}</strong>
          <span>{{ it.content_md.slice(0, 80) }}</span>
        </div>
        <div class="cap-item-actions">
          <button class="cap-convert" title="转收件箱" @click="convert(it, 'inbox')">
            <PhTray :size="14" />
          </button>
          <button class="cap-convert" title="转提醒" @click="convert(it, 'reminder')">
            <PhBell :size="14" />
          </button>
          <button class="cap-convert" title="转记忆候选" @click="convert(it, 'memory')">
            <PhBrain :size="14" />
          </button>
        </div>
      </div>
    </div>
    <p v-else class="cap-empty">暂无待处理捕获草稿。</p>
  </div>
</template>

<style scoped>
.cap-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
}
.panel-head h3 {
  margin: 0;
  font-size: var(--text-md);
}
.hint {
  margin: 2px 0 0;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.cap-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.cap-title,
.cap-text {
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  font-family: inherit;
  font-size: var(--text-sm);
  color: var(--color-fg);
  background: var(--color-surface-sunken);
}
.cap-title {
  height: 32px;
}
.cap-text {
  resize: vertical;
}
.cap-title:focus,
.cap-text:focus {
  outline: none;
  border-color: var(--color-accent);
}
.cap-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.cap-select {
  height: 30px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius);
  background: var(--color-surface);
  font-size: var(--text-sm);
  padding: 0 var(--space-2);
}
.cap-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.cap-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-bg);
}
.cap-item-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cap-item-body strong {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cap-item-body span {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cap-item-actions {
  display: flex;
  gap: var(--space-1);
  flex-shrink: 0;
}
.cap-convert {
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius);
  display: grid;
  place-items: center;
}
.cap-convert:hover {
  color: var(--color-accent);
  border-color: var(--color-accent);
}
.cap-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
  padding: var(--space-3);
}
</style>
