<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { applyAttachmentCleanup, getAttachmentStorage, previewAttachmentCleanup, type AttachmentStorage, type StoredMaterial, type MaterialDraft } from "../api/attachmentStorage";
import TaskAttachmentList from "../features/coding/components/TaskAttachmentList.vue";
import { useNotifications } from "../stores/notifications";
const notify = useNotifications();
const storage = ref<AttachmentStorage | null>(null);
const busy = ref(false), error = ref(""), status = ref("");
let alive = true;
onBeforeUnmount(() => { alive = false; });
function bytes(value: number) { return value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1048576).toFixed(1)} MiB`; }
async function refresh(offset = storage.value?.offset || 0) {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { const result = await getAttachmentStorage(offset); if (alive) storage.value = result; }
  catch (cause) { if (alive) error.value = (cause as Error).message || "附件清单读取失败，请重试"; }
  finally { if (alive) busy.value = false; }
}
async function cleanup(item: StoredMaterial, draft: MaterialDraft) {
  if (busy.value) return;
  busy.value = true; error.value = ""; status.value = "";
  try {
    const preview = await previewAttachmentCleanup(item.id, draft.id);
    if (!alive) return;
    if (!await notify.confirm({ title: `从“${preview.draft.title}”移除 ${preview.name}？`, impact: `保留草稿正文。其他草稿引用 ${preview.remaining_drafts} 个，已发送会话引用 ${preview.sessions.length} 个；预计释放 ${bytes(preview.reclaim_bytes)}。不会修改项目或源文件。`, confirmLabel: "移除草稿引用", danger: true })) return;
    if (!alive) return;
    const result = await applyAttachmentCleanup(preview);
    if (!alive) return;
    status.value = result.cleanup_pending ? "草稿引用已移除，副本清理尚未完成，将在后续清理或重启时重试。" : "草稿引用已移除，正文和已发送材料保留。";
    const updated = await getAttachmentStorage(storage.value?.offset || 0);
    if (alive) storage.value = updated;
  } catch (cause) { if (alive) error.value = (cause as Error).message || "清理未完成，请刷新后重新核对"; }
  finally { if (alive) busy.value = false; }
}
onMounted(() => refresh());
</script>
<template>
  <section class="attachment-storage" aria-label="附件与存储管理">
    <div class="storage-heading"><h3>附件与存储</h3><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="refresh()">刷新材料清单</button></div>
    <p v-if="busy" role="status">正在处理，请稍候…</p><p v-if="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <template v-if="storage">
      <p>{{ storage.total }} 个附件 · 原件快照 {{ bytes(storage.size_bytes) }} · 持久解析缓存 {{ bytes(storage.cache_bytes) }}</p>
      <p>{{ storage.retention }}</p><p class="secondary">{{ storage.cache_policy }}</p>
      <p v-if="!storage.total">目前没有保存的附件。</p>
      <article v-for="item in storage.items" :key="item.id" class="stored-material">
        <TaskAttachmentList :items="[item]" :draft-id="item.drafts[0]?.id" :session-id="item.drafts.length ? undefined : item.sessions[0]?.id" :disabled="busy" />
        <p>{{ item.project_name }} · {{ item.read_status }}</p>
        <div v-for="draft in item.drafts" :key="draft.id" class="material-reference"><span>草稿：{{ draft.title }}{{ draft.session_id ? `（会话 ${draft.session_id}）` : '' }} · 持续保留</span><button class="pa-btn pa-btn--ghost pa-btn--sm" :disabled="busy" @click="cleanup(item, draft)">预览移除影响</button></div>
        <p v-for="session in item.sessions" :key="session.id">已发送：{{ session.title }}（会话 {{ session.id }}）· {{ session.messages }} 条消息引用；随会话保留</p>
        <p v-if="!item.drafts.length && !item.sessions.length">无引用副本，等待文件清理重试。</p>
      </article>
      <div v-if="storage.total > 30" class="storage-heading"><button class="pa-btn pa-btn--ghost" :disabled="busy || storage.offset === 0" @click="refresh(Math.max(0, storage.offset - 30))">上一页</button><span>{{ storage.offset + 1 }}–{{ Math.min(storage.offset + 30, storage.total) }} / {{ storage.total }}</span><button class="pa-btn pa-btn--ghost" :disabled="busy || storage.offset + 30 >= storage.total" @click="refresh(storage.offset + 30)">下一页</button></div>
    </template>
  </section>
</template>
<style scoped>
.attachment-storage { display: grid; gap: 12px; font-size: 13px; line-height: 1.6; margin-top: 24px; border-top: 1px solid var(--color-border); padding-top: 20px; }
.storage-heading, .material-reference { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: space-between; }
h3, p { margin: 0; overflow-wrap: anywhere; }
.stored-material { display: grid; gap: 8px; min-width: 0; border: 1px solid var(--color-border); border-radius: 8px; padding: 12px; }
.secondary { color: var(--color-fg-muted); font-size: 12px; }
[role="alert"] { color: var(--color-danger); }
</style>
