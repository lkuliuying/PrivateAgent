<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhCheck,
  PhCube,
  PhEye,
  PhEyeSlash,
  PhInfo,
  PhPencilSimple,
  PhPlus,
  PhPlugsConnected,
  PhTrash,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import {
  clearModelProviderRuntimeSecret,
  cmdClearModelProviderSecret,
  cmdSetModelProviderSecret,
  deleteModelProvider,
  discoverModelProviderModels,
  getSettings,
  isDesktopRuntime,
  listModelProviders,
  probeModelProviderModel,
  saveModelProvider,
  updateSettings,
  updateModelProviderRuntimeSecret,
  type ModelProvider,
  type ModelProviderApiFormat,
  type ModelProviderModel,
  type ModelProviderProtocol,
  type DiscoveredModel,
  type AppSettings,
  type ModelMetadataSource,
} from "../api";
import { useNotifications } from "../stores/notifications";

const emit = defineEmits<{ saved: [] }>();
const notify = useNotifications();
const desktopRuntime = isDesktopRuntime();
const previewMode =
  import.meta.env.DEV &&
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).get("settings-preview") === "providers-v2";

interface ProviderDraft {
  id: string;
  name: string;
  protocol: ModelProviderProtocol;
  baseUrl: string;
  apiFormat: ModelProviderApiFormat;
  enabled: boolean;
  isBuiltin: boolean;
  apiKeyConfigured: boolean;
  apiKey: string;
  models: ModelProviderModel[];
}

const providers = ref<ModelProvider[]>([]);
const selectedId = ref(previewMode ? "opencodego" : "");
const draft = ref<ProviderDraft>(blankDraft());
const loading = ref(false);
const saving = ref(false);
const discovering = ref(false);
const testingProfileId = ref("");
const showApiKey = ref(false);
const editingName = ref(false);
const catalog = ref<DiscoveredModel[]>([]);
const modelToAdd = ref("");
const editingContextModelId = ref("");
const message = ref("");
const messageKind = ref<"ok" | "error" | "info">("info");
const modelParameters = ref<Pick<
  AppSettings,
  "llm_temperature" | "llm_context_length" | "kb_enabled_by_default"
>>({
  llm_temperature: 0.7,
  llm_context_length: 8192,
  kb_enabled_by_default: false,
});

function safeId(): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replace(/-/g, "").slice(0, 16)
    : Math.random().toString(36).slice(2, 14);
  return `provider-${random}`;
}

function blankDraft(protocol: ModelProviderProtocol = "openai"): ProviderDraft {
  return {
    id: safeId(),
    name: "",
    protocol,
    baseUrl:
      protocol === "ollama"
        ? "http://127.0.0.1:11434"
        : protocol === "claude"
          ? "https://api.anthropic.com/v1"
          : "https://api.openai.com/v1",
    apiFormat:
      protocol === "ollama"
        ? "ollama_chat"
        : protocol === "claude"
          ? "anthropic_messages"
          : "chat_completions",
    enabled: true,
    isBuiltin: protocol === "ollama",
    apiKeyConfigured: false,
    apiKey: "",
    models: [],
  };
}

function fromProvider(provider: ModelProvider): ProviderDraft {
  return {
    id: provider.id,
    name: provider.name,
    protocol: provider.protocol,
    baseUrl: provider.baseUrl,
    apiFormat: provider.apiFormat,
    enabled: provider.enabled,
    isBuiltin: provider.isBuiltin,
    apiKeyConfigured: provider.apiKeyConfigured,
    apiKey: "",
    models: provider.models.map((model) => ({ ...model })),
  };
}

function previewProviders(): ModelProvider[] {
  return [
    {
      id: "zai",
      name: "Z.ai",
      protocol: "openai",
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      apiFormat: "chat_completions",
      enabled: true,
      isBuiltin: true,
      apiKeyConfigured: true,
      models: [
        { profileId: "zai--glm-5", modelId: "glm-5", contextTokens: 131072, maxOutputTokens: null, metadataSource: "provider_api" },
      ],
    },
    {
      id: "opencodego",
      name: "opencodego",
      protocol: "openai",
      baseUrl: "https://opencode.ai/zen/go/v1",
      apiFormat: "chat_completions",
      enabled: true,
      isBuiltin: false,
      apiKeyConfigured: true,
      models: [
        { profileId: "opencodego--deepseek", modelId: "deepseek-v4-flash", contextTokens: 1_000_000, maxOutputTokens: 384_000, metadataSource: "official_catalog" },
        { profileId: "opencodego--ox", modelId: "ox-alpha-free", contextTokens: null, maxOutputTokens: null, metadataSource: "unknown" },
      ],
    },
    {
      id: "bailian",
      name: "百炼",
      protocol: "openai",
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      apiFormat: "chat_completions",
      enabled: true,
      isBuiltin: false,
      apiKeyConfigured: true,
      models: [{ profileId: "bailian--qwen", modelId: "qwen-max", contextTokens: 131072, maxOutputTokens: null, metadataSource: "provider_api" }],
    },
  ];
}

async function load(preferredId?: string): Promise<void> {
  loading.value = true;
  try {
    providers.value = previewMode ? previewProviders() : await listModelProviders();
    const selected =
      providers.value.find((item) => item.id === preferredId) ??
      providers.value.find((item) => item.id === selectedId.value) ??
      providers.value[0];
    if (selected) selectProvider(selected.id);
    else startAdd();
  } catch (error) {
    setMessage(errorText(error), "error");
  } finally {
    loading.value = false;
  }
}

async function loadModelParameters(): Promise<void> {
  if (previewMode) return;
  try {
    const settings = await getSettings();
    modelParameters.value = {
      llm_temperature: settings.llm_temperature,
      llm_context_length: settings.llm_context_length,
      kb_enabled_by_default: settings.kb_enabled_by_default,
    };
  } catch {
    // 供应商配置仍可独立使用；参数保存时会呈现真实 API 错误。
  }
}

function selectProvider(providerId: string): void {
  const provider = providers.value.find((item) => item.id === providerId);
  if (!provider) return;
  selectedId.value = provider.id;
  draft.value = fromProvider(provider);
  catalog.value = provider.models.map((model) => ({ ...model }));
  modelToAdd.value = "";
  editingName.value = false;
  editingContextModelId.value = "";
  message.value = "";
}

function startAdd(): void {
  selectedId.value = "__new__";
  draft.value = blankDraft();
  catalog.value = [];
  modelToAdd.value = "";
  editingName.value = true;
  message.value = "";
}

function onProtocolChanged(): void {
  const next = blankDraft(draft.value.protocol);
  draft.value.baseUrl = next.baseUrl;
  draft.value.apiFormat = next.apiFormat;
  draft.value.isBuiltin = next.isBuiltin;
  draft.value.models = [];
  draft.value.apiKey = "";
  draft.value.apiKeyConfigured = false;
  catalog.value = [];
}

const availableModels = computed(() => {
  const selected = new Set(draft.value.models.map((model) => model.modelId));
  return catalog.value.filter((model) => !selected.has(model.modelId));
});

function addSelectedModel(): void {
  const modelId = modelToAdd.value;
  if (!modelId || draft.value.models.some((item) => item.modelId === modelId)) return;
  const discovered = catalog.value.find((item) => item.modelId === modelId);
  if (!discovered) return;
  draft.value.models.push({
    profileId: "",
    ...discovered,
  });
  modelToAdd.value = "";
}

function removeModel(modelId: string): void {
  draft.value.models = draft.value.models.filter((item) => item.modelId !== modelId);
}

async function discoverModels(): Promise<void> {
  if (!draft.value.baseUrl.trim()) {
    setMessage("请先填写 Base URL", "error");
    return;
  }
  discovering.value = true;
  message.value = "";
  try {
    catalog.value = previewMode
      ? [
          { modelId: "deepseek-v4-flash", contextTokens: 1_000_000, maxOutputTokens: 384_000, metadataSource: "official_catalog" },
          { modelId: "ox-alpha-free", contextTokens: null, maxOutputTokens: null, metadataSource: "unknown" },
          { modelId: "glm-5", contextTokens: 131_072, maxOutputTokens: null, metadataSource: "provider_api" },
          { modelId: "qwen-max", contextTokens: null, maxOutputTokens: null, metadataSource: "unknown" },
        ]
      : await discoverModelProviderModels({
          providerId: selectedId.value === "__new__" ? null : draft.value.id,
          protocol: draft.value.protocol,
          baseUrl: draft.value.baseUrl.trim(),
          apiKey: draft.value.apiKey.trim() || undefined,
        });
    const selected = new Set(draft.value.models.map((model) => model.modelId));
    modelToAdd.value = catalog.value.find((model) => !selected.has(model.modelId))?.modelId ?? "";
    setMessage(`已获取 ${catalog.value.length} 个模型，请从列表中选择`, "ok");
  } catch (error) {
    setMessage(errorText(error), "error");
  } finally {
    discovering.value = false;
  }
}

async function save(): Promise<void> {
  const name = draft.value.name.trim();
  const baseUrl = draft.value.baseUrl.trim().replace(/\/$/, "");
  if (!name) return setMessage("请填写供应商名称", "error");
  if (!baseUrl) return setMessage("请填写 Base URL", "error");
  if (!draft.value.models.length) return setMessage("请至少从模型列表中选择一个模型", "error");
  if (
    draft.value.protocol === "ollama" &&
    (!Number.isFinite(modelParameters.value.llm_temperature) ||
      modelParameters.value.llm_temperature < 0 ||
      modelParameters.value.llm_temperature > 1)
  ) {
    return setMessage("温度必须在 0 到 1 之间", "error");
  }
  if (
    draft.value.protocol === "ollama" &&
    (!Number.isInteger(modelParameters.value.llm_context_length) ||
      modelParameters.value.llm_context_length < 512)
  ) {
    return setMessage("上下文长度必须是大于等于 512 的整数", "error");
  }
  saving.value = true;
  message.value = "";
  try {
    let credentialReference: string | undefined;
    const secret = draft.value.apiKey.trim();
    if (draft.value.protocol !== "ollama" && secret) {
      if (desktopRuntime) {
        const status = await cmdSetModelProviderSecret(draft.value.id, secret);
        credentialReference = status.reference;
      } else {
        credentialReference = `secret://os-keyring/model-provider/${draft.value.id}`;
      }
      if (!previewMode) {
        await updateModelProviderRuntimeSecret(draft.value.id, secret);
      }
    }
    if (!previewMode) {
      await saveModelProvider(draft.value.id, {
        name,
        protocol: draft.value.protocol,
        baseUrl,
        apiFormat: draft.value.apiFormat,
        credentialReference,
        enabled: draft.value.enabled,
        isBuiltin: draft.value.isBuiltin,
        models: draft.value.models.map((model) => ({
          modelId: model.modelId,
          contextTokens: model.contextTokens,
          maxOutputTokens: model.maxOutputTokens,
          metadataSource: model.metadataSource,
        })),
      });
      if (draft.value.protocol === "ollama") {
        await updateSettings({ ...modelParameters.value });
      }
      await load(draft.value.id);
    } else {
      const provider: ModelProvider = {
        id: draft.value.id,
        name,
        protocol: draft.value.protocol,
        baseUrl,
        apiFormat: draft.value.apiFormat,
        enabled: draft.value.enabled,
        isBuiltin: draft.value.isBuiltin,
        apiKeyConfigured: draft.value.apiKeyConfigured || Boolean(secret),
        models: draft.value.models.map((model) => ({ ...model })),
      };
      providers.value = [
        ...providers.value.filter((item) => item.id !== provider.id),
        provider,
      ];
      selectProvider(provider.id);
    }
    draft.value.apiKey = "";
    setMessage("模型配置已保存，可立即在对话中选择", "ok");
    window.dispatchEvent(new CustomEvent("pa:model-providers-changed"));
    emit("saved");
  } catch (error) {
    setMessage(errorText(error), "error");
  } finally {
    saving.value = false;
  }
}

async function removeProvider(): Promise<void> {
  if (selectedId.value === "__new__") return startAdd();
  const confirmed = await notify.confirm({
    title: `删除模型供应商“${draft.value.name}”？`,
    danger: true,
    impact: "该供应商下的模型会同时从对话选择器中移除。",
    confirmLabel: "删除供应商",
  });
  if (!confirmed) return;
  saving.value = true;
  try {
    if (!previewMode) {
      await clearModelProviderRuntimeSecret(draft.value.id);
      if (desktopRuntime) await cmdClearModelProviderSecret(draft.value.id);
      await deleteModelProvider(draft.value.id);
      await load();
    } else {
      providers.value = providers.value.filter((item) => item.id !== draft.value.id);
      if (providers.value[0]) selectProvider(providers.value[0].id);
      else startAdd();
    }
    window.dispatchEvent(new CustomEvent("pa:model-providers-changed"));
    setMessage("供应商已删除", "ok");
  } catch (error) {
    setMessage(errorText(error), "error");
  } finally {
    saving.value = false;
  }
}

async function testModel(profileId: string): Promise<void> {
  if (!profileId || testingProfileId.value) return;
  const provider = providers.value.find((item) => item.id === draft.value.id);
  const model = provider?.models.find((item) => item.profileId === profileId);
  if (!provider || !model) {
    setMessage("请先保存该模型配置，再测试连接", "error");
    return;
  }
  testingProfileId.value = profileId;
  message.value = "";
  try {
    const available = previewMode
      ? true
      : await probeModelProviderModel(provider, model.modelId);
    setMessage(
      available
        ? "模型连接测试成功：模型在可用列表中（未测试聊天生成）"
        : "供应商可连接，但可用列表中未找到该模型",
      available ? "ok" : "error"
    );
  } catch (error) {
    setMessage(errorText(error), "error");
  } finally {
    testingProfileId.value = "";
  }
}

function setMessage(value: string, kind: "ok" | "error" | "info"): void {
  message.value = value;
  messageKind.value = kind;
}

function errorText(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}

function formatContext(tokens: number | null): string {
  if (tokens === null) return "未知";
  if (tokens >= 1_000_000) return `${Math.round(tokens / 1_000_000)}M`;
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`;
  return String(tokens);
}

function metadataSourceLabel(source: ModelMetadataSource): string {
  return {
    provider_api: "供应商接口",
    local_model: "本地模型",
    official_catalog: "官方目录",
    user_override: "手动设置",
    unknown: "未知来源",
  }[source];
}

function setContextOverride(model: ModelProviderModel, event: Event): void {
  const value = (event.target as HTMLInputElement).value.trim();
  const parsed = Number(value);
  if (!value || !Number.isFinite(parsed) || parsed < 1) {
    model.contextTokens = null;
    model.metadataSource = "unknown";
    return;
  }
  model.contextTokens = Math.round(parsed);
  model.metadataSource = "user_override";
}

onMounted(() => {
  void Promise.all([load(), loadModelParameters()]);
});
</script>

<template>
  <section class="provider-manager" data-testid="model-provider-manager">
    <aside class="provider-sidebar" aria-label="模型供应商">
      <div class="sidebar-section">
        <span class="sidebar-heading">模型供应商</span>
        <button
          v-for="provider in providers"
          :key="provider.id"
          type="button"
          class="provider-item"
          :class="{ active: selectedId === provider.id }"
          @click="selectProvider(provider.id)"
        >
          <PhCube :size="18" aria-hidden="true" />
          <span>{{ provider.name }}</span>
          <i class="status-dot" :class="{ off: !provider.enabled }" aria-hidden="true" />
        </button>
      </div>
      <button type="button" class="provider-item add-provider" @click="startAdd">
        <PhPlus :size="19" aria-hidden="true" />
        <span>添加供应商</span>
      </button>
    </aside>

    <div class="provider-detail" :aria-busy="loading || saving">
      <div class="detail-header">
        <div class="provider-title-row">
          <input
            v-if="editingName || selectedId === '__new__'"
            v-model="draft.name"
            class="provider-name-input"
            aria-label="供应商名称"
            placeholder="如：智谱 GLM"
            @blur="editingName = false"
          />
          <h2 v-else>{{ draft.name }}</h2>
          <button
            v-if="selectedId !== '__new__'"
            type="button"
            class="icon-button"
            title="修改名称"
            aria-label="修改供应商名称"
            @click="editingName = true"
          >
            <PhPencilSimple :size="17" />
          </button>
          <span class="enabled-badge" :class="{ off: !draft.enabled }">
            {{ draft.enabled ? "已启用" : "已禁用" }}
          </span>
          <button type="button" class="toggle-button" @click="draft.enabled = !draft.enabled">
            {{ draft.enabled ? "禁用" : "启用" }}
          </button>
        </div>
        <button
          v-if="selectedId !== '__new__' && !draft.isBuiltin"
          type="button"
          class="icon-button danger"
          title="删除供应商"
          aria-label="删除供应商"
          @click="void removeProvider()"
        >
          <PhTrash :size="18" />
        </button>
      </div>

      <p v-if="selectedId === '__new__'" class="detail-intro">
        配置一个模型 API 端点并从服务获取可用模型。保存后即可在对话中选择。
      </p>

      <div class="provider-form-grid">
        <label v-if="selectedId === '__new__'" class="field">
          <span>服务类型</span>
          <select v-model="draft.protocol" @change="onProtocolChanged">
            <option value="openai">OpenAI 兼容 API</option>
            <option value="claude">Claude Messages API</option>
            <option value="ollama">Ollama（本地）</option>
          </select>
        </label>
        <label class="field">
          <span>Base URL</span>
          <input v-model="draft.baseUrl" type="url" spellcheck="false" />
        </label>
        <label class="field">
          <span>API 格式</span>
          <select v-model="draft.apiFormat">
            <option value="chat_completions">Chat Completions（/chat/completions）</option>
            <option value="anthropic_messages">Claude Messages（/messages）</option>
            <option value="ollama_chat">Ollama Chat（/api/chat）</option>
          </select>
        </label>
        <label v-if="draft.protocol !== 'ollama'" class="field">
          <span>API Key</span>
          <div class="secret-field">
            <input
              v-model="draft.apiKey"
              :type="showApiKey ? 'text' : 'password'"
              autocomplete="new-password"
              spellcheck="false"
              :placeholder="draft.apiKeyConfigured ? '已配置；输入新密钥可更新' : '输入 API Key'"
            />
            <button
              type="button"
              class="icon-button"
              :title="showApiKey ? '隐藏密钥' : '显示密钥'"
              :aria-label="showApiKey ? '隐藏密钥' : '显示密钥'"
              @click="showApiKey = !showApiKey"
            >
              <PhEyeSlash v-if="showApiKey" :size="18" />
              <PhEye v-else :size="18" />
            </button>
          </div>
        </label>
      </div>

      <section
        v-if="draft.protocol === 'ollama'"
        class="ollama-parameters"
        aria-labelledby="ollama-parameters-title"
        data-testid="ollama-model-parameters"
      >
        <div class="parameters-heading">
          <h3 id="ollama-parameters-title">本地模型参数</h3>
          <p>这些参数仅在 Ollama 本地配置中集中管理。</p>
        </div>
        <div class="parameters-grid">
          <label class="field">
            <span>温度（0～1）</span>
            <input
              v-model.number="modelParameters.llm_temperature"
              type="number"
              min="0"
              max="1"
              step="0.1"
              data-testid="ollama-temperature"
            />
          </label>
          <label class="field">
            <span>上下文长度</span>
            <input
              v-model.number="modelParameters.llm_context_length"
              type="number"
              min="512"
              step="512"
              data-testid="ollama-context-length"
            />
          </label>
          <label class="parameter-check">
            <input v-model="modelParameters.kb_enabled_by_default" type="checkbox" />
            <span>默认启用知识库</span>
          </label>
        </div>
      </section>

      <div class="models-heading-row">
        <div>
          <h3>模型列表</h3>
          <p>模型 ID 从服务接口获取，不需要手动输入。</p>
        </div>
        <button
          type="button"
          class="secondary-button"
          :disabled="discovering"
          @click="void discoverModels()"
        >
          <PhArrowClockwise :size="16" :class="{ spinning: discovering }" />
          {{ discovering ? "获取中" : "获取模型" }}
        </button>
      </div>

      <div class="model-list">
        <div v-if="!draft.models.length" class="empty-models">
          <PhInfo :size="18" aria-hidden="true" />
          <span>当前尚未选择模型；请先获取模型列表。</span>
        </div>
        <div v-for="model in draft.models" :key="model.modelId" class="model-row">
          <span class="model-id">{{ model.modelId }}</span>
          <input
            v-if="editingContextModelId === model.modelId"
            class="context-editor"
            type="number"
            min="1"
            :value="model.contextTokens ?? ''"
            placeholder="未知"
            aria-label="上下文窗口 tokens"
            @input="setContextOverride(model, $event)"
            @blur="editingContextModelId = ''"
            @keydown.enter="editingContextModelId = ''"
          />
          <span
            v-else
            class="context-pill"
            :title="model.contextTokens === null
              ? '上下文窗口未知，可手动设置'
              : `上下文 ${model.contextTokens.toLocaleString()} tokens · ${metadataSourceLabel(model.metadataSource)}`"
          >
            {{ formatContext(model.contextTokens) }}
          </span>
          <button
            type="button"
            class="icon-button"
            title="修正上下文窗口"
            aria-label="修正上下文窗口"
            @mousedown.prevent="editingContextModelId = model.modelId"
          >
            <PhPencilSimple :size="17" />
          </button>
          <button
            type="button"
            class="icon-button"
            :title="testingProfileId === model.profileId ? '正在测试模型' : '测试模型'"
            aria-label="测试模型"
            :aria-busy="testingProfileId === model.profileId"
            :disabled="!model.profileId || Boolean(testingProfileId)"
            @click="void testModel(model.profileId)"
          >
            <span
              v-if="testingProfileId === model.profileId"
              class="model-test-spinner"
              data-testid="model-test-spinner"
              aria-hidden="true"
            />
            <PhPlugsConnected v-else :size="17" />
          </button>
          <button
            type="button"
            class="icon-button danger"
            title="移除模型"
            aria-label="移除模型"
            @click="removeModel(model.modelId)"
          >
            <PhTrash :size="17" />
          </button>
        </div>
      </div>

      <div class="add-model-row">
        <select v-model="modelToAdd" :disabled="!availableModels.length">
          <option value="">{{ availableModels.length ? "选择一个已获取的模型" : "暂无可添加模型" }}</option>
          <option v-for="model in availableModels" :key="model.modelId" :value="model.modelId">
            {{ model.modelId }}{{ model.contextTokens === null ? ' · 上下文未知' : ` · ${formatContext(model.contextTokens)}` }}
          </option>
        </select>
        <button type="button" class="secondary-button" :disabled="!modelToAdd" @click="addSelectedModel">
          <PhPlus :size="16" /> 添加模型
        </button>
      </div>

      <div v-if="message" class="message" :class="messageKind" role="status">
        <PhCheck v-if="messageKind === 'ok'" :size="16" />
        <PhWarningCircle v-else-if="messageKind === 'error'" :size="16" />
        <PhInfo v-else :size="16" />
        <span>{{ message }}</span>
      </div>

      <div class="detail-actions">
        <span class="save-hint">保存后，已启用模型会立即出现在对话模型菜单中。</span>
        <button type="button" class="primary-button" :disabled="saving" @click="void save()">
          {{ saving ? "保存中…" : selectedId === "__new__" ? "添加供应商" : "保存配置" }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.provider-manager {
  display: grid;
  min-height: 610px;
  grid-template-columns: 260px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}
.provider-sidebar {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-3);
  border-right: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-panel) 58%, var(--color-surface));
}
.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.sidebar-heading {
  padding: 0 var(--space-2) var(--space-1);
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
}
.provider-item {
  display: grid;
  width: 100%;
  min-height: 40px;
  grid-template-columns: 22px minmax(0, 1fr) 10px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.provider-item:hover { background: var(--color-surface-hover); }
.provider-item.active {
  border-color: var(--color-border-strong);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}
.provider-item span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.add-provider { grid-template-columns: 22px 1fr; }
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-success);
}
.status-dot.off { background: var(--color-fg-disabled); }
.provider-detail {
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding: var(--space-6);
}
.detail-header,
.provider-title-row,
.models-heading-row,
.add-model-row,
.detail-actions,
.message {
  display: flex;
  align-items: center;
}
.detail-header { justify-content: space-between; gap: var(--space-3); }
.provider-title-row { min-width: 0; gap: var(--space-2); }
.provider-title-row h2 { margin: 0; font-size: var(--pa-text-section); }
.provider-name-input {
  width: min(360px, 48vw);
  height: var(--pa-input-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--pa-input-border-focus);
  border-radius: var(--pa-input-radius);
  font: inherit;
}
.enabled-badge {
  padding: 3px var(--space-3);
  border-radius: var(--radius-full);
  background: var(--color-success);
  color: var(--color-surface);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-semibold);
}
.enabled-badge.off { background: var(--color-fg-faint); }
.toggle-button,
.secondary-button,
.primary-button {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  font: inherit;
  cursor: pointer;
}
.primary-button {
  border-color: var(--pa-btn-primary-bg);
  background: var(--pa-btn-primary-bg);
  color: var(--pa-btn-primary-fg);
}
.primary-button:hover:not(:disabled) { background: var(--pa-btn-primary-bg-hover); }
.secondary-button:hover:not(:disabled), .toggle-button:hover { background: var(--color-surface-hover); }
.secondary-button:disabled, .primary-button:disabled { opacity: .55; cursor: not-allowed; }
.icon-button {
  display: inline-flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.icon-button:hover { background: var(--color-surface-hover); color: var(--color-fg); }
.icon-button.danger:hover { background: var(--color-danger-soft); color: var(--color-danger-fg); }
.icon-button:disabled { cursor: not-allowed; opacity: .55; }
.model-test-spinner {
  width: 14px;
  height: 14px;
  box-sizing: border-box;
  border: 2px solid var(--color-border-strong);
  border-top-color: transparent;
  border-radius: var(--radius-full);
  animation: spin var(--pa-motion-deliberate) linear infinite;
}
.detail-intro { margin: var(--space-2) 0 0; color: var(--color-fg-subtle); }
.provider-form-grid { display: grid; gap: var(--space-3); margin-top: var(--space-5); }
.ollama-parameters {
  margin-top: var(--space-5);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}
.parameters-heading h3 {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--pa-text-body);
}
.parameters-heading p {
  margin: 3px 0 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.parameters-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-3);
}
.parameter-check {
  display: inline-flex;
  grid-column: 1 / -1;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-body);
}
.parameter-check input { width: 16px; height: 16px; }
.field { display: flex; min-width: 0; flex-direction: column; gap: var(--space-1); }
.field > span, .models-heading-row h3 { color: var(--color-fg-muted); font-size: var(--pa-text-body); }
.field input,
.field select,
.add-model-row select {
  width: 100%;
  height: 42px;
  box-sizing: border-box;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  font: inherit;
}
.field input:focus,
.field select:focus,
.add-model-row select:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: var(--pa-input-ring);
}
.secret-field { position: relative; display: flex; }
.secret-field input { padding-right: 44px; }
.secret-field .icon-button { position: absolute; top: 5px; right: 5px; }
.models-heading-row { justify-content: space-between; gap: var(--space-3); margin-top: var(--space-5); }
.models-heading-row h3 { margin: 0; }
.models-heading-row p { margin: 2px 0 0; color: var(--color-fg-subtle); font-size: var(--pa-text-meta); }
.model-list {
  overflow: hidden;
  margin-top: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
.model-row {
  display: grid;
  min-height: 50px;
  grid-template-columns: minmax(0, 1fr) auto 32px 32px 32px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
}
.model-row + .model-row { border-top: 1px solid var(--color-border); }
.model-id { overflow: hidden; font-family: var(--font-mono); text-overflow: ellipsis; white-space: nowrap; }
.context-pill {
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.context-editor {
  width: 112px;
  height: 32px;
  box-sizing: border-box;
  padding: 0 var(--space-2);
  border: 1px solid var(--color-accent);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg);
  font: inherit;
}
.empty-models { display: flex; min-height: 58px; align-items: center; gap: var(--space-2); padding: 0 var(--space-4); color: var(--color-fg-subtle); }
.add-model-row { gap: var(--space-2); margin-top: var(--space-2); }
.add-model-row select { min-width: 0; flex: 1; }
.message { gap: var(--space-2); margin-top: var(--space-3); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); font-size: var(--pa-text-compact); }
.message.ok { background: var(--color-success-soft); color: var(--color-success-fg); }
.message.error { background: var(--color-danger-soft); color: var(--color-danger-fg); }
.message.info { background: var(--color-accent-soft); color: var(--color-accent-soft-fg); }
.detail-actions {
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: auto;
  padding-top: var(--space-5);
  border-top: 1px solid var(--color-border);
}
.save-hint { color: var(--color-fg-subtle); font-size: var(--pa-text-compact); }
.spinning { animation: spin var(--pa-motion-deliberate) linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 880px) {
  .provider-manager { grid-template-columns: 1fr; }
  .provider-sidebar { flex-direction: row; overflow-x: auto; border-right: 0; border-bottom: 1px solid var(--color-border); }
  .sidebar-section { flex-direction: row; }
  .sidebar-heading { display: none; }
  .provider-item { width: auto; min-width: 150px; }
  .provider-detail { padding: var(--space-4); }
  .parameters-grid { grid-template-columns: 1fr; }
}
</style>
