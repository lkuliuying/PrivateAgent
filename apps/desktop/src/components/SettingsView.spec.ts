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
import { saveModelProviderRecoverably } from "../api/modelSaves";
vi.mock("../api/modelSaves", () => ({ saveModelProviderRecoverably: vi.fn(), listModelSaveOperations: vi.fn().mockResolvedValue([]),
  removeUnusedModelCredentials: vi.fn(), unusedModelCredentials: vi.fn(), resumeModelSave: vi.fn(), discardModelSave: vi.fn() }));
import { secureDraftAvailable, readModelProviderDraft, writeModelProviderDraft, clearModelProviderDraft } from "../api/modelProviderDraft";
vi.mock("../api/modelProviderDraft", () => ({ secureDraftAvailable: vi.fn(), readModelProviderDraft: vi.fn(), writeModelProviderDraft: vi.fn(), clearModelProviderDraft: vi.fn() }));
import { allowDiscardingChanges, resolveUnsavedChanges, unsavedChanges } from "../services/unsavedChanges";
import McpIntegrationsPanel from "./McpIntegrationsPanel.vue";
import { getLocalModelSettings, saveLocalModelSettings } from "../api/modelProviders";

vi.mock("../api/modelProviders", () => ({
  getLocalModelSettings: vi.fn().mockResolvedValue({ llm_temperature: 0.7, llm_context_length: 8192, kb_enabled_by_default: false }),
  saveLocalModelSettings: vi.fn(),
}));

const refreshCoding = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const codingScope = vi.hoisted(() => ({
  projects: { value: [] as { id: number; name: string }[] },
  capabilities: { value: {} as Record<string, unknown> },
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
  vi.mocked(secureDraftAvailable).mockReturnValue(false);
  vi.mocked(readModelProviderDraft).mockResolvedValue(null);
  vi.mocked(writeModelProviderDraft).mockResolvedValue(undefined);
  vi.mocked(clearModelProviderDraft).mockResolvedValue(undefined);
  window.localStorage.clear();
  codingScope.projects.value = [];
  codingScope.capabilities.value = {};
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
  it("应用数据导入后即时刷新工作区、历史记录和材料，配置导入保留数据视图", async () => {
    codingScope.capabilities.value = { coding_app_backups_enabled: true, coding_attachment_storage_enabled: true };
    const wrapper = mount(SettingsView, { props: { activeSection: "backup" }, global: { stubs: { ApplicationBackup: true, AttachmentStoragePanel: true, HistoryMigration: true } } });
    await flushPromises();
    const historyBefore = wrapper.findComponent({ name: "HistoryMigration" }).element;
    const attachmentsBefore = wrapper.findComponent({ name: "AttachmentStoragePanel" }).element;
    wrapper.findComponent({ name: "ApplicationBackup" }).vm.$emit("imported", "configuration", {}); await flushPromises();
    expect(refreshCoding).toHaveBeenCalledOnce();
    expect(wrapper.findComponent({ name: "HistoryMigration" }).element).toBe(historyBefore);
    wrapper.findComponent({ name: "ApplicationBackup" }).vm.$emit("imported", "data", { id: "new-import" }); await flushPromises();
    expect(refreshCoding).toHaveBeenCalledTimes(2);
    expect(wrapper.findComponent({ name: "HistoryMigration" }).element).not.toBe(historyBefore);
    expect(wrapper.findComponent({ name: "AttachmentStoragePanel" }).element).not.toBe(attachmentsBefore);
    expect(wrapper.get("details").attributes("open")).toBeDefined();
    wrapper.findComponent({ name: "HistoryMigration" }).vm.$emit("changed"); await flushPromises();
    expect(refreshCoding).toHaveBeenCalledTimes(3);
    wrapper.unmount();
  });

  it("新版执行器使用分步保存，并保留未完成操作的同一标识", async () => {
    codingScope.capabilities.value = { coding_model_save_recovery_enabled: true };
    vi.mocked(secureDraftAvailable).mockReturnValue(true);
    vi.mocked(saveModelProviderRecoverably).mockRejectedValue(new Error("受控保存中断"));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[type="password"]').setValue("synthetic-staged-value");
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(saveModelProvider).not.toHaveBeenCalled();
    expect(updateModelProviderRuntimeSecret).not.toHaveBeenCalled();
    const first = vi.mocked(saveModelProviderRecoverably).mock.calls[0];
    expect(first[2]).toBe("synthetic-staged-value");
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(vi.mocked(saveModelProviderRecoverably).mock.calls[1][3]).toBe(first[3]);
    expect(wrapper.text()).toContain("受控保存中断");
    wrapper.unmount();
  });

  it("未输入新密钥时也保存和恢复普通模型配置草稿", async () => {
    vi.mocked(secureDraftAvailable).mockReturnValue(true);
    let snapshot: string | null = null;
    vi.mocked(writeModelProviderDraft).mockImplementation(async value => { snapshot = value; });
    let wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[aria-label="模型 ID"]').setValue("another-model");
    await flushPromises();
    expect(JSON.parse(snapshot!).manualModelId).toBe("another-model");
    expect(JSON.parse(snapshot!).draft.apiKey).toBe("");
    expect(wrapper.text()).toContain("配置草稿已加密保存");
    wrapper.unmount();
    vi.mocked(readModelProviderDraft).mockResolvedValue(snapshot);
    wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    expect(wrapper.get('input[aria-label="模型 ID"]').element).toHaveProperty("value", "another-model");
    expect(saveModelProvider).not.toHaveBeenCalled();
    expect(updateModelProviderRuntimeSecret).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("密钥草稿经原生接口落盘，重新进入恢复端点和密钥但不自动调用模型", async () => {
    vi.mocked(secureDraftAvailable).mockReturnValue(true);
    let snapshot: string | null = null;
    vi.mocked(writeModelProviderDraft).mockImplementation(async value => { snapshot = value; });
    let wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[type="password"]').setValue("synthetic-crash-recovery");
    await flushPromises();
    expect(snapshot).toContain("synthetic-crash-recovery");
    expect(wrapper.text()).toContain("密钥草稿已加密保存");
    expect(JSON.stringify(localStorage)).not.toContain("synthetic-crash-recovery");
    expect(JSON.stringify(sessionStorage)).not.toContain("synthetic-crash-recovery");
    wrapper.unmount();
    vi.mocked(readModelProviderDraft).mockResolvedValue(snapshot);
    wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    expect(wrapper.get('input[type="password"]').element).toHaveProperty("value", "synthetic-crash-recovery");
    expect(wrapper.text()).toContain("已恢复上次未保存");
    expect(updateModelProviderRuntimeSecret).not.toHaveBeenCalled();
    expect(discoverModelProviderModels).not.toHaveBeenCalled();
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(updateModelProviderRuntimeSecret).toHaveBeenCalledWith(sampleProvider.id, "synthetic-crash-recovery");
    expect(clearModelProviderDraft).toHaveBeenCalled();
    expect(wrapper.get('input[type="password"]').element).toHaveProperty("value", "");
    wrapper.unmount();
  });

  it("草稿落盘和清除失败时保留输入并阻止离开", async () => {
    vi.mocked(secureDraftAvailable).mockReturnValue(true);
    vi.mocked(writeModelProviderDraft).mockRejectedValueOnce(new Error("synthetic storage failure"));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[type="password"]').setValue("synthetic-retained");
    await flushPromises();
    expect(wrapper.text()).toContain("密钥草稿未能加密保存");
    vi.mocked(clearModelProviderDraft).mockRejectedValueOnce(new Error("synthetic clear failure"));
    const leaving = allowDiscardingChanges();
    await resolveUnsavedChanges("discard");
    expect(unsavedChanges.open).toBe(true);
    expect(wrapper.get('input[type="password"]').element).toHaveProperty("value", "synthetic-retained");
    await resolveUnsavedChanges("cancel");
    expect(await leaving).toBe(false);
    wrapper.unmount();
  });

  it("获取列表失败后手动添加模型，重复 ID 不进入保存请求", async () => {
    vi.mocked(discoverModelProviderModels).mockRejectedValueOnce(new Error("列表接口不可用"));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get(".models-heading-row .secondary-button").trigger("click");
    await flushPromises();
    await wrapper.get('input[aria-label="模型 ID"]').setValue(" custom/coder ");
    await wrapper.get(".manual-model-row button").trigger("click");
    await wrapper.get('input[aria-label="模型 ID"]').setValue("custom/coder");
    await wrapper.get(".manual-model-row button").trigger("click");
    expect(wrapper.text()).toContain("该模型已在列表中");
    await wrapper.get('input[aria-label="模型 ID"]').setValue("");
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    const payload = vi.mocked(saveModelProvider).mock.calls[0][1];
    expect(payload.models.filter(model => model.modelId === "custom/coder")).toEqual([
      { modelId: "custom/coder", contextTokens: null, maxOutputTokens: null, metadataSource: "unknown", supportsVision: false },
    ]);
    wrapper.unmount();
  });

  it("未保存修改阻止切换，取消后保留输入，放弃后允许离开", async () => {
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[type="url"]').setValue("https://draft.example.test");
    await wrapper.get(".add-provider").trigger("click");
    expect(unsavedChanges.open).toBe(true);
    await resolveUnsavedChanges("cancel");
    await flushPromises();
    expect(wrapper.get('input[type="url"]').element).toHaveProperty("value", "https://draft.example.test");
    await wrapper.get(".add-provider").trigger("click");
    await resolveUnsavedChanges("discard");
    await flushPromises();
    expect(wrapper.get(".provider-name-input").element).toHaveProperty("value", "");
    wrapper.unmount();
  });

  it("密钥保存失败保留内存输入，不谎报完成或写入浏览器存储", async () => {
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[type="password"]').setValue("fixture-unsaved-value");
    vi.mocked(updateModelProviderRuntimeSecret).mockRejectedValueOnce(new Error("系统凭据存储不可用"));
    const leaving = allowDiscardingChanges();
    await resolveUnsavedChanges("save");
    expect(unsavedChanges.open).toBe(true);
    expect(wrapper.text()).toContain("供应商配置已保存；后续步骤未完成");
    expect(wrapper.get('input[type="password"]').element).toHaveProperty("value", "fixture-unsaved-value");
    expect(JSON.stringify(window.localStorage)).not.toContain("fixture-unsaved-value");
    expect(wrapper.emitted("return")).toBeUndefined();
    await resolveUnsavedChanges("cancel");
    expect(await leaving).toBe(false);
    wrapper.unmount();
  });

  it("从容量提醒进入配置后，焦点落到对应模型的容量输入框", async () => {
    const wrapper = mount(SettingsView, { props: { activeSection: "provider", focusProfileId: "glm-prod--glm-5" }, attachTo: document.body });
    await flushPromises();
    expect(document.activeElement).toBe(wrapper.get(".context-editor").element);
    expect(wrapper.get(".context-editor").element).toHaveProperty("value", "131072");
    wrapper.unmount();
  });

  it("供应商切换后不接收旧列表请求的迟到结果", async () => {
    const other = { ...sampleProvider, id: "other", name: "另一服务", models: [] };
    vi.mocked(listModelProviders).mockResolvedValue([sampleProvider, other]);
    let finish!: (value: Awaited<ReturnType<typeof discoverModelProviderModels>>) => void;
    vi.mocked(discoverModelProviderModels).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get(".models-heading-row .secondary-button").trigger("click");
    await wrapper.findAll(".provider-item").find(button => button.text() === "另一服务")!.trigger("click");
    finish([{ modelId: "previous-service-only", contextTokens: null, maxOutputTokens: null, metadataSource: "unknown" }]);
    await flushPromises();
    expect(wrapper.text()).not.toContain("previous-service-only");
    expect(wrapper.get(".provider-title-row h2").text()).toBe("另一服务");
    wrapper.unmount();
  });

  it("仅填写模型 ID 也保护未保存输入，保存前明确要求添加", async () => {
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    await wrapper.get('input[aria-label="模型 ID"]').setValue("unfinished-model");
    const leaving = allowDiscardingChanges();
    await resolveUnsavedChanges("save");
    expect(unsavedChanges.open).toBe(true);
    expect(wrapper.text()).toContain("模型 ID 尚未加入配置");
    expect(saveModelProvider).not.toHaveBeenCalled();
    await resolveUnsavedChanges("cancel");
    expect(await leaving).toBe(false);
    expect(wrapper.get('input[aria-label="模型 ID"]').element).toHaveProperty("value", "unfinished-model");
    wrapper.unmount();
  });

  it("Ollama 保存无法读取旧字段时不写入默认值，重试保存保持原值", async () => {
    const ollama = { ...sampleProvider, protocol: "ollama" as const, apiFormat: "ollama_chat" as const };
    vi.mocked(listModelProviders).mockResolvedValue([ollama]);
    vi.mocked(getLocalModelSettings).mockRejectedValueOnce(new Error("参数读取失败"));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    vi.mocked(getLocalModelSettings).mockRejectedValueOnce(new Error("参数仍不可读取"));
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(saveModelProvider).not.toHaveBeenCalled();
    expect(saveLocalModelSettings).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("参数仍不可读取");
    vi.mocked(getLocalModelSettings).mockResolvedValueOnce({ llm_temperature: 0.7, llm_context_length: 8192, kb_enabled_by_default: true });
    await wrapper.get(".detail-actions .primary-button").trigger("click");
    await flushPromises();
    expect(saveLocalModelSettings).toHaveBeenCalledWith(expect.objectContaining({ kb_enabled_by_default: true }));
    wrapper.unmount();
  });

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

  it("服务获取的模型与手动入口共存，未知容量不使用猜测值", async () => {
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
    expect(wrapper.find('input[aria-label="模型 ID"]').exists()).toBe(true);

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

    const button = wrapper.get('button[aria-label="检查模型列表"]');
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

    await wrapper.get('button[aria-label="检查模型列表"]').trigger("click");
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
    await wrapper.get('button[aria-label="检查模型列表"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("无法通过列表确认该模型");
    expect(wrapper.text()).not.toContain("模型连接测试成功");
    wrapper.unmount();
  });

  it("测试请求失败后显示错误并允许重试", async () => {
    vi.mocked(probeModelProviderModel).mockRejectedValueOnce(new Error("无法连接模型服务"));
    const wrapper = mount(SettingsView, { props: { activeSection: "provider" } });
    await flushPromises();
    const button = wrapper.get('button[aria-label="检查模型列表"]');
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
