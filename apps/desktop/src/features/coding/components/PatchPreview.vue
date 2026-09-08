<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { fetchPatchPage, patchOperation, type PatchChange, type PatchPage } from "../api/patches";

const props = defineProps<{ runId: string; patchId: string; previewSha: string; changes: PatchChange[] }>();
const selected = ref("");
const page = ref<PatchPage | null>(null);
const offsets = ref<number[]>([]);
const loading = ref(false);
const error = ref("");
let controller: AbortController | undefined;
let sequence = 0;
let pendingOffset = 0;
let pendingHistory: number[] = [];
const change = computed(() => props.changes.find(item => item.change_id === selected.value));

async function load(offset: number, history: number[] = []) {
  controller?.abort();
  controller = new AbortController();
  const mine = ++sequence;
  pendingOffset = offset;
  pendingHistory = [...history];
  loading.value = true;
  error.value = "";
  try {
    const result = await fetchPatchPage(props.runId, props.patchId, selected.value, offset, controller.signal);
    if (mine !== sequence) return;
    if (result.preview_sha256 !== props.previewSha) throw new Error("预览已变化");
    page.value = result;
    offsets.value = [...history];
  } catch {
    if (mine === sequence) error.value = "补丁内容读取失败或预览已变化，请重试";
  } finally {
    if (mine === sequence) loading.value = false;
  }
}
watch(() => [props.runId, props.patchId, props.previewSha], () => {
  sequence++;
  controller?.abort();
  selected.value = "";
  offsets.value = [];
  pendingOffset = 0;
  pendingHistory = [];
  page.value = null;
  error.value = "";
  loading.value = false;
}, { immediate: true });
function select() {
  page.value = null;
  offsets.value = [];
  if (selected.value) void load(0);
}
function next() {
  if (page.value?.next_offset == null || loading.value) return;
  void load(page.value.next_offset, [...offsets.value, page.value.offset]);
}
function previous() {
  if (loading.value || !offsets.value.length) return;
  void load(offsets.value[offsets.value.length - 1]!, offsets.value.slice(0, -1));
}
onBeforeUnmount(() => { sequence++; controller?.abort(); });
</script>

<template>
  <div class="patch-preview" aria-label="分文件完整补丁预览">
    <label>查看文件
      <select v-model="selected" class="pa-input" :disabled="loading" @change="select">
        <option value="" disabled>选择文件（{{ changes.length }} 项）</option>
        <option v-for="item in changes" :key="item.change_id" :value="item.change_id">{{ patchOperation(item.operation) }} · {{ item.rel_path }}</option>
      </select>
    </label>
    <p v-if="change">{{ patchOperation(change.operation) }} · {{ change.rel_path }} · 完整差异 {{ change.diff_chars }} 字符</p>
    <p v-if="loading" role="status">正在读取…</p>
    <p v-if="error" role="alert">{{ error }} <button class="pa-btn pa-btn--subtle" @click="load(pendingOffset, pendingHistory)">重试</button></p>
    <template v-if="page">
      <pre tabindex="0">{{ page.content || "无文本差异，请核对上方操作类型" }}</pre>
      <div class="patch-preview-nav">
        <button class="pa-btn pa-btn--subtle" :disabled="loading || !offsets.length" @click="previous">上一页</button>
        <span>{{ page.offset }}–{{ page.offset + page.content.length }} / {{ page.total_chars }}</span>
        <button class="pa-btn pa-btn--subtle" :disabled="loading || page.next_offset === null" @click="next">下一页</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.patch-preview { padding: var(--space-3); min-width: 0; font-size: var(--pa-text-meta); overflow-wrap: anywhere; }
.patch-preview select { display: block; width: 100%; margin-top: var(--space-1); }
.patch-preview pre { max-height: 300px; overflow: auto; white-space: pre; background: var(--color-bg); padding: var(--space-2); }
.patch-preview-nav { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); flex-wrap: wrap; }
.patch-preview [role="alert"] { color: var(--color-danger-fg); }
</style>
