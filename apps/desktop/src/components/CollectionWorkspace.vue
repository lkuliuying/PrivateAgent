<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import {
  PhFolders,
  PhPlus,
  PhSparkle,
  PhFileText,
  PhTrash,
  PhX,
  PhDownload,
} from "@phosphor-icons/vue";
import {
  listDocumentCollections,
  createDocumentCollection,
  getDocumentCollection,
  deleteDocumentCollection,
  addCollectionItem,
  removeCollectionItem,
  extractCollection,
  templateReport,
  listCollectionExtractions,
  listDocuments,
} from "../api";
import type {
  DocumentCollection,
  CollectionDetail,
  DocumentItem,
  DocumentExtraction,
  DocExtractionKind,
  TemplateKind,
} from "../types";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();

/**
 * 文档集合工作区 · 第四阶段 M3。
 * 左：集合列表 + 新建；右：集合详情（成员增删）+ 结构化抽取 + 模板报告 + 抽取结果（含来源 doc/chunk）。
 */
const collections = ref<DocumentCollection[]>([]);
const currentId = ref<number | null>(null);
const current = ref<CollectionDetail | null>(null);
const allDocs = ref<DocumentItem[]>([]);
const extractions = ref<DocumentExtraction[]>([]);
const busy = ref(false);
const msg = ref("");

const newOpen = ref(false);
const newTitle = ref("");
const newGoal = ref("");
const addDocId = ref<number | null>(null);

const KIND_LABELS: Record<DocExtractionKind, string> = {
  terms: "术语表",
  actions: "行动项",
  claims: "关键观点",
  table_summary: "表格摘要",
  code: "代码片段",
};
const KINDS: DocExtractionKind[] = ["terms", "actions", "claims", "table_summary", "code"];

const TEMPLATE_LABELS: Record<TemplateKind, string> = {
  study_note: "学习笔记",
  tech_summary: "技术摘要",
  paper_reading: "论文阅读",
  project_materials: "项目资料整理",
  meeting_minutes: "会议纪要",
};
const TEMPLATES: TemplateKind[] = ["study_note", "tech_summary", "paper_reading", "project_materials", "meeting_minutes"];

const memberDocIds = computed(
  () => new Set((current.value?.items || []).map((i) => i.doc_id))
);
const availableDocs = computed(() =>
  allDocs.value.filter((d) => d.status === "ready" && !memberDocIds.value.has(d.id))
);

onMounted(load);

async function load() {
  try {
    collections.value = await listDocumentCollections();
  } catch (e) {
    collections.value = [];
    msg.value = "集合加载失败：" + String(e);
  }
  try {
    allDocs.value = await listDocuments();
  } catch (e) {
    allDocs.value = [];
    msg.value = (msg.value ? msg.value + "；" : "") + "文档列表加载失败：" + String(e);
  }
  if (collections.value.length > 0 && currentId.value === null) {
    await selectCollection(collections.value[0].id);
  }
}

async function selectCollection(id: number) {
  currentId.value = id;
  msg.value = "";
  try {
    const [detail, exts] = await Promise.all([
      getDocumentCollection(id),
      listCollectionExtractions(id),
    ]);
    if (currentId.value !== id) return; // 已切到别的集合，丢弃过期响应
    current.value = detail;
    extractions.value = exts;
    addDocId.value = null;
  } catch (e) {
    if (currentId.value !== id) return;
    current.value = null;
    msg.value = String(e);
  }
}

function openNew() {
  newOpen.value = true;
  newTitle.value = "";
  newGoal.value = "";
}

async function submitNew() {
  if (!newTitle.value.trim()) return;
  try {
    const c = await createDocumentCollection({
      title: newTitle.value.trim(),
      goal: newGoal.value.trim() || undefined,
    });
    collections.value.unshift(c);
    newOpen.value = false;
    await selectCollection(c.id);
  } catch (e) {
    notify.error("创建失败", String(e));
  }
}

async function removeCollection() {
  if (!currentId.value) return;
  if (!await notify.confirm({ title: "确认删除该集合？", danger: true, impact: "该操作不可撤销，集合及其成员关联将被永久删除" })) return;
  try {
    await deleteDocumentCollection(currentId.value);
    collections.value = collections.value.filter((c) => c.id !== currentId.value);
    current.value = null;
    extractions.value = [];
    currentId.value = null;
  } catch (e) {
    notify.error("删除失败", String(e));
  }
}

async function addDoc() {
  if (!currentId.value || !addDocId.value) return;
  try {
    await addCollectionItem(currentId.value, addDocId.value);
    await selectCollection(currentId.value);
    addDocId.value = null;
  } catch (e) {
    notify.error("添加失败", String(e));
  }
}

async function removeDoc(docId: number) {
  if (!currentId.value) return;
  try {
    await removeCollectionItem(currentId.value, docId);
    await selectCollection(currentId.value);
  } catch (e) {
    notify.error("移除失败", String(e));
  }
}

async function runExtract(kind: DocExtractionKind) {
  if (!currentId.value) return;
  busy.value = true;
  msg.value = `正在抽取${KIND_LABELS[kind]}…`;
  try {
    await extractCollection(currentId.value, kind);
    extractions.value = await listCollectionExtractions(currentId.value);
    msg.value = `${KIND_LABELS[kind]}抽取完成`;
  } catch (e) {
    msg.value = "抽取失败：" + String(e);
  } finally {
    busy.value = false;
  }
}

async function runTemplate(t: TemplateKind) {
  if (!currentId.value) return;
  busy.value = true;
  msg.value = `正在生成${TEMPLATE_LABELS[t]}…`;
  try {
    await templateReport({ template: t, collection_id: currentId.value });
    extractions.value = await listCollectionExtractions(currentId.value);
    msg.value = `${TEMPLATE_LABELS[t]}生成完成`;
  } catch (e) {
    msg.value = "生成失败：" + String(e);
  } finally {
    busy.value = false;
  }
}

function exportMd(ex: DocumentExtraction) {
  let content = ex.content_md || "";
  const refs = (ex.source_refs_json || []) as Array<{
    doc_name?: string;
    chunk_ordinal?: number;
    heading?: string;
  }>;
  // 导出时保留来源列表（§5.3 引用与溯源）
  if (refs.length) {
    const seen = new Set<string>();
    const lines = ["", "## 来源", ""];
    for (const r of refs) {
      const key = `${r.doc_name}#${r.chunk_ordinal}`;
      if (seen.has(key)) continue;
      seen.add(key);
      lines.push(
        `- ${r.doc_name || "?"} 片段${r.chunk_ordinal ?? "?"}${r.heading ? `（${r.heading}）` : ""}`
      );
    }
    content += "\n" + lines.join("\n");
  }
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `extraction-${ex.kind}-${ex.id}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function kindLabel(ex: DocumentExtraction): string {
  if (ex.kind === "template_report") {
    const t = ex.content_json?.template as TemplateKind | undefined;
    return t ? TEMPLATE_LABELS[t] : "模板报告";
  }
  return KIND_LABELS[ex.kind as DocExtractionKind] || ex.kind;
}

function fmtRefs(ex: DocumentExtraction): string {
  const refs = (ex.source_refs_json || []) as Array<{
    doc_id?: number;
    doc_name?: string;
    chunk_ordinal?: number;
    heading?: string;
  }>;
  if (!refs.length) return "无来源标注";
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const r of refs.slice(0, 8)) {
    const key = `${r.doc_id ?? "?"}#${r.chunk_ordinal}`;
    if (seen.has(key)) continue;
    seen.add(key);
    parts.push(`${r.doc_name || "?"} 片段${r.chunk_ordinal ?? "?"}`);
  }
  return parts.join("、") + (refs.length > 8 ? ` …（共 ${refs.length} 处）` : "");
}
</script>

<template>
  <section class="cw">
    <aside class="cw-list">
      <div class="pane-head">
        <span>文档集合</span>
        <button class="pa-btn pa-btn--primary pa-btn--icon" title="新建集合" @click="openNew">
          <PhPlus :size="14" />
        </button>
      </div>
      <div class="coll-list">
        <button
          v-for="c in collections"
          :key="c.id"
          class="coll-item"
          :class="{ active: c.id === currentId }"
          @click="selectCollection(c.id)"
        >
          <div class="coll-title pa-ellipsis">{{ c.title }}</div>
          <div class="coll-sub">{{ c.goal || "（无目标）" }}</div>
        </button>
        <div v-if="collections.length === 0" class="pane-empty">尚无集合</div>
      </div>
    </aside>

    <div class="cw-detail">
      <div v-if="!current" class="empty">
        <PhFolders :size="40" weight="duotone" />
        <p>选择或创建一个文档集合</p>
        <p class="hint">把多篇资料聚合成集合，统一抽取术语、行动项与关键观点，或按模板生成报告</p>
      </div>
      <template v-else>
        <header class="detail-head">
          <div class="head-main">
            <h2>{{ current.title }}</h2>
            <p v-if="current.goal" class="head-goal">{{ current.goal }}</p>
          </div>
          <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="removeCollection">
            <PhTrash :size="14" /> 删除集合
          </button>
        </header>

        <p v-if="msg" class="msg">{{ msg }}</p>

        <!-- 成员 -->
        <section class="block">
          <div class="block-head">
            <span>成员文档（{{ current.items.length }}）</span>
            <div class="add-row">
              <select v-model.number="addDocId" class="pa-input">
                <option :value="null">选择文档…</option>
                <option v-for="d in availableDocs" :key="d.id" :value="d.id">{{ d.name }}</option>
              </select>
              <button
                class="pa-btn pa-btn--primary pa-btn--sm"
                :disabled="!addDocId"
                @click="addDoc"
              >添加</button>
            </div>
          </div>
          <div v-if="current.items.length === 0" class="block-empty">尚无成员，从上方添加</div>
          <div v-else class="member-list">
            <div v-for="it in current.items" :key="it.id" class="member-item">
              <PhFileText :size="14" />
              <span class="member-name pa-ellipsis">{{ it.doc_name || `文档#${it.doc_id}` }}</span>
              <span v-if="it.doc_status" class="member-status" :class="it.doc_status">{{ it.doc_status }}</span>
              <button class="icon-x" title="移除" @click="removeDoc(it.doc_id)">
                <PhX :size="13" />
              </button>
            </div>
          </div>
        </section>

        <!-- 抽取 -->
        <section class="block">
          <div class="block-head"><span><PhSparkle :size="14" /> 结构化抽取</span></div>
          <div class="btn-grid">
            <button
              v-for="k in KINDS"
              :key="k"
              class="pa-btn pa-btn--subtle pa-btn--sm"
              :disabled="busy || current.items.length === 0"
              @click="runExtract(k)"
            >{{ KIND_LABELS[k] }}</button>
          </div>
        </section>

        <!-- 模板报告 -->
        <section class="block">
          <div class="block-head"><span><PhFileText :size="14" /> 模板报告</span></div>
          <div class="btn-grid">
            <button
              v-for="t in TEMPLATES"
              :key="t"
              class="pa-btn pa-btn--primary pa-btn--sm"
              :disabled="busy || current.items.length === 0"
              @click="runTemplate(t)"
            >{{ TEMPLATE_LABELS[t] }}</button>
          </div>
        </section>

        <!-- 结果 -->
        <section class="block">
          <div class="block-head"><span>抽取结果（{{ extractions.length }}）</span></div>
          <div v-if="extractions.length === 0" class="block-empty">尚无抽取结果</div>
          <div v-else class="result-list">
            <div v-for="ex in extractions" :key="ex.id" class="result-item">
              <div class="result-head">
                <span class="result-kind">{{ kindLabel(ex) }}</span>
                <span class="result-time">{{ new Date(ex.created_at).toLocaleString() }}</span>
                <button class="icon-x" title="导出 Markdown" @click="exportMd(ex)">
                  <PhDownload :size="13" />
                </button>
              </div>
              <pre v-if="ex.content_md" class="result-md">{{ ex.content_md }}</pre>
              <div class="result-refs">来源：{{ fmtRefs(ex) }}</div>
            </div>
          </div>
        </section>
      </template>
    </div>

    <!-- 新建浮层 -->
    <div v-if="newOpen" class="modal-overlay" @click.self="newOpen = false">
      <div class="modal-card">
        <div class="modal-head">
          <span>新建文档集合</span>
          <button class="pa-btn pa-btn--ghost pa-btn--icon" @click="newOpen = false">
            <PhX :size="14" />
          </button>
        </div>
        <label class="modal-label">标题</label>
        <input v-model="newTitle" class="pa-input" placeholder="如：操作系统论文集" />
        <label class="modal-label">目标</label>
        <textarea v-model="newGoal" class="pa-input" rows="2" placeholder="集合的阅读/研究目标"></textarea>
        <div class="modal-actions">
          <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="newOpen = false">取消</button>
          <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="!newTitle.trim()" @click="submitNew">创建</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.cw {
  display: flex;
  flex: 1;
  min-height: 0;
}
.cw-list {
  flex-shrink: 0;
  width: 240px;
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
}
.pane-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
}
.coll-list {
  flex: 1;
  overflow: auto;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.coll-item {
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.coll-item:hover {
  background: var(--color-surface-sunken);
}
.coll-item.active {
  background: var(--color-accent-soft);
}
.coll-title {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg);
}
.coll-item.active .coll-title {
  color: var(--color-accent-soft-fg);
}
.coll-sub {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pane-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
  padding: var(--space-4);
}

.cw-detail {
  flex: 1;
  min-width: 0;
  overflow: auto;
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg);
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-fg-faint);
  gap: var(--space-2);
}
.empty p {
  margin: 0;
  font-size: var(--text-base);
}
.empty .hint {
  font-size: var(--text-sm);
  max-width: 320px;
  text-align: center;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.detail-head h2 {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
}
.head-goal {
  margin: 4px 0 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
}
.msg {
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
  margin-bottom: var(--space-3);
}
.block {
  margin-bottom: var(--space-4);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
  margin-bottom: var(--space-2);
}
.block-head > span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.block-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  padding: var(--space-3) 0;
}
.add-row {
  display: flex;
  gap: var(--space-2);
}
.add-row select {
  height: 28px;
  font-size: var(--text-sm);
  background: var(--color-surface);
  max-width: 200px;
}
.member-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.member-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
}
.member-name {
  flex: 1;
  min-width: 0;
}
.member-status {
  font-size: var(--text-xs);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  color: var(--color-fg-faint);
  background: var(--color-surface-sunken);
}
.member-status.ready {
  color: var(--color-success-fg);
}
.icon-x {
  border: none;
  background: transparent;
  color: var(--color-fg-faint);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
}
.icon-x:hover {
  color: var(--color-danger-fg);
}
.btn-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.result-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.result-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.result-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.result-kind {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-accent-soft-fg);
  background: var(--color-accent-soft);
  padding: 1px 8px;
  border-radius: var(--radius-full);
}
.result-time {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  flex: 1;
}
.result-md {
  margin: 0 0 var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
  background: var(--color-surface-sunken);
  padding: var(--space-2);
  border-radius: var(--radius);
}
.result-refs {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
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
.modal-card {
  width: 420px;
  max-width: 90vw;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  margin-bottom: var(--space-2);
}
.modal-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: var(--space-2);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
</style>
