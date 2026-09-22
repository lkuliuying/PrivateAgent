<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { fetchProjectObserverConfig, saveProjectObserverConfig, type ObserverCheck, type ObserverCheckKind, type ProjectObserverConfig } from "../api/observer";

const props = withDefaults(defineProps<{ projectId: number; disabled?: boolean }>(), { disabled: false });
const emit = defineEmits<{ "busy-change": [busy: boolean] }>();
const config = ref<ProjectObserverConfig | null>(null);
const enabled = ref(false);
const checks = ref<Array<ObserverCheck & { key: number }>>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const saved = ref(false);
const conflicted = ref(false);
let nextKey = 0;
let generation = 0;
let controller: AbortController | undefined;
const locked = computed(() => props.disabled || loading.value || saving.value);
const cleanChecks = computed(() => checks.value.map(item => ({ id: item.id.trim(), kind: item.kind, scope: item.scope.trim() })));
const validation = computed(() => {
  if (enabled.value && checks.value.length === 0) return "启用前请添加至少一项检查。";
  const ids = new Set<string>();
  for (const item of cleanChecks.value) {
    if (!/^[a-z][a-z0-9_-]{0,47}$/.test(item.id)) return "检查标识须以小写字母开头，仅含小写字母、数字、下划线或短横线，最多 48 个字符。";
    if (ids.has(item.id)) return "检查标识不能重复。";
    ids.add(item.id);
    if (!item.scope || item.scope.length > 1000) return "每项检查范围需填写 1 至 1000 个字符。";
  }
  return "";
});
const dirty = computed(() => config.value && (enabled.value !== config.value.enabled || JSON.stringify(cleanChecks.value) !== JSON.stringify(config.value.checks)));
const canSave = computed(() => !!config.value && !!dirty.value && !locked.value && !validation.value && !conflicted.value);
const scopeLabels: Record<ObserverCheckKind, string> = { artifact: "项目内产物相对路径", test: "需通过的登记测试命令", command: "需核对退出结果的命令" };

function applyConfig(value: ProjectObserverConfig) {
  config.value = value;
  enabled.value = value.enabled;
  checks.value = value.checks.map(item => ({ ...item, key: ++nextKey }));
}

async function load() {
  const mine = ++generation;
  controller?.abort();
  const request = new AbortController();
  controller = request;
  loading.value = true;
  error.value = "";
  saved.value = false;
  try {
    const result = await fetchProjectObserverConfig(props.projectId, request.signal);
    if (mine === generation) { applyConfig(result); conflicted.value = false; }
  } catch {
    if (mine === generation && !request.signal.aborted) error.value = "验收检查配置读取失败，请重试。";
  } finally {
    if (mine === generation) loading.value = false;
  }
}

function addCheck() {
  if (locked.value || checks.value.length >= 8) return;
  let index = 1;
  while (checks.value.some(item => item.id === `check-${index}`)) index++;
  checks.value.push({ key: ++nextKey, id: `check-${index}`, kind: "artifact", scope: "" });
  saved.value = false;
}

async function save() {
  if (!canSave.value || !config.value) return;
  const mine = generation;
  const request = new AbortController();
  controller?.abort();
  controller = request;
  saving.value = true;
  emit("busy-change", true);
  error.value = "";
  saved.value = false;
  try {
    const result = await saveProjectObserverConfig(props.projectId, {
      expected_version: config.value.version, enabled: enabled.value, checks: cleanChecks.value,
    }, request.signal);
    if (mine === generation) { applyConfig(result); saved.value = true; }
  } catch (cause) {
    if (mine !== generation || request.signal.aborted) return;
    const failure = cause as { status?: number; code?: string };
    if (failure?.status === 409 || failure?.code === "observer_config_changed") {
      conflicted.value = true;
      error.value = "配置已在别处更新。当前草稿已保留；请重新读取最新配置后再编辑。";
    } else if (failure?.status === 422) {
      error.value = "验收检查未通过校验，草稿已保留。请确认使用项目内相对文件路径或已登记命令，检查内容不能重复，也不能包含换行或受保护路径。";
    } else error.value = "验收检查保存未确认，草稿已保留。请重新读取核对，或重试保存。";
  } finally {
    if (mine === generation) { saving.value = false; emit("busy-change", false); }
  }
}

function preventParentSubmit(event: KeyboardEvent) {
  // 此面板独立保存，输入检查标识时按 Enter 不得提交外层项目表单。
  if (event.target instanceof HTMLInputElement) event.preventDefault();
}

watch(() => props.projectId, () => {
  config.value = null;
  checks.value = [];
  enabled.value = false;
  saving.value = false;
  conflicted.value = false;
  emit("busy-change", false);
  void load();
}, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); });
</script>

<template>
  <section class="project-observer" aria-label="项目验收检查" data-testid="project-observer-settings" @keydown.enter="preventParentSubmit">
    <header><strong>项目验收检查</strong><span v-if="config">配置 v{{ config.version }}</span></header>
    <p class="project-observer-hint">仅对后续新建的修改任务生效，恢复任务沿用原配置。规划、只读任务和用户禁止项优先；检查不会自动执行命令，也不会增加权限。</p>
    <p v-if="loading" role="status">正在读取验收检查…</p>
    <template v-if="config">
      <label class="project-observer-enable"><input v-model="enabled" type="checkbox" :disabled="locked" data-testid="observer-config-enabled" @change="saved = false" />启用项目验收检查</label>
      <p class="project-observer-hint">产物填写项目内的相对文件路径；命令填写完整的已登记命令，并在项目根目录验收。测试检查不接受帮助、版本或仅收集用例的命令，自定义校验脚本请选择“命令退出证据”。主模型仍需通过已有工具和审批完成操作。</p>
      <div v-for="(check, index) in checks" :key="check.key" class="project-observer-check" data-testid="observer-config-check">
        <div class="project-observer-check-head"><strong>检查 {{ index + 1 }}</strong><button type="button" class="pa-btn pa-btn--ghost" :disabled="locked" :aria-label="`移除检查 ${index + 1}`" @click="checks = checks.filter(item => item.key !== check.key); saved = false">移除</button></div>
        <label>检查标识<input v-model="check.id" class="pa-input" maxlength="48" :disabled="locked" data-testid="observer-check-id" @input="saved = false" /></label>
        <label>检查类型<select v-model="check.kind" class="pa-input" :disabled="locked" data-testid="observer-check-kind" @change="saved = false"><option value="artifact">产物存在</option><option value="test">测试通过</option><option value="command">命令退出证据</option></select></label>
        <label>{{ scopeLabels[check.kind] }}<textarea v-model="check.scope" class="pa-input" rows="2" maxlength="1000" :disabled="locked" data-testid="observer-check-scope" @input="saved = false" /></label>
      </div>
      <p v-if="!checks.length" class="project-observer-hint">尚未配置检查，最多可添加 8 项。</p>
      <button type="button" class="pa-btn pa-btn--subtle" :disabled="locked || checks.length >= 8" data-testid="observer-config-add" @click="addCheck">添加检查 · {{ checks.length }}/8</button>
      <p v-if="validation" role="alert">{{ validation }}</p>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="saved" role="status">验收检查已保存，仅影响后续新建任务。</p>
    <div class="project-observer-actions">
      <button type="button" class="pa-btn pa-btn--subtle" :disabled="locked" data-testid="observer-config-reload" @click="load">{{ dirty ? "放弃检查草稿并重新读取" : "重新读取检查" }}</button>
      <button type="button" class="pa-btn pa-btn--subtle" :disabled="!canSave" data-testid="observer-config-save" @click="save">{{ saving ? "保存中…" : "单独保存验收检查" }}</button>
    </div>
  </section>
</template>

<style scoped>
.project-observer { display: grid; gap: var(--space-3); border-top: 1px solid var(--color-border); padding-top: var(--space-4); min-width: 0; font-size: var(--text-sm); }
.project-observer header, .project-observer-check-head, .project-observer-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); flex-wrap: wrap; }
.project-observer header span, .project-observer-hint { color: var(--color-fg-muted); }
.project-observer p { margin: 0; line-height: 1.6; }
.project-observer-check { display: grid; gap: var(--space-2); padding-block: var(--space-2); border-bottom: 1px solid var(--color-border); }
.project-observer-check label { display: grid; gap: var(--space-1); }
.project-observer-check textarea { resize: vertical; width: 100%; }
.project-observer-check .pa-input { min-width: 0; max-width: 100%; }
.project-observer-enable { display: flex; align-items: center; gap: var(--space-2); }
.project-observer [role="alert"] { color: var(--color-danger-fg); }
.project-observer-actions { justify-content: flex-end; }
</style>
