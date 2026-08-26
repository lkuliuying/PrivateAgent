<script setup lang="ts">
/**
 * ModelProfilesPanel · v0.9.0 H1-D（计划 §5.8）Agent/Coding 模型管理
 *
 * 全局 Provider 与 Coding model profile 的配置闭环：
 * - 列出全部 profile（含停用），支持创建、编辑、验证（受限探测）、
 *   设为默认、启用/停用与删除；
 * - 旧安装一次性导入：发现「全局 Provider 已配置但 profile 为空」时
 *   提供“验证并导入”与“不再提示”（幂等，不静默扩大远程使用范围）；
 * - 所有写操作经 typed API（features/coding/api/modelProfiles.ts），
 *   组件不拼 URL、不接触任何 Provider secret。
 */
import { computed, onMounted, onScopeDispose, ref } from "vue";
import {
  PhCheckCircle,
  PhDownloadSimple,
  PhLightning,
  PhPencilSimple,
  PhPlus,
  PhStar,
  PhTrash,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type {
  CodingModelProfileDetail,
  CodingModelProfileUpsert,
  CodingModelProbeResult,
  CodingProfileImportStatus,
} from "../features/coding/model/contracts";
import {
  deleteCodingModelProfile,
  fetchCodingProfileImportStatus,
  fetchModelToolProbe,
  importCodingModelProfile,
  listCodingModelProfiles,
  probeCodingModelProfile,
  retryModelToolProbe,
  setCodingDefaultProfile,
  upsertCodingModelProfile,
  type ModelToolProbeStatus,
} from "../features/coding/api/modelProfiles";
import { updateSettings } from "../api";
import PaBadge from "../design/PaBadge.vue";
import PaButton from "../design/PaButton.vue";
import PaDialog from "../design/PaDialog.vue";
import PaInlineNotice from "../design/PaInlineNotice.vue";
import PaSpinner from "../design/PaSpinner.vue";

const emit = defineEmits<{ saved: [] }>();

const profiles = ref<CodingModelProfileDetail[]>([]);
const loading = ref(true);
const loadError = ref("");
const busyAction = ref("");

// ============ 一次性导入向导 ============
const importStatus = ref<CodingProfileImportStatus | null>(null);
const importing = ref(false);
const importError = ref("");

const showImportBanner = computed(() => {
  const state = importStatus.value;
  if (!state) return false;
  return state.importState === "pending" || state.importState === "wizard";
});

const importHint = computed(() => {
  const state = importStatus.value;
  if (!state) return "";
  switch (state.reasonCode) {
    case "feature_disabled":
      return "远程 Provider 未启用：请先在「Provider 与隐私」中开启，再导入。";
    case "credentials_missing":
      return "远程 Provider 凭据缺失：请先配置系统凭据，再导入。";
    case "remote_requires_confirmation":
      return "检测到远程 Provider 配置：确认后导入为 Coding 模型（不会扩大远程使用范围）。";
    default:
      return "检测到已配置的全局模型：一键验证并导入为默认 Coding 模型。";
  }
});

// ============ 编辑器 ============
const showEditor = ref(false);
const editingId = ref<string | null>(null);
const saving = ref(false);
const editorError = ref("");
const form = ref<CodingModelProfileUpsert>(emptyForm());

function emptyForm(): CodingModelProfileUpsert {
  return {
    provider: "ollama",
    displayName: "",
    modelName: "",
    isLocal: true,
    nativeToolCalls: true,
    supportsStreaming: true,
    supportsStructuredOutput: false,
    supportsVision: false,
    contextTokens: 32768,
    reasoningEfforts: null,
    usageReporting: true,
    enabled: true,
    isDefault: false,
  };
}

function slugify(text: string): string {
  const slug = text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "coding-model";
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    profiles.value = await listCodingModelProfiles();
  } catch (error) {
    loadError.value = errorText(error);
  } finally {
    loading.value = false;
  }
  try {
    importStatus.value = await fetchCodingProfileImportStatus();
  } catch {
    importStatus.value = null;
  }
}

function errorText(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}

// ============ 探测（受限：可达性/模型存在性，不推断工具能力） ============
const probeResults = ref<Record<string, CodingModelProbeResult>>({});
const probing = ref<string[]>([]);

const PROBE_LABEL: Record<string, { text: string; tone: "success" | "warning" | "danger" }> = {
  ok: { text: "验证通过", tone: "success" },
  tools_unsupported: { text: "可用，但未声明工具调用（仅只读问答）", tone: "warning" },
  provider_unreachable: { text: "Provider 不可达", tone: "danger" },
  model_missing: { text: "Provider 可达，但模型不存在", tone: "danger" },
  credentials_missing: { text: "远程凭据缺失", tone: "danger" },
  feature_disabled: { text: "远程能力未启用", tone: "warning" },
  model_route_missing: { text: "缺少具体模型路由字段（模型标识）", tone: "warning" },
  profile_disabled: { text: "profile 已停用", tone: "warning" },
  probe_failed: { text: "探测失败，请重试", tone: "danger" },
};

async function probe(profile: CodingModelProfileDetail): Promise<void> {
  if (probing.value.includes(profile.id)) return;
  probing.value = [...probing.value, profile.id];
  try {
    probeResults.value = {
      ...probeResults.value,
      [profile.id]: await probeCodingModelProfile(profile.id),
    };
  } catch (error) {
    probeResults.value = {
      ...probeResults.value,
      [profile.id]: {
        status: "probe_failed",
        providerReachable: null,
        modelExists: null,
        nativeToolCalls: null,
        detail: errorText(error),
      },
    };
  } finally {
    probing.value = probing.value.filter((id) => id !== profile.id);
  }
}

// ============ 动作 ============
// ============ v1.0 CT-3（§8.2）：工具能力探测（后台执行，进度/结果/重试） ============
const toolProbes = ref<Record<string, ModelToolProbeStatus>>({});
const toolProbeBusy = ref<string[]>([]);
let toolProbeAbort: AbortController = new AbortController();
let toolProbeTimer: ReturnType<typeof setInterval> | null = null;

const TOOL_PROBE_LABEL: Record<string, string> = {
  none: "工具能力未探测（副作用工具面不可用）",
  running: "工具能力探测中…",
  ok: "工具能力已验证",
  failed: "工具能力探测未通过",
};

async function refreshToolProbe(profileId: string): Promise<void> {
  try {
    const status = await fetchModelToolProbe(profileId, {
      signal: toolProbeAbort?.signal,
    });
    toolProbes.value = { ...toolProbes.value, [profileId]: status };
  } catch {
    /* 状态查询失败保留旧状态；组件卸载时请求已被取消 */
  }
}

async function onToolProbe(profile: CodingModelProfileDetail): Promise<void> {
  if (toolProbeBusy.value.includes(profile.id)) return;
  toolProbeBusy.value = [...toolProbeBusy.value, profile.id];
  try {
    await retryModelToolProbe(profile.id);
  } catch {
    /* running/ineligible 等 409：以状态查询结果为准 */
  } finally {
    toolProbeBusy.value = toolProbeBusy.value.filter((id) => id !== profile.id);
  }
  await refreshToolProbe(profile.id);
}

function startToolProbePolling(profiles: CodingModelProfileDetail[]): void {
  if (toolProbeTimer !== null) return;
  toolProbeTimer = setInterval(() => {
    const running = profiles.filter(
      (profile) =>
        profile.nativeToolCalls &&
        toolProbes.value[profile.id]?.status === "running"
    );
    if (!running.length) return;
    for (const profile of running) void refreshToolProbe(profile.id);
  }, 3000);
}

onScopeDispose(() => {
  toolProbeAbort.abort();
  if (toolProbeTimer !== null) {
    clearInterval(toolProbeTimer);
    toolProbeTimer = null;
  }
});

async function onImport(): Promise<void> {
  if (importing.value) return;
  importing.value = true;
  importError.value = "";
  try {
    await importCodingModelProfile();
    await load();
    emit("saved");
  } catch (error) {
    importError.value = errorText(error);
  } finally {
    importing.value = false;
  }
}

async function onDismissImport(): Promise<void> {
  importStatus.value = { ...(importStatus.value as CodingProfileImportStatus), importState: "dismissed" };
  try {
    await updateSettings({ coding_profile_import_state: "dismissed" });
  } catch {
    /* 关闭状态落盘失败不阻断界面；下次启动仍会评估 */
  }
}

async function onSetDefault(profile: CodingModelProfileDetail): Promise<void> {
  busyAction.value = `default:${profile.id}`;
  try {
    await setCodingDefaultProfile(profile.id);
    await load();
    emit("saved");
  } finally {
    busyAction.value = "";
  }
}

async function onToggleEnabled(profile: CodingModelProfileDetail): Promise<void> {
  busyAction.value = `toggle:${profile.id}`;
  try {
    await upsertCodingModelProfile(profile.id, {
      provider: profile.provider,
      displayName: profile.displayName,
      modelName: profile.modelName,
      isLocal: profile.isLocal,
      nativeToolCalls: profile.nativeToolCalls,
      supportsStreaming: profile.supportsStreaming,
      supportsStructuredOutput: profile.supportsStructuredOutput,
      supportsVision: profile.supportsVision,
      contextTokens: profile.contextTokens,
      reasoningEfforts: profile.reasoningEfforts,
      usageReporting: profile.usageReporting,
      enabled: !profile.enabled,
      isDefault: false,
    });
    await load();
    emit("saved");
  } finally {
    busyAction.value = "";
  }
}

async function onDelete(profile: CodingModelProfileDetail): Promise<void> {
  const confirmed = window.confirm(
    `删除模型「${profile.displayName}」？\n\n删除后新执行不能再选择该模型；既有执行保留创建时快照，不受影响。`
  );
  if (!confirmed) return;
  busyAction.value = `delete:${profile.id}`;
  try {
    await deleteCodingModelProfile(profile.id);
    await load();
    emit("saved");
  } finally {
    busyAction.value = "";
  }
}

function openCreate(): void {
  editingId.value = null;
  form.value = emptyForm();
  editorError.value = "";
  showEditor.value = true;
}

function openEdit(profile: CodingModelProfileDetail): void {
  editingId.value = profile.id;
  form.value = {
    provider: profile.provider,
    displayName: profile.displayName,
    modelName: profile.modelName ?? "",
    isLocal: profile.isLocal,
    nativeToolCalls: profile.nativeToolCalls,
    supportsStreaming: profile.supportsStreaming,
    supportsStructuredOutput: profile.supportsStructuredOutput,
    supportsVision: profile.supportsVision,
    contextTokens: profile.contextTokens,
    reasoningEfforts: profile.reasoningEfforts,
    usageReporting: profile.usageReporting,
    enabled: profile.enabled,
    isDefault: false,
  };
  editorError.value = "";
  showEditor.value = true;
}

async function onSave(): Promise<void> {
  if (saving.value) return;
  if (!form.value.displayName.trim()) {
    editorError.value = "显示名称不能为空";
    return;
  }
  saving.value = true;
  editorError.value = "";
  const id = editingId.value ?? `${slugify(form.value.provider)}-${slugify(form.value.displayName)}-${Date.now().toString(36)}`;
  try {
    await upsertCodingModelProfile(id, {
      ...form.value,
      modelName: (form.value.modelName ?? "").trim() || null,
    });
    showEditor.value = false;
    await load();
    emit("saved");
  } catch (error) {
    editorError.value = errorText(error);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await load();
  // 首次拉取各启用 profile 的工具能力探测状态；运行中状态轮询刷新。
  const probeTargets = profiles.value.filter((p) => p.nativeToolCalls);
  for (const profile of probeTargets) void refreshToolProbe(profile.id);
  startToolProbePolling(profiles.value);
});
</script>

<template>
  <div class="model-profiles" data-testid="model-profiles-panel">
    <!-- 一次性导入向导（旧配置 → 默认 profile，幂等） -->
    <PaInlineNotice
      v-if="showImportBanner"
      tone="info"
      data-testid="model-import-banner"
    >
      <div class="import-row">
        <PhDownloadSimple :size="16" aria-hidden="true" />
        <span class="import-hint">{{ importHint }}</span>
        <PaButton
          size="sm"
          variant="primary"
          data-testid="model-import-run"
          :disabled="importing"
          @click="void onImport()"
        >
          <PaSpinner v-if="importing" :size="14" />
          <template v-else>验证并导入</template>
        </PaButton>
        <PaButton size="sm" variant="ghost" data-testid="model-import-dismiss" @click="void onDismissImport()">
          不再提示
        </PaButton>
      </div>
      <p v-if="importError" class="import-error">{{ importError }}</p>
    </PaInlineNotice>

    <!-- 列表 -->
    <div v-if="loading" class="load-row"><PaSpinner :size="16" /> 加载模型配置…</div>
    <PaInlineNotice v-else-if="loadError" tone="danger">{{ loadError }}</PaInlineNotice>
    <p v-else-if="!profiles.length" class="empty-hint" data-testid="model-profiles-empty">
      尚无 Coding 模型 profile。可从上方导入当前配置，或新建一个。
    </p>
    <ul v-else class="profile-list">
      <li
        v-for="profile in profiles"
        :key="profile.id"
        class="profile-row"
        :data-testid="`model-profile-row-${profile.id}`"
      >
        <div class="profile-main">
          <span class="profile-name">
            <PhStar v-if="profile.isDefault" :size="13" weight="fill" class="default-star" aria-label="默认" />
            {{ profile.displayName }}
          </span>
          <span class="profile-meta">
            {{ profile.provider }} · {{ profile.modelName || "未填写模型标识" }}
            · {{ profile.isLocal ? "本地" : "远程" }}
            · 上下文 {{ profile.contextTokens.toLocaleString() }}
          </span>
          <div class="profile-badges">
            <PaBadge v-if="profile.isDefault" tone="success">默认</PaBadge>
            <PaBadge v-if="!profile.enabled" tone="warning">已停用</PaBadge>
            <PaBadge v-if="profile.nativeToolCalls" tone="info">工具调用</PaBadge>
            <PaBadge v-else tone="warning">仅问答</PaBadge>
          </div>
          <p
            v-if="probeResults[profile.id]"
            class="probe-line"
            :data-testid="`model-probe-${profile.id}`"
          >
            <PhCheckCircle
              v-if="probeResults[profile.id].status === 'ok'"
              :size="13"
              class="probe-ok"
              aria-hidden="true"
            />
            <PhWarningCircle v-else :size="13" class="probe-warn" aria-hidden="true" />
            {{ PROBE_LABEL[probeResults[profile.id].status]?.text ?? probeResults[profile.id].status }}
            <template v-if="probeResults[profile.id].detail"> · {{ probeResults[profile.id].detail }}</template>
          </p>
          <!-- v1.0 CT-3（§8.2）：工具能力探测状态（后台执行；未验证时副作用工具面失败关闭） -->
          <p
            v-if="profile.nativeToolCalls && toolProbes[profile.id]"
            class="probe-line"
            :data-testid="`tool-probe-${profile.id}`"
          >
            <PhCheckCircle
              v-if="toolProbes[profile.id].status === 'ok'"
              :size="13"
              class="probe-ok"
              aria-hidden="true"
            />
            <PhWarningCircle v-else :size="13" class="probe-warn" aria-hidden="true" />
            {{ TOOL_PROBE_LABEL[toolProbes[profile.id].status] ?? toolProbes[profile.id].status }}
            <template v-if="toolProbes[profile.id].status === 'ok'">
              · {{ toolProbes[profile.id].pass_count }}/{{ toolProbes[profile.id].sample_count }}
            </template>
            <template v-else-if="toolProbes[profile.id].error_code">
              · {{ toolProbes[profile.id].error_code }}
            </template>
          </p>
        </div>
        <div class="profile-actions">
          <PaButton
            v-if="profile.nativeToolCalls"
            size="sm"
            variant="ghost"
            :data-testid="`tool-probe-btn-${profile.id}`"
            :disabled="toolProbeBusy.includes(profile.id) || toolProbes[profile.id]?.status === 'running'"
            @click="void onToolProbe(profile)"
          >
            <PaSpinner
              v-if="toolProbeBusy.includes(profile.id) || toolProbes[profile.id]?.status === 'running'"
              :size="13"
            />
            <template v-else>探测能力</template>
          </PaButton>
          <PaButton
            size="sm"
            variant="ghost"
            :data-testid="`model-probe-btn-${profile.id}`"
            :disabled="probing.includes(profile.id)"
            @click="void probe(profile)"
          >
            <PaSpinner v-if="probing.includes(profile.id)" :size="13" />
            <template v-else>验证</template>
          </PaButton>
          <PaButton
            v-if="!profile.isDefault && profile.enabled"
            size="sm"
            variant="ghost"
            :data-testid="`model-default-btn-${profile.id}`"
            :disabled="busyAction === `default:${profile.id}`"
            @click="void onSetDefault(profile)"
          >设为默认</PaButton>
          <PaButton
            size="sm"
            variant="ghost"
            :disabled="busyAction === `toggle:${profile.id}`"
            @click="void onToggleEnabled(profile)"
          >{{ profile.enabled ? "停用" : "启用" }}</PaButton>
          <PaButton size="sm" variant="ghost" :aria-label="`编辑 ${profile.displayName}`" @click="openEdit(profile)">
            <PhPencilSimple :size="13" />
          </PaButton>
          <PaButton
            size="sm"
            variant="ghost"
            :aria-label="`删除 ${profile.displayName}`"
            :disabled="busyAction === `delete:${profile.id}`"
            @click="void onDelete(profile)"
          >
            <PhTrash :size="13" />
          </PaButton>
        </div>
      </li>
    </ul>

    <div class="panel-actions">
      <PaButton variant="primary" data-testid="model-profile-create" @click="openCreate">
        <PhPlus :size="14" /> 新建 Coding 模型
      </PaButton>
      <span class="panel-note">
        <PhLightning :size="12" aria-hidden="true" />
        模型能力以显式声明为准（不按名称推断）；不支持工具调用的模型仅可用于只读问答。
      </span>
    </div>

    <!-- 创建/编辑对话框 -->
    <PaDialog
      :open="showEditor"
      :title="editingId ? '编辑 Coding 模型' : '新建 Coding 模型'"
      data-testid="model-profile-editor"
      @close="showEditor = false"
    >
      <div class="editor-form">
        <label class="field">
          <span>Provider</span>
          <select v-model="form.provider">
            <option value="ollama">Ollama（本地）</option>
            <option value="openai">OpenAI 兼容（远程）</option>
            <option value="claude">Claude（远程）</option>
          </select>
        </label>
        <label class="field">
          <span>显示名称</span>
          <input v-model="form.displayName" maxlength="200" placeholder="例如：本地编码模型" />
        </label>
        <label class="field">
          <span>模型标识（实际路由的 model）</span>
          <input
            v-model="form.modelName"
            maxlength="200"
            data-testid="model-profile-editor-model-name"
            placeholder="例如：qwen3-coder（缺失时执行会失败关闭）"
          />
        </label>
        <label class="field">
          <span>上下文窗口（tokens）</span>
          <input v-model.number="form.contextTokens" type="number" min="1" />
        </label>
        <label class="check"><input v-model="form.isLocal" type="checkbox" /> 本地模型（不发送远程）</label>
        <label class="check">
          <input v-model="form.nativeToolCalls" type="checkbox" data-testid="model-profile-editor-tools" />
          支持原生工具调用（Coding 执行必需）
        </label>
        <label class="check"><input v-model="form.supportsStreaming" type="checkbox" /> 支持流式输出</label>
        <label class="check"><input v-model="form.usageReporting" type="checkbox" /> Provider 上报 token 用量</label>
        <label class="check"><input v-model="form.enabled" type="checkbox" /> 启用</label>
        <label v-if="!editingId" class="check">
          <input v-model="form.isDefault" type="checkbox" data-testid="model-profile-editor-default" />
          设为默认 Coding 模型
        </label>
        <PaInlineNotice v-if="editorError" tone="danger">{{ editorError }}</PaInlineNotice>
      </div>
      <template #footer>
        <PaButton variant="ghost" @click="showEditor = false">取消</PaButton>
        <PaButton variant="primary" data-testid="model-profile-save" :disabled="saving" @click="void onSave()">
          <PaSpinner v-if="saving" :size="14" />
          <template v-else>保存</template>
        </PaButton>
      </template>
    </PaDialog>
  </div>
</template>

<style scoped>
.model-profiles {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.import-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.import-hint {
  flex: 1;
  min-width: 200px;
}
.import-error {
  margin: var(--space-2) 0 0;
  color: var(--color-danger);
  font-size: var(--pa-text-meta);
}
.load-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
}
.empty-hint {
  margin: 0;
  color: var(--color-fg-subtle);
}
.profile-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.profile-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.profile-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.profile-name {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-weight: 600;
}
.default-star {
  color: var(--color-warning);
}
.profile-meta {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.profile-badges {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.probe-line {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.probe-ok {
  color: var(--color-success);
}
.probe-warn {
  color: var(--color-warning);
}
.profile-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
  flex-shrink: 0;
}
.panel-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.panel-note {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.editor-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--pa-text-meta);
}
.field input,
.field select {
  height: 32px;
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
}
.check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--pa-text-meta);
}
</style>
