<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  createMemory, editMemory, forgetMemory, memoryItems, memoryProjects, memorySettings, memoryStatus, reviewMemory, saveMemorySettings, searchMemories,
  type MemoryConfig, type MemoryInput, type MemoryItem, type MemorySettings, type MemoryStatus, type MemorySourceTarget,
} from "../api/memories";
import MemoryEvidence from "./MemoryEvidence.vue";
import { useNotifications } from "../stores/notifications";
import { fetchCodingModelProfiles } from "../features/coding/api/modelProfiles";
import type { CodingModelProfileSummary } from "../features/coding/model/contracts";

const notify = useNotifications();
const props = defineProps<{ initialProjectId?: number | null }>();
const emit = defineEmits<{ "open-source": [target: MemorySourceTarget] }>();
const settings = ref<MemorySettings | null>(null);
const draft = ref<MemoryConfig | null>(null);
const status = ref<MemoryStatus | null>(null);
const profiles = ref<CodingModelProfileSummary[]>([]);
const projects = ref<Array<{ id: number; name: string }>>([]);
const projectId = ref<number | null>(props.initialProjectId ?? null);
const rangeTouched = ref(false);
const items = ref<MemoryItem[]>([]);
const pendingCount = computed(() => items.value.filter(item => item.status === "pending_review").length);
const editing = ref<MemoryItem | null>(null);
const form = ref<MemoryInput>({ scope: projectId.value === null ? "user" : "project", kind: "preference", title: "", content: "" });
const busy = ref(false);
const error = ref("");
const feedback = ref("");
const query = ref("");
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
  query.value = "";
  resetEditor();
  if (!settings.value) { void refresh(); return; }
  const project = projectId.value;
  void run(async (signal, valid) => {
    const records = await memoryItems(project, signal);
    if (valid()) items.value = records;
  });
});
watch(() => props.initialProjectId, value => {
  if (!rangeTouched.value && !editing.value && !form.value.title && !form.value.content) projectId.value = value ?? null;
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
    items.value = [record, ...items.value.filter(item => item.id !== record.id && item.id !== selected?.id && item.supersedes_id !== record.id)];
    resetEditor(); feedback.value = `已保存到${record.scope === 'user' ? '跨项目偏好' : '当前项目'}。你的编辑不会被后台生成覆盖。${settings.value?.enabled && settings.value.use_memories ? '' : '当前未启用使用，开关保持不变。'}`;
  });
}
async function forget(item: MemoryItem) {
  if (busy.value) return;
  const project = projectId.value;
  await run(async (signal, valid) => {
    const accepted = await notify.confirm({ title: "遗忘这条记忆", message: item.title, danger: true, confirmLabel: "遗忘",
      impact: "删除记忆及修订正文并停止后续召回；保留去重标记以阻止相同内容重新生成。会话原文保持不变。" });
    if (!accepted || !valid()) return;
    await forgetMemory(project, item, signal);
    if (valid()) { items.value = items.value.filter(record => record.id !== item.id); resetEditor(); feedback.value = "已遗忘，下次请求不再引用。"; }
  });
}
const stateLabels = { running: "生成中", completed: "已完成", cancelled: "已取消", failed: "未完成" };
const memoryStates = { active: "可使用", pending_review: "待复核", stale: "已过期／需更新" };
async function search() {
  const project = projectId.value, text = query.value.trim();
  await run(async (signal, valid) => {
    const result = text ? await searchMemories(project, text, signal) : await memoryItems(project, signal);
    if (valid()) items.value = result;
  });
}
async function review(item: MemoryItem, decision: "accept" | "reject" | "stale") {
  const project = projectId.value;
  await run(async (signal, valid) => {
    if (decision === "reject") {
      const accepted = await notify.confirm({ title: "不采用这条候选", message: item.title, impact: "移除候选正文，保留其去重标记；有冲突的旧记忆恢复使用。", confirmLabel: "不采用" });
      if (!accepted || !valid()) return;
    }
    await reviewMemory(project, item, decision, signal);
    const result = await memoryItems(project, signal);
    if (valid()) { items.value = result; resetEditor(); feedback.value = "记忆复核结果已保存。"; }
  });
}
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
        <label><input v-model="draft.exclude_external_context" type="checkbox">跳过包含 MCP、网页等外部内容的会话</label>
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
      <p v-if="pendingCount">当前列表有 {{ pendingCount }} 条待复核记忆，确认前不会自动使用。</p>
      <label>查看范围<select v-model="projectId" class="pa-input" :disabled="busy" @change="rangeTouched = true">
        <option :value="null">跨项目偏好</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}（含跨项目偏好）</option>
      </select></label>
      <p v-if="projectId === null">当前范围为跨项目偏好。保存后可在所有项目使用；如只适用于一个项目，请先选择该项目。</p>
      <form class="memory-panel__actions" @submit.prevent="search"><input v-model="query" class="pa-input" aria-label="搜索记忆" placeholder="搜索标题、中文关键词或路径" maxlength="500"><button class="pa-btn pa-btn--subtle" :disabled="busy">搜索</button></form>
      <p v-if="!items.length && !busy">此范围暂无记忆。可以手动添加，也可以开启后台生成。</p>
      <article v-for="item in items" :key="item.id" class="memory-panel__item">
        <strong>{{ item.title }}</strong>
        <small>{{ item.scope === 'user' ? '跨项目偏好' : '项目记忆' }} · {{ item.origin === 'user' ? '手动维护' : '自动提取' }} · {{ memoryStates[item.status ?? 'active'] }} · 版本 {{ item.version }}</small>
        <small v-if="item.legacy">历史自动记忆 · 保留原有使用状态，尚未按新策略复核</small>
        <p class="memory-panel__content">{{ item.content }}</p>
        <p v-if="item.review_reason === 'conflict'">同一主题出现不同陈述，复核前不会作为当前事实引用。</p>
        <p v-if="item.review_reason === 'volatile'">工作流、项目事实或参考位置需要核对，确认后再使用。</p>
        <p v-if="item.review_reason === 'cross_project'">跨项目推广需要你确认，确认前不会用于任何项目。</p>
        <p v-if="item.review_reason === 'needs_confirmation'">尚不能核验为用户直接陈述的稳定偏好，请核对来源。</p>
        <details v-if="item.source_session_id"><summary>来源会话 {{ item.source_session_id }}</summary><p>来源条目：{{ item.source_item_ids.join('、') }}</p></details>
        <MemoryEvidence :memory-id="item.id" :project-id="projectId" :source-item-ids="item.source_item_ids" show-revisions @open-source="emit('open-source', $event)" />
        <div class="memory-panel__actions">
          <button v-if="item.status === 'pending_review' || item.status === 'stale'" class="pa-btn pa-btn--subtle" :disabled="busy" @click="review(item, 'accept')">确认使用</button>
          <button v-if="item.status === 'pending_review'" class="pa-btn pa-btn--ghost" :disabled="busy" @click="review(item, 'reject')">不采用</button>
          <button v-if="!item.status || item.status === 'active'" class="pa-btn pa-btn--ghost" :disabled="busy" @click="review(item, 'stale')">标记过期</button>
          <button class="pa-btn pa-btn--subtle" :disabled="busy" @click="selectItem(item)">编辑</button><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="forget(item)">遗忘</button>
        </div>
      </article>
      <form class="memory-panel__section" aria-label="编辑记忆" @submit.prevent="saveItem">
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
