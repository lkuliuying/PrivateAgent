import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  discoverModelProviderModels,
  listModelProviders,
  probeModelProviderModel,
  saveModelProvider,
  updateModelProviderRuntimeSecret,
} from "../api";
import {
  fetchCodingModelProfiles,
  probeCodingModelProfile,
} from "../features/coding/api/modelProfiles";
import SettingsView from "./SettingsView.vue";
import McpIntegrationsPanel from "./McpIntegrationsPanel.vue";
import { getLocalModelSettings, saveLocalModelSettings } from "../api/modelProviders";

vi.mock("../api/modelProviders", () => ({
  getLocalModelSettings: vi.fn().mockResolvedValue({ llm_temperature: 0.7, llm_context_length: 8192, kb_enabled_by_default: false }),
  saveLocalModelSettings: vi.fn(),
}));

const refreshCoding = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const codingScope = vi.hoisted(() => ({
  projects: { value: [] as { id: number; name: string }[] },
  selectedProjectId: { value: null as number | null },
  selectProject: vi.fn(),
}));

vi.mock("../api", () => ({
  clearModelProviderRuntimeSecret: vi.fn(),
  cmdClearModelProviderSecret: vi.fn(),
  deleteModelProvider: vi.fn(),
  discoverModelProviderModels: vi.fn(),
  exportBackup: vi.fn(),
  isDesktopRuntime: () => true,
  listModelProviders: vi.fn(),
  probeModelProviderModel: vi.fn(),
  previewRestoreBackup: vi.fn(),
  saveModelProvider: vi.fn(),
  updateModelProviderRuntimeSecret: vi.fn(),
}));

vi.mock("../features/coding/model/codingWorkspaceStore", () => ({
  useCodingWorkspace: () => ({ refresh: refreshCoding, ...codingScope }),
}));

vi.mock("../features/coding/api/modelProfiles", () => ({
  fetchCodingModelProfiles: vi.fn(),
  probeCodingModelProfile: vi.fn(),
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
  window.localStorage.clear();
  codingScope.projects.value = [];
  codingScope.selectedProjectId.value = null;
  vi.mocked(probeModelProviderModel).mockResolvedValue(true);
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

  vi.mocked(saveModelProvider).mockResolvedValue(sampleProvider);
  vi.mocked(updateModelProviderRuntimeSecret).mockResolvedValue(undefined);
});

describe("SettingsView 统一模型设置", () => {
  it("MCP 设置绑定当前项目，切换使用已有工作区选择入口", async () => {
    codingScope.projects.value = [{ id: 1, name: "项目甲" }, { id: 2, name: "项目乙" }];
    codingScope.selectedProjectId.value = 1;
    const wrapper = mount(SettingsView, {
      props: { activeSection: "mcp" },
      global: { stubs: { McpIntegrationsPanel: true, DocumentationMcpPanel: true } },
    });
    await flushPromises();
    expect(wrapper.findComponent(McpIntegrationsPanel).props("projectId")).toBe(1);
    await wrapper.get('[aria-label="MCP 所属项目"]').setValue("2");
    expect(codingScope.selectProject).toHaveBeenCalledWith(2);
    wrapper.unmount();
  });

  it("没有项目时显示引导，不请求项目 MCP 配置", async () => {
    const wrapper = mount(SettingsView, {
      props: { activeSection: "mcp" },
      global: { stubs: { McpIntegrationsPanel: true, DocumentationMcpPanel: true } },
    });
    await flushPromises();
    expect(wrapper.findComponent(McpIntegrationsPanel).exists()).toBe(false);
    expect(wrapper.text()).toContain("请先在工作台打开项目");
    expect(codingScope.selectProject).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("OpenAI 供应商可以选择 Responses 并保留保存结果", async () => {
    const configured = { ...sampleProvider, apiFormat: "responses" as const };
    vi.mocked(saveModelProvider).mockResolvedValue(configured);
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    const format = wrapper.get('[data-testid="provider-api-format"]');
    expect(format.element).toHaveProperty("value", "chat_completions");
    await format.setValue("responses");
    vi.mocked(listModelProviders).mockResolvedValue([configured]);
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(saveModelProvider).toHaveBeenCalledWith(sampleProvider.id, expect.objectContaining({
      protocol: "openai", apiFormat: "responses",
    }));
    expect(wrapper.get('[data-testid="provider-api-format"]').element).toHaveProperty("value", "responses");
    wrapper.unmount();
  });

  it("旧本机模式仍可管理供应商，当前模型与模型设置均无手动执行模块", async () => {
    window.localStorage.setItem("privateagent.local-model.v1", JSON.stringify({
      inference_mode: "local", model_protocol: "ollama", model_endpoint: "http://127.0.0.1:11434",
      model_name: "old-model", context_tokens: 8192,
    }));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    expect(wrapper.find('[data-testid="model-provider-manager"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain("模型执行设置");
    await wrapper.setProps({ activeSection: "current-model" });
    await flushPromises();
    expect(wrapper.text()).toContain("glm-5");
    expect(wrapper.text()).not.toContain("模型执行设置");
    wrapper.unmount();
    window.localStorage.clear();
  });

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
    vi.mocked(getLocalModelSettings).mockResolvedValue({
      llm_temperature: 0.3,
      llm_context_length: 4096,
      kb_enabled_by_default: true,
    });
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();

    expect(wrapper.find('[data-testid="ollama-model-parameters"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="ollama-temperature"]').element).toHaveProperty("value", "0.3");
    await wrapper.get('[data-testid="ollama-temperature"]').setValue("0.5");
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(saveLocalModelSettings).toHaveBeenCalledWith({
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

    vi.mocked(listModelProviders).mockRejectedValue(new Error("temporary failure"));

    const wrapper = mount(SettingsView, { props: { activeSection: "current-model" } });
    await flushPromises();

    expect(wrapper.text()).toContain("glm-5");
    expect(wrapper.text()).toContain("智谱 GLM");
    expect(wrapper.text()).not.toContain("fallback-model");
    wrapper.unmount();
  });

  it("模型连接测试期间显示旋转圆环并阻止重复点击", async () => {
    let resolveProbe!: (value: boolean) => void;
    vi.mocked(probeModelProviderModel).mockImplementationOnce(
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
    await button.trigger("click");
    expect(probeModelProviderModel).toHaveBeenCalledTimes(1);

    resolveProbe(true);
    await flushPromises();
    expect(wrapper.find('[data-testid="model-test-spinner"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("模型连接测试成功");
    expect(wrapper.text()).toContain("未测试聊天生成");
    wrapper.unmount();
  });

  it("Coding 关闭时仍用已保存的供应商测试，不使用未保存的地址或密钥", async () => {
    vi.mocked(probeCodingModelProfile).mockRejectedValue(
      new Error("Model profiles are disabled")
    );
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[type="url"]').setValue("https://unsaved.example.test");
    await wrapper.get('input[type="password"]').setValue("unsaved-test-value");

    await wrapper.get('button[aria-label="测试模型"]').trigger("click");
    await flushPromises();

    expect(probeModelProviderModel).toHaveBeenCalledWith(sampleProvider, "glm-5");
    expect(probeCodingModelProfile).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("模型连接测试成功");
    expect(updateModelProviderRuntimeSecret).not.toHaveBeenCalled();
    expect(saveModelProvider).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("列表中缺少所选模型时不显示连接测试成功", async () => {
    vi.mocked(probeModelProviderModel).mockResolvedValue(false);
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('button[aria-label="测试模型"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("可用列表中未找到该模型");
    expect(wrapper.text()).not.toContain("模型连接测试成功");
    wrapper.unmount();
  });

  it("测试请求失败后显示错误并允许重试", async () => {
    vi.mocked(probeModelProviderModel).mockRejectedValueOnce(new Error("无法连接模型服务"));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    const button = wrapper.get('button[aria-label="测试模型"]');
    await button.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("无法连接模型服务");
    expect(button.attributes("disabled")).toBeUndefined();
    await button.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("模型连接测试成功");
    wrapper.unmount();
  });

  it.each([false, true])("普通设置不显示或轮询服务器状态（远程模式：%s）", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const wrapper = mount(SettingsView);
    try {
      await flushPromises();
      await vi.advanceTimersByTimeAsync(15_000);
      expect(wrapper.find(".status-card").exists()).toBe(false);
      expect(wrapper.text()).not.toContain("运行状态");
      expect(wrapper.text()).not.toContain("MySQL");
      expect(wrapper.text()).not.toContain("ChromaDB");
      expect(wrapper.text()).not.toContain("本地后端 API");
      expect(wrapper.find("h1").text()).toBe("当前模型");
    } finally {
      wrapper.unmount();
      vi.useRealTimers();
    }
  });
});
