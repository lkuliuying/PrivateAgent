<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { PhArrowClockwise, PhBrain, PhCheck } from "@phosphor-icons/vue";
import {
  createMemory,
  deleteMemory,
  listMemories,
  listMemoryEvents,
  updateMemory,
} from "../api";
import type {
  MemoryEvent,
  MemoryItem,
  MemoryKind,
} from "../types";

const memories = ref<MemoryItem[]>([]);
const selectedId = ref<number | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");

const filterKind = ref<string>("");
const filterStatus = ref<string>("confirmed");
const filterSearch = ref<string>("");

const events = ref<MemoryEvent[]>([]);
const mode = ref<"view" | "edit" | "new">("view");

interface FormState {
  id?: number;
  kind: MemoryKind;
  title: string;
  content_md: string;
  summary: string;
  tags: string;
  sensitive: boolean;
  confidence: string;
}
const form = ref<FormState>({
  kind: "preference",
  title: "",
  content_md: "",
  summary: "",
  tags: "",
  sensitive: false,
  confidence: "",
});

const selected = computed(
  () => memories.value.find((m) => m.id === selectedId.value) || null
);

const KINDS: MemoryKind[] = [
  "preference",
  "learning",
  "project",
  "document",
  "workflow",
  "note",
];
const KIND_LABEL: Record<string, string> = {
  preference: "偏好",
  learning: "学习",
  project: "项目",
  document: "文档",
  workflow: "工作流",
  note: "笔记",
};

async function load() {
  loading.value = true;
  error.value = "";
  try {
    memories.value = await listMemories({
      kind: filterKind.value || undefined,
      status: filterStatus.value || undefined,
      search: filterSearch.value || undefined,
    });
    if (selectedId.value && !memories.value.find((m) => m.id === selectedId.value)) {
      selectedId.value = null;
      mode.value = "view";
      events.value = [];
    }
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function selectMemory(id: number) {
  selectedId.value = id;
  mode.value = "view";
  events.value = [];
  try {
    events.value = await listMemoryEvents(id);
  } catch (e) {
    // 事件流读取失败不影响查看
  }
}

function startNew() {
  mode.value = "new";
  form.value = {
    kind: "preference",
    title: "",
    content_md: "",
    summary: "",
    tags: "",
    sensitive: false,
    confidence: "",
  };
  selectedId.value = null;
  events.value = [];
}

function startEdit(m: MemoryItem) {
  mode.value = "edit";
  form.value = {
    id: m.id,
    kind: m.kind,
    title: m.title,
    content_md: m.content_md,
    summary: m.summary || "",
    tags: (m.tags_json || []).join(", "),
    sensitive: m.sensitive,
    confidence: m.confidence != null ? String(m.confidence) : "",
  };
}

async function saveForm() {
  if (!form.value.title.trim() || !form.value.content_md.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    const tags = form.value.tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    const confidence = form.value.confidence.trim()
      ? Number(form.value.confidence)
      : undefined;
    if (mode.value === "new") {
      const m = await createMemory({
        kind: form.value.kind,
        title: form.value.title.trim(),
        content_md: form.value.content_md,
        summary: form.value.summary.trim() || undefined,
        tags: tags.length ? tags : undefined,
        sensitive: form.value.sensitive,
        confidence,
      });
      await load();
      await selectMemory(m.id);
    } else {
      const id = form.value.id!;
      await updateMemory(id, {
        title: form.value.title.trim(),
        content_md: form.value.content_md,
        summary: form.value.summary.trim(),
        tags,
        sensitive: form.value.sensitive,
        confidence,
      });
      await load();
      await selectMemory(id);
    }
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function toggleEnabled(m: MemoryItem) {
  busy.value = true;
  error.value = "";
  try {
    await updateMemory(m.id, { enabled: !m.enabled });
    await load();
    await selectMemory(m.id);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function confirmDraft(m: MemoryItem) {
  busy.value = true;
  error.value = "";
  try {
    await updateMemory(m.id, { status: "confirmed" });
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function removeMemory(m: MemoryItem) {
  if (!window.confirm(`确定删除记忆「${m.title}」？此操作不可撤销。`)) return;
  busy.value = true;
  error.value = "";
  try {
    await deleteMemory(m.id);
    if (selectedId.value === m.id) {
      selectedId.value = null;
      mode.value = "view";
      events.value = [];
    }
    await load();
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

function statusLabel(s: string): string {
  return ({ draft: "待确认", confirmed: "已确认", archived: "已归档" } as Record<string, string>)[s] || s;
}
function statusClass(s: string): string {
  if (s === "draft") return "warn";
  if (s === "archived") return "muted";
  return "ok";
}
function eventLabel(t: string): string {
  return (
    { created: "创建", used: "使用", edited: "编辑", disabled: "禁用", deleted: "删除" } as Record<string, string>
  )[t] || t;
}
function fmt(s: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

onMounted(load);
</script>

<template>
  <section class="mem-shell">
    <aside class="mem-list">
      <div class="pane-head">
        <div>
          <h1>记忆</h1>
          <p>长期记忆库：偏好、学习、项目经验。</p>
        </div>
        <button class="icon-btn" :disabled="loading" title="刷新" @click="load">
          <PhArrowClockwise :size="16" />
        </button>
      </div>

      <div class="filters">
        <input v-model="filterSearch" class="pa-input" placeholder="搜索标题/内容…" @keydown.enter="load" />
        <select v-model="filterKind" class="pa-input" @change="load">
          <option value="">全部类型</option>
          <option v-for="k in KINDS" :key="k" :value="k">{{ KIND_LABEL[k] }}</option>
        </select>
        <select v-model="filterStatus" class="pa-input" @change="load">
          <option value="confirmed">已确认</option>
          <option value="draft">待确认（候选）</option>
          <option value="archived">已归档</option>
          <option value="">全部</option>
        </select>
        <button class="pa-btn pa-btn--primary" @click="startNew">
          <PhBrain :size="15" />
          <span>新建记忆</span>
        </button>
      </div>

      <div v-if="error" class="error-line">{{ error }}</div>

      <button
        v-for="m in memories"
        :key="m.id"
        class="mem-row"
        :class="{ active: selected?.id === m.id, disabled: !m.enabled }"
        @click="selectMemory(m.id)"
      >
        <span class="mem-title">{{ m.title }}</span>
        <span class="mem-meta">
          <span class="status-dot" :class="statusClass(m.status)" />
          {{ KIND_LABEL[m.kind] }} · {{ statusLabel(m.status) }}
          <span v-if="!m.enabled"> · 已禁用</span>
          <span v-if="m.sensitive"> · 敏感</span>
        </span>
      </button>
      <div v-if="!loading && memories.length === 0" class="empty-list">暂无记忆</div>
    </aside>

    <main class="mem-main">
      <!-- 编辑 / 新建表单 -->
      <div v-if="mode === 'new' || mode === 'edit'" class="editor">
        <h2>{{ mode === "new" ? "新建记忆" : "编辑记忆" }}</h2>
        <div class="form-grid">
          <label class="field">
            <span>类型</span>
            <select v-model="form.kind" class="pa-input">
              <option v-for="k in KINDS" :key="k" :value="k">{{ KIND_LABEL[k] }}</option>
            </select>
          </label>
          <label class="field">
            <span>标题</span>
            <input v-model="form.title" class="pa-input" placeholder="简短标题" />
          </label>
          <label class="field field--full">
            <span>内容（Markdown）</span>
            <textarea v-model="form.content_md" class="pa-input" rows="8" placeholder="详细内容…"></textarea>
          </label>
          <label class="field field--full">
            <span>摘要（可选）</span>
            <input v-model="form.summary" class="pa-input" placeholder="一句话摘要" />
          </label>
          <label class="field field--full">
            <span>标签（逗号分隔）</span>
            <input v-model="form.tags" class="pa-input" placeholder="os, 类比, 进程" />
          </label>
          <label class="field">
            <span>把握度（0-1，可选）</span>
            <input v-model="form.confidence" class="pa-input" placeholder="0.8" />
          </label>
          <label class="field field--full checkbox">
            <input type="checkbox" v-model="form.sensitive" />
            <span>敏感记忆（不自动进入聊天 prompt）</span>
          </label>
        </div>
        <div class="form-actions">
          <button class="pa-btn pa-btn--primary" :disabled="busy" @click="saveForm">
            <PhCheck :size="15" />
            <span>保存</span>
          </button>
          <button class="pa-btn pa-btn--subtle" :disabled="busy" @click="mode = 'view'">
            取消
          </button>
        </div>
      </div>

      <!-- 详情视图 -->
      <template v-else-if="selected">
        <div class="detail-head">
          <div class="detail-title">
            <h2>{{ selected.title }}</h2>
            <p>
              {{ KIND_LABEL[selected.kind] }} · {{ statusLabel(selected.status) }}
              <span v-if="!selected.enabled"> · 已禁用</span>
              <span v-if="selected.sensitive"> · 敏感</span>
              <span v-if="selected.confidence != null"> · 把握 {{ selected.confidence }}</span>
            </p>
          </div>
          <div class="head-actions">
            <button
              v-if="selected.status === 'draft'"
              class="pa-btn pa-btn--primary pa-btn--sm"
              :disabled="busy"
              @click="confirmDraft(selected)"
            >
              <PhCheck :size="14" />
              <span>确认沉淀</span>
            </button>
            <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="startEdit(selected)">
              编辑
            </button>
            <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="toggleEnabled(selected)">
              {{ selected.enabled ? "禁用" : "启用" }}
            </button>
            <button class="pa-btn pa-btn--danger pa-btn--sm" :disabled="busy" @click="removeMemory(selected)">
              删除
            </button>
          </div>
        </div>

        <section v-if="selected.summary" class="block">
          <h3>摘要</h3>
          <p class="summary-text">{{ selected.summary }}</p>
        </section>

        <section class="block">
          <h3>内容</h3>
          <pre>{{ selected.content_md }}</pre>
        </section>

        <section v-if="selected.tags_json && selected.tags_json.length" class="block">
          <h3>标签</h3>
          <div class="tags">
            <span v-for="t in selected.tags_json" :key="t" class="tag">{{ t }}</span>
          </div>
        </section>

        <section class="block">
          <h3>事件流</h3>
          <div v-if="events.length === 0" class="hint">暂无事件记录。</div>
          <ul v-else class="events">
            <li v-for="ev in events" :key="ev.id">
              <span class="ev-type" :class="statusClass(ev.event_type === 'used' ? 'confirmed' : ev.event_type === 'disabled' ? 'draft' : 'ok')">
                {{ eventLabel(ev.event_type) }}
              </span>
              <span class="ev-time">{{ fmt(ev.created_at) }}</span>
              <span v-if="ev.ref_type" class="ev-ref">{{ ev.ref_type }}{{ ev.ref_id != null ? ` #${ev.ref_id}` : "" }}</span>
            </li>
          </ul>
        </section>
      </template>

      <!-- 空状态 -->
      <div v-else class="empty">
        <PhBrain :size="44" weight="duotone" />
        <p>选择左侧记忆查看详情，或新建一条记忆</p>
      </div>
    </main>
  </section>
</template>

<style scoped>
.mem-shell {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  min-height: 0;
  flex: 1;
}
.mem-list {
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
  overflow: auto;
  padding: var(--space-4);
}
.pane-head,
.detail-head,
.head-actions {
  display: flex;
  align-items: center;
}
.pane-head {
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
h1,
h2,
h3,
p {
  margin: 0;
}
h1 {
  font-size: var(--text-xl);
}
h2 {
  font-size: var(--text-2xl);
}
h3 {
  font-size: var(--text-lg);
  margin-bottom: var(--space-2);
}
.pane-head p,
.detail-title p,
.hint,
.mem-meta {
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
.filters {
  display: grid;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.error-line {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius);
  padding: var(--space-2);
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
}
.mem-row {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  display: grid;
  gap: 4px;
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  text-align: left;
  cursor: pointer;
}
.mem-row.active,
.mem-row:hover {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}
.mem-row.disabled {
  opacity: 0.55;
}
.mem-title {
  font-weight: var(--font-medium);
}
.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-fg-faint);
  vertical-align: middle;
  margin-right: 4px;
}
.status-dot.ok {
  background: var(--color-success-fg);
}
.status-dot.warn {
  background: var(--color-warning-fg);
}
.status-dot.muted {
  background: var(--color-fg-faint);
}
.empty-list {
  text-align: center;
  color: var(--color-fg-faint);
  padding: 40px 0;
  font-size: var(--text-sm);
}
.mem-main {
  overflow: auto;
  padding: 28px 32px;
}
.detail-head {
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.head-actions {
  gap: var(--space-2);
  flex-wrap: wrap;
}
.block {
  margin-bottom: var(--space-5);
}
.summary-text {
  color: var(--color-fg-muted);
  font-size: var(--text-base);
}
pre {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.tag {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 2px 8px;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
}
.events {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: var(--space-2);
}
.events li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-sm);
}
.ev-type {
  font-weight: var(--font-medium);
  min-width: 48px;
}
.ev-type.ok {
  color: var(--color-success-fg);
}
.ev-type.warn {
  color: var(--color-warning-fg);
}
.ev-type.muted {
  color: var(--color-fg-faint);
}
.ev-time {
  color: var(--color-fg-faint);
}
.ev-ref {
  color: var(--color-fg-faint);
}
.empty {
  min-height: 420px;
  display: grid;
  place-items: center;
  color: var(--color-fg-faint);
  text-align: center;
  gap: var(--space-3);
}
.editor h2 {
  margin-bottom: var(--space-4);
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}
.field {
  display: grid;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
}
.field--full {
  grid-column: 1 / -1;
}
.field--full textarea {
  resize: vertical;
  min-height: 160px;
  font-family: var(--font-mono);
}
.checkbox {
  flex-direction: row;
  align-items: center;
  gap: var(--space-2);
}
.checkbox input {
  margin: 0;
}
.form-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

@media (max-width: 900px) {
  .mem-shell {
    grid-template-columns: 1fr;
  }
  .mem-list {
    border-right: 0;
    border-bottom: 1px solid var(--color-border);
    max-height: 420px;
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
