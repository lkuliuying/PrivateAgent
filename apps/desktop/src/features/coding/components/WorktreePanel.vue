<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { createWorktree, cleanupWorktree } from "../api/recovery";
import { useNotifications } from "../../../stores/notifications";
import type { CodingWorkspaceStore } from "../model/codingWorkspaceStore";

const props = defineProps<{ store: CodingWorkspaceStore }>();
const notify = useNotifications();
const selectedRef = ref("HEAD");
const busy = ref(false);
const error = ref("");
let generation = 0;
let pending: { ref: string; request: string } | null = null;
watch(() => props.store.selectedProjectId.value, () => { generation++; pending = null; busy.value = false; error.value = ""; });
onBeforeUnmount(() => { generation++; });
async function create() {
  const project = props.store.selectedProjectId.value;
  if (!project || busy.value || !selectedRef.value.trim()) return;
  const mine = generation;
  busy.value = true;
  error.value = "";
  try {
    const ref = selectedRef.value.trim();
    const accepted = await notify.confirm({ title: "创建独立工作区", message: `从 ${ref} 对应的提交创建独立 worktree。当前目录的未提交修改会留在原处。`, confirmLabel: "创建 worktree" });
    if (!accepted || mine !== generation) return;
    if (!pending || pending.ref !== ref) pending = { ref, request: crypto.randomUUID() };
    const result = await createWorktree(project, ref, pending.request);
    if (mine !== generation) return;
    pending = null;
    await props.store.refresh();
    if (mine !== generation) return;
    props.store.selectWorkspace(result.id);
    props.store.startNewTask();
  } catch (cause) {
    if (mine === generation) error.value = (cause as { message?: string }).message || "创建未确认完成，请检查工作区列表后重试";
  } finally {
    if (mine === generation) busy.value = false;
  }
}
async function cleanup() {
  const workspace = props.store.selectedWorkspace.value;
  const project = props.store.selectedProjectId.value;
  if (!project || !workspace || workspace.kind !== "git_worktree" || busy.value) return;
  const mine = generation;
  busy.value = true;
  error.value = "";
  try {
    const accepted = await notify.confirm({ title: "清理独立工作区", message: "删除本应用创建的当前 worktree 目录。存在文件修改、未跟踪文件、忽略文件或未结束任务时会拒绝清理。历史任务记录保留。", confirmLabel: "检查并清理" });
    if (!accepted || mine !== generation) return;
    await cleanupWorktree(project, workspace.id);
    if (mine === generation) await props.store.refresh();
  } catch (cause) {
    if (mine === generation) error.value = (cause as { message?: string }).message || "工作区未清理，请核对文件和任务状态";
  } finally {
    if (mine === generation) busy.value = false;
  }
}
</script>

<template>
  <details class="worktree-panel">
    <summary>独立工作区</summary>
    <form @submit.prevent="create">
      <label for="worktree-ref">从提交或已有 ref 创建</label>
      <input id="worktree-ref" v-model="selectedRef" class="pa-input" maxlength="255" :disabled="busy" />
      <button class="pa-btn pa-btn--subtle" :disabled="busy || !selectedRef.trim()">创建并选择 worktree</button>
      <button v-if="store.selectedWorkspace.value?.kind === 'git_worktree'" type="button" class="pa-btn pa-btn--subtle" :disabled="busy" @click="cleanup">清理当前 worktree</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
  </details>
</template>

<style scoped>
.worktree-panel { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border); font-size: var(--pa-text-meta); }
.worktree-panel form { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; padding-top: var(--space-2); }
.worktree-panel input { width: 12rem; max-width: 100%; }
.worktree-panel [role="alert"] { color: var(--color-danger-fg); overflow-wrap: anywhere; }
</style>
