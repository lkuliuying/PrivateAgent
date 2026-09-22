<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { cancelChildAgent, fetchBrowserEvidence, fetchBrowserImage, fetchChildAgents, type BrowserEvidence, type ChildAgent } from "../api/runEvidence";
import { isTerminalRunStatus, RUN_STATUS_META, type AgentRunStatus } from "../model/runContracts";
const props = defineProps<{ runId: string; active: boolean }>();
const emit = defineEmits<{ feedback: [message: string] }>();
const browser = ref<BrowserEvidence[]>([]), agents = ref<ChildAgent[]>([]), images = ref<Record<string, string>>({}), error = ref("");
let controller: AbortController | undefined, timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0, loadSequence = 0;
let imageController = new AbortController();
const imageLoading = new Set<string>();
function clearImages() { Object.values(images.value).forEach(url => URL.revokeObjectURL(url)); images.value = {}; }
async function load() {
  const mine = generation, request = ++loadSequence; controller?.abort(); const current = controller = new AbortController();
  try { const [b, a] = await Promise.all([fetchBrowserEvidence(props.runId, current.signal), fetchChildAgents(props.runId, current.signal)]); if (mine === generation && request === loadSequence) { browser.value = b.items; agents.value = a.items; error.value = ""; } }
  catch (cause) { if (mine === generation && request === loadSequence && !current.signal.aborted) error.value = (cause as { message?: string }).message || "证据读取失败"; }
  finally { if (mine === generation && request === loadSequence) { clearTimeout(timer); if (props.active) timer = setTimeout(() => void load(), 1800); } }
}
async function showImage(item: BrowserEvidence) {
  if (images.value[item.screenshot_id] || imageLoading.has(item.screenshot_id)) return;
  imageLoading.add(item.screenshot_id);
  const mine = generation;
  try { const blob = await fetchBrowserImage(props.runId, item.screenshot_id, imageController.signal); if (mine === generation) images.value[item.screenshot_id] = URL.createObjectURL(blob); }
  catch { if (mine === generation) error.value = "截图加载失败，请重试"; }
  finally { imageLoading.delete(item.screenshot_id); }
}
async function cancel(child: ChildAgent) {
  try { await cancelChildAgent(props.runId, child.id); await load(); } catch { error.value = "停止子任务失败，请重试"; }
}
watch(() => props.runId, () => { generation++; controller?.abort(); imageController.abort(); imageController = new AbortController(); imageLoading.clear(); clearTimeout(timer); clearImages(); browser.value = []; agents.value = []; void load(); }, { immediate: true });
watch(() => props.active, () => void load());
onBeforeUnmount(() => { generation++; controller?.abort(); imageController.abort(); imageController = new AbortController(); imageLoading.clear(); clearTimeout(timer); clearImages(); });
</script>
<template><section class="run-evidence"><p v-if="error" role="alert">{{ error }} <button class="pa-btn pa-btn--ghost" @click="load">重试</button></p><h3>浏览器验证</h3><p v-if="!browser.length">暂无浏览器证据。启动项目预览后，可要求 Agent 读取页面、检查交互并保存截图。</p><details v-for="item in browser" :key="item.screenshot_id"><summary @click="showImage(item)">{{ item.url }} · {{ new Date(item.created_at).toLocaleTimeString() }}</summary><p>{{ item.notice }}</p><ul><li v-for="(check, i) in item.checks" :key="i">{{ check.action }} · {{ check.selector }} · {{ check.passed === true ? '断言通过' : check.passed === false ? '断言失败' : '操作已执行' }}</li></ul><img v-if="images[item.screenshot_id]" :src="images[item.screenshot_id]" alt="本机预览验证截图" /><button v-else class="pa-btn pa-btn--ghost" @click="showImage(item)">加载截图</button><button class="pa-btn pa-btn--ghost" @click="emit('feedback', `请核对浏览器证据 ${item.screenshot_id}（${item.url}）中的问题：`)">对截图反馈</button></details><h3>只读子任务</h3><p v-if="!agents.length">尚未创建子任务。在输入区的任务预算与协作中启用后，可委托独立探索或审查。</p><article v-for="agent in agents" :key="agent.id"><strong>{{ agent.title }}</strong><p>{{ RUN_STATUS_META[agent.status as AgentRunStatus]?.label ?? agent.status }} · 输入 {{ agent.input_tokens }} / 输出 {{ agent.output_tokens }} tokens · 费用 {{ agent.cost_usd === null ? '未知' : `$${agent.cost_usd.toFixed(4)}` }}</p><button v-if="!isTerminalRunStatus(agent.status as AgentRunStatus)" class="pa-btn pa-btn--ghost" @click="cancel(agent)">停止子任务</button><p v-if="agent.error" role="alert">{{ agent.error }}</p><pre v-if="agent.output">{{ agent.output }}</pre></article></section></template>
<style scoped>.run-evidence { font-size: 13px; display: grid; gap: 10px; }h3,p { margin: 0; }p { color: var(--color-fg-muted); line-height: 1.6; }summary { cursor: pointer; padding: 10px 0; overflow-wrap: anywhere; }img { width: 100%; margin-top: 12px; border: 1px solid var(--color-border); }pre { white-space: pre-wrap; max-height: 320px; overflow: auto; overflow-wrap: anywhere; font-size: 12px; }article { padding: 12px 0; border-top: 1px solid var(--color-border); }[role="alert"] { color: var(--color-danger-fg); }</style>
