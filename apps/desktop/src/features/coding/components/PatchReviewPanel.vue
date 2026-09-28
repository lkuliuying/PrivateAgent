<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { PhArrowCounterClockwise, PhCaretDown, PhFiles } from "@phosphor-icons/vue";
import { useNotifications } from "../../../stores/notifications";
import { applyRollback, fetchPatches, patchStatus, previewRollback, type PatchReview, type PatchSummary } from "../api/patches";
import PatchPreview from "./PatchPreview.vue";
import { summarizeEditedFiles } from "../model/patchSummary";

const props = defineProps<{ runId: string; revision?: string | number; active: boolean; presentation?: "inspector" | "result" }>();
const notify = useNotifications();
const emit = defineEmits<{ feedback: [message: string] }>();
const state = ref<PatchReview | null>(null);
const changedFiles = computed(() => [...new Set(state.value?.patches.flatMap(patch => patch.changes.map(change => change.rel_path)) ?? [])]);
const editedFiles = computed(() => summarizeEditedFiles(state.value?.patches ?? []));
const filesExpanded = ref(false);
const reviewOpen = ref(false);
const shownFiles = computed(() => filesExpanded.value ? editedFiles.value : editedFiles.value.slice(0, 3));
const lineStats = computed(() => {
  if (!editedFiles.value.length || editedFiles.value.some(file => file.additions === null || file.deletions === null)) return null;
  return editedFiles.value.reduce((total, file) => ({ additions: total.additions + file.additions!, deletions: total.deletions + file.deletions! }), { additions: 0, deletions: 0 });
});
const undoable = computed(() => state.value?.patches.filter(patch => patch.kind === "patch" && patch.patch_set_id
  && ["applied", "partially_applied", "failed", "interrupted"].includes(patch.status)
  && patch.journal.some(entry => entry.status === "applied")) ?? []);
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
  filesExpanded.value = false;
  reviewOpen.value = false;
  void load();
}, { immediate: true });
watch(() => props.revision, () => { if (!busy.value) void load(); });
onBeforeUnmount(() => { epoch++; request++; controller?.abort(); });

async function showUndo() {
  reviewOpen.value = true;
  if (undoable.value.length === 1) await preview(undoable.value[0]);
}

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
  <section v-if="presentation !== 'result' || loading || error || editedFiles.length || reviewOpen" :class="{ 'result-files': presentation === 'result' }" :data-testid="presentation === 'result' ? 'result-patch-card' : undefined">
    <template v-if="presentation === 'result'">
      <header v-if="editedFiles.length" class="result-files-head">
        <span class="result-files-icon"><PhFiles :size="24" aria-hidden="true" /></span>
        <div class="result-files-heading">
          <strong>已编辑 {{ editedFiles.length }} 个文件</strong>
          <span v-if="lineStats" class="result-files-stats" title="本任务已落盘操作的累计增删行数">
            <span class="stat-add">+{{ lineStats.additions }}</span> <span class="stat-del">-{{ lineStats.deletions }}</span>
          </span>
        </div>
        <div class="result-files-actions">
          <button v-if="undoable.length" type="button" class="pa-btn pa-btn--ghost" :disabled="busy || active" aria-label="撤销本任务文件修改，先查看预览" @click="showUndo">撤销 <PhArrowCounterClockwise :size="15" aria-hidden="true" /></button>
          <button type="button" class="pa-btn pa-btn--subtle" :aria-expanded="reviewOpen" @click="reviewOpen = !reviewOpen">审核</button>
        </div>
      </header>
      <p v-if="loading && !state" class="result-files-notice" role="status">正在读取文件变更…</p>
      <p v-if="error && !reviewOpen" class="result-files-notice" role="alert">{{ error }} <button class="pa-btn pa-btn--ghost" :disabled="loading || busy" @click="load">重试</button></p>
      <ul v-if="editedFiles.length" class="result-files-list">
        <li v-for="file in shownFiles" :key="file.path" data-testid="result-file-row">
          <button type="button" class="result-file-path" :title="file.path" :aria-label="`审核文件 ${file.path}`" @click="reviewOpen = true">{{ file.path }}</button>
          <span v-if="file.additions !== null && file.deletions !== null" class="result-files-stats">
            <span class="stat-add">+{{ file.additions }}</span> <span class="stat-del">-{{ file.deletions }}</span>
          </span>
        </li>
      </ul>
      <button v-if="editedFiles.length > 3" type="button" class="result-files-more" :aria-expanded="filesExpanded" @click="filesExpanded = !filesExpanded">
        {{ filesExpanded ? '收起文件列表' : `再显示 ${editedFiles.length - 3} 个文件` }}
        <PhCaretDown :size="15" :class="{ expanded: filesExpanded }" aria-hidden="true" />
      </button>
    </template>
  <details class="patch-review" :class="{ 'result-review': presentation === 'result' }" :open="reviewOpen" @toggle="reviewOpen = ($event.target as HTMLDetailsElement).open">
    <summary>
      <strong>本任务文件变更</strong> · {{ changedFiles.length }} 个文件 · {{ state?.patches.length ?? 0 }} 组补丁
      <span v-if="changedFiles.length" class="patch-files">
        <span v-for="path in changedFiles.slice(0, 3)" :key="path">{{ path }}</span>
        <span v-if="changedFiles.length > 3">展开查看其余 {{ changedFiles.length - 3 }} 个文件</span>
      </span>
      <span v-if="error" role="alert"> · {{ error }}</span>
    </summary>
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
          <PatchPreview @feedback="emit('feedback', $event)" v-if="patch.patch_set_id" :run-id="runId" :patch-id="patch.patch_set_id" :preview-sha="patch.preview_sha256" :changes="patch.changes" />
          <ul><li v-for="(entry, index) in patch.journal" :key="`${entry.change_id}-${index}`">{{ entry.rel_path }} · {{ entry.status === 'applied' ? '已落盘并回读' : '已记录执行意图，结果需核对' }}</li></ul>
          <button v-if="patch.kind === 'patch' && ['applied', 'partially_applied', 'failed', 'interrupted'].includes(patch.status)" class="pa-btn pa-btn--subtle" :disabled="busy || active" @click="preview(patch)">预览回滚</button>
        </details>
        <section v-if="rollback" aria-label="待确认回滚">
          <p><strong>回滚预览 · {{ patchStatus(rollback.status) }}</strong></p>
          <ul><li v-for="conflict in rollback.conflicts" :key="conflict.rel_path">已保留 {{ conflict.rel_path }}：{{ conflict.reason }}</li></ul>
          <PatchPreview @feedback="emit('feedback', $event)" v-if="rollback.patch_set_id" :run-id="runId" :patch-id="rollback.patch_set_id" :preview-sha="rollback.preview_sha256" :changes="rollback.changes" />
          <button v-if="rollback.patch_set_id && rollback.status === 'validated'" class="pa-btn pa-btn--danger" :disabled="busy || active" @click="apply">应用此回滚预览</button>
        </section>
      </template>
    </div>
  </details>
  </section>
</template>

<style scoped>
.patch-review { border: 1px solid var(--color-border); border-radius: var(--radius-lg); font-size: var(--pa-text-meta); min-width: 0; }
.patch-review > summary { padding: var(--space-3); }
.patch-files { display: grid; gap: var(--space-2); margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--color-border); color: var(--color-fg-muted); }
.patch-review summary { padding: var(--space-2); cursor: pointer; overflow-wrap: anywhere; }
.patch-review-body { padding: var(--space-3); max-height: 45vh; overflow: auto; overflow-wrap: anywhere; }
.patch-review [role="alert"] { color: var(--color-danger-fg); }
.patch-review ul { padding-left: var(--space-4); }
.result-files { margin-top: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-lg); overflow: hidden; color: var(--color-fg); }
.result-files-head { display: flex; align-items: center; gap: var(--space-3); min-width: 0; padding: var(--space-4); }
.result-files-icon { display: inline-flex; flex: 0 0 48px; height: 48px; align-items: center; justify-content: center; border-radius: var(--radius-md); background: var(--color-surface-muted); color: var(--color-fg-muted); }
.result-files-heading { display: grid; gap: var(--space-1); min-width: 0; }
.result-files-heading strong { font-size: 17px; font-weight: 600; }
.result-files-actions { display: flex; gap: var(--space-2); margin-left: auto; flex-shrink: 0; }
.result-files-actions .pa-btn--ghost { border-color: transparent; }
.result-files-actions .pa-btn--subtle { border: 1px solid var(--color-border); }
.result-files-list { margin: 0; padding: 0 var(--space-4); list-style: none; border-top: 1px solid var(--color-border); }
.result-files-list li { display: flex; align-items: center; min-width: 0; gap: var(--space-3); padding: 10px 0; }
.result-file-path { min-width: 0; flex: 1; padding: 0; border: 0; background: transparent; color: var(--color-fg-muted); font: inherit; font-size: 16px; text-align: left; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; cursor: pointer; }
.result-file-path:hover { color: var(--color-fg); }
.result-files-stats { flex-shrink: 0; font-size: 14px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.stat-add { color: var(--color-success-fg); }
.stat-del { color: var(--color-danger-fg); }
.result-files-more { display: flex; align-items: center; gap: var(--space-2); margin: var(--space-1) var(--space-4) var(--space-3); padding: 0; border: 0; background: transparent; color: var(--color-fg); font: inherit; font-size: 16px; cursor: pointer; }
.result-files-more .expanded { transform: rotate(180deg); }
.result-file-path:focus-visible, .result-files-more:focus-visible { outline: var(--focus-ring); outline-offset: 2px; border-radius: var(--radius-sm); }
.result-files-notice { padding: var(--space-3); margin: 0; font-size: var(--pa-text-meta); }
.result-review { border: 0; border-radius: 0; }
.result-review:not([open]) { display: none; }
.result-review > summary { border-top: 1px solid var(--color-border); }
.result-review .patch-files { display: none; }
@media (max-width: 600px) {
  .result-files-head { flex-wrap: wrap; padding: var(--space-3); }
  .result-files-actions { margin-left: auto; }
  .result-files-heading strong { font-size: 15px; }
  .result-files-icon { flex-basis: 36px; height: 36px; }
  .result-files-list { padding-inline: var(--space-3); }
  .result-file-path { font-size: 14px; }
}
</style>
