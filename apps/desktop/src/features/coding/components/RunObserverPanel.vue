<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { fetchRunObserver, observerReportJson, type ObserverCheckStatus, type RunObserverReport } from "../api/observer";
import { RUN_STATUS_META, type AgentRunStatus } from "../model/runContracts";

const props = defineProps<{ runId: string }>();
const report = ref<RunObserverReport | null>(null);
const loading = ref(false);
const copying = ref(false);
const copied = ref(false);
const error = ref("");
const copyError = ref("");
let generation = 0;
let controller: AbortController | undefined;

const checkLabels: Record<ObserverCheckStatus, string> = {
  pending: "待核验", passed: "已通过", failed: "未通过", blocked: "已阻断", unverified: "未验证", skipped: "已跳过",
};
const kindLabels = { artifact: "产物存在", test: "测试结果", command: "命令证据" };
const outcomeLabels: Record<string, string> = { answered: "已回答", verified: "已验证", unmet: "未满足", blocked: "已阻断", unknown: "结果未确认" };
const categoryLabels: Record<string, string> = { progress: "运行进展", verification: "完成核验", budget: "预算限制", permission: "权限限制", tool: "工具调用", execution: "命令执行", model: "模型请求", control: "任务控制", recovery: "运行恢复", storage: "本机存储", context: "上下文", plan: "执行计划", other: "其他" };
const reasonLabels: Record<string, string> = {
  disabled: "项目检查未启用", plan_mode: "规划任务不执行检查", readonly: "只读任务不执行检查",
  user_constraint: "遵循用户限制", not_applicable: "当前任务不适用", awaiting_evidence: "等待执行证据",
  scope_unavailable: "工作范围暂不可用", evidence_stale: "执行现场已变化，等待重新核验",
  evidence_passed: "已有通过证据", evidence_failed: "已有失败证据", evidence_blocked: "证据核验受阻", evidence_unverified: "证据尚不足以确认",
};
const statusLabel = (value: string) => RUN_STATUS_META[value as AgentRunStatus]?.label ?? value;

async function load() {
  const mine = ++generation;
  controller?.abort();
  const request = new AbortController();
  controller = request;
  loading.value = true;
  copying.value = false;
  error.value = "";
  copyError.value = "";
  copied.value = false;
  try {
    const result = await fetchRunObserver(props.runId, request.signal);
    if (mine === generation) report.value = result;
  } catch {
    if (mine === generation && !request.signal.aborted) error.value = "观察诊断读取失败，请重试；已显示的数据仍为上次读取结果。";
  } finally {
    if (mine === generation) loading.value = false;
  }
}

async function copyReport() {
  if (!report.value || copying.value) return;
  const mine = generation;
  copying.value = true;
  copied.value = false;
  copyError.value = "";
  try {
    await navigator.clipboard.writeText(observerReportJson(report.value));
    if (mine === generation) copied.value = true;
  } catch {
    if (mine === generation) copyError.value = "复制诊断失败，请检查剪贴板权限后重试。";
  } finally {
    if (mine === generation) copying.value = false;
  }
}

watch(() => props.runId, () => {
  report.value = null;
  copying.value = false;
  copied.value = false;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); });
</script>

<template>
  <section class="run-observer" aria-label="运行观察诊断" data-testid="run-observer-panel">
    <div class="run-observer-actions">
      <button type="button" class="pa-btn pa-btn--subtle" :disabled="loading" data-testid="observer-refresh" @click="load">{{ loading ? "读取中…" : "刷新诊断" }}</button>
      <button type="button" class="pa-btn pa-btn--subtle" :disabled="!report || loading || copying" data-testid="observer-copy" @click="copyReport">{{ copying ? "复制中…" : "复制诊断 JSON" }}</button>
    </div>
    <p class="run-observer-hint">仅显示运行事实与关联标识，不含对话正文、模型正文、工具参数、命令日志或绝对路径。检查结论取自上次核验；刷新仅读取记录，外部文件变化将在下一次完成核验时检测。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="copyError" role="alert">{{ copyError }}</p>
    <p v-if="copied" role="status">已复制诊断摘要。</p>
    <p v-if="loading && !report" role="status">正在读取观察诊断…</p>
    <template v-if="report">
      <dl class="run-observer-meta">
        <div><dt>任务结果</dt><dd>{{ report.goal_outcome ? outcomeLabels[report.goal_outcome] ?? report.goal_outcome : "尚无结论" }}</dd></div>
        <div><dt>运行状态</dt><dd>{{ statusLabel(report.status) }}</dd></div>
        <div><dt>检查配置</dt><dd>{{ report.config_version === null ? "未应用" : `v${report.config_version}` }}</dd></div>
        <div><dt>末事件序号</dt><dd>{{ report.last_event_sequence }}</dd></div>
        <div><dt>记录总数</dt><dd>事件 {{ report.counts.events }} · 步骤 {{ report.counts.steps }} · 执行 {{ report.counts.executions }}</dd></div>
        <div><dt>停滞与重试</dt><dd>重复观察 {{ report.progress.repeated_observations }} · 重复失败 {{ report.progress.failure_repeats }} · 核验重试 {{ report.progress.verification_retries }}</dd></div>
      </dl>
      <p v-if="report.error" class="run-observer-error" data-testid="observer-error-category">错误分类：{{ categoryLabels[report.error.category] ?? report.error.category }} · <code>{{ report.error.code }}</code></p>
      <p v-else class="run-observer-hint">暂无已记录错误；这不代表任务已经通过验收。</p>
      <h4>内置验收检查</h4>
      <p v-if="!report.checks.length" class="run-observer-hint">本次任务没有应用项目验收检查。</p>
      <ul v-else class="run-observer-list">
        <li v-for="check in report.checks" :key="check.id" data-testid="observer-check">
          <strong>{{ check.id }}</strong><span>{{ kindLabels[check.kind] }} · {{ checkLabels[check.status] }}</span>
          <span>{{ reasonLabels[check.reason_code] ?? "详见原因码" }}</span><code>{{ check.reason_code }}</code>
          <small v-if="check.evidence_ids.length">证据：{{ check.evidence_ids.join("、") }}</small>
          <small v-else>暂无关联证据</small>
        </li>
      </ul>
      <p v-if="report.truncated" class="run-observer-hint" role="status">记录已截断：以下最多展示最近 100 个步骤及 100 条事件，并非完整历史。</p>
      <details>
        <summary>关联步骤 · {{ report.steps.length }}</summary>
        <p v-if="!report.steps.length" class="run-observer-hint">暂无步骤记录。</p>
        <ul v-else class="run-observer-list">
          <li v-for="step in report.steps" :key="`${step.ordinal}:${step.id ?? 'unknown'}`"><strong>#{{ step.ordinal }} {{ step.kind }} · {{ step.status }}</strong><code>{{ step.id ?? "未关联步骤" }}</code><span v-if="step.name">{{ step.name }}</span><small v-if="step.plan_item_key">计划引用：{{ step.plan_item_key }}</small></li>
        </ul>
      </details>
      <details>
        <summary>关联事件 · {{ report.events.length }}</summary>
        <p v-if="!report.events.length" class="run-observer-hint">暂无事件记录。</p>
        <ul v-else class="run-observer-list">
          <li v-for="event in report.events" :key="event.sequence"><strong>#{{ event.sequence }} {{ event.type }}</strong><span>{{ categoryLabels[event.category] ?? event.category }}</span><small v-if="event.step_id">步骤：{{ event.step_id }}</small><small v-if="event.execution_id">执行：{{ event.execution_id }}</small></li>
        </ul>
      </details>
    </template>
  </section>
</template>

<style scoped>
.run-observer { display: grid; gap: var(--space-3); min-width: 0; font-size: var(--text-sm); overflow-wrap: anywhere; }
.run-observer-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.run-observer p, .run-observer h4 { margin: 0; }
.run-observer-hint, .run-observer small { color: var(--color-fg-muted); line-height: 1.6; }
.run-observer [role="alert"], .run-observer-error { color: var(--color-danger-fg); }
.run-observer-meta { margin: 0; }
.run-observer-meta > div { display: grid; grid-template-columns: 6em minmax(0, 1fr); gap: var(--space-2); padding-block: var(--space-1); }
.run-observer-meta dt { color: var(--color-fg-muted); }
.run-observer-meta dd { margin: 0; }
.run-observer-list { display: grid; gap: var(--space-2); margin: var(--space-2) 0 0; padding: 0; list-style: none; }
.run-observer-list li { display: grid; gap: var(--space-1); border-bottom: 1px solid var(--color-border); padding-bottom: var(--space-2); }
.run-observer summary { cursor: pointer; padding-block: var(--space-1); }
.run-observer summary:focus-visible { outline: var(--focus-ring); outline-offset: 2px; }
</style>
