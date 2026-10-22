<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { ContextBudgetResponse } from "../../../api";
import { useNotifications } from "../../../stores/notifications";
import SessionMemoryPanel from "./SessionMemoryPanel.vue";
import { compactSessionContext, fetchSessionBudget, fetchSessionContext, setInstructionTrust, type ContextState } from "../api/context";

const props = defineProps<{ sessionId: number; revision?: number }>();
const emit = defineEmits<{ "open-source": [source: { projectId: number; sessionId: number; messageId: number | null }] }>();
const notify = useNotifications();
const state = ref<ContextState | null>(null);
const budget = ref<ContextBudgetResponse | null>(null);
const error = ref<string | null>(null);
const busy = ref(false);
const loading = ref(true);
let sequence = 0;
let scopeEpoch = 0;
let timer: ReturnType<typeof setInterval> | undefined;
const rules = computed(() => state.value?.active_sources.length ? state.value.active_sources : state.value?.sources ?? []);
const breakdown = computed(() => budget.value?.breakdown ?? null);
const metrics = computed(() => state.value?.checkpoint?.compaction_metrics ?? null);
function tokens(value: number | null | undefined) {
  return typeof value === "number" ? `${value.toLocaleString()} tokens` : "未知";
}
function beforeAfter() {
  const value = metrics.value;
  if (!value) return "未记录";
  const counts = `归档 ${value.archived_items ?? 0} 项 · 保留 ${value.retained_messages ?? 0} 条`;
  return value.measured ? `${tokens(value.estimated_before_tokens)} → ${tokens(value.estimated_after_tokens)} · ${counts}` : `估算未记录 · ${counts}`;
}
const statusLabels: Record<string, string> = {
  known: "有来源", unknown: "未知 / 待核对", recheck_required: "需复核",
};
const handoffSections = computed(() => {
  const value = state.value?.handoff;
  if (!value) return [];
  return [
    // 后端目标区段使用 requirements；其余区段使用 items，这里统一成同一渲染契约。
    { key: "goal", title: "当前目标与验收条件", section: { ...value.goal, items: value.goal.requirements ?? [] } },
    { key: "constraints", title: "生效限制与规则", section: value.constraints },
    { key: "plan", title: "当前计划与下一步", section: value.plan },
    { key: "findings", title: "关键发现与决定", section: value.findings },
    { key: "changes", title: "修改与验证", section: value.changes },
    { key: "unresolved", title: "未解决问题", section: value.unresolved },
  ];
});
function statusLabel(status: string | undefined) {
  return statusLabels[status ?? "unknown"] ?? "未知 / 待核对";
}

async function load() {
  const mine = ++sequence;
  try {
    const [context, usage] = await Promise.all([fetchSessionContext(props.sessionId), fetchSessionBudget(props.sessionId)]);
    if (mine !== sequence) return;
    state.value = context;
    budget.value = usage;
    error.value = null;
  } catch {
    if (mine === sequence) error.value = "上下文状态读取失败，请刷新重试";
  } finally {
    if (mine === sequence) loading.value = false;
  }
}
watch(() => props.sessionId, () => {
  scopeEpoch++;
  sequence++;
  state.value = null;
  budget.value = null;
  error.value = null;
  loading.value = true;
  busy.value = false;
  void load();
  if (timer) clearInterval(timer);
  timer = setInterval(() => void load(), 5000);
}, { immediate: true });
onBeforeUnmount(() => { sequence++; scopeEpoch++; if (timer) clearInterval(timer); });

async function compact() {
  if (busy.value) return;
  const session = props.sessionId;
  const epoch = scopeEpoch;
  busy.value = true;
  error.value = null;
  try {
    const result = await compactSessionContext(session, crypto.randomUUID());
    if (epoch !== scopeEpoch) return;
    await load();
    if (epoch !== scopeEpoch) return;
    if (result.state === "failed") error.value = result.error ?? "压缩失败，原历史已保留";
  } catch {
    if (epoch === scopeEpoch) error.value = "压缩请求失败，原历史保持可读";
  } finally {
    if (epoch === scopeEpoch) busy.value = false;
  }
}
async function trust() {
  if (busy.value || !state.value) return;
  const epoch = scopeEpoch;
  const project = state.value.project_id;
  const trusted = !state.value.trusted;
  busy.value = true;
  try {
    const accepted = await notify.confirm({ title: trusted ? "信任项目规则" : "停止使用项目规则",
      message: "规则仅适用于其目录，不增加文件或命令权限。活动任务的规则信任变化会停止本轮后续写入，需要重新发起任务。", confirmLabel: "确认" });
    if (!accepted || epoch !== scopeEpoch) return;
    await setInstructionTrust(project, trusted);
    if (epoch === scopeEpoch) await load();
  } catch {
    if (epoch === scopeEpoch) error.value = "规则信任设置未保存，请重试";
  } finally {
    if (epoch === scopeEpoch) busy.value = false;
  }
}
</script>

<template>
  <section class="local-context" aria-label="项目指令与上下文预算">
    <p v-if="loading" role="status">正在读取上下文…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error" class="pa-btn pa-btn--subtle" @click="load">刷新</button>
    <template v-if="state">
      <p><strong>项目规则</strong> · {{ state.trusted ? "已信任" : "仅展示，未作为指令使用" }}</p>
      <button class="pa-btn pa-btn--subtle" :disabled="busy" @click="trust">{{ state.trusted ? "停止信任" : "信任此项目规则" }}</button>
      <p v-if="!rules.length">适用目录未发现 AGENTS.md</p>
      <ul v-else>
        <li v-for="rule in rules" :key="rule.path">
          <strong>{{ rule.path }}</strong><br>适用：{{ rule.scope }} · {{ rule.trusted ? "生效" : "未信任" }}
          <small :title="rule.sha256">摘要 {{ rule.sha256.slice(0, 12) }}</small>
        </li>
      </ul>
      <details v-for="rule in state.sources" :key="rule.path">
        <summary>查看 {{ rule.path }}</summary><pre>{{ rule.content }}</pre>
      </details>
      <dl v-if="budget">
        <dt>本次输入估算</dt><dd>{{ budget.estimated_input_tokens?.toLocaleString() ?? "尚未组装" }} tokens</dd>
        <dt>最近供应商实测</dt><dd>{{ budget.source === 'provider_usage' ? budget.used_tokens.toLocaleString() : "未知" }} tokens</dd>
        <dt>输入预算 / 输出预留</dt><dd>{{ budget.input_budget_tokens ?? "未知" }} / {{ budget.reserved_output_tokens }} tokens</dd>
        <dt>自动压缩阈值</dt><dd>{{ budget.auto_compact_threshold_tokens?.toLocaleString() ?? "尚未组装" }} tokens</dd>
        <dt>压缩状态</dt><dd>{{ state.pending ? "等待安全请求边界" : budget.compaction_state === 'failed' ? "失败，原历史保留" : state.checkpoint ? "已提交检查点" : "尚未压缩" }}</dd>
        <template v-if="state.checkpoint">
          <dt>历史保留方式</dt><dd>{{ state.checkpoint.summary_strategy === 'model' ? "工作摘要与事实索引" : "事实索引" }} · 原文可续读</dd>
          <dt>压缩前后估算</dt><dd>{{ beforeAfter() }}</dd>
        </template>
      </dl>
      <details v-if="budget" class="local-context__breakdown">
        <summary>上下文分项明细</summary>
        <p v-if="!breakdown">暂无分项明细（该记录未保存分项或尚未组装请求）。</p>
        <template v-else>
          <table>
            <thead><tr><th scope="col">分类</th><th scope="col">估算</th><th scope="col">字节</th></tr></thead>
            <tbody>
              <tr v-for="item in breakdown.items" :key="item.category">
                <td>{{ item.label }}</td><td>{{ item.estimated_tokens.toLocaleString() }}</td><td>{{ item.bytes.toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
          <p>分项合计 {{ breakdown.estimate_tokens.toLocaleString() }} tokens（估算，非供应商实测）。</p>
          <p v-if="breakdown.provider_usage_tokens">供应商实测前缀 {{ breakdown.provider_usage_tokens.toLocaleString() }} tokens 已用于总量校准。</p>
          <p><small>{{ breakdown.notice }}</small></p>
        </template>
      </details>
      <template v-if="state.checkpoint">
        <details v-if="state.handoff" class="local-context__handoff">
          <summary>压缩交接（程序投影）</summary>
          <div v-for="entry in handoffSections" :key="entry.key">
            <p><strong>{{ entry.title }}</strong> · {{ statusLabel(entry.section.status) }}</p>
            <p v-if="entry.key === 'plan' && entry.section.next_step"><small>下一步：{{ entry.section.next_step }}</small></p>
            <ul v-if="entry.section.items?.length">
              <li v-for="(item, index) in entry.section.items" :key="index">
                {{ item.text }}<span v-if="item.stale"> · 需复核</span>
              </li>
            </ul>
            <p v-else><small>暂无来源；不影响原始历史读取。</small></p>
            <p v-if="entry.section.note"><small>{{ entry.section.note }}</small></p>
          </div>
        </details>
        <p v-else><small>压缩交接：旧检查点未保存该明细（待核对）。</small></p>
      </template>
      <p v-if="state.checkpoint?.summary_fallback_reason">本次未采用工作摘要，已保留事实索引和原始历史。</p>
      <p v-if="state.compaction_error" role="alert">{{ state.compaction_error }}</p>
      <p v-if="state.loop_budget">模型 {{ state.loop_budget.model_requests }}/{{ state.loop_budget.max_model_requests }} · 工具 {{ state.loop_budget.tool_calls }}/{{ state.loop_budget.max_tool_calls }}<br>
        有效执行 {{ state.loop_budget.active_seconds.toFixed(1) }} 秒 · 等待审批 {{ state.loop_budget.approval_wait_seconds.toFixed(1) }} 秒<br>
        费用 {{ state.loop_budget.cost_usd === null ? "未知" : `$${state.loop_budget.cost_usd}` }}</p>
      <button class="pa-btn pa-btn--subtle" :disabled="busy || !!state.pending" @click="compact">{{ state.pending ? "压缩已排队" : busy ? "处理中…" : "压缩历史" }}</button>
    </template>
  </section>
  <SessionMemoryPanel :session-id="sessionId" :revision="revision" @open-source="emit('open-source', $event)" />
</template>

<style scoped>
.local-context { margin-top: var(--space-3); font-size: var(--pa-text-meta); line-height: var(--leading-normal); overflow-wrap: anywhere; }
.local-context ul { padding-left: var(--space-4); }
.local-context small { display: block; color: var(--color-fg-muted); }
.local-context dt { color: var(--color-fg-muted); }
.local-context dd { margin: 0 0 var(--space-2); }
.local-context pre { max-height: 240px; overflow: auto; white-space: pre-wrap; }
.local-context__breakdown { margin-top: var(--space-2); }
.local-context__breakdown table { width: 100%; border-collapse: collapse; margin: var(--space-2) 0; }
.local-context__breakdown th, .local-context__breakdown td { text-align: left; padding: 2px var(--space-2) 2px 0; border-bottom: 1px solid var(--color-border-subtle, #ddd); }
.local-context [role="alert"] { color: var(--color-danger-fg); }
</style>
