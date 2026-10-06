<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import PaDialog from "../../../design/PaDialog.vue";
import PaSelect from "../../../design/PaSelect.vue";
import type { CodingModelProfileSummary } from "../model/contracts";
import { getModelPreference, setModelPreference, type ModelPreference, type ModelScope } from "../api/modelPreferences";
const props = defineProps<{ projectId: number | null; sessionId: number | null; profiles: CodingModelProfileSummary[]; disabled?: boolean }>();
const emit = defineEmits<{ resolved: [id: string | null, ready: boolean] }>();
const preference = ref<ModelPreference | null>(null);
const busy = ref(false);
const error = ref("");
const open = ref(false);
const scope = ref<ModelScope>("global");
const choice = ref("");
const pendingChoice = "__pending_model_selection__";
const names = { global: "全局默认", project: "项目设置", session: "会话设置" };
let generation = 0;
const label = computed(() => preference.value?.requires_confirmation ? "恢复的模型待确认" : props.profiles.find(item => item.id === preference.value?.profile_id)?.modelName || "未配置模型");
const scopes = computed(() => [
  { value: "global", label: "全局默认" },
  ...(props.projectId ? [{ value: "project", label: "当前项目" }] : []),
  ...(props.sessionId ? [{ value: "session", label: "当前会话" }] : []),
]);
const options = computed(() => [ ...(preference.value?.requires_confirmation ? [{ value: pendingChoice, label: "请选择模型或明确继承上级", disabled: true }] : []), ...(scope.value !== "global" ? [{ value: "", label: "继承上级设置" }] : []),
  ...props.profiles.map(item => ({ value: item.id, label: `${item.modelName || item.displayName} · ${item.providerName || item.provider}` })) ]);
const restoreIdentity = computed(() => preference.value?.restore_source?.source_identity);
const canSave = computed(() => choice.value !== pendingChoice && (choice.value ? props.profiles.some(item => item.id === choice.value) : scope.value !== "global"));
function apply(value: ModelPreference) { preference.value = value; emit("resolved", value.requires_confirmation ? null : value.profile_id, value.available && !value.requires_confirmation); }
async function load() {
  const sequence = ++generation;
  busy.value = true; error.value = ""; emit("resolved", null, false);
  try { const value = await getModelPreference(props.projectId, props.sessionId); if (sequence === generation) apply(value); }
  catch (cause) { if (sequence === generation) error.value = (cause as Error).message || "模型选择读取失败，请重试"; }
  finally { if (sequence === generation) busy.value = false; }
}
function resetChoice() { choice.value = preference.value?.requires_confirmation ? pendingChoice : preference.value?.overrides[scope.value] || ""; }
function show() { scope.value = props.sessionId ? "session" : props.projectId ? "project" : "global"; resetChoice(); open.value = true; }
watch(scope, resetChoice);
async function save() {
  if (busy.value || !canSave.value) return;
  const sequence = generation;
  busy.value = true; error.value = "";
  try { const value = await setModelPreference(scope.value, choice.value || null, props.projectId, props.sessionId); if (sequence === generation) { apply(value); open.value = false; } }
  catch (cause) { if (sequence === generation) error.value = (cause as Error).message || "模型选择未保存，请重试"; }
  finally { if (sequence === generation) busy.value = false; }
}
watch(() => [props.projectId, props.sessionId, props.profiles], () => { open.value = false; void load(); }, { immediate: true, flush: "post" });
onBeforeUnmount(() => { generation += 1; });
</script>
<template>
  <div class="model-scope-picker">
    <button class="pa-btn pa-btn--ghost pa-btn--sm scope-trigger" :disabled="disabled || busy" data-testid="model-scope-picker" @click="show">
      <span>{{ label }}</span><small>{{ preference ? names[preference.source] : '正在读取' }}</small>
    </button>
    <span v-if="preference?.requires_confirmation" class="scope-error" role="alert">恢复的模型选择需重新确认，确认前不能发送。{{ preference.confirmation_reason }}</span>
    <span v-else-if="preference && !preference.available" class="scope-error" role="alert">所选模型不可用，请重新选择</span>
    <span v-if="error && !open" class="scope-error" role="alert">{{ error }} <button class="pa-btn pa-btn--ghost pa-btn--sm" @click="load">重试</button></span>
    <PaDialog :open="open" title="模型选择与作用范围" :dismissible="!busy" @close="open = false">
      <div class="scope-form">
        <div v-if="preference?.requires_confirmation" class="scope-restore" role="alert">
          <p>原模型选择来自{{ names[preference.restore_source?.source_scope || preference.source] }}。请核对供应商与模型后主动选择；相同 ID 不代表相同模型。</p>
          <p v-if="restoreIdentity">{{ restoreIdentity.provider_id }} · {{ restoreIdentity.protocol }}/{{ restoreIdentity.api_format }} · {{ restoreIdentity.base_url }} · {{ restoreIdentity.model_id }}</p>
          <p v-else>旧备份未记录可核对的模型身份。</p>
          <p>选择“继承上级设置”只清除当前范围的恢复标记，上级模型若仍待确认，发送会继续受阻。</p>
        </div>
        <label>应用范围<PaSelect v-model="scope" :options="scopes" :disabled="busy" aria-label="模型应用范围" /></label>
        <label>使用模型<PaSelect v-model="choice" :options="options" :disabled="busy" aria-label="作用域模型" /></label>
        <p>会话设置优先于项目设置，项目设置优先于全局默认。只影响后续发送，当前运行继续使用原模型。</p>
        <p v-if="scope === 'global'">更改全局默认会影响所有未单独设置模型的项目和会话。</p>
        <p v-if="error" role="alert">{{ error }}</p>
        <button class="pa-btn pa-btn--primary" :disabled="busy || !canSave" @click="save">{{ busy ? '正在保存' : '保存选择' }}</button>
      </div>
    </PaDialog>
  </div>
</template>
<style scoped>
.model-scope-picker { min-width: 0; max-width: 220px; }
.scope-trigger { display: grid; gap: 0; text-align: left; max-width: 100%; min-height: 32px; }
.scope-trigger span { overflow: hidden; text-overflow: ellipsis; }
.scope-trigger small { color: var(--color-fg-muted); font-size: 12px; }
.scope-form { display: grid; gap: 14px; font-size: 13px; line-height: 1.5; }
.scope-form label { display: grid; gap: 6px; }
.scope-restore { overflow-wrap: anywhere; }
.scope-error, [role="alert"] { color: var(--color-danger); font-size: 12px; overflow-wrap: anywhere; }
</style>
