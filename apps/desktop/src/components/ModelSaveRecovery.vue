<script setup lang="ts">
import { onMounted, ref } from "vue";
import { discardModelSave, listModelSaveOperations, removeUnusedModelCredentials, resumeModelSave, unusedModelCredentials, type ModelSaveOperation } from "../api/modelSaves";
import { useNotifications } from "../stores/notifications";
const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false });
const emit = defineEmits<{ applied: []; discarded: [id: string] }>();
const notify = useNotifications();
const operations = ref<ModelSaveOperation[]>([]);
const busy = ref(false);
const error = ref("");
const status = ref("");
async function refresh(): Promise<void> {
  try { operations.value = await listModelSaveOperations(); }
  catch { error.value = "配置保存记录暂时无法读取，请重试。"; }
}
async function resume(operation: ModelSaveOperation): Promise<void> {
  if (busy.value || props.disabled) return;
  busy.value = true;
  error.value = "";
  try { await resumeModelSave(operation); status.value = "配置已保存并应用，尚未调用模型验证。"; emit("applied"); await refresh(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "保存尚未完成，原配置继续保留。"; }
  finally { busy.value = false; }
}
async function discard(operation: ModelSaveOperation): Promise<void> {
  if (busy.value || props.disabled) return;
  if (!await notify.confirm({ title: "放弃这次未完成的保存？", impact: "保留当前活动配置；待提交密钥可通过清理旧凭据解除。", confirmLabel: "放弃保存" })) return;
  busy.value = true;
  try { await discardModelSave(operation.id); emit("discarded", operation.id); await refresh(); }
  catch { error.value = "放弃保存未完成，请重试。"; }
  finally { busy.value = false; }
}
async function cleanCredentials(): Promise<void> {
  if (busy.value || props.disabled) return;
  busy.value = true;
  error.value = "";
  try {
    const aliases = await unusedModelCredentials();
    if (!aliases.length) { status.value = "没有可清理的旧凭据。"; return; }
    if (!await notify.confirm({ title: `清理 ${aliases.length} 项旧凭据？`, impact: "仅清理已无活动配置和待保存配置引用的已知凭据；不会修改模型配置。", confirmLabel: "确认清理", danger: true })) return;
    const count = await removeUnusedModelCredentials(aliases);
    status.value = `已清理 ${count} 项旧凭据。`;
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "清理尚未完成，请重新核对后重试。"; }
  finally { busy.value = false; }
}
onMounted(refresh);
defineExpose({ refresh });
</script>
<template>
  <section class="model-save-recovery" aria-label="配置保存与恢复">
    <p v-if="error" role="alert">{{ error }} <button class="pa-btn pa-btn--subtle" :disabled="busy || disabled" @click="refresh">重新读取</button></p>
    <p v-if="status" role="status">{{ status }}</p>
    <article v-for="operation in operations" :key="operation.id">
      <strong>{{ operation.configuration.name }}：配置保存尚未完成</strong>
      <p>{{ operation.configuration.base_url }}</p>
      <p>{{ operation.credential_ready ? '配置草案与所需凭据已就绪，等待应用。' : '配置草案已保存，密钥尚未确认。若未输入密钥，请在下方表单补齐。' }} 原配置仍在使用。</p>
      <button class="pa-btn pa-btn--primary" :disabled="busy || disabled" @click="resume(operation)">继续保存</button>
      <button class="pa-btn pa-btn--subtle" :disabled="busy || disabled" @click="discard(operation)">放弃这次保存</button>
    </article>
    <button class="pa-btn pa-btn--subtle" :disabled="busy || disabled" @click="cleanCredentials">检查并清理旧凭据</button>
  </section>
</template>
<style scoped>
.model-save-recovery { padding: var(--space-3); border-bottom: 1px solid var(--color-border); }
.model-save-recovery p { font-size: 12px; color: var(--color-fg-muted); overflow-wrap: anywhere; }
.model-save-recovery article { padding-block: var(--space-3); }
.model-save-recovery button { min-height: 32px; margin-right: var(--space-2); }
</style>
