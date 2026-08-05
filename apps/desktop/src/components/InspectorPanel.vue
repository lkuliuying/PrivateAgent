<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch, type Component } from "vue";
import {
  PhArrowClockwise,
  PhArrowsClockwise,
  PhClock,
  PhFile,
  PhFileArrowUp,
  PhFiles,
  PhFileText,
  PhFolderOpen,
  PhFolderSimple,
  PhGearSix,
  PhMagnifyingGlass,
  PhPackage,
  PhPlus,
  PhPushPinSimple,
  PhStack,
  PhTerminalWindow,
  PhX,
} from "@phosphor-icons/vue";
import type {
  Activity,
  ChunkDetail,
  ScanResponse,
  Session,
  SummarizeResult,
  TrustedPath,
} from "../types";
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

const props = defineProps<{
  session: Session | null;
  messageCount: number;
  chunkId: number | null;
  previewTrusted?: TrustedPath[];
  previewActivities?: Activity[];
}>();
const emit = defineEmits<{ close: [] }>();

type InspectorTab = "files" | "context" | "artifacts";
const activeTab = ref<InspectorTab>("files");
const pathInput = ref("");
const fileQuery = ref("");
const kind = ref<"file" | "directory">("file");
const trusted = ref<TrustedPath[]>([]);
const authMsg = ref("");
const summaryResult = ref<SummarizeResult | null>(null);
const scanResult = ref<ScanResponse | null>(null);
const fileActionLoading = ref("");
const fileActionError = ref("");
let msgTimer: number | null = null;

const filteredTrusted = computed(() => {
  const query = fileQuery.value.trim().toLocaleLowerCase();
  if (!query) return trusted.value;
  return trusted.value.filter((item) =>
    item.path.toLocaleLowerCase().includes(query)
  );
});

async function loadTrusted() {
  if (props.previewTrusted) {
    trusted.value = props.previewTrusted;
    return;
  }
  try {
    trusted.value = await listTrustedPaths();
  } catch {
    trusted.value = [];
  }
}

function flash(message: string) {
  authMsg.value = message;
  if (msgTimer) window.clearTimeout(msgTimer);
  msgTimer = window.setTimeout(() => (authMsg.value = ""), 2500);
}

async function authorize() {
  const path = pathInput.value.trim();
  if (!path) return;
  authMsg.value = "";
  try {
    await authorizeFile(path, kind.value);
    pathInput.value = "";
    await loadTrusted();
    flash("路径已授权");
  } catch (error) {
    flash(`授权失败：${String(error)}`);
  }
}

async function pickPath() {
  try {
    const selected =
      kind.value === "directory" ? await pickDirectory() : await pickFile();
    if (!selected) {
      flash("未选择路径；浏览器开发模式可手动输入");
      return;
    }
    pathInput.value = selected;
    await authorize();
  } catch (error) {
    flash(`选择器不可用：${String(error)}`);
  }
}

async function summarizeTrusted(path: string) {
  fileActionLoading.value = `summary:${path}`;
  fileActionError.value = "";
  scanResult.value = null;
  try {
    summaryResult.value = await summarizeFile(path);
  } catch (error) {
    summaryResult.value = null;
    fileActionError.value = String(error);
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
  } catch (error) {
    scanResult.value = null;
    fileActionError.value = String(error);
  } finally {
    fileActionLoading.value = "";
  }
}

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
      activeTab.value = "context";
    } catch (error) {
      chunkDetail.value = null;
      chunkError.value = String(error);
    } finally {
      chunkLoading.value = false;
    }
  },
  { immediate: true }
);

const activities = ref<Activity[]>([]);
const expandedActivity = ref<number | null>(null);
let activityTimer: ReturnType<typeof setInterval> | undefined;

async function loadActivities() {
  if (props.previewActivities) {
    activities.value = props.previewActivities;
    return;
  }
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
  void loadTrusted();
  void loadActivities();
  activityTimer = setInterval(loadActivities, 5000);
});
onUnmounted(() => {
  if (activityTimer) clearInterval(activityTimer);
  if (msgTimer) window.clearTimeout(msgTimer);
});

const artifacts = computed(() =>
  activities.value.filter(
    (activity) => activity.status === "succeeded" && Boolean(activity.detail_json)
  )
);

function toggleActivity(id: number) {
  expandedActivity.value = expandedActivity.value === id ? null : id;
}

const ACT_STATUS_TEXT: Record<string, string> = {
  pending: "等待中",
  waiting_approval: "待审批",
  running: "执行中",
  succeeded: "完成",
  failed: "失败",
  cancelled: "已取消",
};
const ACT_STATUS_CLASS: Record<string, string> = {
  succeeded: "ok",
  failed: "bad",
  running: "info",
  pending: "warn",
  waiting_approval: "warn",
  cancelled: "muted",
};
const ACTIVITY_ICONS: Record<string, Component> = {
  tool: PhTerminalWindow,
  document_import: PhFileArrowUp,
  reindex: PhArrowsClockwise,
  system: PhGearSix,
  ocr: PhFileText,
};

function fmt(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getMonth() + 1}/${date.getDate()} ${date
    .getHours()
    .toString()
    .padStart(2, "0")}:${date.getMinutes().toString().padStart(2, "0")}`;
}
</script>

<template>
  <aside class="inspector" aria-label="任务上下文">
    <div class="insp-head">
      <div class="insp-tabs" role="tablist" aria-label="上下文类型">
        <button
          :class="{ active: activeTab === 'files' }"
          role="tab"
          :aria-selected="activeTab === 'files'"
          @click="activeTab = 'files'"
        >
          Files
        </button>
        <button
          :class="{ active: activeTab === 'context' }"
          role="tab"
          :aria-selected="activeTab === 'context'"
          @click="activeTab = 'context'"
        >
          Context
        </button>
        <button
          :class="{ active: activeTab === 'artifacts' }"
          role="tab"
          :aria-selected="activeTab === 'artifacts'"
          @click="activeTab = 'artifacts'"
        >
          Artifacts
        </button>
      </div>
      <button class="close-btn" aria-label="关闭上下文面板" title="关闭" @click="emit('close')">
        <PhX :size="17" />
      </button>
    </div>

    <div v-if="activeTab === 'files'" class="insp-body" role="tabpanel">
      <div class="file-toolbar">
        <div class="file-search">
          <PhMagnifyingGlass :size="15" />
          <input v-model="fileQuery" placeholder="筛选已授权路径…" aria-label="筛选已授权路径" />
        </div>
        <button title="刷新文件" aria-label="刷新文件" :disabled="Boolean(fileActionLoading)" @click="loadTrusted">
          <PhArrowClockwise :size="16" />
        </button>
      </div>

      <section class="insp-section">
        <div class="section-label">
          <PhFiles :size="14" />
          <span>任务文件</span>
        </div>
        <div v-if="filteredTrusted.length" class="trusted-list">
          <div v-for="item in filteredTrusted" :key="item.id" class="trusted-item">
            <component :is="item.kind === 'directory' ? PhFolderOpen : PhFile" :size="16" class="trusted-icon" />
            <div class="trusted-info">
              <div class="trusted-path" :title="item.path">{{ item.path }}</div>
              <div class="trusted-meta">{{ item.kind === "directory" ? "目录" : "文件" }} · {{ fmt(item.granted_at) }}</div>
            </div>
            <button
              class="trusted-action"
              :disabled="Boolean(fileActionLoading)"
              @click="item.kind === 'directory' ? scanTrusted(item.path) : summarizeTrusted(item.path)"
            >
              {{ item.kind === "directory" ? "扫描" : "摘要" }}
            </button>
          </div>
        </div>
        <div v-else class="empty-panel">
          <PhFolderSimple :size="24" />
          <span>{{ fileQuery ? "没有匹配的路径" : "尚未授权任务文件" }}</span>
        </div>
      </section>

      <section class="insp-section">
        <div class="section-label">
          <PhPlus :size="14" />
          <span>添加路径</span>
        </div>
        <div class="auth-card">
          <input
            v-model="pathInput"
            class="pa-input auth-input"
            placeholder="输入文件或目录绝对路径"
            @keydown.enter="authorize"
          />
          <div class="auth-row">
            <label><input v-model="kind" type="radio" value="file" /> 文件</label>
            <label><input v-model="kind" type="radio" value="directory" /> 目录</label>
            <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="pickPath">选择…</button>
            <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="!pathInput.trim()" @click="authorize">
              授权
            </button>
          </div>
          <p v-if="authMsg" class="auth-msg">{{ authMsg }}</p>
        </div>
      </section>

      <div v-if="fileActionError" class="file-result file-result--error">{{ fileActionError }}</div>
      <div v-if="summaryResult" class="file-result">
        <div class="file-result-head">
          <strong :title="summaryResult.name">{{ summaryResult.name }}</strong>
          <span>{{ Math.ceil(summaryResult.size_bytes / 1024) }} KB</span>
        </div>
        <div class="file-summary">{{ summaryResult.summary }}</div>
      </div>
      <div v-if="scanResult" class="file-result">
        <div class="file-result-head">
          <strong>{{ scanResult.count }} 个文件</strong>
          <span v-if="scanResult.truncated">已截断</span>
        </div>
        <div class="scan-list">
          <div v-for="file in scanResult.files.slice(0, 12)" :key="file.path" class="scan-row">
            <span :title="file.path">{{ file.name }}</span>
            <small>{{ Math.ceil(file.size_bytes / 1024) }} KB</small>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="activeTab === 'context'" class="insp-body" role="tabpanel">
      <section class="insp-section">
        <div class="section-label">
          <PhPushPinSimple :size="14" />
          <span>当前任务</span>
        </div>
        <div v-if="props.session" class="ctx-card">
          <strong :title="props.session.title">{{ props.session.title }}</strong>
          <dl>
            <div><dt>消息</dt><dd>{{ props.messageCount }}</dd></div>
            <div><dt>更新</dt><dd>{{ fmt(props.session.updated_at) }}</dd></div>
            <div><dt>处理方式</dt><dd>本地优先</dd></div>
          </dl>
        </div>
        <div v-else class="empty-panel">
          <PhStack :size="24" />
          <span>选择或新建任务后显示上下文</span>
        </div>
      </section>

      <section class="insp-section">
        <div class="section-label">
          <PhFileText :size="14" />
          <span>引用片段</span>
        </div>
        <div v-if="chunkLoading" class="empty-panel">正在载入引用…</div>
        <div v-else-if="chunkError" class="file-result file-result--error">{{ chunkError }}</div>
        <div v-else-if="chunkDetail" class="chunk-card">
          <div class="chunk-head">
            <span>片段 #{{ chunkDetail.ordinal }}</span>
            <span>doc {{ chunkDetail.doc_id }}</span>
          </div>
          <div class="chunk-content">{{ chunkDetail.content }}</div>
        </div>
        <div v-else class="empty-panel">
          <PhFileText :size="24" />
          <span>点击活动流中的引用查看原文</span>
        </div>
      </section>

      <section class="insp-section">
        <div class="section-label">
          <PhClock :size="14" />
          <span>会话活动</span>
        </div>
        <div v-if="activities.length === 0" class="empty-panel">暂无活动记录</div>
        <div v-else class="act-list">
          <div
            v-for="activity in activities"
            :key="activity.id"
            class="act-item"
            :class="{ expanded: expandedActivity === activity.id }"
          >
            <button class="act-row" @click="toggleActivity(activity.id)">
              <component :is="ACTIVITY_ICONS[activity.kind] || PhClock" :size="15" />
              <span class="act-title" :title="activity.title">{{ activity.title }}</span>
              <span class="act-status" :class="ACT_STATUS_CLASS[activity.status]">
                {{ ACT_STATUS_TEXT[activity.status] || activity.status }}
              </span>
            </button>
            <div v-if="expandedActivity === activity.id" class="act-detail">
              <span>{{ fmt(activity.started_at || activity.created_at) }}</span>
              <pre v-if="activity.detail_json">{{ JSON.stringify(activity.detail_json, null, 2) }}</pre>
              <p v-if="activity.error_message">{{ activity.error_message }}</p>
            </div>
          </div>
        </div>
      </section>
    </div>

    <div v-else class="insp-body" role="tabpanel">
      <section class="insp-section">
        <div class="section-label">
          <PhPackage :size="14" />
          <span>生成产物</span>
        </div>
        <div v-if="artifacts.length" class="artifact-list">
          <article v-for="artifact in artifacts" :key="artifact.id" class="artifact-card">
            <div class="artifact-icon">
              <component :is="ACTIVITY_ICONS[artifact.kind] || PhPackage" :size="20" />
            </div>
            <div>
              <strong :title="artifact.title">{{ artifact.title }}</strong>
              <span>{{ fmt(artifact.finished_at || artifact.updated_at) }}</span>
            </div>
            <button aria-label="查看产物详情" title="查看详情" @click="activeTab = 'context'; toggleActivity(artifact.id)">
              查看
            </button>
          </article>
        </div>
        <div v-else class="empty-panel empty-panel--large">
          <PhPackage :size="28" />
          <strong>暂无生成产物</strong>
          <span>工具执行完成后，包含输出的文档、代码和报告会显示在这里。</span>
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.inspector { display: flex; height: 100%; min-height: 0; flex-direction: column; background: var(--color-panel); }
.insp-head { display: flex; height: var(--topbar-h); flex-shrink: 0; align-items: center; gap: var(--space-2); padding: 0 var(--space-3); border-bottom: 1px solid var(--color-border); background: var(--color-surface); }
.insp-tabs { display: flex; height: 100%; flex: 1; align-items: stretch; gap: var(--space-1); }
.insp-tabs button { position: relative; min-width: 0; flex: 1; padding: 0 var(--space-1); border: none; background: transparent; color: var(--color-fg-subtle); font-size: var(--text-xs); font-weight: var(--font-medium); cursor: pointer; }
.insp-tabs button::after { content: ""; position: absolute; right: var(--space-2); bottom: 0; left: var(--space-2); height: 2px; border-radius: var(--radius-full); background: transparent; }
.insp-tabs button:hover { color: var(--color-fg); }
.insp-tabs button.active { color: var(--color-fg); }
.insp-tabs button.active::after { background: var(--color-accent); }
.insp-tabs button:focus-visible, .close-btn:focus-visible, .file-toolbar button:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.close-btn, .file-toolbar > button { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; border: none; border-radius: var(--radius); background: transparent; color: var(--color-fg-faint); cursor: pointer; }
.close-btn:hover, .file-toolbar > button:hover:not(:disabled) { background: var(--color-surface-sunken); color: var(--color-fg); }
.insp-body { display: flex; flex: 1; min-height: 0; flex-direction: column; gap: var(--space-4); padding: var(--space-3); overflow: auto; overscroll-behavior: contain; }
.file-toolbar { display: flex; align-items: center; gap: var(--space-2); }
.file-search { display: flex; min-width: 0; height: 34px; flex: 1; align-items: center; gap: var(--space-2); padding: 0 var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-fg-faint); }
.file-search:focus-within { border-color: var(--color-accent); box-shadow: 0 0 0 3px var(--color-accent-soft); }
.file-search input { min-width: 0; flex: 1; border: none; outline: none; background: transparent; color: var(--color-fg); font-size: var(--text-xs); }
.insp-section { display: flex; flex-direction: column; gap: var(--space-2); }
.section-label { display: flex; align-items: center; gap: var(--space-2); color: var(--color-fg-faint); font-size: 10px; font-weight: var(--font-semibold); letter-spacing: .08em; text-transform: uppercase; }
.trusted-list, .act-list, .artifact-list { display: flex; flex-direction: column; gap: var(--space-2); }
.trusted-item { display: flex; min-width: 0; align-items: center; gap: var(--space-2); padding: var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.trusted-icon { flex-shrink: 0; color: var(--color-accent-soft-fg); }
.trusted-info { min-width: 0; flex: 1; }
.trusted-path { overflow: hidden; color: var(--color-fg); font-family: var(--font-mono); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.trusted-meta { margin-top: 2px; color: var(--color-fg-faint); font-size: 9px; }
.trusted-action { padding: 3px var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface-sunken); color: var(--color-accent-soft-fg); font-size: 10px; cursor: pointer; }
.trusted-action:hover:not(:disabled) { border-color: var(--color-accent); }
.trusted-action:disabled { cursor: wait; opacity: .6; }
.empty-panel { display: flex; min-height: 96px; align-items: center; justify-content: center; flex-direction: column; gap: var(--space-2); padding: var(--space-4); border: 1px dashed var(--color-border-strong); border-radius: var(--radius-md); color: var(--color-fg-faint); font-size: var(--text-xs); text-align: center; }
.empty-panel--large { min-height: 260px; }
.empty-panel strong { color: var(--color-fg-muted); font-size: var(--text-sm); }
.auth-card { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.auth-input { height: 32px; font-family: var(--font-mono); font-size: 10px; }
.auth-row { display: flex; align-items: center; gap: var(--space-2); }
.auth-row label { display: inline-flex; align-items: center; gap: 3px; color: var(--color-fg-subtle); font-size: 10px; cursor: pointer; }
.auth-row .pa-btn--subtle { margin-left: auto; }
.auth-msg { margin: 0; color: var(--color-accent-soft-fg); font-size: 10px; }
.file-result { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-fg-muted); font-size: var(--text-xs); }
.file-result--error { border-color: color-mix(in srgb, var(--color-danger) 24%, var(--color-border)); background: var(--color-danger-soft); color: var(--color-danger-fg); }
.file-result-head { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-2); }
.file-result-head strong { overflow: hidden; color: var(--color-fg); text-overflow: ellipsis; white-space: nowrap; }
.file-summary, .chunk-content { max-height: 240px; overflow: auto; color: var(--color-fg); line-height: var(--leading-normal); white-space: pre-wrap; word-break: break-word; }
.scan-list { display: flex; flex-direction: column; gap: var(--space-1); }
.scan-row { display: flex; min-width: 0; justify-content: space-between; gap: var(--space-2); }
.scan-row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ctx-card, .chunk-card { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.ctx-card > strong { display: block; overflow: hidden; color: var(--color-fg); font-size: var(--text-sm); text-overflow: ellipsis; white-space: nowrap; }
.ctx-card dl { display: flex; margin: var(--space-3) 0 0; flex-direction: column; gap: var(--space-1); }
.ctx-card dl > div { display: flex; justify-content: space-between; font-size: var(--text-xs); }
.ctx-card dt { color: var(--color-fg-faint); }
.ctx-card dd { margin: 0; color: var(--color-fg-muted); }
.chunk-head { display: flex; justify-content: space-between; margin-bottom: var(--space-2); color: var(--color-fg-faint); font-size: 10px; }
.act-item { overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.act-row { display: flex; width: 100%; min-width: 0; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border: none; background: transparent; text-align: left; cursor: pointer; }
.act-row:hover { background: var(--color-surface-sunken); }
.act-title { overflow: hidden; flex: 1; color: var(--color-fg); font-size: var(--text-xs); text-overflow: ellipsis; white-space: nowrap; }
.act-status { font-size: 10px; font-weight: var(--font-medium); }
.act-status.ok { color: var(--color-success-fg); }
.act-status.bad { color: var(--color-danger-fg); }
.act-status.info { color: var(--color-accent-soft-fg); }
.act-status.warn { color: var(--color-warning-fg); }
.act-status.muted { color: var(--color-fg-faint); }
.act-detail { padding: var(--space-2) var(--space-3); border-top: 1px solid var(--color-border); background: var(--color-surface-sunken); color: var(--color-fg-faint); font-size: 10px; }
.act-detail pre { max-height: 180px; margin: var(--space-2) 0 0; overflow: auto; color: var(--color-fg-muted); font-family: var(--font-mono); white-space: pre-wrap; word-break: break-word; }
.act-detail p { color: var(--color-danger-fg); }
.artifact-card { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.artifact-icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: var(--radius-md); background: var(--color-accent-soft); color: var(--color-accent); }
.artifact-card > div:nth-child(2) { display: flex; min-width: 0; flex-direction: column; }
.artifact-card strong { overflow: hidden; color: var(--color-fg); font-size: var(--text-xs); text-overflow: ellipsis; white-space: nowrap; }
.artifact-card span { margin-top: 2px; color: var(--color-fg-faint); font-size: 9px; }
.artifact-card button { border: none; background: transparent; color: var(--color-accent-soft-fg); font-size: 10px; cursor: pointer; }
@media (prefers-reduced-motion: reduce) {
  .insp-tabs button, .act-row { transition: none; }
}
</style>
