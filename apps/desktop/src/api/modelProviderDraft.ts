import { invoke, isTauri } from "@tauri-apps/api/core";

// 原生调用串行执行，避免较早的输入覆盖新草稿或在清除后重新落盘。
let pending: Promise<unknown> = Promise.resolve();
function ordered<T>(operation: () => Promise<T>): Promise<T> {
  const result = pending.catch(() => undefined).then(operation);
  pending = result.catch(() => undefined);
  return result;
}
export function secureDraftAvailable(): boolean { return isTauri(); }
export function readModelProviderDraft(): Promise<string | null> {
  return ordered(() => invoke<string | null>("read_model_provider_draft"));
}
export function writeModelProviderDraft(payload: string): Promise<void> {
  return ordered(() => invoke<void>("write_model_provider_draft", { payload }));
}
export function clearModelProviderDraft(): Promise<void> {
  return ordered(() => invoke<void>("clear_model_provider_draft"));
}
