import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cmdSetModelProviderSecret,
  discoverModelProviderModels,
  getSettings,
  listModelProviders,
  saveModelProvider,
  updateSettings,
  updateModelProviderRuntimeSecret,
} from "../api";
import {
  fetchCodingModelProfiles,
  probeCodingModelProfile,
} from "../features/coding/api/modelProfiles";
import SettingsView from "./SettingsView.vue";

const refreshHealth = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const refreshCoding = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock("../api", () => ({
  clearModelProviderRuntimeSecret: vi.fn(),
  cmdClearModelProviderSecret: vi.fn(),
  cmdSetModelProviderSecret: vi.fn(),
  deleteModelProvider: vi.fn(),
  discoverModelProviderModels: vi.fn(),
  exportBackup: vi.fn(),
  getSettings: vi.fn().mockRejectedValue(new Error("not needed")),
  isDesktopRuntime: () => true,
  listBackups: vi.fn().mockResolvedValue({ items: [] }),
  listModelProviders: vi.fn(),
  previewRestoreBackup: vi.fn(),
  saveModelProvider: vi.fn(),
  updateModelProviderRuntimeSecret: vi.fn(),
  updateSettings: vi.fn(),
}));

vi.mock("../features/coding/model/codingWorkspaceStore", () => ({
  useCodingWorkspace: () => ({ refresh: refreshCoding }),
}));

vi.mock("../features/coding/api/modelProfiles", () => ({
  fetchCodingModelProfiles: vi.fn(),
  probeCodingModelProfile: vi.fn(),
}));

vi.mock("../stores/health", () => ({
  useHealth: () => ({
    health: { value: null },
    refreshing: { value: false },
    error: { value: null },
    refresh: refreshHealth,
  }),
}));

vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}));

const sampleProvider = {
  id: "glm-prod",
  name: "智谱 GLM",
  protocol: "openai" as const,
  baseUrl: "https://open.bigmodel.cn/api/paas/v4",
  apiFormat: "chat_completions" as const,
  enabled: true,
  isBuiltin: false,
  apiKeyConfigured: true,
  models: [
    {
      profileId: "glm-prod--glm-5",
      modelId: "glm-5",
      contextTokens: 131072,
      maxOutputTokens: null,
      metadataSource: "provider_api" as const,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSettings).mockRejectedValue(new Error("not needed"));
  vi.mocked(listModelProviders).mockResolvedValue([sampleProvider]);
  vi.mocked(fetchCodingModelProfiles).mockResolvedValue({
    status: "ok",
    profiles: [
      {
        id: "glm-prod--glm-5",
        provider: "openai",
        providerId: "glm-prod",
        providerName: "智谱 GLM",
        displayName: "glm-5",
        modelName: "glm-5",
        isDefault: true,
        isLocal: false,
        contextTokens: 131072,
        reasoningEfforts: ["low", "medium", "high", "max"],
      },
    ],
  });
  vi.mocked(probeCodingModelProfile).mockResolvedValue({
    status: "ok",
    providerReachable: true,
    modelExists: true,
    nativeToolCalls: true,
    detail: "",
  });
  vi.mocked(discoverModelProviderModels).mockResolvedValue([
    { modelId: "glm-5", contextTokens: 131072, maxOutputTokens: null, metadataSource: "provider_api" },
    { modelId: "glm-4.7", contextTokens: null, maxOutputTokens: null, metadataSource: "unknown" },
  ]);
  vi.mocked(cmdSetModelProviderSecret).mockResolvedValue({
    reference: "secret://os-keyring/model-provider/glm-prod",
    configured: true,
  });
  vi.mocked(saveModelProvider).mockResolvedValue(sampleProvider);
  vi.mocked(updateModelProviderRuntimeSecret).mockResolvedValue(undefined);
});

describe("SettingsView 统一模型设置", () => {
  it("显示供应商双栏管理并移除项目模型区", async () => {
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();

    expect(wrapper.find('[data-testid="model-provider-manager"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("智谱 GLM");
    expect(wrapper.text()).not.toContain("项目模型");
    wrapper.unmount();
  });

  it("Ollama 本地配置中合并显示并保存模型参数", async () => {
    vi.mocked(listModelProviders).mockResolvedValue([
      {
        ...sampleProvider,
        id: "ollama-local",
        name: "Ollama（本地）",
        protocol: "ollama",
        baseUrl: "http://127.0.0.1:11434",
        apiFormat: "ollama_chat",
        isBuiltin: true,
        apiKeyConfigured: false,
      },
    ]);
    const { getSettings } = await import("../api");
    vi.mocked(getSettings).mockResolvedValue({
      llm_temperature: 0.3,
      llm_context_length: 4096,
      kb_enabled_by_default: true,
    } as Awaited<ReturnType<typeof getSettings>>);
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();

    expect(wrapper.find('[data-testid="ollama-model-parameters"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="ollama-temperature"]').element).toHaveProperty("value", "0.3");
    await wrapper.get('[data-testid="ollama-temperature"]').setValue("0.5");
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(updateSettings).toHaveBeenCalledWith({
      llm_temperature: 0.5,
      llm_context_length: 4096,
      kb_enabled_by_default: true,
    });
    wrapper.unmount();
  });

  it("模型 ID 只能从服务返回列表中选择", async () => {
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();

    await wrapper.get(".add-provider").trigger("click");
    await wrapper.get(".provider-name-input").setValue("新供应商");
    await wrapper.findAll(".field input")[0].setValue("https://api.example.com/v1");
    await wrapper.findAll(".field input")[1].setValue("sk-new");
    await wrapper.get(".models-heading-row .secondary-button").trigger("click");
    await flushPromises();

    expect(discoverModelProviderModels).toHaveBeenCalled();
    const select = wrapper.get(".add-model-row select");
    await select.setValue("glm-4.7");
    await wrapper.get(".add-model-row button").trigger("click");
    expect(wrapper.text()).toContain("glm-4.7");
    expect(wrapper.text()).toContain("未知");
    expect(wrapper.text()).not.toContain("33K");
    expect(wrapper.find('input[aria-label="模型 ID"]').exists()).toBe(false);

    await wrapper.get('button[aria-label="修正上下文窗口"]').trigger("mousedown");
    await wrapper.get('input[aria-label="上下文窗口 tokens"]').setValue("200000");
    expect(wrapper.get('input[aria-label="上下文窗口 tokens"]').element).toHaveProperty(
      "value",
      "200000"
    );
    wrapper.unmount();
  });

  it("当前模型卡片显示统一配置的默认模型，而不是旧设置 ID", async () => {
    vi.mocked(listModelProviders).mockResolvedValue([
      {
        ...sampleProvider,
        id: "deepseek",
        name: "deepseek",
        baseUrl: "https://api.deepseek.com",
        models: [
          {
            profileId: "deepseek--deepseek-v4-flash",
            modelId: "deepseek-v4-flash",
            contextTokens: 1_000_000,
            maxOutputTokens: 384_000,
            metadataSource: "official_catalog",
          },
        ],
      },
    ]);
    vi.mocked(fetchCodingModelProfiles).mockResolvedValue({
      status: "ok",
      profiles: [
        {
          id: "deepseek--deepseek-v4-flash",
          provider: "openai",
          providerId: "deepseek",
          providerName: "deepseek",
          displayName: "deepseek-v4-flash",
          modelName: "deepseek-v4-flash",
          isDefault: true,
          isLocal: false,
          contextTokens: 1_000_000,
          reasoningEfforts: ["low", "medium", "high", "max"],
        },
      ],
    });

    const wrapper = mount(SettingsView, { props: { activeSection: "current-model" } });
    await flushPromises();

    expect(wrapper.text()).toContain("deepseek-v4-flash");
    expect(wrapper.text()).toContain("https://api.deepseek.com");
    expect(wrapper.text()).not.toContain("glm-5.3-flash");
    wrapper.unmount();
  });

  it("供应商列表暂时失败时仍显示已加载的当前模型", async () => {
    vi.mocked(getSettings).mockResolvedValue({
      provider_type: "openai",
      openai_config_name: "OpenAI 兼容 API",
      openai_model: "fallback-model",
      openai_base_url: "https://api.example.com/v1",
      embed_model: "bge-m3",
    } as Awaited<ReturnType<typeof getSettings>>);
    vi.mocked(listModelProviders).mockRejectedValue(new Error("temporary failure"));

    const wrapper = mount(SettingsView, { props: { activeSection: "current-model" } });
    await flushPromises();

    expect(wrapper.text()).toContain("glm-5");
    expect(wrapper.text()).toContain("智谱 GLM");
    expect(wrapper.text()).toContain("https://api.example.com/v1");
    expect(wrapper.text()).toContain("bge-m3");
    wrapper.unmount();
  });

  it("模型连接测试期间显示旋转圆环并阻止重复点击", async () => {
    let resolveProbe!: (value: Awaited<ReturnType<typeof probeCodingModelProfile>>) => void;
    vi.mocked(probeCodingModelProfile).mockImplementationOnce(
      () => new Promise((resolve) => { resolveProbe = resolve; })
    );
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();

    const button = wrapper.get('button[aria-label="测试模型"]');
    await button.trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[data-testid="model-test-spinner"]').exists()).toBe(true);
    expect(button.attributes("aria-busy")).toBe("true");
    expect(button.attributes("disabled")).toBeDefined();

    resolveProbe({
      status: "ok",
      providerReachable: true,
      modelExists: true,
      nativeToolCalls: true,
      detail: "",
    });
    await flushPromises();
    expect(wrapper.find('[data-testid="model-test-spinner"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("模型连接测试成功");
    wrapper.unmount();
  });
});
