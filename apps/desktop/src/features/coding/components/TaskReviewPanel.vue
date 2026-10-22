<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { fetchTaskReview, fetchWorkspaceDiff, type TaskReview, type TaskReviewRun, type WorkspaceDiff } from "../api/taskReview";
import PatchReviewPanel from "./PatchReviewPanel.vue";
import DiffFeedback from "./DiffFeedback.vue";
import { RUN_STATUS_META, type AgentRunStatus } from "../model/runContracts";
const props = defineProps<{ sessionId: number; revision?: string; active: boolean }>();
const emit = defineEmits<{ feedback: [message: string] }>();
const scope = ref("last_turn"), state = ref<TaskReview | null>(null), loading = ref(false), error = ref("");
const selected = ref(""), staged = ref(false), diff = ref<WorkspaceDiff | null>(null);
let controller: AbortController | undefined, diffController: AbortController | undefined;
let generation = 0, diffGeneration = 0;
async function load(more = false) {
  const mine = ++generation; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = "";
  try { const result = await fetchTaskReview(props.sessionId, scope.value, more ? state.value?.workspace?.next_cursor ?? undefined : undefined, controller.signal); if (mine === generation) { if (more && state.value?.workspace && result.workspace) result.workspace.entries.unshift(...state.value.workspace.entries); state.value = result; } }
  catch (cause) { if (mine === generation && !controller.signal.aborted) error.value = (cause as { message?: string }).message || "审阅数据读取失败"; }
  finally { if (mine === generation) loading.value = false; }
}
async function loadDiff(more = false) {
  if (!selected.value) return;
  const mine = ++diffGeneration; diffController?.abort(); diffController = new AbortController(); error.value = "";
  try { const result = await fetchWorkspaceDiff(props.sessionId, selected.value, staged.value, more ? diff.value?.next_offset ?? 0 : 0, more ? diff.value?.version : undefined, diffController.signal); if (mine === diffGeneration) diff.value = more && diff.value ? { ...result, diff: diff.value.diff + result.diff } : result; }
  catch (cause) { if (mine === diffGeneration && !diffController.signal.aborted) error.value = (cause as { message?: string }).message || "差异读取失败"; }
}
watch([scope, () => props.sessionId, () => props.revision], () => { state.value = null; selected.value = ""; diff.value = null; diffGeneration++; diffController?.abort(); void load(); }, { immediate: true });
watch([selected, staged], () => { diff.value = null; void loadDiff(); });
onBeforeUnmount(() => { generation++; diffGeneration++; controller?.abort(); diffController?.abort(); });
/** 续跑链与恢复来源文案：只读已提交事实，不改写旧运行结论。 */
function chainLabels(run: TaskReviewRun): string[] {
  const lines: string[] = [];
  if (run.resumed_from_run_id) lines.push(`由前一轮继续${run.ancestor_count ? ` · 第 ${run.ancestor_count + 1} 轮` : ""}`);
  if (run.error_code) lines.push(`结束原因 · ${run.error_message || run.error_code}`);
  if (run.recovery_class === "model_error") lines.push("模型传输故障，可人工继续");
  if (run.model_switch) lines.push(`模型切换 · ${run.model_switch_from ?? "未知"} → ${run.model_switch_to ?? "未知"} · 旧运行配置未改写`);
  if (run.resolution_count) lines.push(`人工核对 ${run.resolution_count} 项 · 用户已核对，系统未验证`);
  if (run.patch_status?.length) lines.push(`补丁状态 · ${run.patch_status.join(" / ")}`);
  if (run.rollback_available) lines.push("该轮补丁可逐个预览撤销；运行中或预览过期时拒绝");
  return lines;
}
</script>
<template><section class="task-review"><label>审阅范围<select v-model="scope" class="pa-input"><option value="last_turn">最近一轮</option><option value="task">整个任务</option><option value="workspace">当前工作区</option></select></label><p v-if="loading" role="status">正在读取…</p><p v-if="error" role="alert">{{ error }} <button class="pa-btn pa-btn--ghost" @click="load()">刷新</button></p><template v-if="state"><template v-if="scope !== 'workspace'"><p v-if="!state.runs.length">暂无运行记录。</p><details v-for="run in state.runs" :key="run.id" :open="state.runs.length === 1"><summary>{{ new Date(run.created_at).toLocaleString() }} · {{ RUN_STATUS_META[run.status as AgentRunStatus]?.label ?? run.status }}</summary><p>工作区 #{{ run.workspace_id }}</p><ul v-if="chainLabels(run).length" aria-label="恢复关系"><li v-for="line in chainLabels(run)" :key="line">{{ line }}</li></ul><ul v-if="run.outcome?.verification_results?.length"><li v-for="check in run.outcome.verification_results" :key="check.requirement_id">{{ { passed: '已验证', failed: '验证失败', blocked: '受阻', unverified: '未验证' }[check.status] }} · {{ check.message || check.requirement_id }}</li></ul><p v-else>没有可核实的验证记录。</p><ul v-if="run.outcome?.unverified_items?.length"><li v-for="item in run.outcome.unverified_items" :key="item">待核实：{{ item }}</li></ul><PatchReviewPanel :run-id="run.id" :active="active" @feedback="emit('feedback', $event)" /></details></template><template v-else><p>此范围包含当前目录中的全部 Git 改动，可能来自其他任务或手动编辑。</p><p v-if="!state.workspace?.is_git">当前目录不是 Git 仓库。</p><label v-else>文件<select v-model="selected" class="pa-input"><option value="">选择文件</option><option v-for="file in state.workspace.entries" :key="file.rel_path" :value="file.rel_path">{{ file.status }} · {{ file.rel_path }}</option></select></label><button v-if="state.workspace?.next_cursor" class="pa-btn pa-btn--ghost" :disabled="loading" @click="load(true)">更多文件</button><label v-if="selected"><input v-model="staged" type="checkbox" />查看暂存区差异</label><p v-if="diff && !diff.diff">当前比较范围没有文本差异。未跟踪文件请在文件面板查看。</p><DiffFeedback v-if="diff?.diff" :content="diff.diff" :path="selected" :version="diff.version" @feedback="emit('feedback', $event)" /><button v-if="diff?.next_offset" class="pa-btn pa-btn--subtle" @click="loadDiff(true)">继续加载差异</button></template></template></section></template>
<style scoped>.task-review { display: grid; gap: 12px; font-size: 13px; }.task-review label { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }select { max-width: 100%; }p { margin: 0; color: var(--color-fg-muted); line-height: 1.5; }summary { cursor: pointer; padding: 10px 0; }li { margin: 6px 0; overflow-wrap: anywhere; }[role="alert"] { color: var(--color-danger-fg); }</style>

