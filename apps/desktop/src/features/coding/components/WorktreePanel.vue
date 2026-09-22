<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import type { CodingWorkspaceStore } from "../model/codingWorkspaceStore";
import { applyHandoff, previewHandoff, fetchHandoffs, type HandoffRecord, type HandoffPreview } from "../api/projects";
import { useNotifications } from "../../../stores/notifications";
const props = defineProps<{ store: CodingWorkspaceStore; active: boolean }>();
const preview = ref<HandoffPreview | null>(null), error = ref(""), busy = ref(false);
const result = ref<{ state: string; error?: string; files: { rel_path: string; state: string }[] } | null>(null);
let requestId: string | null = null;
let alive = true;
const history = ref<HandoffRecord[]>([]);
const historyController = new AbortController();
async function loadHistory(event: Event) {
  if (!(event.target as HTMLDetailsElement).open) return;
  const project = props.store.selectedProject.value, thread = props.store.selectedThread.value;
  if (!project || !thread) return;
  try { const data = await fetchHandoffs(project.id, historyController.signal); if (alive) history.value = data.items.filter(item => item.session_id === thread.id).reverse(); }
  catch { if (alive) error.value = "交接记录读取失败，请重新展开重试"; }
}
onBeforeUnmount(() => { alive = false; historyController.abort(); });
async function inspect() {
  const project = props.store.selectedProject.value, workspace = props.store.selectedWorkspace.value;
  if (!project || !workspace || busy.value) return;
  busy.value = true; error.value = "";
  try { preview.value = await previewHandoff(project.id, workspace.id); requestId = crypto.randomUUID(); result.value = null; }
  catch (cause) { error.value = (cause as { message?: string }).message || "交接预览失败"; }
  finally { busy.value = false; }
}
async function apply() {
  const project = props.store.selectedProject.value, thread = props.store.selectedThread.value, selected = preview.value;
  if (!project || !thread || !selected || busy.value || !requestId) return;
  busy.value = true; error.value = "";
  try {
    const confirmed = await useNotifications().confirm({ title: "将改动交接到本地目录？", message: `将应用预览中的 ${selected.changes.length} 项操作，并把此任务后续运行切换到项目根目录。`, impact: "源 worktree 会保留。两端文件变化或本地冲突会阻止操作。", confirmLabel: "应用并切换" });
    if (!confirmed || !alive || props.store.selectedThreadId.value !== thread.id || props.active) return;
    result.value = await applyHandoff(project.id, selected.source_workspace_id, thread.id, selected.version, requestId);
    if (result.value.state === "applied") { await props.store.refresh(); if (alive && props.store.selectedThreadId.value === thread.id) { props.store.selectThread(thread.id); preview.value = null; } }
  } catch (cause) { error.value = (cause as { message?: string }).message || "交接结果未确认，请使用原请求重试"; }
  finally { busy.value = false; }
}
</script>
<template><section class="worktree-panel"><p>{{ store.selectedWorkspace.value?.kind === 'git_worktree' ? '当前任务运行在独立 worktree 中。' : '当前任务使用项目本地目录。新建任务时可选择独立 worktree。' }}</p><button v-if="store.selectedWorkspace.value?.kind === 'git_worktree'" class="pa-btn pa-btn--subtle" :disabled="active || busy" @click="inspect">预览交接到本地</button><details @toggle="loadHistory"><summary>交接记录</summary><p v-if="!history.length">暂无交接记录。</p><article v-for="item in history" :key="item.request_id"><p>{{ new Date(item.created_at).toLocaleString() }} · {{ item.state === 'applied' ? '已完成' : '未完整确认，请核对文件' }}</p><p v-if="item.error">{{ item.error }}</p><p v-for="file in item.files" :key="file.rel_path">{{ file.rel_path }} · {{ file.state === 'applied' ? '已应用' : '落盘结果未确认' }}</p></article></details><p v-if="error" role="alert">{{ error }}</p><template v-if="preview"><p>{{ preview.changes.length }} 项操作 · {{ preview.conflicts.length }} 项冲突</p><p v-for="conflict in preview.conflicts" :key="conflict.rel_path" role="alert">{{ conflict.rel_path }}：{{ conflict.reason }}</p><details v-for="file in preview.changes" :key="file.rel_path"><summary>{{ file.operation }} · {{ file.rel_path }}</summary><pre>{{ file.diff || '目录操作或空文件' }}</pre></details><p>较长差异预览最多显示 16000 字符；应用绑定完整内容版本。</p><button class="pa-btn pa-btn--primary" :disabled="busy || active || !!preview.conflicts.length" @click="apply">确认交接</button></template><div v-if="result" role="status"><p>{{ result.state === 'applied' ? '改动已交接，后续运行使用本地目录' : result.error }}</p><p v-for="file in result.files" :key="file.rel_path">{{ file.rel_path }} · {{ file.state }}</p></div></section></template>
<style scoped>.worktree-panel { display: grid; gap: 10px; font-size: 13px; }p { margin: 0; color: var(--color-fg-muted); }pre { max-height: 300px; overflow: auto; white-space: pre; font-size: 12px; }summary { cursor: pointer; padding: 8px 0; }[role="alert"] { color: var(--color-danger-fg); }</style>
