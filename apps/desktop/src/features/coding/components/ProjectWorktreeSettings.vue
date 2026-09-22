<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { createIsolatedWorkspace, fetchCodingBranches } from "../api/projects";
import type { CodingBranchState } from "../model/contracts";

const props = defineProps<{ projectId: number; disabled?: boolean }>();
const emit = defineEmits<{ created: [workspaceId: number]; "busy-change": [busy: boolean] }>();
const branches = ref<CodingBranchState | null>(null);
const branch = ref("");
const loading = ref(false);
const creating = ref(false);
const error = ref("");
let requestId: string | null = null;
let generation = 0;
let alive = true;

async function load(): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  error.value = "";
  branches.value = null;
  branch.value = "";
  requestId = null;
  try {
    const result = await fetchCodingBranches(props.projectId);
    if (!alive || mine !== generation) return;
    branches.value = result;
    branch.value = result.currentBranch ?? result.branches[0]?.name ?? "";
  } catch (cause) {
    if (alive && mine === generation) error.value = (cause as { message?: string })?.message || "分支读取失败，请重试";
  } finally {
    if (alive && mine === generation) loading.value = false;
  }
}

async function create(): Promise<void> {
  if (props.disabled || loading.value || creating.value || !branches.value?.isGit || !branch.value) return;
  creating.value = true;
  emit("busy-change", true);
  error.value = "";
  try {
    // 失败后重试复用请求标识，防止回执丢失时重复创建目录。
    requestId ??= crypto.randomUUID();
    const workspace = await createIsolatedWorkspace(props.projectId, branch.value, requestId);
    if (alive) emit("created", workspace.id);
  } catch (cause) {
    if (alive) error.value = (cause as { message?: string })?.message || "worktree 创建失败，请重试";
  } finally {
    if (alive) { creating.value = false; emit("busy-change", false); }
  }
}

watch(() => props.projectId, load, { immediate: true });
onBeforeUnmount(() => { alive = false; generation++; });
</script>

<template>
  <section class="project-worktree" aria-label="独立 worktree">
    <strong>独立 worktree</strong>
    <p>从所选分支的提交创建独立工作目录，创建后可用于新会话。未提交的修改保留在原目录。</p>
    <p v-if="loading" role="status">正在读取分支…</p>
    <p v-else-if="branches && !branches.isGit">当前项目不是 Git 仓库，无法创建 worktree。</p>
    <template v-else-if="branches?.isGit">
      <label>起始分支<select v-model="branch" class="pa-input" :disabled="disabled || creating" @change="requestId = null"><option v-for="item in branches.branches" :key="item.name" :value="item.name">{{ item.name }}</option></select></label>
      <p v-if="!branches.branches.length">仓库尚无本地分支，请先完成首次提交。</p>
      <button type="button" class="pa-btn pa-btn--subtle" :disabled="disabled || creating || !branch" data-testid="project-create-worktree" @click="create">{{ creating ? "创建中…" : "创建独立 worktree" }}</button>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error && !branches" type="button" class="pa-btn pa-btn--ghost" :disabled="disabled || loading" @click="load">重新读取分支</button>
  </section>
</template>

<style scoped>
.project-worktree { display: grid; gap: var(--space-2); padding-block: var(--space-3); border-top: 1px solid var(--color-border); }
.project-worktree p { margin: 0; font-size: var(--text-sm); color: var(--color-fg-muted); line-height: 1.6; }
.project-worktree label { display: grid; gap: var(--space-2); }
.project-worktree [role="alert"] { color: var(--color-danger-fg); }
</style>
