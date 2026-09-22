import { apiFetch as fetch, ensureApiBase } from "./api/http";
export { apiFetch, ensureApiBase } from "./api/http";
export {
  cmdCheckForUpdates, cmdDownloadAndInstallUpdate, cmdRelaunchApp, cmdGetUpdateConfiguration,
  isDesktopRuntime, pickDirectory, pickFile,
} from "./api/tauri";
export type { UpdateInfo, UpdateConfiguration } from "./api/tauri";
export {
  clearModelProviderRuntimeSecret, deleteModelProvider, discoverModelProviderModels,
  listModelProviders, probeModelProviderModel, saveModelProvider, updateModelProviderRuntimeSecret,
} from "./api/modelProviders";
export type {
  DiscoveredModel, ModelMetadataSource, ModelProvider, ModelProviderApiFormat,
  ModelProviderModel, ModelProviderProtocol, ModelProviderSaveInput,
} from "./api/modelProviders";
export { getRuntimeCapabilities, supportsCodingRunCreation } from "./api/runtime";
export type { RuntimeCapabilities } from "./api/runtime";

export interface ContextBudgetResponse {
  used_tokens: number;
  max_context_tokens: number;
  reserved_output_tokens: number;
  cache_hit_percent: number | null;
  cache_hit_scope?: "latest_request" | "session";
  usage_percent: number | null;
  source: "provider_usage" | "tokenizer" | "runtime_count" | "estimated" | "unavailable";
  estimated_input_tokens?: number;
  input_budget_tokens?: number;
  auto_compact_threshold_tokens?: number;
  measurement_source?: string;
  model_config_version?: string;
  compaction_error?: string | null;
  compaction_state: "idle" | "compacting" | "compacted" | "failed";
  last_compacted_at: string | null;
  error_code: string | null;
  error_reason: string | null;
}

export async function getContextBudget(
  sessionId: number,
  modelProfileId?: string | null
): Promise<ContextBudgetResponse> {
  const base = await ensureApiBase();
  const query = modelProfileId ? `?model_profile_id=${encodeURIComponent(modelProfileId)}` : "";
  const response = await fetch(`${base}/sessions/${sessionId}/context-budget${query}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as ContextBudgetResponse;
}
