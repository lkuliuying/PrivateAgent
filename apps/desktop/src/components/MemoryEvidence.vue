<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { memoryRevisions, memorySource, type MemoryRevision, type MemorySource, type MemorySourceTarget } from "../api/memories";

const props = defineProps<{ memoryId: string; projectId: number | null; sourceItemIds: string[]; showRevisions?: boolean }>();
const emit = defineEmits<{ "open-source": [target: MemorySourceTarget] }>();
const source = ref<MemorySource | null>(null);
const revisions = ref<MemoryRevision[]>([]);
const error = ref("");
const busy = ref(false);
let controller = new AbortController();
let generation = 0;
const text = computed(() => {
  const raw = source.value?.content ?? "";
  try { const parsed = JSON.parse(raw); return typeof parsed.content === "string" ? parsed.content : raw; }
  catch { return raw; }
});
async function load(sourceId?: string, offset = 0) {
  controller.abort(); controller = new AbortController();
  const signal = controller.signal, mine = ++generation;
  busy.value = true; error.value = "";
  try {
    if (sourceId) {
      const value = await memorySource(props.projectId, props.memoryId, sourceId, offset, signal);
      if (mine === generation && !signal.aborted) source.value = value;
    } else {
      const values = await memoryRevisions(props.projectId, props.memoryId, signal);
      if (mine === generation && !signal.aborted) revisions.value = values;
    }
  } catch (cause) { if (mine === generation && !signal.aborted) error.value = cause instanceof Error ? cause.message : "来源读取失败"; }
  finally { if (mine === generation) busy.value = false; }
}
watch(() => [props.memoryId, props.projectId, props.sourceItemIds.join(",")], () => {
  controller.abort(); generation++; source.value = null; revisions.value = []; error.value = ""; busy.value = false;
});
onBeforeUnmount(() => { generation++; controller.abort(); });
</script>

<template>
  <details class="memory-evidence">
    <summary>查看来源{{ showRevisions ? '与修订' : '' }}</summary>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="busy" role="status">正在读取…</p>
    <p v-if="!sourceItemIds.length">这条记忆没有会话来源，可能由设置页面手动创建。</p>
    <div class="memory-evidence__actions">
      <button v-for="(id, index) in sourceItemIds" :key="id" class="pa-btn pa-btn--ghost" :disabled="busy" @click="load(id)">来源 {{ index + 1 }}</button>
      <button v-if="showRevisions" class="pa-btn pa-btn--ghost" :disabled="busy" @click="load()">修订记录</button>
    </div>
    <template v-if="source">
      <pre>{{ text }}</pre>
      <p>原文 {{ source.offset + 1 }}–{{ source.offset + source.content.length }} / {{ source.total_chars }} 字符</p>
      <button class="pa-btn pa-btn--subtle" @click="emit('open-source', { projectId: source.project_id, sessionId: source.session_id, messageId: source.message_id })">打开来源会话</button>
      <button v-if="source.next_offset !== null" class="pa-btn pa-btn--ghost" :disabled="busy" @click="load(source.item_id, source.next_offset)">继续读取原文</button>
    </template>
    <ol v-if="revisions.length"><li v-for="revision in revisions" :key="revision.version"><strong>版本 {{ revision.version }}</strong> · {{ revision.updated_at }}<p>{{ revision.content }}</p></li></ol>
  </details>
</template>

<style scoped>
.memory-evidence { font-size: var(--pa-text-meta); overflow-wrap: anywhere; }
.memory-evidence summary { cursor: pointer; }
.memory-evidence__actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-block: var(--space-2); }
.memory-evidence pre { white-space: pre-wrap; max-height: 240px; overflow: auto; padding: var(--space-3); background: var(--color-surface-muted); }
.memory-evidence [role='alert'] { color: var(--color-danger-fg); }
.memory-evidence ol { padding-left: var(--space-4); }
</style>
