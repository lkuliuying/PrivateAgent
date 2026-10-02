<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { TaskAttachment } from "../../../types";
import PaDialog from "../../../design/PaDialog.vue";
import PaButton from "../../../design/PaButton.vue";
import { importTaskAttachment, readTaskAttachment } from "../api/attachments";
const props = defineProps<{ items: TaskAttachment[]; draftId?: string; sessionId?: number; removable?: boolean; disabled?: boolean }>();
const emit = defineEmits<{ remove: [item: TaskAttachment] }>();
const selected = ref<TaskAttachment | null>(null);
const content = ref("");
const pageNumber = ref(1);
const imageUrl = ref("");
const nextOffset = ref<number | null>(null);
const busy = ref(false);
const error = ref("");
const target = ref("");
const importing = ref(false);
const imported = ref(false);
let generation = 0;
function closePreview(): void { generation += 1; selected.value = null; busy.value = false; }
onBeforeUnmount(() => { generation += 1; });
watch(() => [props.draftId, props.sessionId], closePreview);
const owner = computed(() => props.draftId ? { draft_id: props.draftId } : { session_id: props.sessionId });
async function readMore(): Promise<void> {
  if (!selected.value || busy.value) return;
  const mine = generation;
  busy.value = true;
  error.value = "";
  try {
    const page = await readTaskAttachment(selected.value.id, owner.value, nextOffset.value ?? 0, pageNumber.value);
    if (mine !== generation) return;
    content.value += page.content;
    imageUrl.value = page.image_data_url?.startsWith("data:image/jpeg;base64,") ? page.image_data_url : "";
    nextOffset.value = page.next_offset;
  } catch (cause) { if (mine === generation) error.value = (cause as { message?: string }).message || "附件读取失败，请重新选择。"; }
  finally { if (mine === generation) busy.value = false; }
}
async function preview(item: TaskAttachment): Promise<void> {
  generation += 1;
  busy.value = false;
  selected.value = item;
  content.value = "";
  pageNumber.value = 1;
  imageUrl.value = "";
  nextOffset.value = null;
  target.value = item.name;
  importing.value = false;
  imported.value = false;
  await readMore();
}
async function changePage(value: number): Promise<void> {
  if (busy.value || !selected.value || value < 1 || value > (selected.value.page_count ?? 1)) return;
  generation += 1;
  pageNumber.value = value;
  content.value = "";
  imageUrl.value = "";
  nextOffset.value = null;
  await readMore();
}
async function importFile(): Promise<void> {
  if (!selected.value || busy.value) return;
  busy.value = true;
  error.value = "";
  const mine = generation;
  try { await importTaskAttachment(selected.value.id, owner.value, target.value.trim()); if (mine === generation) { imported.value = true; importing.value = false; } }
  catch (cause) { if (mine === generation) error.value = (cause as { message?: string }).message || "导入未完成，请检查目标路径。"; }
  finally { if (mine === generation) busy.value = false; }
}
</script>
<template>
  <div v-if="items.length" class="task-attachments" aria-label="对话附件">
    <span v-for="item in items" :key="item.id" class="task-attachment">
      <button type="button" :disabled="disabled" :title="item.error ?? '预览附件'" @click="preview(item)">{{ item.name }} · {{ item.kind === "pdf" ? `PDF ${item.page_count} 页 · ` : item.kind === "image" ? "图片 · " : "" }}{{ item.size_bytes }} 字节 · {{ item.error ? '不可读取' : '已保存副本' }}</button>
      <button v-if="removable" type="button" :disabled="disabled" :aria-label="'移除附件 ' + item.name" @click="emit('remove', item)">×</button>
    </span>
    <p v-if="items.some(item => item.kind === 'image' || item.kind === 'pdf')" class="media-notice">图片和 PDF 单文件最多 10 MiB、PDF 最多 50 页，每条消息最多 8 个附件。PDF 文字在本机提取；发送后图片和扫描页会按需交给所选视觉模型，页面最长边缩放至 1536 像素。仅添加和预览不会调用模型。</p>
  </div>
  <PaDialog :open="Boolean(selected)" :title="selected?.name ?? '附件预览'" :width="720" :dismissible="!busy" @close="closePreview">
    <p>附件保存在应用内；仅在确认导入后创建项目文件。文本分段读取，PDF 按页预览。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="selected?.kind === 'pdf'" class="page-controls">
      <PaButton :disabled="busy || pageNumber <= 1" @click="changePage(pageNumber - 1)">上一页</PaButton>
      <span role="status">第 {{ pageNumber }} / {{ selected.page_count }} 页</span>
      <PaButton :disabled="busy || pageNumber >= (selected.page_count ?? 1)" @click="changePage(pageNumber + 1)">下一页</PaButton>
    </div>
    <p v-if="busy" role="status">正在读取附件…</p>
    <img v-if="imageUrl" class="attachment-image" :src="imageUrl" :alt="`${selected?.name} 第 ${pageNumber} 页预览`" />
    <p v-if="selected?.kind === 'pdf' && !content && !busy && !error">本页没有可提取文字，可由视觉模型读取页面图片。</p>
    <pre v-if="content" class="attachment-content">{{ content }}</pre>
    <PaButton v-if="nextOffset !== null" :loading="busy" @click="readMore">继续读取</PaButton>
    <p v-if="imported" role="status">已创建项目文件：{{ target }}。对话附件仍保留。</p>
    <label v-if="importing" class="import-target">导入到项目的相对路径
      <input v-model="target" class="pa-input" aria-label="附件导入目标路径" :disabled="busy" />
      <span>确认后创建新文件；已有文件不会被覆盖。</span>
    </label>
    <template #footer>
      <PaButton :disabled="busy" @click="closePreview">关闭</PaButton>
      <PaButton v-if="!importing" :disabled="busy || Boolean(error)" @click="importing = true">导入项目…</PaButton>
      <PaButton v-else variant="primary" :disabled="!target.trim()" :loading="busy" @click="importFile">确认创建项目文件</PaButton>
    </template>
  </PaDialog>
</template>
<style scoped>
.task-attachments { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.task-attachment { display: inline-flex; max-width: 100%; align-items: center; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.task-attachment button { min-height: 32px; min-width: 32px; border: 0; background: transparent; color: var(--color-fg); font-size: 12px; overflow-wrap: anywhere; cursor: pointer; }
.task-attachment button:disabled { opacity: .5; cursor: not-allowed; }
.task-attachment button:hover:not(:disabled) { background: var(--color-surface-sunken); }
.task-attachment button:focus-visible { outline: var(--focus-ring); outline-offset: -2px; }
.attachment-content { max-height: 45vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.5; }
.media-notice { flex-basis: 100%; margin: 4px 0; font-size: 12px; line-height: 1.5; color: var(--color-fg-muted); }
.page-controls { display: flex; align-items: center; justify-content: center; gap: 12px; }
.attachment-image { display: block; max-width: 100%; max-height: 45vh; object-fit: contain; margin: 12px auto; }
.import-target { display: grid; gap: 8px; margin-top: 12px; }
</style>
