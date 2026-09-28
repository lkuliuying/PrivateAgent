<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { PhFolder, PhFileText, PhX, PhArrowClockwise, PhCaretRight, PhMagnifyingGlass } from "@phosphor-icons/vue";
import { listWorkspaceFiles, readWorkspaceFile, type WorkspaceFile, type FilePage } from "../api/workspaceFiles";
import { resolveWorkspaceFileTarget, type WorkspaceFileOpenRequest } from "../model/outputFiles";

const props = defineProps<{ projectId: number; workspaceId: number; projectName: string; openRequest?: WorkspaceFileOpenRequest | null }>();
const emit = defineEmits<{ close: [] }>();
const pane = ref<HTMLElement>();
const path = ref(".");
const query = ref("");
const entries = ref<WorkspaceFile[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(false);
const error = ref("");
type Tab = { path: string; page: FilePage | null; error: string; loading: boolean; line?: number };
const tabs = ref<Tab[]>([]);
const selected = ref("");
const current = computed(() => tabs.value.find(tab => tab.path === selected.value));
const currentLine = computed(() => {
  const tab = current.value;
  if (!tab?.page || !tab.line) return null;
  const content = tab.page.content;
  let start = 0;
  // 最多渲染前文、目标行与后文，避免短行文件生成数十万个 DOM 节点。
  for (let line = 1; line < tab.line; line += 1) {
    const newline = content.indexOf("\n", start);
    if (newline === -1) return null;
    start = newline + 1;
  }
  const newline = content.indexOf("\n", start);
  const end = newline === -1 ? content.length : newline + 1;
  return { before: content.slice(0, start), text: content.slice(start, end), after: content.slice(end) };
});
const lineMessage = computed(() => {
  const tab = current.value;
  if (!tab?.line || !tab.page || currentLine.value) return "";
  return tab.page.next_offset === null ? `文件中没有第 ${tab.line} 行` : `第 ${tab.line} 行尚未加载，请继续读取`;
});
const visible = computed(() => entries.value.filter(file => file.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())));
const crumbs = computed(() => path.value === "." ? [] : path.value.split("/").map((name, index, parts) => ({ name, path: parts.slice(0, index + 1).join("/") })));
let sequence = 0;
let scope = 0;
let listing: AbortController | undefined;
const reads = new Map<string, AbortController>();

function dispose() {
  scope++;
  sequence++;
  listing?.abort();
  for (const request of reads.values()) request.abort();
  reads.clear();
}
async function directory(next = ".", more = false) {
  const mine = ++sequence;
  listing?.abort();
  listing = new AbortController();
  loading.value = true;
  error.value = "";
  if (!more) { path.value = next; entries.value = []; cursor.value = null; query.value = ""; }
  try {
    const page = await listWorkspaceFiles(props.projectId, props.workspaceId, next, more ? cursor.value : null, listing.signal);
    if (mine !== sequence) return;
    entries.value = more ? [...entries.value, ...page.entries] : page.entries;
    cursor.value = page.next_cursor;
  } catch (cause) {
    if (mine === sequence) error.value = (cause as { message?: string }).message || "目录读取失败，请刷新重试";
  } finally { if (mine === sequence) loading.value = false; }
}
async function file(target: string, more = false, line?: number) {
  let tab = tabs.value.find(item => item.path === target);
  if (!tab) {
    // 标签数量有界；只回收最早的预览页，不写入或修改磁盘。
    if (tabs.value.length >= 12) closeTab(tabs.value[0].path);
    tabs.value.push({ path: target, page: null, error: "", loading: false });
    tab = tabs.value[tabs.value.length - 1];
  }
  if (line !== undefined) tab.line = line;
  selected.value = target;
  if (tab.loading || (!more && tab.page)) return;
  const mine = scope;
  const request = new AbortController();
  reads.set(target, request);
  tab.loading = true;
  tab.error = "";
  try {
    const page = await readWorkspaceFile(props.projectId, props.workspaceId, target, more ? tab.page?.next_offset ?? 0 : 0, more ? tab.page?.sha256 ?? null : null, request.signal);
    if (mine !== scope || request.signal.aborted) return;
    tab.page = { ...page, content: (more ? tab.page?.content ?? "" : "") + page.content };
  } catch (cause) {
    if (mine === scope && !request.signal.aborted) tab.error = (cause as { message?: string }).message || "文件无法预览，请刷新重试";
  } finally { if (mine === scope && !request.signal.aborted) { tab.loading = false; reads.delete(target); } }
}
function refreshFile() {
  if (!current.value || current.value.loading) return;
  current.value.page = null;
  void file(current.value.path);
}
function closeTab(target: string) {
  reads.get(target)?.abort();
  reads.delete(target);
  const index = tabs.value.findIndex(item => item.path === target);
  tabs.value = tabs.value.filter(item => item.path !== target);
  if (selected.value === target) selected.value = tabs.value[Math.min(index, tabs.value.length - 1)]?.path ?? "";
}
watch(() => [props.projectId, props.workspaceId], () => { dispose(); tabs.value = []; selected.value = ""; void directory(); }, { immediate: true });
watch(() => props.openRequest, () => {
  const target = props.openRequest ? resolveWorkspaceFileTarget(props.openRequest) : null;
  if (target) void file(target.path, false, target.line);
}, { immediate: true });
watch(() => [selected.value, current.value?.line, current.value?.page?.content, props.openRequest?.requestId], async () => {
  const mine = scope;
  await nextTick();
  if (mine !== scope) return;
  pane.value?.querySelector(".code-line--target")?.scrollIntoView?.({ block: "center" });
});
onBeforeUnmount(dispose);
onMounted(() => pane.value?.focus());
</script>

<template>
  <aside ref="pane" tabindex="-1" class="file-workspace" data-testid="file-workspace" aria-label="文件工作区" @keydown.esc="emit('close')">
    <header class="workspace-head"><strong>文件工作区</strong><span>{{ projectName }}</span><button class="icon" title="刷新目录" aria-label="刷新目录" :disabled="loading" @click="directory(path)"><PhArrowClockwise :size="16" /></button><button class="icon" aria-label="关闭文件工作区" @click="emit('close')"><PhX :size="17" /></button></header>
    <div class="file-tabs" role="tablist" aria-label="打开的文件">
      <span v-if="!tabs.length" class="tab-empty">浏览并预览项目文件</span>
      <div v-for="tab in tabs" :key="tab.path" class="file-tab" :class="{ active: selected === tab.path }">
        <button role="tab" :aria-selected="selected === tab.path" :title="tab.path" @click="selected = tab.path"><PhFileText :size="14" />{{ tab.path.split('/').pop() }}</button><button :aria-label="`关闭 ${tab.path}`" @click="closeTab(tab.path)"><PhX :size="12" /></button>
      </div>
    </div>
    <div class="file-layout">
      <div class="explorer">
        <nav class="breadcrumbs" aria-label="文件夹路径"><button @click="directory()">{{ projectName }}</button><template v-for="crumb in crumbs" :key="crumb.path"><PhCaretRight :size="11" /><button @click="directory(crumb.path)">{{ crumb.name }}</button></template></nav>
        <label class="filter"><PhMagnifyingGlass :size="15" /><input v-model="query" placeholder="筛选当前目录" aria-label="筛选当前目录" /></label>
        <div class="file-list" aria-label="项目文件">
          <button v-if="path !== '.'" class="file-row parent-row" @click="directory(path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '.')">返回上一级</button>
          <button v-for="entry in visible" :key="entry.rel_path" class="file-row" :class="{ selected: selected === entry.rel_path }" :title="entry.rel_path" @click="entry.kind === 'directory' ? directory(entry.rel_path) : file(entry.rel_path)"><component :is="entry.kind === 'directory' ? PhFolder : PhFileText" :size="16" /><span>{{ entry.name }}</span><PhCaretRight v-if="entry.kind === 'directory'" :size="12" /></button>
          <p v-if="loading" role="status">正在读取…</p><p v-else-if="error" role="alert">{{ error }}<button class="pa-btn pa-btn--subtle" @click="directory(path)">重试</button></p><p v-else-if="!visible.length">{{ query ? "没有匹配的文件" : "目录为空" }}</p>
          <button v-if="cursor && !loading" class="more" @click="directory(path, true)">加载更多文件</button>
        </div>
      </div>
      <section class="file-preview" aria-label="文件预览">
        <template v-if="current">
          <header><code :title="current.path">{{ current.path }}{{ current.line ? `:${current.line}` : '' }}</code><button class="icon" aria-label="刷新文件" :disabled="current.loading" @click="refreshFile"><PhArrowClockwise :size="15" /></button></header>
          <p v-if="current.loading" class="preview-message" role="status">正在读取文件…</p>
          <p v-if="current.error" class="preview-message" role="alert">{{ current.error }}</p>
          <p v-if="lineMessage" class="preview-message" role="status">{{ lineMessage }}</p>
          <div v-if="current.page" class="code-scroll"><pre v-if="current.page.content"><code><template v-if="currentLine">{{ currentLine.before }}<mark class="code-line--target" aria-current="location" :aria-label="`第 ${current.line} 行`">{{ currentLine.text }}</mark>{{ currentLine.after }}</template><template v-else>{{ current.page.content }}</template></code></pre><p v-else class="preview-message">空文件</p><button v-if="current.page.next_offset !== null" class="more" :disabled="current.loading" @click="file(current.path, true)">继续读取（{{ current.page.content.length.toLocaleString() }} / {{ current.page.total_chars.toLocaleString() }} 字符）</button></div>
        </template>
        <div v-else class="preview-empty"><PhFileText :size="32" /><strong>选择文件开始预览</strong><span>支持 UTF-8 文本、代码与 Markdown</span></div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.file-workspace { display: flex; flex-direction: column; flex: 0 0 48%; min-width: 350px; min-height: 0; border-left: 1px solid var(--color-border); background: var(--color-surface); z-index: 20; }
.workspace-head { display: flex; align-items: center; gap: 10px; padding: 10px 12px; font-size: 13px; border-bottom: 1px solid var(--color-border); }
.workspace-head > span { color: var(--color-fg-muted); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.icon { display: inline-flex; justify-content: center; align-items: center; flex-shrink: 0; width: 28px; height: 28px; border: 0; background: transparent; color: var(--color-fg-muted); border-radius: 6px; cursor: pointer; }
.icon:hover, .file-row:hover { background: var(--color-surface-sunken); }
button:focus-visible, input:focus-visible { outline: var(--focus-ring); outline-offset: -2px; }
.file-tabs { display: flex; min-height: 39px; overflow-x: auto; border-bottom: 1px solid var(--color-border); flex-shrink: 0; }
.tab-empty { padding: 11px 14px; font-size: 12px; color: var(--color-fg-muted); }
.file-tab { display: flex; flex-shrink: 0; border-right: 1px solid var(--color-border); border-bottom: 2px solid transparent; }
.file-tab.active { border-bottom-color: var(--color-fg); background: var(--color-surface-sunken); }
.file-tab button { display: flex; gap: 7px; align-items: center; padding: 8px; border: 0; background: transparent; color: var(--color-fg); cursor: pointer; font-size: 12px; }
.file-layout { display: flex; flex: 1; min-height: 0; overflow: hidden; }
.explorer { display: flex; flex: 0 0 36%; min-width: 135px; flex-direction: column; min-height: 0; border-right: 1px solid var(--color-border); background: var(--color-panel); }
.breadcrumbs { display: flex; flex-wrap: wrap; gap: 3px; align-items: center; padding: 9px; font-size: 11px; border-bottom: 1px solid var(--color-border); }
.breadcrumbs button { max-width: 100%; overflow-wrap: anywhere; padding: 2px; border: 0; background: transparent; color: var(--color-fg-muted); cursor: pointer; text-align: left; }
.filter { display: flex; gap: 5px; align-items: center; margin: 10px 8px; color: var(--color-fg-muted); }
.filter input { width: 100%; min-width: 0; border: 0; background: transparent; color: var(--color-fg); font-size: 12px; padding: 4px 0; }
.file-list { overflow: auto; flex: 1; padding: 0 5px 10px; }
.file-list p { font-size: 12px; color: var(--color-fg-muted); padding: 8px; overflow-wrap: anywhere; }
.file-row { display: flex; align-items: center; width: 100%; gap: 7px; padding: 8px; border: 0; border-radius: 5px; background: transparent; color: var(--color-fg); cursor: pointer; font-size: 12px; text-align: left; }
.file-row > span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-row > svg { flex-shrink: 0; }.file-row.selected { background: var(--color-surface-sunken); }.parent-row { color: var(--color-fg-muted); font-size: 11px; }
.file-preview { display: flex; flex: 1; min-width: 0; min-height: 0; flex-direction: column; }
.file-preview > header { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-bottom: 1px solid var(--color-border); }
.file-preview > header code { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--color-fg-muted); }
.code-scroll { flex: 1; overflow: auto; min-height: 0; }.code-scroll pre { margin: 0; padding: 18px; tab-size: 4; font-size: 12px; line-height: 1.8; font-family: var(--font-mono, monospace); }
.code-line--target { background: var(--color-accent-subtle, var(--color-surface-sunken)); color: inherit; outline: 1px solid var(--color-accent); }
.preview-message { margin: 0; padding: 18px; font-size: 12px; overflow-wrap: anywhere; }
.preview-empty { margin: auto; padding: 20px; display: flex; align-items: center; flex-direction: column; gap: 14px; color: var(--color-fg-muted); text-align: center; font-size: 12px; }
.preview-empty strong { font-size: 14px; font-weight: 500; color: var(--color-fg); }
.more { margin: 10px; padding: 7px 10px; border: 1px solid var(--color-border); border-radius: 6px; color: var(--color-fg); background: var(--color-surface); cursor: pointer; font-size: 12px; }
@media (max-width: 1000px) { .file-workspace { position: absolute; inset: 0; min-width: 0; border-left: 0; } }
</style>
