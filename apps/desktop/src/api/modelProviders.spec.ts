import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ensureApiBase } from "./http";
import { probeModelProviderModel, type ModelProvider } from "./modelProviders";

vi.mock("./http", () => ({
  apiFetch: vi.fn(),
  ensureApiBase: vi.fn(),
}));

const provider: ModelProvider = {
  id: "deepseek",
  name: "DeepSeek",
  protocol: "openai",
  baseUrl: "https://api.deepseek.com",
  apiFormat: "chat_completions",
  enabled: true,
  isBuiltin: false,
  apiKeyConfigured: true,
  models: [{
    profileId: "deepseek--flash",
    modelId: "deepseek-v4-flash",
    contextTokens: 1_000_000,
    maxOutputTokens: 384_000,
    metadataSource: "official_catalog",
  }],
};

function modelList(modelId: string): Response {
  return new Response(JSON.stringify({ models: [{ model_id: modelId }] }), {
    status: 200,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(ensureApiBase).mockResolvedValue("https://backend.example.test");
  vi.mocked(apiFetch).mockResolvedValue(modelList("deepseek-v4-flash"));
});

describe("供应商模型连接检查", () => {
  it("只请求现有供应商发现接口，用服务器保存的密钥检查指定模型", async () => {
    await expect(probeModelProviderModel(provider, "deepseek-v4-flash")).resolves.toBe(true);

    expect(apiFetch).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(apiFetch).mock.calls[0];
    expect(url).toBe("https://backend.example.test/model-providers/discover/models");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      provider_id: "deepseek",
      protocol: "openai",
      base_url: "https://api.deepseek.com",
      credential_reference: null,
    });
  });

  it("服务可达但只返回其他模型时报告所选模型不存在", async () => {
    vi.mocked(apiFetch).mockResolvedValue(modelList("another-model"));
    await expect(probeModelProviderModel(provider, "deepseek-v4-flash")).resolves.toBe(false);
  });

  it("凭据失败时保留服务器错误而不是报告成功", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(
      JSON.stringify({ detail: "模型服务认证失败" }), { status: 401 }
    ));
    await expect(probeModelProviderModel(provider, "deepseek-v4-flash"))
      .rejects.toThrow("模型服务认证失败");
  });

  it("不检查禁用的供应商", async () => {
    await expect(probeModelProviderModel({ ...provider, enabled: false }, "deepseek-v4-flash"))
      .rejects.toThrow("供应商已禁用");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("不检查尚未保存的模型", async () => {
    await expect(probeModelProviderModel(provider, "unsaved-model"))
      .rejects.toThrow("请先保存该模型配置");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it.each(["ollama", "openai"] as const)("%s 模型名称匹配保留 Ollama latest 兼容性", async (protocol) => {
    const testProvider: ModelProvider = {
      ...provider,
      protocol,
      models: [{ ...provider.models[0], modelId: "example" }],
    };
    vi.mocked(apiFetch).mockResolvedValue(modelList("example:latest"));
    await expect(probeModelProviderModel(testProvider, "example"))
      .resolves.toBe(protocol === "ollama");
  });

  it("列表格式损坏时报告错误", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ models: null })));
    await expect(probeModelProviderModel(provider, "deepseek-v4-flash"))
      .rejects.toThrow("模型列表响应格式异常");
  });
});
