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
const names = { global: "全局默认", project: "项目设置", session: "会话设置" };
let generation = 0;
const label = computed(() => props.profiles.find(item => item.id === preference.value?.profile_id)?.modelName || "未配置模型");
const scopes = computed(() => [
  { value: "global", label: "全局默认" },
  ...(props.projectId ? [{ value: "project", label: "当前项目" }] : []),
  ...(props.sessionId ? [{ value: "session", label: "当前会话" }] : []),
]);
const options = computed(() => [ ...(scope.value !== "global" ? [{ value: "", label: "继承上级设置" }] : []),
  ...props.profiles.map(item => ({ value: item.id, label: `${item.modelName || item.displayName} · ${item.providerName || item.provider}` })) ]);
function apply(value: ModelPreference) { preference.value = value; emit("resolved", value.profile_id, value.available); }
async function load() {
  const sequence = ++generation;
  busy.value = true; error.value = ""; emit("resolved", null, false);
  try { const value = await getModelPreference(props.projectId, props.sessionId); if (sequence === generation) apply(value); }
  catch (cause) { if (sequence === generation) error.value = (cause as Error).message || "模型选择读取失败，请重试"; }
  finally { if (sequence === generation) busy.value = false; }
}
function show() { scope.value = props.sessionId ? "session" : props.projectId ? "project" : "global"; choice.value = preference.value?.overrides[scope.value] || ""; open.value = true; }
watch(scope, () => { choice.value = preference.value?.overrides[scope.value] || ""; });
async function save() {
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
    <span v-if="preference && !preference.available" class="scope-error" role="alert">所选模型不可用，请重新选择</span>
    <span v-if="error && !open" class="scope-error" role="alert">{{ error }} <button class="pa-btn pa-btn--ghost pa-btn--sm" @click="load">重试</button></span>
    <PaDialog :open="open" title="模型选择与作用范围" :dismissible="!busy" @close="open = false">
      <div class="scope-form">
        <label>应用范围<PaSelect v-model="scope" :options="scopes" :disabled="busy" aria-label="模型应用范围" /></label>
        <label>使用模型<PaSelect v-model="choice" :options="options" :disabled="busy" aria-label="作用域模型" /></label>
        <p>会话设置优先于项目设置，项目设置优先于全局默认。只影响后续发送，当前运行继续使用原模型。</p>
        <p v-if="scope === 'global'">更改全局默认会影响所有未单独设置模型的项目和会话。</p>
        <p v-if="error" role="alert">{{ error }}</p>
        <button class="pa-btn pa-btn--primary" :disabled="busy || (scope === 'global' && !choice)" @click="save">{{ busy ? '正在保存' : '保存选择' }}</button>
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
.scope-error, [role="alert"] { color: var(--color-danger); font-size: 12px; overflow-wrap: anywhere; }
</style>
