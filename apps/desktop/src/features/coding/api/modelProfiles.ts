/**
 * v0.8.0 W1 · Coding 模型 profile API（v0.9.0 H1-D 配置闭环扩展）
 *
 * flag PA_CODING_PERMISSION_MODELS_ENABLED 关闭时后端返回
 * 409 coding_mode_disabled——这是「能力未开放」而非故障，收敛为
 * result 联合类型交给 homeState 派生（W0 冻结矩阵第 3 项）。
 *
 * H1-D（计划 §5.8）：补齐 list/get/upsert/delete/probe/set-default/import
 * typed client；设置页管理区只经这些封装访问后端（组件不拼 URL）。
 * 无任何 secret 字段进出。
 */
import type {
  CodingModelProfileDetail,
  CodingModelProfilesResult,
  CodingModelProfileSummary,
  CodingModelProfileUpsert,
  CodingModelProbeResult,
  CodingProfileImportResult,
  CodingProfileImportStatus,
} from "../model/contracts";
import { codingFetch, codingFetchJson, codingJsonInit, toCodingApiError } from "./codingHttp";

interface ModelProfileDto {
  id: string;
  provider: string;
  provider_id?: string | null;
  provider_name?: string | null;
  display_name: string;
  model_name?: string | null;
  is_default?: boolean;
  is_local: boolean;
  native_tool_calls?: boolean;
  supports_streaming?: boolean;
  supports_structured_output?: boolean;
  supports_vision?: boolean;
  context_tokens?: number | null;
  reasoning_efforts: string[] | null;
  usage_reporting?: boolean;
  enabled: boolean;
}

export function toModelProfileDetail(dto: ModelProfileDto): CodingModelProfileDetail {
  return {
    id: dto.id,
    provider: dto.provider as CodingModelProfileDetail["provider"],
    ...(dto.provider_id ? { providerId: dto.provider_id } : {}),
    ...(dto.provider_name ? { providerName: dto.provider_name } : {}),
    displayName: dto.display_name,
    modelName: dto.model_name ?? null,
    isDefault: dto.is_default ?? false,
    isLocal: dto.is_local,
    nativeToolCalls: dto.native_tool_calls ?? true,
    supportsStreaming: dto.supports_streaming ?? false,
    supportsStructuredOutput: dto.supports_structured_output ?? false,
    supportsVision: dto.supports_vision ?? false,
    contextTokens: dto.context_tokens ?? null,
    reasoningEfforts: dto.reasoning_efforts,
    usageReporting: dto.usage_reporting ?? false,
    enabled: dto.enabled,
  };
}

export async function fetchCodingModelProfiles(): Promise<CodingModelProfilesResult> {
  const response = await codingFetch("/agent-model-profiles?enabled_only=true");
  if (response.status === 409) {
    const error = await toCodingApiError(response);
    if (error.code === "coding_mode_disabled") {
      return { status: "disabled" };
    }
    return { status: "error", message: error.message };
  }
  if (!response.ok) {
    const error = await toCodingApiError(response);
    return { status: "error", message: error.message };
  }
  const body: unknown = await response.json();
  // 兼容非数组响应体（旧后端/代理兜底页）：按可恢复错误处理，不让 bootstrap 整体失败
  if (!Array.isArray(body)) {
    return { status: "error", message: "模型配置响应格式异常" };
  }
  const list = body as ModelProfileDto[];
  const profiles = list
    .filter((dto) => dto.enabled)
    .map((dto) => ({
      id: dto.id,
      provider: dto.provider as CodingModelProfileSummary["provider"],
      ...(dto.provider_id ? { providerId: dto.provider_id } : {}),
      ...(dto.provider_name ? { providerName: dto.provider_name } : {}),
      displayName: dto.display_name,
      modelName: dto.model_name ?? null,
      isDefault: dto.is_default ?? false,
      isLocal: dto.is_local,
      contextTokens: dto.context_tokens ?? null,
      reasoningEfforts: dto.reasoning_efforts,
    }));
  return { status: "ok", profiles };
}

// ============ v0.9.0 H1-D：管理区 typed client ============

/** 全量列表（含停用项；设置页管理用，错误直接抛 CodingApiError） */
export async function listCodingModelProfiles(): Promise<CodingModelProfileDetail[]> {
  const list = await codingFetchJson<ModelProfileDto[]>("/agent-model-profiles");
  return list.map(toModelProfileDetail);
}

export async function getCodingModelProfile(
  profileId: string
): Promise<CodingModelProfileDetail> {
  const dto = await codingFetchJson<ModelProfileDto>(
    `/agent-model-profiles/${encodeURIComponent(profileId)}`
  );
  return toModelProfileDetail(dto);
}

function toUpsertBody(input: CodingModelProfileUpsert): Record<string, unknown> {
  return {
    provider: input.provider,
    display_name: input.displayName,
    model_name: input.modelName,
    is_local: input.isLocal,
    native_tool_calls: input.nativeToolCalls,
    supports_streaming: input.supportsStreaming,
    supports_structured_output: input.supportsStructuredOutput,
    supports_vision: input.supportsVision,
    context_tokens: input.contextTokens,
    reasoning_efforts: input.reasoningEfforts,
    usage_reporting: input.usageReporting,
    enabled: input.enabled,
    is_default: input.isDefault,
  };
}

export async function upsertCodingModelProfile(
  profileId: string,
  input: CodingModelProfileUpsert
): Promise<CodingModelProfileDetail> {
  const dto = await codingFetchJson<ModelProfileDto>(
    `/agent-model-profiles/${encodeURIComponent(profileId)}`,
    codingJsonInit("PUT", toUpsertBody(input))
  );
  return toModelProfileDetail(dto);
}

export async function deleteCodingModelProfile(profileId: string): Promise<void> {
  const response = await codingFetch(
    `/agent-model-profiles/${encodeURIComponent(profileId)}`,
    { method: "DELETE" }
  );
  if (!response.ok && response.status !== 204) {
    throw await toCodingApiError(response);
  }
}

export async function probeCodingModelProfile(
  profileId: string
): Promise<CodingModelProbeResult> {
  const body = await codingFetchJson<{
    status: CodingModelProbeResult["status"];
    provider_reachable: boolean | null;
    model_exists: boolean | null;
    native_tool_calls: boolean | null;
    detail: string;
  }>(
    `/agent-model-profiles/${encodeURIComponent(profileId)}/probe`,
    codingJsonInit("POST", {})
  );
  return {
    status: body.status,
    providerReachable: body.provider_reachable,
    modelExists: body.model_exists,
    nativeToolCalls: body.native_tool_calls,
    detail: body.detail ?? "",
  };
}

export async function setCodingDefaultProfile(
  profileId: string
): Promise<CodingModelProfileDetail> {
  const dto = await codingFetchJson<ModelProfileDto>(
    `/agent-model-profiles/${encodeURIComponent(profileId)}/set-default`,
    codingJsonInit("POST", {})
  );
  return toModelProfileDetail(dto);
}

/** v1.0 CT-3（§8.2）：工具能力探测最新快照（进度/结果可查；后台执行）。*/
export interface ModelToolProbeStatus {
  status: "none" | "running" | "ok" | "failed";
  error_code: string | null;
  pass_count: number;
  sample_count: number;
  results: Record<string, boolean> | null;
  requirements: Record<string, boolean> | null;
  probed_at: string | null;
}

export async function fetchModelToolProbe(
  profileId: string,
  options?: { signal?: AbortSignal }
): Promise<ModelToolProbeStatus> {
  return codingFetchJson<ModelToolProbeStatus>(
    `/agent-model-profiles/${encodeURIComponent(profileId)}/tool-probe`,
    options?.signal ? { signal: options.signal } : undefined
  );
}

/** 重试入口：调度后台探测（立即返回；运行中/不合格时后端返回 409）。*/
export async function retryModelToolProbe(profileId: string): Promise<void> {
  const response = await codingFetch(
    `/agent-model-profiles/${encodeURIComponent(profileId)}/tool-probe`,
    codingJsonInit("POST", {})
  );
  if (!response.ok && response.status !== 202) {
    throw await toCodingApiError(response);
  }
}

/** 幂等导入全局 Provider 配置为默认 profile（用户在向导中显式发起） */
export async function importCodingModelProfile(): Promise<CodingProfileImportResult> {
  const body = await codingFetchJson<{
    imported: boolean;
    already_exists: boolean;
    profile_id: string | null;
  }>("/agent-model-profiles/import", codingJsonInit("POST", {}));
  return {
    imported: body.imported,
    alreadyExists: body.already_exists,
    profileId: body.profile_id,
  };
}

/** 旧配置导入状态（一次性向导依据；能力未开放按 not_needed 收敛） */
export async function fetchCodingProfileImportStatus(): Promise<CodingProfileImportStatus> {
  const response = await codingFetch("/agent-model-profiles/import-status");
  if (!response.ok) {
    if (response.status === 409) {
      return {
        importState: "not_needed",
        reasonCode: "feature_disabled",
        provider: null,
        modelAvailable: false,
      };
    }
    throw await toCodingApiError(response);
  }
  const body = (await response.json()) as {
    import_state: CodingProfileImportStatus["importState"];
    reason_code: string | null;
    provider: string | null;
    model_available: boolean;
  };
  return {
    importState: body.import_state,
    reasonCode: body.reason_code,
    provider: body.provider,
    modelAvailable: body.model_available,
  };
}
