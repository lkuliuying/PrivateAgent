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
import { DocListItem } from "../features/knowledge";
import PaEmptyState from "../design/PaEmptyState.vue";
import PaErrorState from "../design/PaErrorState.vue";
import { PhBooks } from "@phosphor-icons/vue";

const notify = useNotifications();

const docs = ref<DocumentItem[]>([]);
const search = ref("");
const statusFilter = ref("");
const docTypeFilter = ref("");
const uploading = ref(false);
const batchUploading = ref(false);
const loading = ref(false);
const loadedOnce = ref(false);
const loadError = ref("");
const reindexingAll = ref(false);
const batchResult = ref<{
  imported: number;
  duplicate: number;
  error: number;
} | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const batchInput = ref<HTMLInputElement | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let batchResultTimer: ReturnType<typeof setTimeout> | undefined;
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
  if (!loadedOnce.value) loading.value = true;
  try {
    const result = await listDocuments(
      search.value || undefined,
      statusFilter.value || undefined,
      undefined,
      docTypeFilter.value || undefined
    );
    // 丢弃过期响应（防抖搜索与 3s 轮询竞态），仅保留最新一次结果
    if (seq === loadSeq) {
      docs.value = result;
      loadError.value = "";
      loadedOnce.value = true;
      const visibleIds = new Set(result.map((doc) => doc.id));
      selectedIds.value = new Set(
        [...selectedIds.value].filter((id) => visibleIds.has(id))
      );
    }
  } catch (error) {
    if (seq === loadSeq) {
      loadError.value = error instanceof Error ? error.message : String(error);
      loadedOnce.value = true;
    }
  } finally {
    if (seq === loadSeq) loading.value = false;
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
  if (searchTimer) clearTimeout(searchTimer);
  if (batchResultTimer) clearTimeout(batchResultTimer);
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
    if (batchResultTimer) clearTimeout(batchResultTimer);
    batchResultTimer = setTimeout(() => (batchResult.value = null), 8000);
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
  if (reindexingAll.value) return;
  if (!await notify.confirm({ title: "确认重建全部文档索引？", message: "此操作会重新解析所有文档。", danger: true, impact: "将重新解析并重建全部文档的向量索引，耗时较长" })) return;
  reindexingAll.value = true;
  try {
    const res = await reindexAllDocuments();
    notify.success("已触发重建", `触发 ${res.triggered} 个文档重建，跳过 ${res.skipped} 个（文件缺失）`);
    await load();
  } catch (err) {
    notify.error("重建全部失败", String(err));
  } finally {
    reindexingAll.value = false;
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
</script>

<template>
  <section class="content">
    <div class="kv-head">
      <div class="title-row">
        <div>
          <span class="eyebrow">LOCAL KNOWLEDGE</span>
          <h1>知识库</h1>
          <p class="subtitle">导入本地资料，让回答有据可查、来源可追溯。</p>
        </div>
        <div class="library-stat"><strong>{{ docs.length }}</strong><span>当前文档</span></div>
      </div>
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
      <button
        class="pa-btn pa-btn--subtle pa-btn--sm"
        :disabled="reindexingAll"
        @click="reindexAll"
      >
        {{ reindexingAll ? "正在重建…" : "重建全部" }}
      </button>
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

    <div v-if="loadError" class="load-error-wrap">
      <PaErrorState title="知识库刷新失败" :message="loadError" @retry="load" />
    </div>
    <div v-else-if="loading && !loadedOnce" class="empty-state">
      <PaEmptyState :icon="PhBooks" title="正在加载文档…" description="读取本地知识库索引中" />
    </div>
    <div v-else-if="docs.length === 0" class="empty-state">
      <PaEmptyState
        :icon="PhBooks"
        title="知识库为空"
        description="导入本地资料后，Agent 的回答将有据可查、来源可追溯。"
      />
    </div>
    <div v-else class="doc-list">
      <DocListItem
        v-for="d in docs"
        :key="d.id"
        :doc="d"
        :selected="selectedIds.has(d.id)"
        @toggle-select="toggleSelect"
        @summary="runSummary"
        @ocr="runOcr"
        @edit-metadata="editMetadata"
        @toggle-enabled="toggleEnabled"
        @reindex="reindex"
        @retry="retry"
        @remove="remove"
      />
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
          <button
            class="pa-btn pa-btn--ghost pa-btn--icon"
            title="关闭章节摘要"
            aria-label="关闭章节摘要"
            @click="showSummary = false"
          >
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
  padding: 30px clamp(28px, 3.5vw, 52px) 0;
  background: radial-gradient(circle at 92% 12%, color-mix(in srgb, var(--color-accent) 7%, transparent), transparent 28%);
}
.docs-view {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 clamp(28px, 3.5vw, 52px) 32px;
}
.title-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; }
.eyebrow { color: var(--color-accent); font-size: 10px; font-weight: 700; letter-spacing: .16em; }
.library-stat { display: grid; min-width: 94px; padding: 11px 14px; border: 1px solid var(--color-border); border-radius: 14px; background: var(--color-surface); }
.library-stat strong { color: var(--color-accent); font-size: 20px; line-height: 1; }
.library-stat span { margin-top: 4px; color: var(--color-fg-faint); font-size: 10px; }
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
  margin: 4px 0 5px;
  font-size: 30px;
  font-weight: var(--font-semibold);
  letter-spacing: -.045em;
}
.subtitle {
  margin: 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-base);
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 16px 0;
  padding: 10px;
  border: 1px solid var(--color-border);
  border-radius: 14px;
  background: color-mix(in srgb, var(--color-surface) 92%, transparent);
}
.search-input {
  width: 220px;
  flex: 1 1 220px;
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
.load-error-wrap {
  margin-bottom: var(--space-4);
  border: 1px solid color-mix(in srgb, var(--color-danger) 25%, transparent);
  border-radius: var(--radius-md);
  background: var(--color-danger-soft);
}
.empty-state {
  padding: var(--space-4) 0;
}
.doc-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
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
@media (max-width: 920px) {
  .kv-head,
  .docs-view {
    padding-left: var(--space-5);
    padding-right: var(--space-5);
  }
  .toolbar-spacer {
    display: none;
  }
}
</style>
