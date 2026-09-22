<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import {
  createMemory, editMemory, forgetMemory, memoryItems, memoryProjects, memorySettings, memoryStatus, saveMemorySettings,
  type MemoryConfig, type MemoryInput, type MemoryItem, type MemorySettings, type MemoryStatus,
} from "../api/memories";
import { useNotifications } from "../stores/notifications";
import { fetchCodingModelProfiles } from "../features/coding/api/modelProfiles";
import type { CodingModelProfileSummary } from "../features/coding/model/contracts";

const notify = useNotifications();
const settings = ref<MemorySettings | null>(null);
const draft = ref<MemoryConfig | null>(null);
const status = ref<MemoryStatus | null>(null);
const profiles = ref<CodingModelProfileSummary[]>([]);
const projects = ref<Array<{ id: number; name: string }>>([]);
const projectId = ref<number | null>(null);
const items = ref<MemoryItem[]>([]);
const editing = ref<MemoryItem | null>(null);
const form = ref<MemoryInput>({ scope: "user", kind: "preference", title: "", content: "" });
const busy = ref(false);
const error = ref("");
const feedback = ref("");
let controller = new AbortController();
let generation = 0;

async function run(action: (signal: AbortSignal, valid: () => boolean) => Promise<void>) {
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  const mine = ++generation;
  const valid = () => mine === generation && !signal.aborted;
  busy.value = true;
  error.value = "";
  feedback.value = "";
  try { await action(signal, valid); }
  catch (cause) { if (valid()) error.value = cause instanceof Error ? cause.message : "操作失败，请刷新重试"; }
  finally { if (valid()) busy.value = false; }
}
function acceptSettings(value: MemorySettings) {
  settings.value = value;
  const { version: _version, generation_since: _since, ...config } = value;
  draft.value = config;
}
function resetEditor() {
  editing.value = null;
  form.value = { scope: projectId.value === null ? "user" : "project", kind: projectId.value === null ? "preference" : "project", title: "", content: "" };
}
async function refresh() {
  await run(async (signal, valid) => {
    const [config, state, available, records, models] = await Promise.all([
      memorySettings(signal), memoryStatus(signal), memoryProjects(signal), memoryItems(projectId.value, signal), fetchCodingModelProfiles({ signal }),
    ]);
    if (!valid()) return;
    acceptSettings(config); status.value = state; projects.value = available; items.value = records;
    profiles.value = models.status === "ok" ? models.profiles : [];
    resetEditor();
  });
}
watch(projectId, () => {
  items.value = [];
  resetEditor();
  const project = projectId.value;
  void run(async (signal, valid) => {
    const records = await memoryItems(project, signal);
    if (valid()) items.value = records;
  });
});
watch(() => form.value.scope, scope => { if (scope === "user") form.value.kind = "preference"; });
onMounted(refresh);
onUnmounted(() => { generation++; controller.abort(); });

async function savePolicy() {
  if (busy.value || !draft.value || !settings.value) return;
  const config = { ...draft.value };
  const previous = settings.value;
  await run(async (signal, valid) => {
    if (config.enabled && config.generate_memories && (!previous.enabled || !previous.generate_memories)) {
      const accepted = await notify.confirm({ title: "开启后台记忆生成", confirmLabel: "开启",
        message: "空闲时会把启用后的合格会话片段发送给所选模型，用于提取长期记忆。这些额外模型调用可能产生费用。",
        impact: `每天最多 ${config.max_calls_per_day} 次（UTC）。可随时停止生成，或在单个会话中关闭。` });
      if (!accepted || !valid()) return;
    }
    const value = await saveMemorySettings(config, previous.version, signal);
    if (!valid()) return;
    acceptSettings(value); feedback.value = "记忆设置已保存，从下一次请求起按新设置使用。";
    status.value = null;
    const current = await memoryStatus(signal);
    if (valid()) status.value = current;
  });
}
function selectItem(item: MemoryItem) {
  editing.value = item;
  form.value = { scope: item.scope, kind: item.kind, title: item.title, content: item.content };
}
async function saveItem() {
  if (busy.value || !form.value.title.trim() || !form.value.content.trim()) return;
  const project = projectId.value, selected = editing.value;
  const data = { ...form.value };
  await run(async (signal, valid) => {
    const record = selected ? await editMemory(project, selected, data, signal) : await createMemory(project, data, signal);
    if (!valid()) return;
    items.value = [record, ...items.value.filter(item => item.id !== record.id)];
    resetEditor(); feedback.value = "已保存。你的编辑不会被后台生成覆盖。";
  });
}
async function forget(item: MemoryItem) {
  if (busy.value) return;
  const project = projectId.value;
  await run(async (signal, valid) => {
    const accepted = await notify.confirm({ title: "遗忘这条记忆", message: item.title, danger: true, confirmLabel: "遗忘",
      impact: "删除记忆正文并停止后续召回；保留去重标记以阻止相同内容重新生成。会话原文保持不变。" });
    if (!accepted || !valid()) return;
    await forgetMemory(project, item, signal);
    if (valid()) { items.value = items.value.filter(record => record.id !== item.id); resetEditor(); feedback.value = "已遗忘，下次请求不再引用。"; }
  });
}
const stateLabels = { running: "生成中", completed: "已完成", cancelled: "已取消", failed: "未完成" };
</script>

<template>
  <div class="memory-panel" :aria-busy="busy">
    <p>长期记忆保存可复用的偏好和项目决定，供后续会话参考。项目规则仍由 AGENTS.md 管理，当前会话历史单独保存。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="feedback" role="status">{{ feedback }}</p>
    <p v-if="busy" role="status">正在处理…</p>
    <button class="pa-btn pa-btn--subtle" :disabled="busy" @click="refresh">刷新记忆与设置</button>
    <form v-if="draft" class="memory-panel__section" @submit.prevent="savePolicy">
      <h3>使用与生成</h3>
      <fieldset :disabled="busy">
        <label><input v-model="draft.enabled" type="checkbox">启用本机长期记忆</label>
        <label><input v-model="draft.use_memories" type="checkbox">在模型请求中使用相关记忆</label>
        <label><input v-model="draft.generate_memories" type="checkbox">从空闲会话自动生成记忆</label>
        <label><input v-model="draft.exclude_external_context" type="checkbox">跳过使用过外部文档工具的会话</label>
        <label>生成模型<select v-model="draft.model_profile_id" class="pa-input">
          <option :value="null">沿用会话模型</option>
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{ profile.modelName || profile.id }}</option>
          <option v-if="draft.model_profile_id && !profiles.some(p => p.id === draft?.model_profile_id)" :value="draft.model_profile_id">{{ draft.model_profile_id }}（当前不可用）</option>
        </select></label>
        <label>会话结束后等待（秒）<input v-model.number="draft.idle_seconds" class="pa-input" type="number" min="30" max="86400" step="1" required></label>
        <label>每日生成调用上限（UTC）<input v-model.number="draft.max_calls_per_day" class="pa-input" type="number" min="1" max="100" step="1" required></label>
      </fieldset>
      <p>默认关闭。开启后只处理新产生的合格内容；短会话、活动任务和疑似凭据会被跳过。自动过滤不能保证识别所有敏感内容。</p>
      <button class="pa-btn pa-btn--primary" :disabled="busy">保存记忆设置</button>
    </form>
    <p v-if="status">今日已发起 {{ status.calls_today }} 次生成调用 · 后台{{ status.worker_running ? '已启用' : '未运行' }}<template v-if="status.last_attempt"> · 最近一次{{ stateLabels[status.last_attempt.state] }}<template v-if="status.last_attempt.saved !== undefined">，保存 {{ status.last_attempt.saved }} 条</template></template></p>
    <p v-if="status?.error || status?.last_attempt?.error" role="alert">{{ status.error || status.last_attempt?.error }}</p>
    <section class="memory-panel__section" aria-label="管理长期记忆">
      <h3>记忆内容</h3>
      <label>查看范围<select v-model="projectId" class="pa-input" :disabled="busy">
        <option :value="null">跨项目偏好</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}（含跨项目偏好）</option>
      </select></label>
      <p v-if="!items.length && !busy">此范围暂无记忆。可以手动添加，也可以开启后台生成。</p>
      <article v-for="item in items" :key="item.id" class="memory-panel__item">
        <strong>{{ item.title }}</strong>
        <small>{{ item.scope === 'user' ? '跨项目偏好' : '项目记忆' }} · {{ item.origin === 'user' ? '手动维护' : '自动提取' }}</small>
        <p class="memory-panel__content">{{ item.content }}</p>
        <details v-if="item.source_session_id"><summary>来源会话 {{ item.source_session_id }}</summary><p>来源条目：{{ item.source_item_ids.join('、') }}</p></details>
        <div class="memory-panel__actions"><button class="pa-btn pa-btn--subtle" :disabled="busy" @click="selectItem(item)">编辑</button><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="forget(item)">遗忘</button></div>
      </article>
      <form class="memory-panel__section" @submit.prevent="saveItem">
        <h3>{{ editing ? '编辑记忆' : '添加记忆' }}</h3>
        <fieldset :disabled="busy">
          <label>适用范围<select v-model="form.scope" class="pa-input" :disabled="!!editing">
            <option value="user">跨项目偏好</option><option v-if="projectId !== null" value="project">当前项目</option>
          </select></label>
          <label>类型<select v-model="form.kind" class="pa-input" :disabled="form.scope === 'user'">
            <option value="preference">偏好</option><option value="project">项目决定</option><option value="workflow">工作流经验</option><option value="reference">参考位置</option>
          </select></label>
          <label>标题<input v-model="form.title" class="pa-input" maxlength="120" required></label>
          <label>内容<textarea v-model="form.content" class="pa-input" rows="4" maxlength="1600" required /></label>
        </fieldset>
        <div class="memory-panel__actions"><button class="pa-btn pa-btn--primary" :disabled="busy">保存记忆</button><button v-if="editing" type="button" class="pa-btn pa-btn--subtle" :disabled="busy" @click="resetEditor">取消编辑</button></div>
      </form>
    </section>
  </div>
</template>

<style scoped>
.memory-panel { display: grid; gap: var(--space-4); overflow-wrap: anywhere; font-size: var(--pa-text-body); line-height: 1.6; }
.memory-panel > button, .memory-panel form > button { justify-self: start; }
.memory-panel p { margin: 0; color: var(--color-fg-muted); }
.memory-panel__section { display: grid; gap: var(--space-4); padding-top: var(--space-5); border-top: 1px solid var(--color-border); }
.memory-panel h3 { margin: 0; font-size: 16px; }
.memory-panel fieldset { display: grid; gap: var(--space-3); border: 0; padding: 0; margin: 0; min-width: 0; }
.memory-panel label { display: grid; gap: var(--space-2); }
.memory-panel label:has(input[type='checkbox']) { display: flex; align-items: center; padding: var(--space-3); border-radius: var(--radius-md); background: var(--color-surface-muted); }
.memory-panel__item { display: grid; gap: var(--space-2); padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-lg); }
.memory-panel__item small { color: var(--color-fg-muted); }
.memory-panel__content { white-space: pre-wrap; }
.memory-panel__actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.memory-panel [role='alert'] { color: var(--color-danger-fg); }
.memory-panel [role='status'] { color: var(--color-accent-soft-fg); }
@media (min-width: 900px) {
  .memory-panel fieldset { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .memory-panel label:has(textarea), .memory-panel label:has(input[type='checkbox']), .memory-panel label:has(input[maxlength='120']) { grid-column: 1 / -1; }
}
</style>
