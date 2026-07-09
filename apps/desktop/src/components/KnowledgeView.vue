<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import {
  batchImportDocuments,
  compareDocuments,
  deleteDocument,
  importDocument,
  listDocuments,
  ocrDocument,
  patchDocument,
  reindexAllDocuments,
  reindexDocument,
  retryDocument,
  summarizeSections,
} from "../api";
import type { CompareResult, DocumentItem, SectionSummary } from "../types";
import DocumentComparePanel from "./DocumentComparePanel.vue";
import CollectionWorkspace from "./CollectionWorkspace.vue";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();

const docs = ref<DocumentItem[]>([]);
const search = ref("");
const statusFilter = ref("");
const docTypeFilter = ref("");
const uploading = ref(false);
const batchUploading = ref(false);
const batchResult = ref<{
  imported: number;
  duplicate: number;
  error: number;
} | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const batchInput = ref<HTMLInputElement | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let loadSeq = 0;

// 子视图切换：文档列表 / 文档集合
const subView = ref<"docs" | "collections">("docs");

// 多选 + 对比
const selectedIds = ref<Set<number>>(new Set());
const showCompare = ref(false);
const compareResult = ref<CompareResult | null>(null);
const comparing = ref(false);

// 章节摘要
const showSummary = ref(false);
const summaryTitle = ref("");
const summarySections = ref<SectionSummary[]>([]);
const summarizing = ref(false);

async function load() {
  const seq = ++loadSeq;
  try {
    const result = await listDocuments(
      search.value || undefined,
      statusFilter.value || undefined,
      undefined,
      docTypeFilter.value || undefined
    );
    // 丢弃过期响应（防抖搜索与 3s 轮询竞态），仅保留最新一次结果
    if (seq === loadSeq) docs.value = result;
  } catch {
    // 后端未连接
  }
}

function onSearchInput() {
  // 搜索防抖：避免每个字符都打后端
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(load, 300);
}

onMounted(() => {
  load();
  timer = setInterval(() => {
    if (subView.value === "docs") load();
  }, 3000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});

async function onFile(e: Event) {
  const target = e.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  uploading.value = true;
  try {
    await importDocument(file);
    await load();
  } catch (err) {
    notify.error("导入失败", String(err));
  } finally {
    uploading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}

async function onBatchFiles(e: Event) {
  const target = e.target as HTMLInputElement;
  const files = target.files ? Array.from(target.files) : [];
  if (!files.length) return;
  batchUploading.value = true;
  batchResult.value = null;
  try {
    const items = await batchImportDocuments(files);
    batchResult.value = {
      imported: items.filter((i) => i.status === "imported").length,
      duplicate: items.filter((i) => i.status === "duplicate").length,
      error: items.filter((i) => i.status === "error").length,
    };
    await load();
  } catch (err) {
    notify.error("批量导入失败", String(err));
  } finally {
    batchUploading.value = false;
    if (batchInput.value) batchInput.value.value = "";
    setTimeout(() => (batchResult.value = null), 8000);
  }
}

async function toggleEnabled(d: DocumentItem) {
  try {
    await patchDocument(d.id, !d.enabled);
    d.enabled = !d.enabled;
  } catch (err) {
    notify.error("切换启用状态失败", String(err));
  }
}

async function editMetadata(d: DocumentItem) {
  const topic = await notify.prompt({ title: "主题（topic，留空清除）", defaultValue: d.topic || "" });
  if (topic === null) return;
  const tagsStr = await notify.prompt({ title: "标签（逗号分隔，留空清除）", defaultValue: (d.tags_json || []).join(", ") });
  if (tagsStr === null) return;
  const language = await notify.prompt({ title: "语言（如 zh / en，留空清除）", defaultValue: d.language || "" });
  if (language === null) return;
  const tags = tagsStr
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  try {
    const updated = await patchDocument(d.id, d.enabled, {
      topic,
      tags,
      language,
    });
    Object.assign(d, updated);
  } catch (err) {
    notify.error("保存元数据失败", String(err));
  }
}

async function reindex(d: DocumentItem) {
  try {
    await reindexDocument(d.id);
    await load();
  } catch (err) {
    notify.error("重建索引失败", String(err));
  }
}

async function reindexAll() {
  if (!await notify.confirm({ title: "确认重建全部文档索引？", message: "此操作会重新解析所有文档。", danger: true, impact: "将重新解析并重建全部文档的向量索引，耗时较长" })) return;
  try {
    const res = await reindexAllDocuments();
    notify.success("已触发重建", `触发 ${res.triggered} 个文档重建，跳过 ${res.skipped} 个（文件缺失）`);
    await load();
  } catch (err) {
    notify.error("重建全部失败", String(err));
  }
}

async function remove(id: number) {
  if (!await notify.confirm({ title: "确认删除该文档？", danger: true, impact: "该操作不可撤销，文档及其向量数据将被永久删除" })) return;
  try {
    await deleteDocument(id);
    await load();
  } catch (err) {
    notify.error("删除失败", String(err));
  }
}

async function retry(id: number) {
  try {
    await retryDocument(id);
    await load();
  } catch (err) {
    notify.error("重试失败", String(err));
  }
}

// ============ 多选 / 对比 / 摘要 ============

function toggleSelect(id: number) {
  if (selectedIds.value.has(id)) selectedIds.value.delete(id);
  else selectedIds.value.add(id);
  selectedIds.value = new Set(selectedIds.value);
}

const canCompare = computed(
  () => selectedIds.value.size >= 2 && selectedIds.value.size <= 5
);

async function runCompare() {
  if (!canCompare.value) return;
  showCompare.value = true;
  compareResult.value = null;
  comparing.value = true;
  try {
    compareResult.value = await compareDocuments(Array.from(selectedIds.value));
  } catch (e) {
    notify.error("对比失败", String(e));
    showCompare.value = false;
  } finally {
    comparing.value = false;
  }
}

async function runSummary(d: DocumentItem) {
  showSummary.value = true;
  summaryTitle.value = d.name;
  summarySections.value = [];
  summarizing.value = true;
  try {
    summarySections.value = await summarizeSections(d.id);
  } catch (e) {
    notify.error("摘要失败", String(e));
    showSummary.value = false;
  } finally {
    summarizing.value = false;
  }
}

async function runOcr(d: DocumentItem) {
  try {
    const r = await ocrDocument(d.id);
    notify.info("OCR 结果", r.message);
  } catch (e) {
    notify.error("OCR 失败", String(e));
  }
}

const STATUS_TEXT: Record<string, string> = {
  pending: "等待中",
  processing: "处理中",
  ready: "已就绪",
  failed: "失败",
  deleting: "删除中",
};
const STATUS_CLASS: Record<string, string> = {
  ready: "ok",
  failed: "bad",
  processing: "warn",
  pending: "warn",
  deleting: "warn",
};

function fmtSize(b: number | null): string {
  if (!b) return "-";
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / 1024 / 1024).toFixed(1) + " MB";
}
</script>

<template>
  <section class="content">
    <div class="kv-head">
      <h1>知识库</h1>
      <p class="subtitle">
        导入本地文档（PDF / Word / Markdown / TXT），启用知识库后助手可基于资料回答并标注来源。
      </p>
      <nav class="sub-tabs">
        <button :class="{ active: subView === 'docs' }" @click="subView = 'docs'">文档</button>
        <button :class="{ active: subView === 'collections' }" @click="subView = 'collections'">集合</button>
      </nav>
    </div>

    <div v-if="subView === 'docs'" class="docs-view">
    <div class="toolbar">
      <input
        v-model="search"
        class="pa-input search-input"
        placeholder="搜索文档名…"
        @input="onSearchInput"
      />
      <select v-model="statusFilter" class="pa-input status-select" @change="load">
        <option value="">全部状态</option>
        <option value="ready">已就绪</option>
        <option value="processing">处理中</option>
        <option value="pending">等待中</option>
        <option value="failed">失败</option>
      </select>
      <select v-model="docTypeFilter" class="pa-input status-select" @change="load">
        <option value="">全部类型</option>
        <option value="markdown">Markdown</option>
        <option value="pdf">PDF</option>
        <option value="docx">Word</option>
        <option value="text">文本</option>
      </select>
      <div class="toolbar-spacer" />
      <input
        ref="batchInput"
        type="file"
        accept=".pdf,.docx,.md,.markdown,.txt"
        multiple
        @change="onBatchFiles"
        hidden
      />
      <button class="pa-btn pa-btn--ghost pa-btn--sm" @click="batchInput?.click()" :disabled="batchUploading">
        {{ batchUploading ? "批量导入中…" : "批量导入" }}
      </button>
      <input
        ref="fileInput"
        type="file"
        accept=".pdf,.docx,.md,.markdown,.txt"
        @change="onFile"
        hidden
      />
      <button class="pa-btn pa-btn--primary pa-btn--sm" @click="fileInput?.click()" :disabled="uploading">
        {{ uploading ? "导入中…" : "+ 导入文档" }}
      </button>
      <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="reindexAll">重建全部</button>
      <button
        class="pa-btn pa-btn--primary pa-btn--sm"
        :disabled="!canCompare"
        :title="canCompare ? '对比所选文档' : '请选择 2-5 个文档'"
        @click="runCompare"
      >
        对比所选（{{ selectedIds.size }}）
      </button>
    </div>

    <div v-if="batchResult" class="batch-result">
      批量导入完成：{{ batchResult.imported }} 个导入，{{ batchResult.duplicate }} 个重复跳过<template v-if="batchResult.error">，{{ batchResult.error }} 个失败</template>
    </div>

    <div v-if="docs.length === 0" class="empty">暂无文档，点击上方按钮导入</div>
    <div v-else class="doc-list">
      <div v-for="d in docs" :key="d.id" class="doc-item" :class="{ disabled: !d.enabled, selected: selectedIds.has(d.id) }">
        <div class="doc-select">
          <input
            type="checkbox"
            :checked="selectedIds.has(d.id)"
            @change="toggleSelect(d.id)"
            title="选择以对比"
          />
        </div>
        <div class="doc-main">
          <div class="doc-name">{{ d.name }}</div>
          <div class="doc-meta">
            <span class="status" :class="STATUS_CLASS[d.status]">{{ STATUS_TEXT[d.status] || d.status }}</span>
            <span v-if="d.doc_type" class="meta-chip">{{ d.doc_type }}</span>
            <span>{{ fmtSize(d.size_bytes) }}</span>
            <span v-if="d.chunk_count">切片 {{ d.chunk_count }}</span>
            <span v-if="d.topic" class="meta-chip topic">主题：{{ d.topic }}</span>
            <span v-if="d.language" class="meta-chip">{{ d.language }}</span>
            <span v-for="t in d.tags_json || []" :key="t" class="meta-chip tag">#{{ t }}</span>
          </div>
          <div v-if="d.error_message" class="doc-err">失败原因：{{ d.error_message }}</div>
        </div>
        <div class="doc-actions">
          <button class="icon-btn" title="章节摘要" @click="runSummary(d)">摘要</button>
          <button class="icon-btn" title="OCR（预留接口）" @click="runOcr(d)">OCR</button>
          <button class="icon-btn" title="编辑元数据" @click="editMetadata(d)">元数据</button>
          <label class="enable-toggle" :title="d.enabled ? '已启用，参与检索' : '已禁用，不参与检索'">
            <input type="checkbox" :checked="d.enabled" @change="toggleEnabled(d)" />
            <span>{{ d.enabled ? "启用" : "禁用" }}</span>
          </label>
          <button v-if="d.status === 'ready'" class="icon-btn" title="重建索引" @click="reindex(d)">重建</button>
          <button v-if="d.status === 'failed'" class="icon-btn" title="重试" @click="retry(d.id)">重试</button>
          <button class="icon-btn del" title="删除" @click="remove(d.id)">删除</button>
        </div>
      </div>
    </div>
    </div>

    <CollectionWorkspace v-else-if="subView === 'collections'" />

    <!-- 对比浮层 -->
    <DocumentComparePanel
      v-if="showCompare"
      :result="compareResult"
      :loading="comparing"
      @close="showCompare = false"
    />

    <!-- 章节摘要浮层 -->
    <div v-if="showSummary" class="modal-overlay" @click.self="showSummary = false">
      <div class="summary-card">
        <div class="summary-head">
          <span>章节摘要：{{ summaryTitle }}</span>
          <button class="pa-btn pa-btn--ghost pa-btn--icon" @click="showSummary = false">
            ✕
          </button>
        </div>
        <div class="summary-body">
          <p v-if="summarizing" class="muted">生成中…</p>
          <div v-else-if="summarySections.length === 0" class="muted">未生成摘要</div>
          <div v-for="(s, i) in summarySections" :key="i" class="summary-item">
            <div class="summary-heading">{{ s.heading }}</div>
            <div class="summary-text">{{ s.summary }}</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.content {
  overflow: hidden;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.kv-head {
  flex-shrink: 0;
  padding: 28px 32px 0;
}
.docs-view {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 32px 28px;
}
.sub-tabs {
  display: flex;
  gap: 2px;
  margin: var(--space-3) 0 0;
  border-bottom: 1px solid var(--color-border);
}
.sub-tabs button {
  border: none;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  border-bottom: 2px solid transparent;
}
.sub-tabs button:hover {
  color: var(--color-fg);
}
.sub-tabs button.active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}
h1 {
  margin: 0 0 4px;
  font-size: var(--text-2xl);
  font-weight: var(--font-semibold);
}
.subtitle {
  margin: 0 0 var(--space-5);
  color: var(--color-fg-subtle);
  font-size: var(--text-base);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.search-input {
  width: 220px;
  height: 30px;
  font-size: var(--text-base);
}
.status-select {
  height: 30px;
  font-size: var(--text-base);
  background: var(--color-surface);
}
.toolbar-spacer {
  flex: 1;
}
.batch-result {
  background: var(--color-success-soft);
  color: var(--color-success-fg);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  margin-bottom: var(--space-4);
}
.empty {
  text-align: center;
  color: var(--color-fg-faint);
  padding: 60px 0;
  font-size: var(--text-base);
}
.doc-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.doc-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.doc-item.disabled {
  opacity: 0.55;
}
.doc-item.selected {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}
.doc-select {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}
.doc-select input {
  margin: 0;
  cursor: pointer;
}
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.summary-card {
  width: 560px;
  max-width: 92vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}
.summary-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
}
.summary-body {
  flex: 1;
  overflow: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.summary-item {
  border-left: 3px solid var(--color-accent);
  padding-left: var(--space-3);
}
.summary-heading {
  font-weight: var(--font-medium);
  font-size: var(--text-sm);
  margin-bottom: 2px;
}
.summary-text {
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
}
.muted {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
  padding: var(--space-4);
}
.doc-name {
  font-weight: var(--font-medium);
  font-size: var(--text-base);
  word-break: break-all;
}
.doc-meta {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-fg-subtle);
  margin-top: var(--space-1);
  flex-wrap: wrap;
}
.status {
  font-weight: var(--font-medium);
}
.status.ok {
  color: var(--color-success-fg);
}
.status.bad {
  color: var(--color-danger-fg);
}
.status.warn {
  color: var(--color-warning-fg);
}
.meta-chip {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  background: var(--color-surface-sunken);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}
.meta-chip.topic {
  color: var(--color-accent-soft-fg);
  background: var(--color-accent-soft);
}
.meta-chip.tag {
  color: var(--color-fg-subtle);
}
.doc-err {
  font-size: var(--text-sm);
  color: var(--color-danger-fg);
  margin-top: var(--space-1);
}
.doc-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
.enable-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
  cursor: pointer;
  user-select: none;
  padding: 4px var(--space-2);
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
}
.enable-toggle input {
  margin: 0;
}
.icon-btn {
  border-radius: var(--radius);
  padding: 5px 10px;
  font-size: var(--text-sm);
  cursor: pointer;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-fg-muted);
}
.icon-btn:hover {
  background: var(--color-surface-sunken);
}
.icon-btn.del {
  color: var(--color-danger-fg);
}
</style>
