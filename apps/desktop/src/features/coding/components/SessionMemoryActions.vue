<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { editMemory, forgetMemory, memoryItem, type MemoryInput, type MemoryItem } from "../../../api/memories";
import { useNotifications } from "../../../stores/notifications";

const props = defineProps<{ memoryId: string; projectId: number | null; recalledVersion: number }>();
const emit = defineEmits<{ changed: [change: { forgotten: boolean; title?: string; memoryId?: string }] }>();
const notify = useNotifications();
const selected = ref<MemoryItem | null>(null);
const draft = ref<MemoryInput | null>(null);
const busy = ref(false);
const error = ref("");
const feedback = ref("");
let controller = new AbortController();
let generation = 0;

async function run(action: (signal: AbortSignal, valid: () => boolean) => Promise<void>) {
  controller.abort(); controller = new AbortController();
  const signal = controller.signal, mine = ++generation;
  const valid = () => mine === generation && !signal.aborted;
  busy.value = true; error.value = ""; feedback.value = "";
  try { await action(signal, valid); }
  catch (cause) { if (valid()) error.value = cause instanceof Error ? cause.message : "记忆操作失败，请重试"; }
  finally { if (valid()) busy.value = false; }
}
async function edit() {
  await run(async (signal, valid) => {
    const item = await memoryItem(props.projectId, props.memoryId, signal);
    if (!valid()) return;
    selected.value = item;
    draft.value = { scope: item.scope, kind: item.kind, title: item.title, content: item.content };
  });
}
async function save() {
  if (busy.value || !selected.value || !draft.value) return;
  const item = selected.value, data = { ...draft.value };
  await run(async (signal, valid) => {
    const result = await editMemory(props.projectId, item, data, signal);
    if (!valid()) return;
    selected.value = null; draft.value = null;
    feedback.value = "已保存，从下一次请求起使用新内容；本轮引用记录保持原版本。";
    emit("changed", { forgotten: false, title: result.title, memoryId: result.id });
  });
}
async function forget() {
  await run(async (signal, valid) => {
    const item = selected.value ?? await memoryItem(props.projectId, props.memoryId, signal);
    if (!valid()) return;
    const accepted = await notify.confirm({ title: "遗忘这条记忆", message: item.title, danger: true, confirmLabel: "遗忘",
      impact: "删除记忆及修订正文，下次请求不再引用；保留去重标记，会话原文和本轮历史引用记录保持不变。" });
    if (!accepted || !valid()) return;
    await forgetMemory(props.projectId, item, signal);
    if (valid()) { selected.value = null; draft.value = null; emit("changed", { forgotten: true }); }
  });
}
watch(() => [props.memoryId, props.projectId], () => {
  generation++; controller.abort(); selected.value = null; draft.value = null; error.value = ""; feedback.value = ""; busy.value = false;
});
onBeforeUnmount(() => { generation++; controller.abort(); });
</script>

<template>
  <div class="session-memory-actions" :aria-busy="busy">
    <p v-if="error" role="alert">{{ error }}。未提交的编辑已保留。</p>
    <p v-if="feedback" role="status">{{ feedback }}</p>
    <p v-if="busy" role="status">正在处理记忆…</p>
    <div class="session-memory-actions__buttons">
      <button v-if="!draft" class="pa-btn pa-btn--subtle" :disabled="busy" @click="edit">编辑此条</button>
      <button class="pa-btn pa-btn--ghost" :disabled="busy" @click="forget">遗忘此条</button>
    </div>
    <form v-if="draft && selected" aria-label="编辑本轮记忆" @submit.prevent="save">
      <p v-if="selected.version !== recalledVersion">本轮引用版本 {{ recalledVersion }}；正在编辑最新版本 {{ selected.version }}。</p>
      <fieldset :disabled="busy">
        <label>标题<input v-model="draft.title" class="pa-input" maxlength="120" required></label>
        <label>内容<textarea v-model="draft.content" class="pa-input" maxlength="1600" rows="4" required /></label>
      </fieldset>
      <div class="session-memory-actions__buttons">
        <button class="pa-btn pa-btn--primary" :disabled="busy">保存此条</button>
        <button type="button" class="pa-btn pa-btn--ghost" :disabled="busy" @click="draft = null; selected = null">取消编辑</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.session-memory-actions, .session-memory-actions form, .session-memory-actions fieldset, .session-memory-actions label { display: grid; gap: var(--space-2); }
.session-memory-actions fieldset { margin: 0; padding: 0; border: 0; min-width: 0; }
.session-memory-actions__buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.session-memory-actions p { margin: 0; color: var(--color-fg-muted); }
.session-memory-actions [role='alert'] { color: var(--color-danger-fg); }
</style>
