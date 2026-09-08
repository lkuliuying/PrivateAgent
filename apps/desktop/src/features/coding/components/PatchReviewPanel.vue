<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { useNotifications } from "../../../stores/notifications";
import { applyRollback, fetchPatches, patchStatus, previewRollback, type PatchReview, type PatchSummary } from "../api/patches";
import PatchPreview from "./PatchPreview.vue";

const props = defineProps<{ runId: string; revision?: string | number; active: boolean }>();
const notify = useNotifications();
const state = ref<PatchReview | null>(null);
const rollback = ref<PatchSummary | null>(null);
const error = ref("");
const busy = ref(false);
const loading = ref(false);
let epoch = 0;
let request = 0;
let controller: AbortController | undefined;

async function load() {
  controller?.abort();
  controller = new AbortController();
  const mine = ++request;
  loading.value = true;
  try {
    const result = await fetchPatches(props.runId, controller.signal);
    if (mine === request) { state.value = result; error.value = ""; }
  } catch {
    if (mine === request) error.value = "变更记录读取失败，请刷新重试";
  } finally {
    if (mine === request) loading.value = false;
  }
}
watch(() => props.runId, () => {
  epoch++;
  rollback.value = null;
  state.value = null;
  busy.value = false;
  void load();
}, { immediate: true });
watch(() => props.revision, () => { if (!busy.value) void load(); });
onBeforeUnmount(() => { epoch++; request++; controller?.abort(); });

async function preview(patch: PatchSummary) {
  if (busy.value || props.active || !patch.patch_set_id) return;
  const scope = epoch;
  busy.value = true;
  try {
    const result = await previewRollback(props.runId, patch.patch_set_id, crypto.randomUUID());
    if (scope === epoch) rollback.value = result;
  } catch {
    if (scope === epoch) error.value = "回滚预览失败，请检查当前项目授权和文件状态";
  } finally {
    if (scope === epoch) busy.value = false;
  }
}
async function apply() {
  if (busy.value || props.active || !rollback.value?.patch_set_id) return;
  const scope = epoch;
  const runId = props.runId;
  const selected = rollback.value;
  busy.value = true;
  try {
    const accepted = await notify.confirm({ title: "应用回滚预览", message: `将撤销预览中的 ${selected.changes.length} 项操作。存在冲突的文件会保留；执行前将再次核对版本。`, confirmLabel: "应用回滚" });
    if (!accepted || scope !== epoch || props.active) return;
    const result = await applyRollback(runId, selected.patch_set_id!, selected.preview_sha256);
    if (scope !== epoch) return;
    rollback.value = result;
    await load();
    if (scope === epoch && result.status !== "applied") error.value = result.error ?? "回滚未全部完成，请检查日志";
  } catch {
    if (scope === epoch) error.value = "回滚未确认完成，请刷新操作记录后核对";
  } finally {
    if (scope === epoch) busy.value = false;
  }
}
</script>

<template>
  <details class="patch-review">
    <summary>本任务文件变更 · {{ state?.patches.length ?? 0 }} 组补丁</summary>
    <div class="patch-review-body">
      <p v-if="loading" role="status">正在读取变更记录…</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <button class="pa-btn pa-btn--subtle" :disabled="loading || busy" @click="load">刷新变更</button>
      <template v-if="state">
        <p>{{ state.ownership_note }}</p>
        <details>
          <summary>任务开始前已有改动 · {{ state.baseline?.dirty_entries?.length ?? 0 }} 项</summary>
          <p v-if="!state.baseline">未记录起始 Git 状态</p>
          <p v-else-if="!state.baseline.is_git">项目根目录不是 Git 仓库，使用文件摘要保护修改</p>
          <p v-else>{{ state.baseline.current_branch ?? "游离 HEAD" }} · {{ state.baseline.head_sha?.slice(0, 12) ?? "暂无提交" }}</p>
          <ul><li v-for="item in state.baseline?.dirty_entries" :key="item.rel_path">{{ item.status }} · {{ item.rel_path }}</li></ul>
        </details>
        <details><summary>当前 Git 改动（包含外部或未知来源）</summary>
          <ul><li v-for="item in state.current_git.dirty_entries" :key="item.rel_path">{{ item.status }} · {{ item.rel_path }}</li></ul>
          <p v-if="!state.current_git.is_git">当前项目未检测到 Git 仓库</p>
        </details>
        <p v-if="!state.patches.length">本任务尚无补丁记录</p>
        <details v-for="patch in state.patches" :key="patch.patch_set_id ?? patch.preview_sha256">
          <summary>{{ patch.kind === 'rollback' ? '回滚' : '补丁' }} · {{ patchStatus(patch.status) }} · {{ patch.changes.length }} 项</summary>
          <p v-if="patch.error" role="alert">{{ patch.error }}</p>
          <PatchPreview v-if="patch.patch_set_id" :run-id="runId" :patch-id="patch.patch_set_id" :preview-sha="patch.preview_sha256" :changes="patch.changes" />
          <ul><li v-for="(entry, index) in patch.journal" :key="`${entry.change_id}-${index}`">{{ entry.rel_path }} · {{ entry.status === 'applied' ? '已落盘并回读' : '已记录执行意图，结果需核对' }}</li></ul>
          <button v-if="patch.kind === 'patch' && ['applied', 'partially_applied', 'failed', 'interrupted'].includes(patch.status)" class="pa-btn pa-btn--subtle" :disabled="busy || active" @click="preview(patch)">预览回滚</button>
        </details>
        <section v-if="rollback" aria-label="待确认回滚">
          <p><strong>回滚预览 · {{ patchStatus(rollback.status) }}</strong></p>
          <ul><li v-for="conflict in rollback.conflicts" :key="conflict.rel_path">已保留 {{ conflict.rel_path }}：{{ conflict.reason }}</li></ul>
          <PatchPreview v-if="rollback.patch_set_id" :run-id="runId" :patch-id="rollback.patch_set_id" :preview-sha="rollback.preview_sha256" :changes="rollback.changes" />
          <button v-if="rollback.patch_set_id && rollback.status === 'validated'" class="pa-btn pa-btn--danger" :disabled="busy || active" @click="apply">应用此回滚预览</button>
        </section>
      </template>
    </div>
  </details>
</template>

<style scoped>
.patch-review { border-top: 1px solid var(--color-border); font-size: var(--pa-text-meta); min-width: 0; }
.patch-review summary { padding: var(--space-2); cursor: pointer; overflow-wrap: anywhere; }
.patch-review-body { padding: var(--space-3); max-height: 45vh; overflow: auto; overflow-wrap: anywhere; }
.patch-review [role="alert"] { color: var(--color-danger-fg); }
.patch-review ul { padding-left: var(--space-4); }
</style>
