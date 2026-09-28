<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { fetchModelToolProbe, retryModelToolProbe, type ModelToolProbeStatus } from "../features/coding/api/modelProfiles";
import { useNotifications } from "../stores/notifications";
const props = defineProps<{ profileId: string }>();
const notify = useNotifications();
const status = ref<ModelToolProbeStatus | null>(null), error = ref(""), busy = ref(false), opened = ref(false);
let controller: AbortController | undefined, timer: ReturnType<typeof setTimeout> | undefined, generation = 0;
async function load() {
  const mine = ++generation; controller?.abort(); const current = controller = new AbortController();
  try { const value = await fetchModelToolProbe(props.profileId, { signal: current.signal }); if (mine === generation) { status.value = value; error.value = ""; } }
  catch { if (mine === generation && !current.signal.aborted) error.value = "能力记录读取失败"; }
  finally { if (mine === generation) { clearTimeout(timer); if (opened.value && status.value?.status === "running") timer = setTimeout(() => void load(), 1500); } }
}
async function probe() {
  if (busy.value) return;
  busy.value = true;
  try {
    const accepted = await notify.confirm({ title: "探测模型工具能力", message: "将使用已保存的模型配置发送测试请求，可能产生模型费用。", confirmLabel: "开始探测" });
    if (!accepted || !opened.value) return;
    await retryModelToolProbe(props.profileId); await load();
  } catch (cause) { error.value = (cause as { message?: string }).message || "探测未启动，请重试"; }
  finally { busy.value = false; }
}
function toggle(event: Event) { opened.value = (event.target as HTMLDetailsElement).open; if (opened.value) void load(); else { generation++; controller?.abort(); clearTimeout(timer); } }
onBeforeUnmount(() => { opened.value = false; generation++; controller?.abort(); clearTimeout(timer); });
</script>
<template><details class="capability-status" @toggle="toggle"><summary>能力记录</summary><p>连接测试检查模型列表；工具能力以实际探测记录为准，任务完成情况见任务内的验证面板。</p><p v-if="status">工具探测：{{ { none: '尚未探测', running: '进行中', ok: '通过', failed: '未通过' }[status.status] }} · {{ status.pass_count }} / {{ status.sample_count }} 样本 <span v-if="status.probed_at">· {{ new Date(status.probed_at).toLocaleString() }}</span></p><ul v-if="status?.results"><li v-for="(value, name) in status.results" :key="name">{{ name }}：{{ value ? '通过' : '未通过' }}</li></ul><p v-if="error" role="alert">{{ error }}</p><button class="secondary-button" :disabled="busy || status?.status === 'running'" @click="probe">{{ busy ? '正在处理…' : '测试工具能力（可能产生费用）' }}</button></details></template>
<style scoped>.capability-status { grid-column: 1 / -1; font-size: 12px; color: var(--color-fg-muted); width: 100%; }summary { cursor: pointer; padding: 5px 0; }p { line-height: 1.6; }[role="alert"] { color: var(--color-danger-fg); }.secondary-button { border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-fg); border-radius: 8px; padding: 7px 10px; cursor: pointer; }</style>
