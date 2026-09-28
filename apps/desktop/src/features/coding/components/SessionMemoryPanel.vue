<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { sessionMemorySettings, saveSessionMemorySettings, type SessionMemorySettings } from "../../../api/memories";

const props = defineProps<{ sessionId: number; revision?: number }>();
const state = ref<SessionMemorySettings | null>(null);
const busy = ref(false);
const error = ref("");
const dirty = ref(false);
let generation = 0;
let controller = new AbortController();

async function load(save = false) {
  const session = props.sessionId;
  const data = state.value ? { ...state.value } : null;
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  const mine = ++generation;
  const valid = () => mine === generation && !signal.aborted;
  busy.value = true; error.value = "";
  try {
    const result = save && data ? await saveSessionMemorySettings(session, data, signal) : await sessionMemorySettings(session, signal);
    if (valid()) { state.value = result; dirty.value = false; }
  } catch (cause) {
    if (valid()) error.value = cause instanceof Error ? cause.message : "会话记忆设置读取失败";
  } finally { if (valid()) busy.value = false; }
}
watch(() => props.sessionId, () => { state.value = null; dirty.value = false; void load(); }, { immediate: true });
watch(() => props.revision, () => { if (!busy.value && !dirty.value) void load(); });
onBeforeUnmount(() => { generation++; controller.abort(); });
</script>

<template>
  <section class="session-memory" aria-label="本会话长期记忆" :aria-busy="busy">
    <strong>本会话长期记忆</strong>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="busy" role="status">正在读取或保存…</p>
    <template v-if="state">
      <label><input v-model="state.use_memories" type="checkbox" :disabled="busy" @change="dirty = true">使用已有记忆</label>
      <label><input v-model="state.generate_memories" type="checkbox" :disabled="busy" @change="dirty = true">允许本会话生成记忆</label>
      <p>当前生效：使用{{ state.effective_use ? '开' : '关' }} · 生成{{ state.effective_generate ? '开' : '关' }}。还需在设置中启用对应的全局选项。</p>
      <p v-if="state.last_recall">最近一次请求引用 {{ state.last_recall.recalled_ids.length }} 条记忆，因预算省略 {{ state.last_recall.omitted_ids.length }} 条。</p>
      <button class="pa-btn pa-btn--subtle" :disabled="busy" @click="load(true)">保存会话设置</button>
    </template>
    <button class="pa-btn pa-btn--ghost" :disabled="busy" @click="load()">刷新记忆状态</button>
  </section>
</template>

<style scoped>
.session-memory { display: grid; gap: var(--space-2); border-top: 1px solid var(--color-border); margin-top: var(--space-4); padding-top: var(--space-3); }
.session-memory label { display: flex; align-items: center; gap: var(--space-2); }
.session-memory p { margin: 0; color: var(--color-fg-muted); }
.session-memory [role='alert'] { color: var(--color-danger-fg); }
</style>
