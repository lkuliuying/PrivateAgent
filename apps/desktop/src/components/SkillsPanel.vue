<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { createSkill, enableSkill, listSkills, readSkill, type LocalSkill } from "../features/coding/api/skills";
const props = defineProps<{ projectId: number }>();
const items = ref<LocalSkill[]>([]), loading = ref(false), busy = ref(false), error = ref("");
const preview = ref(""), previewSkill = ref<LocalSkill | null>(null);
const creating = ref(false), name = ref(""), scope = ref("project");
const content = ref('---\nname: project-review\ndescription: 审查项目改动并核对验证证据\nrequires: ["git"]\n---\n\n先阅读项目规则，再检查差异；按影响报告可复现的问题，附文件和行号。\n');
let controller: AbortController | undefined;
let generation = 0;
async function load() {
  const mine = ++generation; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = "";
  try { const result = await listSkills(props.projectId, controller.signal); if (mine === generation) items.value = result.items; }
  catch (cause) { if (mine === generation && !controller.signal.aborted) error.value = (cause as { message?: string }).message || "技能读取失败"; }
  finally { if (mine === generation) loading.value = false; }
}
async function inspect(skill: LocalSkill) {
  if (!skill.version) return;
  const mine = generation; error.value = "";
  try { const result = await readSkill(props.projectId, skill, controller?.signal); if (mine === generation) { preview.value = result.content; previewSkill.value = skill; } }
  catch (cause) { if (mine === generation) error.value = (cause as { message?: string }).message || "技能读取失败"; }
}
async function toggle(skill: LocalSkill) {
  if (busy.value) return; busy.value = true;
  try { await enableSkill(props.projectId, skill, !skill.enabled); previewSkill.value = null; await load(); }
  catch (cause) { error.value = (cause as { message?: string }).message || "启用失败"; }
  finally { busy.value = false; }
}
async function save() {
  if (busy.value) return; busy.value = true;
  try { await createSkill(props.projectId, { name: name.value, scope: scope.value, content: content.value }); creating.value = false; await load(); }
  catch (cause) { error.value = (cause as { message?: string }).message || "保存失败，请检查名称是否已存在"; }
  finally { busy.value = false; }
}
watch(() => props.projectId, () => { previewSkill.value = null; void load(); }, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); });
</script>
<template>
  <section class="skills-panel" aria-label="Skills 技能">
    <div class="skills-heading"><div><h2>Skills 技能</h2><p>项目技能来自 .agents/skills；用户技能保存在本机资料目录，可在不同项目中启用。正文按需读取，权限沿用当前任务。</p></div><button class="pa-btn pa-btn--subtle" :disabled="loading" @click="load">重新扫描</button><button class="pa-btn pa-btn--primary" @click="creating = !creating">新建技能</button></div>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="loading" role="status">正在扫描…</p>
    <form v-if="creating" class="skill-form" @submit.prevent="save"><label>目录名称<input v-model="name" class="pa-input" required pattern="[a-zA-Z0-9_-]{1,64}" placeholder="project-review" /></label><label>作用域<select v-model="scope" class="pa-input"><option value="project">当前项目</option><option value="user">当前用户</option></select></label><label>SKILL.md<textarea v-model="content" class="pa-input" rows="12" maxlength="64000" /></label><button class="pa-btn pa-btn--primary" :disabled="busy">保存后检查</button></form>
    <p v-if="!loading && !items.length">暂无技能。创建一个 SKILL.md，或把已有技能目录放入项目的 .agents/skills 后重新扫描。</p>
    <article v-for="skill in items" :key="skill.id" class="skill-row"><div><strong>{{ skill.name }}</strong><small>{{ skill.scope === 'user' ? '用户' : '项目' }} · {{ skill.enabled ? '已启用' : '未启用或内容已变化' }}</small><p>{{ skill.description }}</p><p v-if="skill.error" role="alert">{{ skill.error }}</p><p v-if="skill.missing_dependencies.length">缺少命令：{{ skill.missing_dependencies.join('、') }}</p></div><button class="pa-btn pa-btn--subtle" :disabled="!skill.version" @click="inspect(skill)">检查内容</button><button v-if="skill.enabled" class="pa-btn pa-btn--ghost" :disabled="busy" @click="toggle(skill)">停用</button></article>
    <section v-if="previewSkill" class="skill-preview"><div class="skills-heading"><strong>{{ previewSkill.name }}</strong><button class="pa-btn pa-btn--ghost" @click="previewSkill = null">关闭</button></div><pre>{{ preview }}</pre><button class="pa-btn pa-btn--primary" :disabled="busy || !!previewSkill.missing_dependencies.length" @click="toggle(previewSkill)">{{ previewSkill.enabled ? '停用' : '允许当前项目按需使用' }}</button></section>
  </section>
</template>
<style scoped>
.skills-panel { display: grid; gap: 18px; font-size: 14px; }
.skills-heading { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }.skills-heading > div { flex: 1; min-width: 240px; }
h2, p { margin: 0 0 8px; } h2 { font-size: 18px; } p, small { color: var(--color-fg-muted); line-height: 1.6; }
.skill-row { display: flex; gap: 12px; align-items: center; padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-lg); flex-wrap: wrap; }.skill-row > div { flex: 1; min-width: 230px; }.skill-row small { display: block; margin: 4px 0; }
.skill-form, .skill-form label { display: grid; gap: 8px; }.skill-form { gap: 16px; padding: var(--space-5); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface-muted); } .skill-form > button { justify-self: start; }.skill-form textarea { font-family: var(--font-mono); }
.skill-preview { padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface-muted); }.skill-preview pre { max-height: 45vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
[role="alert"] { color: var(--color-danger-fg); }
</style>
