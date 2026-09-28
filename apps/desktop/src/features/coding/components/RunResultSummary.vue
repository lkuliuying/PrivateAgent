<script setup lang="ts">
import { computed } from "vue";
import type { RunProjection } from "../model/runProjector";
import { runResultMeta } from "../model/runOutcome";
const props = defineProps<{ projection: RunProjection }>();
const meta = computed(() => runResultMeta(props.projection.status, props.projection.runOutcome, props.projection.verifying));
const labels = { passed: "已验证", failed: "验证失败", blocked: "受阻", unverified: "未验证" };
const incompleteUsage = computed(() => props.projection.entries.some(item => item.kind === "model-turn" && item.usageComplete === false));
</script>
<template>
  <section class="result-summary" aria-label="结果与用量">
    <strong>{{ meta.label }}</strong>
    <dl><dt>已记录输入 / 输出</dt><dd>{{ projection.usage.inputTokens.toLocaleString() }} / {{ projection.usage.outputTokens.toLocaleString() }} tokens</dd><dt>工具调用</dt><dd>{{ projection.usage.toolCallCount }}</dd><dt>服务返回费用</dt><dd>{{ projection.usage.costUsd === null ? '未知（服务未提供）' : `$${projection.usage.costUsd.toFixed(4)}` }}</dd></dl>
    <p v-if="incompleteUsage">部分请求未返回完整用量；当前数字不能视为最终账单。</p>
    <ul v-if="projection.runOutcome.verification_results?.length"><li v-for="check in projection.runOutcome.verification_results" :key="check.requirement_id"><b>{{ labels[check.status] }}</b> · {{ check.message || check.requirement_id }}<small v-if="check.evidence_ids?.length">证据：{{ check.evidence_ids?.join('、') }}</small></li></ul>
    <p v-else>本轮尚无可核实的验证记录。</p>
    <ul v-if="projection.runOutcome.unverified_items?.length"><li v-for="item in projection.runOutcome.unverified_items" :key="item">待核实：{{ item }}</li></ul>
  </section>
</template>
<style scoped>
.result-summary { font-size: 13px; padding-bottom: 18px; margin-bottom: 18px; border-bottom: 1px solid var(--color-border); }dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; }dt,p { color: var(--color-fg-muted); }dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }li { margin: 8px 0; overflow-wrap: anywhere; line-height: 1.6; }small { display: block; color: var(--color-fg-muted); }
</style>
