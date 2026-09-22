<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import {
  createDocumentationSource, deleteDocumentationSource, discoverDocumentationSource,
  documentationProjects, documentationSources, selectDocumentationTools,
  type DocumentationSource,
} from "../api/documentationMcp";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const projects = ref<Array<{ id: number; name: string }>>([]);
const projectId = ref<number | null>(null);
const sources = ref<DocumentationSource[]>([]);
const selected = ref<Record<string, string[]>>({});
const name = ref("Microsoft Learn 技术文档");
const url = ref("https://learn.microsoft.com/api/mcp");
const busy = ref(false);
const error = ref("");
const status = ref("");
let controller = new AbortController();
let generation = 0;

function replace(source: DocumentationSource) {
  const index = sources.value.findIndex(item => item.id === source.id);
  if (index < 0) sources.value.push(source);
  else sources.value.splice(index, 1, source);
  selected.value[source.id] = [...source.tools];
}

async function run(action: (signal: AbortSignal, valid: () => boolean) => Promise<void>) {
  const revision = ++generation;
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  const valid = () => revision === generation && !signal.aborted;
  busy.value = true;
  error.value = "";
  status.value = "";
  try { await action(signal, valid); }
  catch (cause) {
    if (valid()) error.value = cause instanceof Error ? cause.message : "文档服务操作失败，请重试";
  } finally {
    if (valid()) busy.value = false;
  }
}

async function load() {
  sources.value = [];
  selected.value = {};
  const project = projectId.value;
  if (project === null) return;
  await run(async (signal, valid) => {
    const items = await documentationSources(project, signal);
    if (valid()) items.forEach(replace);
  });
}
watch(projectId, load);

async function loadProjects() {
  await run(async (signal, valid) => {
    const items = await documentationProjects(signal);
    if (valid()) {
      projects.value = items;
      projectId.value = items[0]?.id ?? null;
    }
  });
}
onMounted(loadProjects);
onUnmounted(() => { generation += 1; controller.abort(); });

async function create() {
  const project = projectId.value;
  if (project === null || busy.value || !name.value.trim() || !url.value.trim()) return;
  await run(async (signal, valid) => {
    const source = await createDocumentationSource(project, { name: name.value.trim(), url: url.value.trim() }, signal);
    if (valid()) { replace(source); status.value = "已保存。点击“发现工具”连接文档服务。"; }
  });
}

async function discover(source: DocumentationSource) {
  const project = projectId.value;
  if (project === null || busy.value) return;
  await run(async (signal, valid) => {
    const accepted = await notify.confirm({ title: "发现文档工具", confirmLabel: "连接并发现",
      message: `将连接 ${source.url} 获取工具目录。不会发送项目文件或会话内容。`,
      impact: "更新目录后需重新选择并启用工具；检索调用仍逐次审批。" });
    if (!accepted || !valid()) return;
    const result = await discoverDocumentationSource(project, source, signal);
    if (valid()) { replace(result); status.value = "发现完成，请选择文档检索工具后启用。"; }
  });
}

async function select(source: DocumentationSource, enabled: boolean) {
  const project = projectId.value;
  if (project === null || busy.value) return;
  const tools = [...(selected.value[source.id] ?? [])];
  await run(async (signal, valid) => {
    if (enabled && !await notify.confirm({ title: "启用文档检索", confirmLabel: "启用所选工具",
      message: `${source.name}：${tools.join("、")}`,
      impact: "仅当前项目可用。每次调用前会展示目标服务与发送参数供你审批。" })) return;
    if (!valid()) return;
    const result = await selectDocumentationTools(project, source, tools, enabled, signal);
    if (valid()) { replace(result); status.value = enabled ? "已启用，可在项目对话中请求检索技术文档。" : "已停用文档检索。"; }
  });
}

async function remove(source: DocumentationSource) {
  const project = projectId.value;
  if (project === null || busy.value) return;
  await run(async (signal, valid) => {
    if (!await notify.confirm({ title: "移除文档服务", message: source.name, danger: true,
      confirmLabel: "移除", impact: "删除当前项目的连接配置，已有检索记录保留。" }) || !valid()) return;
    await deleteDocumentationSource(project, source, signal);
    if (valid()) { sources.value = sources.value.filter(item => item.id !== source.id); delete selected.value[source.id]; }
  });
}

function expired(source: DocumentationSource) {
  return !source.discovered_at || Date.parse(source.discovered_at) + 86400000 <= Date.now();
}
</script>

<template>
  <div class="docs-mcp" :aria-busy="busy">
    <p class="docs-mcp__intro">为项目接入技术文档搜索和原文读取。仅支持公开 HTTPS MCP 服务，每次检索单独审批，结果保留在任务工具记录中。</p>
    <label class="docs-mcp__field">所属项目
      <select v-model="projectId" class="pa-input" :disabled="busy || !projects.length">
        <option :value="null" disabled>选择项目</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
      </select>
    </label>
    <p v-if="error" class="docs-mcp__error" role="alert">{{ error }}</p>
    <p v-if="status" role="status">{{ status }}</p>
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <div v-if="!projects.length && !busy" class="docs-mcp__empty">
      <p>请先在工作台添加一个项目，再为它配置文档服务。</p>
      <button class="pa-btn pa-btn--subtle" @click="loadProjects">重新加载项目</button>
    </div>
    <template v-if="projectId !== null">
      <form class="docs-mcp__form" @submit.prevent="create">
        <label class="docs-mcp__field">服务名称<input v-model="name" class="pa-input" maxlength="80" required :disabled="busy" /></label>
        <label class="docs-mcp__field">公开 MCP 地址<input v-model="url" class="pa-input" type="url" maxlength="2048" required :disabled="busy" aria-describedby="docs-mcp-url-help" /></label>
        <p id="docs-mcp-url-help">填写公开 HTTPS 文档服务地址，不含密钥或查询参数。预填地址来自 Microsoft Learn 官方文档，可替换为其他公开文档服务。</p>
        <button class="pa-btn pa-btn--primary" :disabled="busy || !name.trim() || !url.trim()">添加文档服务</button>
      </form>
      <button class="pa-btn pa-btn--ghost" :disabled="busy" @click="load">刷新当前项目配置</button>
      <p v-if="!sources.length && !busy">尚未配置文档服务。添加后发现工具，选择搜索或读取能力并启用。</p>
      <article v-for="source in sources" :key="source.id" class="docs-mcp__source">
        <header><strong>{{ source.name }}</strong><span class="pa-badge">{{ source.enabled ? '已启用' : '未启用' }}</span></header>
        <p class="docs-mcp__url">{{ source.url }}</p>
        <p v-if="source.catalog && expired(source)">目录已过期，请重新发现。工具目录有效期为 24 小时。</p>
        <fieldset v-if="source.catalog" :disabled="busy" class="docs-mcp__tools">
          <legend>仅选择文档搜索或读取工具（描述来自外部服务）</legend>
          <label v-for="tool in source.catalog.tools" :key="tool.name">
            <input v-model="selected[source.id]" type="checkbox" :value="tool.name" />
            <span><strong>{{ tool.name }}</strong><small>{{ tool.description || '服务未提供描述' }}</small></span>
          </label>
          <p v-if="!source.catalog.tools.length">服务未返回工具。</p>
        </fieldset>
        <div class="docs-mcp__actions">
          <button class="pa-btn pa-btn--subtle" :disabled="busy" @click="discover(source)">发现工具</button>
          <button class="pa-btn pa-btn--primary" :disabled="busy || expired(source) || !selected[source.id]?.length" @click="select(source, true)">{{ source.enabled ? '保存工具选择' : '启用所选工具' }}</button>
          <button v-if="source.enabled" class="pa-btn pa-btn--subtle" :disabled="busy" @click="select(source, false)">停用</button>
          <button class="pa-btn pa-btn--ghost" :disabled="busy" @click="remove(source)">移除</button>
        </div>
      </article>
    </template>
  </div>
</template>

<style scoped>
.docs-mcp { display: grid; gap: var(--space-4); min-width: 0; }
.docs-mcp p { margin: 0; font-size: var(--text-sm); }
.docs-mcp__intro, .docs-mcp__url, .docs-mcp small, #docs-mcp-url-help { color: var(--color-fg-muted); overflow-wrap: anywhere; }
.docs-mcp__field { display: grid; gap: var(--space-1); font-size: var(--text-sm); }
.docs-mcp__form { display: grid; gap: var(--space-2); padding-block: var(--space-4); border-block: 1px solid var(--color-border); }
.docs-mcp__form button { justify-self: start; }
.docs-mcp__source { display: grid; gap: var(--space-2); padding-block: var(--space-4); border-top: 1px solid var(--color-border); }
.docs-mcp__source header, .docs-mcp__actions { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; }
.docs-mcp__tools { display: grid; gap: var(--space-2); border: 0; padding: 0; margin: 0; min-width: 0; max-height: 320px; overflow: auto; }
.docs-mcp__tools legend { padding-bottom: var(--space-2); font-size: var(--text-sm); }
.docs-mcp__tools label { display: flex; gap: var(--space-2); align-items: baseline; overflow-wrap: anywhere; }
.docs-mcp__tools small { display: block; white-space: pre-wrap; }
.docs-mcp__error { color: var(--color-danger); }
</style>
