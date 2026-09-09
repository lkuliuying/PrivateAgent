<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch, type ComponentPublicInstance } from "vue";
import { useNotifications } from "../../../stores/notifications";
import { cancelExecution, closeExecutions, executionText, listExecutions, readExecution, writeExecution, type ManagedExecution } from "../api/executions";

const props = defineProps<{ sessionId: number }>();
const notify = useNotifications();
const items = ref<ManagedExecution[]>([]);
const output = ref<Record<string, { cursor: number; text: string; gap: boolean }>>({});
const panelElement = ref<HTMLElement | null>(null);
const outputElements = new Map<string, HTMLPreElement>();
const selected = ref<string | null>(null);
const input = ref("");
const busy = ref(false);
const error = ref("");
const active = computed(() => items.value.filter(item => ["starting", "running"].includes(item.status)));
const labels = { starting: "启动中", running: "运行中", exited: "已退出", cancelled: "已取消", timed_out: "超时", failed: "失败", unknown: "结果未知" };
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;

function setOutputElement(id: string, element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLPreElement) outputElements.set(id, element);
  else outputElements.delete(id);
}

async function refresh(mine = generation) {
  const session = props.sessionId;
  controller?.abort();
  const request = new AbortController();
  controller = request;
  try {
    const result = await listExecutions(session, request.signal);
    if (mine !== generation) return;
    const panel = panelElement.value;
    const followPanel = !panel || panel.scrollHeight - panel.scrollTop - panel.clientHeight < 48;
    items.value = result.items;
    for (const item of result.items.filter(item => item.execution_id === selected.value || ["starting", "running"].includes(item.status))) {
      const old = output.value[item.execution_id] ?? { cursor: 0, text: "", gap: false };
      const page = await readExecution(session, item.execution_id, old.cursor, request.signal);
      if (mine !== generation) return;
      const element = outputElements.get(item.execution_id);
      const follow = !element || element.scrollHeight - element.scrollTop - element.clientHeight < 48;
      const text = old.text + page.chunks.filter(chunk => chunk.sequence > old.cursor).map(chunk => chunk.data).join("");
      output.value = { ...output.value, [item.execution_id]: { cursor: page.next_cursor, text: executionText(text).slice(-64000), gap: old.gap || page.gap || text.length > 64000 } };
      await nextTick();
      if (mine !== generation) return;
      // 只跟随正在阅读尾部的用户，保留向上翻阅历史输出的位置。
      const current = outputElements.get(item.execution_id);
      if (follow && current) {
        current.scrollTop = current.scrollHeight;
        // 面板被其他区域压缩时，外层也需跟随尾部，避免最后几行被裁掉。
        if (followPanel && panelElement.value) panelElement.value.scrollTop = panelElement.value.scrollHeight;
      }
    }
    error.value = "";
  } catch {
    if (mine === generation && !request.signal.aborted) error.value = "执行状态读取失败，可重试；未推断进程已停止。";
  } finally {
    if (mine === generation) timer = setTimeout(() => void refresh(mine), active.value.length ? 300 : 2000);
  }
}

async function action(work: () => Promise<unknown>) {
  const mine = generation;
  busy.value = true;
  try { await work(); if (mine === generation) error.value = ""; }
  catch { if (mine === generation) error.value = "操作未确认，请刷新执行状态后重试。"; }
  finally { if (mine === generation) busy.value = false; }
}

async function send(item: ManagedExecution, eof: boolean) {
  const text = input.value;
  const session = props.sessionId;
  const mine = generation;
  if (!await notify.confirm({ title: "向进程输入", message: eof ? "发送输入并关闭 stdin" : "发送当前输入", impact: "输入可能使正在运行的项目程序执行新的操作，请勿输入凭据。" })) return;
  if (mine !== generation) return;
  await action(() => writeExecution(session, item, text, eof));
  if (mine === generation) input.value = "";
}

watch(() => props.sessionId, () => {
  generation += 1;
  clearTimeout(timer);
  controller?.abort();
  outputElements.clear();
  items.value = []; output.value = {}; selected.value = null; error.value = ""; input.value = ""; busy.value = false;
  void refresh();
}, { immediate: true });
onBeforeUnmount(() => { generation += 1; clearTimeout(timer); controller?.abort(); outputElements.clear(); });
</script>

<template>
  <section ref="panelElement" class="execution-panel" data-testid="execution-panel" aria-label="本机会话进程">
    <div class="execution-panel__head"><strong>本机进程 · {{ active.length }} 个运行中</strong>
      <button v-if="active.length" class="pa-btn" :disabled="busy" @click="action(() => closeExecutions(sessionId))">停止本会话全部进程</button>
    </div>
    <p v-if="!items.length">暂无持续执行。可信项目程序以当前系统用户运行，可访问项目外文件和网络。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <article v-for="item in items" :key="item.execution_id" class="execution-panel__item">
      <button class="pa-btn" @click="selected = selected === item.execution_id ? null : item.execution_id">{{ labels[item.status] }} · {{ item.argv.join(' ') }} · {{ item.cwd }}</button>
      <span v-if="item.retention === 'session'">保留至会话关闭或授权到期</span>
      <span v-if="item.exit_code !== null">退出码 {{ item.exit_code }}</span>
      <span v-if="item.status !== 'running' && !item.stopped">进程树停止状态未确认</span>
      <button v-if="['starting', 'running'].includes(item.status)" class="pa-btn" :disabled="busy" @click="action(() => cancelExecution(sessionId, item.execution_id))">停止</button>
      <p v-if="item.error">{{ item.error }}</p>
      <template v-if="selected === item.execution_id || ['starting', 'running'].includes(item.status)">
        <p v-if="item.dropped_bytes || output[item.execution_id]?.gap" role="status">输出窗口存在截断或缺口，已丢弃 {{ item.dropped_bytes }} 字节；此处不代表完整日志。</p>
        <pre :ref="element => setOutputElement(item.execution_id, element)">{{ output[item.execution_id]?.text || '等待输出…' }}</pre>
        <div v-if="item.stdin_open" class="execution-panel__stdin">
          <input v-model="input" class="pa-input" maxlength="8192" aria-label="进程输入" />
          <button class="pa-btn" :disabled="busy" @click="send(item, false)">发送</button>
          <button class="pa-btn" :disabled="busy" @click="send(item, true)">发送并结束输入</button>
        </div>
      </template>
    </article>
  </section>
</template>

<style scoped>
.execution-panel { border-top: 1px solid var(--pa-border, #ddd); padding: 12px 16px; max-height: 360px; overflow: auto; font-size: 12px; }
.execution-panel__head, .execution-panel__stdin { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
.execution-panel__item { padding-top: 10px; display: grid; gap: 6px; }
.execution-panel pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 180px; overflow: auto; }
</style>
