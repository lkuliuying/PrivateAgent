/**
 * v0.8.0 W1 · Coding 模型 profile API（GET /agent-model-profiles）
 *
 * flag PA_CODING_PERMISSION_MODELS_ENABLED 关闭时后端返回
 * 409 coding_mode_disabled——这是「能力未开放」而非故障，收敛为
 * result 联合类型交给 homeState 派生（W0 冻结矩阵第 3 项）。
 */
import type {
  CodingModelProfileSummary,
  CodingModelProfilesResult,
} from "../model/contracts";
import { codingFetch, toCodingApiError } from "./codingHttp";

interface ModelProfileDto {
  id: string;
  provider: string;
  display_name: string;
  is_local: boolean;
  reasoning_efforts: string[] | null;
  enabled: boolean;
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
  const list = (await response.json()) as ModelProfileDto[];
  const profiles = list
    .filter((dto) => dto.enabled)
    .map((dto) => ({
      id: dto.id,
      provider: dto.provider as CodingModelProfileSummary["provider"],
      displayName: dto.display_name,
      isLocal: dto.is_local,
      reasoningEfforts: dto.reasoning_efforts,
    }));
  return { status: "ok", profiles };
}
