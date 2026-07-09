<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from "vue";
import {
  PhPushPinSimple,
  PhFolderSimple,
  PhPlus,
  PhFileText,
  PhClock,
} from "@phosphor-icons/vue";
import type { Activity, ChunkDetail, Session, TrustedPath } from "../types";
import {
  authorizeFile,
  getChunk,
  listActivities,
  listTrustedPaths,
  pickDirectory,
  pickFile,
  scanDirectory,
  summarizeFile,
} from "../api";
import type { ScanResponse, SummarizeResult } from "../types";

/**
 * 右侧检查器面板。
 * 当前会话上下文 + 引用片段详情（M3）+ 文件授权（文本输入 + Tauri 选择器）
 * + 当前会话活动（M4，可展开输入/输出摘要）。
 */
const props = defineProps<{
  session: Session | null;
  messageCount: number;
  chunkId: number | null;
}>();

// ---- 文件授权 ----
const pathInput = ref("");
const kind = ref<"file" | "directory">("file");
const trusted = ref<TrustedPath[]>([]);
const authMsg = ref("");
const summaryResult = ref<SummarizeResult | null>(null);
const scanResult = ref<ScanResponse | null>(null);
const fileActionLoading = ref("");
const fileActionError = ref("");
let msgTimer: number | null = null;

async function loadTrusted() {
  try {
    trusted.value = await listTrustedPaths();
  } catch {
    trusted.value = [];
  }
}

async function authorize() {
  const p = pathInput.value.trim();
  if (!p) return;
  authMsg.value = "";
  try {
    await authorizeFile(p, kind.value);
    pathInput.value = "";
    await loadTrusted();
    flash("已授权");
  } catch (e) {
    flash("授权失败：" + String(e));
  }
}

async function summarizeTrusted(path: string) {
  fileActionLoading.value = `summary:${path}`;
  fileActionError.value = "";
  scanResult.value = null;
  try {
    summaryResult.value = await summarizeFile(path);
  } catch (e) {
    summaryResult.value = null;
    fileActionError.value = String(e);
  } finally {
    fileActionLoading.value = "";
  }
}

async function scanTrusted(path: string) {
  fileActionLoading.value = `scan:${path}`;
  fileActionError.value = "";
  summaryResult.value = null;
  try {
    scanResult.value = await scanDirectory(path);
  } catch (e) {
    scanResult.value = null;
    fileActionError.value = String(e);
  } finally {
    fileActionLoading.value = "";
  }
}

function flash(msg: string) {
  authMsg.value = msg;
  if (msgTimer) window.clearTimeout(msgTimer);
  msgTimer = window.setTimeout(() => (authMsg.value = ""), 2500);
}

async function pickPath() {
  // Tauri 打包模式用原生选择器；浏览器开发模式或取消选择时保留手动输入。
  try {
    const selected = kind.value === "directory" ? await pickDirectory() : await pickFile();
    if (!selected) {
      flash("未选择路径；浏览器开发模式请手动输入");
      return;
    }
    pathInput.value = selected;
    await authorize();
  } catch (e) {
    flash("选择器不可用：" + String(e));
  }
}

// ---- 引用片段详情（M3）----
const chunkDetail = ref<ChunkDetail | null>(null);
const chunkLoading = ref(false);
const chunkError = ref("");

watch(
  () => props.chunkId,
  async (id) => {
    if (id == null) {
      chunkDetail.value = null;
      chunkError.value = "";
      return;
    }
    chunkLoading.value = true;
    chunkError.value = "";
    try {
      chunkDetail.value = await getChunk(id);
    } catch (e) {
      chunkDetail.value = null;
      chunkError.value = String(e);
    } finally {
      chunkLoading.value = false;
    }
  },
  { immediate: true }
);

// ---- 当前会话活动（M4）----
const activities = ref<Activity[]>([]);
const expandedActivity = ref<number | null>(null);
let activityTimer: ReturnType<typeof setInterval> | undefined;

async function loadActivities() {
  if (!props.session) {
    activities.value = [];
    return;
  }
  try {
    activities.value = await listActivities(props.session.id);
  } catch {
    activities.value = [];
  }
}

watch(() => props.session?.id, loadActivities, { immediate: true });

onMounted(() => {
  loadTrusted();
  loadActivities();
  activityTimer = setInterval(loadActivities, 5000);
});
onUnmounted(() => {
  if (activityTimer) clearInterval(activityTimer);
  if (msgTimer) window.clearTimeout(msgTimer);
});

function toggleActivity(id: number) {
  expandedActivity.value = expandedActivity.value === id ? null : id;
}

const ACT_STATUS_TEXT: Record<string, string> = {
  pending: "等待中",
  waiting_approval: "待审批",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
};
const ACT_STATUS_CLASS: Record<string, string> = {
  succeeded: "ok",
  failed: "bad",
  running: "warn",
  pending: "warn",
  waiting_approval: "warn",
  cancelled: "muted",
};

function fmt(s: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  return `${d.getMonth() + 1}/${d.getDate()} ${d
    .getHours()
    .toString()
    .padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

function activityIcon(kind: string): string {
  return (
    ({ tool: "🔧", document_import: "📥", reindex: "🔄", system: "⚙" } as Record<
      string,
      string
    >)[kind] || "•"
  );
}
</script>

<template>
  <aside class="inspector" aria-label="检查器面板">
    <div class="insp-head">
      <span class="insp-title">检查器</span>
    </div>

    <div class="insp-body">
      <!-- 当前会话上下文 -->
      <section class="insp-section">
        <div class="section-label">
          <PhPushPinSimple :size="13" weight="regular" />
          <span>当前会话</span>
        </div>
        <div v-if="props.session" class="ctx-card">
          <div class="ctx-title pa-ellipsis" :title="props.session.title">
            {{ props.session.title }}
          </div>
          <dl class="ctx-meta">
            <div class="meta-row">
              <dt>消息</dt>
              <dd>{{ props.messageCount }}</dd>
            </div>
            <div class="meta-row">
              <dt>更新</dt>
              <dd>{{ fmt(props.session.updated_at) }}</dd>
            </div>
          </dl>
        </div>
        <div v-else class="ctx-empty">未选择会话</div>
      </section>

      <!-- 引用片段详情（M3）-->
      <section class="insp-section">
        <div class="section-label">
          <PhFileText :size="13" weight="regular" />
          <span>引用片段</span>
        </div>
        <div v-if="chunkLoading" class="chunk-empty">加载中…</div>
        <div v-else-if="chunkError" class="chunk-empty">加载失败：{{ chunkError }}</div>
        <div v-else-if="chunkDetail" class="chunk-card">
          <div class="chunk-head">
            <span>片段 #{{ chunkDetail.ordinal }}</span>
            <span class="chunk-meta">doc_id {{ chunkDetail.doc_id }}</span>
          </div>
          <div class="chunk-content">{{ chunkDetail.content }}</div>
        </div>
        <div v-else class="chunk-empty">点击对话中的来源引用查看片段原文</div>
      </section>

      <!-- 文件授权（M2 文本式，待替换为 Tauri 选择器）-->
      <section class="insp-section">
        <div class="section-label">
          <PhFolderSimple :size="13" weight="regular" />
          <span>文件授权</span>
        </div>
        <div class="auth-card">
          <input
            v-model="pathInput"
            class="pa-input auth-input"
            placeholder="输入文件/目录绝对路径"
            @keydown.enter="authorize"
          />
          <div class="auth-row">
            <label class="kind-toggle">
              <input type="radio" value="file" v-model="kind" />
              <span>文件</span>
            </label>
            <label class="kind-toggle">
              <input type="radio" value="directory" v-model="kind" />
              <span>目录</span>
            </label>
            <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="pickPath">
              <span>选择…</span>
            </button>
            <button
              class="pa-btn pa-btn--primary pa-btn--sm auth-btn"
              :disabled="!pathInput.trim()"
              @click="authorize"
            >
              <PhPlus :size="14" weight="bold" />
              <span>授权</span>
            </button>
          </div>
          <p v-if="authMsg" class="auth-msg">{{ authMsg }}</p>
        </div>
        <div v-if="trusted.length" class="trusted-list">
          <div v-for="t in trusted" :key="t.id" class="trusted-item">
            <PhFolderSimple :size="12" weight="regular" class="trusted-icon" />
            <div class="trusted-info">
              <div class="trusted-path pa-ellipsis" :title="t.path">{{ t.path }}</div>
              <div class="trusted-meta">
                {{ t.kind === "directory" ? "目录" : "文件" }} · {{ fmt(t.granted_at) }}
              </div>
            </div>
            <button
              v-if="t.kind === 'file'"
              class="trusted-action"
              :disabled="fileActionLoading === `summary:${t.path}`"
              @click="summarizeTrusted(t.path)"
            >
              {{ fileActionLoading === `summary:${t.path}` ? "处理中" : "摘要" }}
            </button>
            <button
              v-else
              class="trusted-action"
              :disabled="fileActionLoading === `scan:${t.path}`"
              @click="scanTrusted(t.path)"
            >
              {{ fileActionLoading === `scan:${t.path}` ? "扫描中" : "扫描" }}
            </button>
          </div>
        </div>
        <div v-else class="trusted-empty">尚未授权任何路径</div>

        <div v-if="fileActionError" class="file-result file-result--error">
          {{ fileActionError }}
        </div>
        <div v-if="summaryResult" class="file-result">
          <div class="file-result-head">
            <span class="pa-ellipsis" :title="summaryResult.name">{{ summaryResult.name }}</span>
            <span>{{ Math.ceil(summaryResult.size_bytes / 1024) }} KB</span>
          </div>
          <div class="file-summary">{{ summaryResult.summary }}</div>
        </div>
        <div v-if="scanResult" class="file-result">
          <div class="file-result-head">
            <span>{{ scanResult.count }} 个可处理文件</span>
            <span v-if="scanResult.truncated">已截断</span>
          </div>
          <div class="scan-list">
            <div v-for="f in scanResult.files.slice(0, 12)" :key="f.path" class="scan-row">
              <span class="pa-ellipsis" :title="f.path">{{ f.name }}</span>
              <span>{{ Math.ceil(f.size_bytes / 1024) }} KB</span>
            </div>
            <div v-if="scanResult.files.length > 12" class="scan-more">
              还有 {{ scanResult.files.length - 12 }} 个文件
            </div>
          </div>
        </div>
      </section>

      <!-- 当前会话活动（M4）-->
      <section class="insp-section">
        <div class="section-label">
          <PhClock :size="13" weight="regular" />
          <span>会话活动</span>
        </div>
        <div v-if="activities.length === 0" class="act-empty">暂无活动</div>
        <div v-else class="act-list">
          <div
            v-for="a in activities"
            :key="a.id"
            class="act-item"
            :class="{ expanded: expandedActivity === a.id }"
          >
            <div class="act-row" @click="toggleActivity(a.id)">
              <span class="act-icon">{{ activityIcon(a.kind) }}</span>
              <span class="act-title pa-ellipsis" :title="a.title">{{ a.title }}</span>
              <span class="act-status" :class="ACT_STATUS_CLASS[a.status]">
                {{ ACT_STATUS_TEXT[a.status] || a.status }}
              </span>
            </div>
            <div v-if="expandedActivity === a.id" class="act-detail">
              <div class="act-time">
                {{ fmt(a.started_at || a.created_at) }}
                <span v-if="a.finished_at"> → {{ fmt(a.finished_at) }}</span>
              </div>
              <div v-if="a.detail_json" class="act-io">
                <pre>{{ JSON.stringify(a.detail_json, null, 2) }}</pre>
              </div>
              <div v-if="a.error_message" class="act-err">{{ a.error_message }}</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.insp-head {
  flex-shrink: 0;
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--color-border);
}
.insp-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-fg-muted);
  letter-spacing: 0.04em;
}

.insp-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.insp-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.section-label {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--color-fg-faint);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.ctx-card {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-3);
}
.ctx-title {
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  color: var(--color-fg);
  margin-bottom: var(--space-2);
}
.ctx-meta {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--text-xs);
}
.meta-row dt {
  color: var(--color-fg-faint);
  margin: 0;
}
.meta-row dd {
  color: var(--color-fg-muted);
  margin: 0;
  font-variant-numeric: tabular-nums;
}
.ctx-empty {
  font-size: var(--text-sm);
  color: var(--color-fg-faint);
  padding: var(--space-2) 0;
}

/* 引用片段 */
.chunk-empty {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  padding: var(--space-2) 0;
}
.chunk-card {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
}
.chunk-head {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  margin-bottom: var(--space-1);
}
.chunk-meta {
  color: var(--color-fg-faint);
}
.chunk-content {
  font-size: var(--text-sm);
  color: var(--color-fg);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}

/* 文件授权 */
.auth-card {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.auth-input {
  height: 28px;
  font-size: var(--text-xs);
  font-family: var(--font-mono);
}
.auth-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.kind-toggle {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  cursor: pointer;
  user-select: none;
}
.kind-toggle input {
  margin: 0;
}
.auth-btn {
  margin-left: auto;
}
.auth-msg {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-accent-soft-fg);
}

.trusted-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.trusted-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
}
.trusted-icon {
  color: var(--color-fg-faint);
  margin-top: 2px;
  flex-shrink: 0;
}
.trusted-info {
  min-width: 0;
  flex: 1;
}
.trusted-action {
  flex-shrink: 0;
  border: 1px solid var(--color-border);
  background: var(--color-surface-sunken);
  color: var(--color-accent-soft-fg);
  border-radius: var(--radius);
  padding: 3px var(--space-2);
  font-size: var(--text-xs);
  line-height: 1.2;
  cursor: pointer;
}
.trusted-action:hover:not(:disabled) {
  background: var(--color-accent-soft);
}
.trusted-action:disabled {
  color: var(--color-fg-faint);
  cursor: wait;
}
.trusted-path {
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--color-fg);
}
.trusted-meta {
  font-size: 10px;
  color: var(--color-fg-faint);
  margin-top: 1px;
}
.trusted-empty {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  padding: var(--space-2) 0;
  text-align: center;
}
.file-result {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.file-result--error {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
}
.file-result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}
.file-summary {
  color: var(--color-fg);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow: auto;
}
.scan-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.scan-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}
.scan-more {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  padding-top: var(--space-1);
}

/* 会话活动 */
.act-empty {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  padding: var(--space-2) 0;
}
.act-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.act-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  overflow: hidden;
}
.act-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  cursor: pointer;
  font-size: var(--text-xs);
}
.act-row:hover {
  background: var(--color-surface-sunken);
}
.act-icon {
  flex-shrink: 0;
}
.act-title {
  flex: 1;
  color: var(--color-fg);
}
.act-status {
  flex-shrink: 0;
  font-weight: var(--font-medium);
}
.act-status.ok {
  color: var(--color-success-fg);
}
.act-status.bad {
  color: var(--color-danger-fg);
}
.act-status.warn {
  color: var(--color-warning-fg);
}
.act-status.muted {
  color: var(--color-fg-faint);
}
.act-detail {
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-sunken);
  font-size: var(--text-xs);
}
.act-time {
  color: var(--color-fg-faint);
  margin-bottom: var(--space-1);
}
.act-io {
  margin: var(--space-1) 0 0;
}
.act-io pre {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 160px;
  overflow: auto;
}
.act-err {
  margin-top: var(--space-1);
  color: var(--color-danger-fg);
}
</style>
