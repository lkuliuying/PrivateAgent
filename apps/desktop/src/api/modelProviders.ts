import { apiFetch, ensureApiBase } from "./http";

export type ModelProviderProtocol = "ollama" | "openai" | "claude";
export type ModelMetadataSource =
  | "provider_api"
  | "local_model"
  | "official_catalog"
  | "user_override"
  | "unknown";
export type ModelProviderApiFormat =
  | "ollama_chat"
  | "chat_completions"
  | "anthropic_messages";

export interface ModelProviderModel {
  profileId: string;
  modelId: string;
  contextTokens: number | null;
  maxOutputTokens: number | null;
  metadataSource: ModelMetadataSource;
}

export interface DiscoveredModel {
  modelId: string;
  contextTokens: number | null;
  maxOutputTokens: number | null;
  metadataSource: ModelMetadataSource;
}

export interface ModelProvider {
  id: string;
  name: string;
  protocol: ModelProviderProtocol;
  baseUrl: string;
  apiFormat: ModelProviderApiFormat;
  enabled: boolean;
  isBuiltin: boolean;
  apiKeyConfigured: boolean;
  models: ModelProviderModel[];
}

export interface ModelProviderSaveInput {
  name: string;
  protocol: ModelProviderProtocol;
  baseUrl: string;
  apiFormat: ModelProviderApiFormat;
  credentialReference?: string | null;
  enabled: boolean;
  isBuiltin?: boolean;
  models: DiscoveredModel[];
}

interface ModelProviderDto {
  id: string;
  name: string;
  protocol: ModelProviderProtocol;
  base_url: string;
  api_format: ModelProviderApiFormat;
  enabled: boolean;
  is_builtin: boolean;
  api_key_configured: boolean;
  models: Array<{
    profile_id: string;
    model_id: string;
    context_tokens: number | null;
    max_output_tokens?: number | null;
    metadata_source?: ModelMetadataSource;
  }>;
}

function fromDto(dto: ModelProviderDto): ModelProvider {
  return {
    id: dto.id,
    name: dto.name,
    protocol: dto.protocol,
    baseUrl: dto.base_url,
    apiFormat: dto.api_format,
    enabled: dto.enabled,
    isBuiltin: dto.is_builtin,
    apiKeyConfigured: dto.api_key_configured,
    models: dto.models.map((model) => ({
      profileId: model.profile_id,
      modelId: model.model_id,
      contextTokens: model.context_tokens,
      maxOutputTokens: model.max_output_tokens ?? null,
      metadataSource: model.metadata_source ?? "unknown",
    })),
  };
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await ensureApiBase();
  const response = await apiFetch(`${base}${path}`, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
      error_code?: unknown;
    };
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : typeof body.error_code === "string"
          ? body.error_code
          : `HTTP ${response.status}`
    );
  }
  return (await response.json()) as T;
}

export async function listModelProviders(): Promise<ModelProvider[]> {
  const list = await requestJson<ModelProviderDto[]>("/model-providers");
  return list.map(fromDto);
}

export async function saveModelProvider(
  providerId: string,
  input: ModelProviderSaveInput
): Promise<ModelProvider> {
  const dto = await requestJson<ModelProviderDto>(
    `/model-providers/${encodeURIComponent(providerId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: input.name,
        protocol: input.protocol,
        base_url: input.baseUrl,
        api_format: input.apiFormat,
        credential_reference: input.credentialReference ?? null,
        enabled: input.enabled,
        is_builtin: input.isBuiltin ?? false,
        models: input.models.map((model) => ({
          model_id: model.modelId,
          context_tokens: model.contextTokens,
          max_output_tokens: model.maxOutputTokens,
          metadata_source: model.metadataSource,
        })),
      }),
    }
  );
  return fromDto(dto);
}

export async function deleteModelProvider(providerId: string): Promise<void> {
  const base = await ensureApiBase();
  const response = await apiFetch(
    `${base}/model-providers/${encodeURIComponent(providerId)}`,
    { method: "DELETE" }
  );
  if (!response.ok && response.status !== 204) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
}

export async function discoverModelProviderModels(input: {
  providerId?: string | null;
  protocol: ModelProviderProtocol;
  baseUrl: string;
  credentialReference?: string | null;
  apiKey?: string;
}): Promise<DiscoveredModel[]> {
  const body = await requestJson<{ models: unknown }>("/model-providers/discover/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_id: input.providerId ?? null,
      protocol: input.protocol,
      base_url: input.baseUrl,
      credential_reference: input.credentialReference ?? null,
      ...(input.apiKey ? { api_key: input.apiKey } : {}),
    }),
  });
  if (!Array.isArray(body.models)) throw new Error("模型列表响应格式异常");
  return body.models.flatMap((item): DiscoveredModel[] => {
    // 兼容旧 sidecar 的字符串响应；未知窗口必须保持 null。
    if (typeof item === "string" && item.trim()) {
      return [{
        modelId: item,
        contextTokens: null,
        maxOutputTokens: null,
        metadataSource: "unknown",
      }];
    }
    if (!item || typeof item !== "object") return [];
    const value = item as Record<string, unknown>;
    const modelId = typeof value.model_id === "string" ? value.model_id.trim() : "";
    if (!modelId) return [];
    const source = value.metadata_source;
    const knownSources: ModelMetadataSource[] = [
      "provider_api", "local_model", "official_catalog", "user_override", "unknown",
    ];
    return [{
      modelId,
      contextTokens: typeof value.context_tokens === "number" ? value.context_tokens : null,
      maxOutputTokens:
        typeof value.max_output_tokens === "number" ? value.max_output_tokens : null,
      metadataSource:
        typeof source === "string" && knownSources.includes(source as ModelMetadataSource)
          ? source as ModelMetadataSource
          : "unknown",
    }];
  });
}

/** Check saved provider credentials and model availability without enabling Coding. */
export async function probeModelProviderModel(
  provider: ModelProvider,
  modelId: string
): Promise<boolean> {
  if (!provider.enabled) throw new Error("供应商已禁用，请先启用并保存配置");
  if (!provider.models.some((model) => model.modelId === modelId)) {
    throw new Error("请先保存该模型配置，再测试连接");
  }
  // 不使用表单里的未保存密钥；让服务器按供应商 ID 解析已保存的凭据。
  const models = await discoverModelProviderModels({
    providerId: provider.id,
    protocol: provider.protocol,
    baseUrl: provider.baseUrl,
  });
  return models.some((model) =>
    model.modelId === modelId ||
    (provider.protocol === "ollama" && model.modelId === `${modelId}:latest`)
  );
}

export async function updateModelProviderRuntimeSecret(
  providerId: string,
  secret: string
): Promise<void> {
  await requestJson(`/model-providers/${encodeURIComponent(providerId)}/runtime-secret`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secret }),
  });
}

export async function clearModelProviderRuntimeSecret(
  providerId: string
): Promise<void> {
  await requestJson(`/model-providers/${encodeURIComponent(providerId)}/runtime-secret`, {
    method: "DELETE",
  });
}
