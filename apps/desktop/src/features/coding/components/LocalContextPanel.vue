<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { ContextBudgetResponse } from "../../../api";
import { useNotifications } from "../../../stores/notifications";
import { compactSessionContext, fetchSessionBudget, fetchSessionContext, setInstructionTrust, type ContextState } from "../api/context";

const props = defineProps<{ sessionId: number; revision?: number }>();
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
        <dt>压缩状态</dt><dd>{{ state.pending ? "等待安全请求边界" : budget.compaction_state === 'failed' ? "失败，原历史保留" : state.checkpoint ? "已提交检查点" : "尚未压缩" }}</dd>
      </dl>
      <p v-if="state.compaction_error" role="alert">{{ state.compaction_error }}</p>
      <p v-if="state.loop_budget">模型 {{ state.loop_budget.model_requests }}/{{ state.loop_budget.max_model_requests }} · 工具 {{ state.loop_budget.tool_calls }}/{{ state.loop_budget.max_tool_calls }}<br>
        有效执行 {{ state.loop_budget.active_seconds.toFixed(1) }} 秒 · 等待审批 {{ state.loop_budget.approval_wait_seconds.toFixed(1) }} 秒<br>
        费用 {{ state.loop_budget.cost_usd === null ? "未知" : `$${state.loop_budget.cost_usd}` }}</p>
      <button class="pa-btn pa-btn--subtle" :disabled="busy || !!state.pending" @click="compact">{{ state.pending ? "压缩已排队" : busy ? "处理中…" : "压缩历史" }}</button>
    </template>
  </section>
</template>

<style scoped>
.local-context { margin-top: var(--space-3); font-size: var(--pa-text-meta); line-height: var(--leading-normal); overflow-wrap: anywhere; }
.local-context ul { padding-left: var(--space-4); }
.local-context small { display: block; color: var(--color-fg-muted); }
.local-context dt { color: var(--color-fg-muted); }
.local-context dd { margin: 0 0 var(--space-2); }
.local-context pre { max-height: 240px; overflow: auto; white-space: pre-wrap; }
.local-context [role="alert"] { color: var(--color-danger-fg); }
</style>
