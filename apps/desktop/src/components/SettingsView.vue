<script setup lang="ts">
import McpIntegrationsPanel from "./McpIntegrationsPanel.vue";
import { useCodingWorkspace } from "../features/coding/model/codingWorkspaceStore";
const codingWorkspace = useCodingWorkspace();
import WallpaperSettingsPanel from "./ExtensionRegistryPanel.vue";
import { ref, computed, onMounted } from "vue";
import { PhArchiveBox, PhCpu, PhInfo, PhPlugs } from "@phosphor-icons/vue";
import { listModelProviders, type ModelProvider } from "../api";
import UpdateChecker from "./UpdateChecker.vue";
import DocumentationMcpPanel from "./DocumentationMcpPanel.vue";
import MemorySettingsPanel from "./MemorySettingsPanel.vue";
import ModelProvidersPanel from "./ModelProvidersPanel.vue";
import ProfileSettingsPanel from "./ProfileSettingsPanel.vue";
import HistoryMigration from "./HistoryMigration.vue";
import {
  settingsSectionMeta,
  type SettingsSection,
} from "../models/settingsSections";

import { fetchCodingModelProfiles } from "../features/coding/api/modelProfiles";
import type { CodingModelProfileSummary } from "../features/coding/model/contracts";

/**
 * v0.9.0 H1-D（计划 §5.8）：配置闭环往返——PrivateAgent 入口与 Coding 首页
 * 阻塞操作都定位到同一模型管理区（focusSection），保存后自动返回
 * returnTo 视图（项目/会话/草稿由调用方保留）。
 */
const props = withDefaults(
  defineProps<{
    activeSection?: SettingsSection;
    focusSection?: SettingsSection | null;
    returnTo?: string | null;
  }>(),
  { activeSection: "current-model", focusSection: null, returnTo: null }
);
const emit = defineEmits<{
  (e: "reconfigure"): void;
  (e: "return"): void;
  (e: "select-section", section: SettingsSection): void;
}>();
const currentSectionMeta = computed(() => settingsSectionMeta(props.activeSection));
const sectionSubtitle = computed(() => currentSectionMeta.value.description);

async function onModelProfilesSaved(): Promise<void> {
  await Promise.all([useCodingWorkspace().refresh(), loadCurrentModel()]);
  if (props.returnTo) emit("return");
}
const modelProviders = ref<ModelProvider[]>([]);
const modelProfiles = ref<CodingModelProfileSummary[]>([]);

async function loadCurrentModel(): Promise<void> {
  try {
    // 供应商列表读取会先完成后端的统一默认 Profile 校正；随后再读取
    // Profile，保证当前模型卡片与实际请求使用同一份事实。
    modelProviders.value = await listModelProviders();
  } catch {
    modelProviders.value = [];
  }
  try {
    const result = await fetchCodingModelProfiles();
    modelProfiles.value = result.status === "ok" ? result.profiles : [];
  } catch {
    modelProfiles.value = [];
  }
}

onMounted(() => {
  void loadCurrentModel();
  // H1-D：由父级模块导航定位到模型管理区，不再依赖长页面滚动。
  if (props.focusSection === "provider") {
    emit("select-section", "provider");
  }
});

const activeModelProfile = computed(
  () =>
    modelProfiles.value.find((profile) => profile.isDefault) ??
    modelProfiles.value[0] ??
    null
);

const activeModelProvider = computed(() => {
  const profile = activeModelProfile.value;
  if (!profile) return null;
  return (
    modelProviders.value.find((provider) => provider.id === profile.providerId) ??
    modelProviders.value.find(
      (provider) => provider.enabled && provider.protocol === profile.provider
    ) ??
    null
  );
});

const activeModelName = computed(() => {
  const profile = activeModelProfile.value;
  return profile ? profile.modelName?.trim() || profile.id : "—";
});
const activeServiceName = computed(() => activeModelProvider.value?.name || activeModelProfile.value?.providerName || "—");
const activeEndpoint = computed(() => activeModelProvider.value?.baseUrl || "—");
</script>

<template>
  <section class="content" :class="{ 'content--profile': activeSection === 'profile' }">
    <header class="settings-hero">
      <div>
        <p class="settings-eyebrow">应用设置</p>
        <h1>{{ currentSectionMeta.label }}</h1>
        <p class="subtitle">{{ sectionSubtitle }}</p>
      </div>
    </header>

    <!-- v0.9.0 H1-D：配置往返返回栏（从 Coding/Agent 入口进入时可见） -->
    <div v-if="returnTo" class="settings-return-bar" data-testid="settings-return-bar">
      <span>正在配置项目模型；保存后将自动返回原页面（项目与会话保留）。</span>
      <button class="return-btn" data-testid="settings-return" @click="emit('return')">返回</button>
    </div>

    <div class="settings-grid">

    <!-- 模型信息（只读） -->
    <section v-if="activeSection === 'current-model'" class="setting-card wide">
      <div class="card-heading"><span><PhCpu :size="21" /></span><div><h2>当前模型</h2><p>当前选用的模型供应商与推理模型</p></div></div>
      <div class="info-grid">
        <div><span class="k">模型服务</span><span class="v">{{ activeServiceName }}</span></div>
        <div><span class="k">LLM 模型 ID</span><span class="v">{{ activeModelName }}</span></div>
        <div><span class="k">请求地址</span><span class="v">{{ activeEndpoint }}</span></div>
      </div>
    </section>

    <!-- 统一模型供应商：保存后的启用模型直接进入对话/Coding 选择器。 -->
    <section v-if="activeSection === 'provider'" class="model-provider-section">
      <ModelProvidersPanel @saved="onModelProfilesSaved" />
    </section>

    <!-- MCP -->
    <section v-if="activeSection === 'mcp'" class="setting-card wide">
      <div class="card-heading"><span><PhPlugs :size="21" /></span><div><h2>MCP 外部能力</h2><p>配置项目工具、连接状态与授权范围</p></div></div>
      <label class="settings-project-scope">所属项目
        <select class="pa-input" aria-label="MCP 所属项目" :value="codingWorkspace.selectedProjectId.value ?? ''" @change="codingWorkspace.selectProject(Number(($event.target as HTMLSelectElement).value))">
          <option v-if="!codingWorkspace.projects.value.length" value="" disabled>请先打开项目</option>
          <option v-for="project in codingWorkspace.projects.value" :key="project.id" :value="project.id">{{ project.name }}</option>
        </select>
      </label>
      <McpIntegrationsPanel v-if="codingWorkspace.selectedProjectId.value" :key="codingWorkspace.selectedProjectId.value" :project-id="codingWorkspace.selectedProjectId.value" />
      <p v-else class="subtitle">请先在工作台打开项目，再管理它的 MCP 工具。</p>
      <details><summary>公开文档服务</summary><DocumentationMcpPanel /></details>
    </section>

    <section v-if="activeSection === 'memories'" class="setting-card wide">
      <MemorySettingsPanel />
    </section>

    <section v-if="activeSection === 'appearance'" class="setting-card wide"><WallpaperSettingsPanel /></section>

    <!-- 个人资料：首版头像和个性资料保存在当前设备。 -->
    <section v-if="activeSection === 'profile'" class="profile-section">
      <ProfileSettingsPanel />
    </section>

    <!-- 备份 -->
    <section v-if="activeSection === 'backup'" class="setting-card wide">
      <div class="card-heading"><span><PhArchiveBox :size="21" /></span><div><h2>备份与恢复</h2><p>导入或导出本机会话历史，导入前可预览内容</p></div></div>
      <HistoryMigration />
    </section>

    <!-- 关于 / 更新 -->
    <section v-if="activeSection === 'about'" class="setting-card wide compact-card">
      <div class="card-heading"><span><PhInfo :size="21" /></span><div><h2>关于与更新</h2><p>检查桌面端的新版本</p></div></div>
      <UpdateChecker />
    </section>
    </div>
  </section>
</template>

<style scoped>
.settings-project-scope { display: grid; gap: var(--space-2); max-width: 360px; margin-bottom: var(--space-6); color: var(--color-fg-muted); font-size: var(--pa-text-body); }
.settings-eyebrow { margin: 0 0 var(--space-2); color: var(--color-accent-soft-fg); font-size: var(--pa-text-meta); font-weight: var(--font-medium); }
.setting-card > details { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--color-border); }
.setting-card > details > summary { color: var(--color-fg-muted); cursor: pointer; }
.content {
  padding: var(--space-5) clamp(20px, 3vw, 48px) var(--space-10);
  overflow: auto;
  flex: 1;
  background: var(--color-bg);
}
.content--profile {
  padding-bottom: var(--space-10);
}
.profile-section { min-width: 0; }
.provider-subheading {
  margin: 0 0 var(--space-3);
  font-size: var(--pa-text-body);
}
.model-config-divider {
  margin: var(--space-5) 0 var(--space-3);
  padding-top: var(--space-5);
  border-top: 1px solid var(--color-border);
}
.model-config-divider .provider-subheading {
  margin-bottom: var(--space-1);
}
.model-config-divider p {
  margin: 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.settings-hero {
  max-width: 1060px;
  margin: 0 auto var(--space-6);
  display: flex;
  align-items: flex-start;
}
h1 {
  margin: 0 0 8px;
  font-size: var(--pa-text-page-title);
  font-weight: var(--font-semibold);
  letter-spacing: -.035em;
}
.subtitle {
  margin: 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-body);
}
.settings-grid {
  max-width: 1060px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}
.model-provider-section {
  min-width: 0;
  grid-column: 1 / -1;
}
.settings-return-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  max-width: 1060px;
  margin: 0 auto 12px;
  padding: 8px 14px;
  border: 1px solid color-mix(in srgb, var(--color-accent) 35%, var(--color-border));
  border-radius: var(--radius-md);
  background: var(--color-accent-soft);
  color: var(--color-fg);
  font-size: 13px;
}
.return-btn {
  height: 28px;
  padding: 0 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  cursor: pointer;
}
.setting-card {
  padding: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: none;
}
.setting-card.wide { grid-column: 1 / -1; }
.card-heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 16px;
}
.card-heading > span {
  display: grid;
  place-items: center;
  flex: 0 0 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.card-heading h2 { margin: 0; font-size: 16px; letter-spacing: -.02em; }
.card-heading p { margin: var(--space-1) 0 0; color: var(--color-fg-subtle); font-size: var(--pa-text-compact); }
.status-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 13px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.status-pill.ok {
  color: var(--color-success-fg);
  border-color: var(--color-success-soft);
}
.status-pill.bad {
  color: var(--color-danger-fg);
  border-color: var(--color-danger-soft);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-pill.ok .dot {
  background: var(--color-success);
}
.status-pill.bad .dot {
  background: var(--color-danger);
}
.warn-text {
  margin-top: 10px;
  color: var(--color-danger-fg);
  font-size: 13px;
}
.loading-text {
  margin-top: 10px;
  color: var(--color-fg-muted);
  font-size: 13px;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}
.info-grid > div {
  padding: var(--space-4);
  border-left: 2px solid var(--color-accent-soft);
}
.k {
  display: block;
  font-size: 12px;
  color: var(--color-fg-subtle);
}
.v {
  display: block;
  font-size: 14px;
  margin-top: 3px;
  word-break: break-all;
}
.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: none;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field label {
  font-size: 13px;
  color: var(--color-fg-muted);
}
.field input,
.field select {
  padding: 8px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  width: 100%;
  background: var(--color-surface);
}
.field input:focus,
.field select:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-soft);
}
.field-check label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.form-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.save-btn {
  background: var(--pa-btn-primary-bg);
  color: var(--color-accent-fg);
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-size: 14px;
  cursor: pointer;
}
.save-btn:disabled {
  background: var(--color-fg-disabled);
  cursor: not-allowed;
}
.save-btn.secondary {
  background: var(--color-surface-sunken);
  color: var(--color-fg);
  border: 1px solid var(--color-border);
}
.msg {
  font-size: 13px;
  color: var(--color-success-fg);
}
.provider-form {
  max-width: none;
  gap: 10px;
}
.provider-card {
  padding: 16px 18px;
  border-radius: 14px;
}
.provider-card .card-heading {
  margin-bottom: 12px;
}
.provider-card .field {
  gap: 4px;
}
.provider-card .field input,
.provider-card .field select {
  box-sizing: border-box;
  min-height: 36px;
  padding: 6px 10px;
  border-radius: 7px;
  font-size: 13px;
}
.provider-consent {
  display: flex;
  align-items: center;
  min-height: 28px;
}
.provider-consent label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--color-fg-muted);
  font-size: 12px;
  cursor: pointer;
}
.provider-consent input {
  flex: 0 0 auto;
  width: 16px;
  height: 16px;
  margin: 0;
  padding: 0;
  accent-color: var(--color-accent);
}
.provider-protocol-note {
  padding: 7px 10px;
  border: 1px solid color-mix(in srgb, var(--color-accent) 24%, var(--color-border));
  border-radius: 7px;
  background: var(--color-accent-soft);
  color: var(--color-fg-muted);
  font-size: 12px;
  line-height: 1.45;
}
.provider-protocol-note code {
  color: var(--color-accent-soft-fg);
  font-family: var(--font-mono);
}
.provider-scope {
  border: 1px solid var(--color-border);
  border-radius: 7px;
  background: var(--color-surface);
  padding: 7px 10px;
}
.secret-status {
  color: var(--color-fg-muted);
  font-size: 11px;
}
.secret-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.secret-input-row input {
  min-width: 0;
}
.secret-clear {
  flex: 0 0 auto;
  height: 34px;
  padding: 0 11px;
  border: 1px solid var(--color-border);
  border-radius: 7px;
  background: var(--color-surface-sunken);
  color: var(--color-danger-fg);
  cursor: pointer;
  font-size: 12px;
}
.secret-clear:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.provider-card .form-actions {
  gap: 8px;
}
.provider-card .save-btn {
  min-height: 34px;
  padding: 7px 14px;
  font-size: 13px;
}
.provider-card .small-pre {
  max-height: 140px;
  padding: 7px 10px;
  border-radius: 7px;
  font-size: 11px;
}
.backup-list {
  display: grid;
  gap: 8px;
}
.backup-row {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  padding: 10px 12px;
  text-align: left;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
}
.backup-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.backup-row small {
  color: var(--color-fg-subtle);
  flex: none;
}
.small-pre {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--color-surface-sunken);
  font-size: 12px;
}
.hint {
  font-size: 12px;
  color: var(--color-fg-subtle);
  margin-top: 8px;
}
@media (max-width: 940px) {
  .settings-grid { grid-template-columns: 1fr; }
  .setting-card.wide { grid-column: auto; }
}
</style>
