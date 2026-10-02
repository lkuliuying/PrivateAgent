import { isTauri } from "@tauri-apps/api/core";
import { getWorkspaceAccessToken } from "../auth/session";
import { cmdClearModelProviderSecret, cmdSetModelProviderSecret } from "./tauri";
import { modelProviderPayload, requestJson, type LocalModelSettings, type ModelProviderSaveInput } from "./modelProviders";

export interface ModelSaveOperation {
  id: string;
  provider_id: string;
  configuration: { name: string; base_url: string; protocol: string };
  parameters: LocalModelSettings | null;
  credential_action: "keep" | "replace";
  credential_alias: string;
  credential_ready: boolean;
  status: "prepared" | "credential_ready" | "completed" | "discarded";
  updated_at: string;
}
function session() {
  const token = getWorkspaceAccessToken();
  const check = () => { if (!token || getWorkspaceAccessToken() !== token) throw new Error("本机会话已变化，保存尚未完成，请重新打开模型设置"); };
  check();
  return { check, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } };
}
export function listModelSaveOperations(): Promise<ModelSaveOperation[]> { return requestJson("/model-save-operations"); }
export async function saveModelProviderRecoverably(providerId: string, input: ModelProviderSaveInput, secret: string,
  operationId: string, parameters: LocalModelSettings | null): Promise<ModelSaveOperation> {
  const { check, headers } = session();
  let completed = "";
  try {
    const operation = await requestJson<ModelSaveOperation>("/model-save-operations", {
      method: "POST", headers, body: JSON.stringify({ operation_id: operationId, provider_id: providerId,
        configuration: modelProviderPayload(input), parameters, credential_action: secret ? "replace" : "keep" }),
    });
    if (operation.status === "completed") return operation;
    completed = "配置草案已保存在本机，原配置尚未替换。";
    if (secret) {
      check();
      if (!isTauri()) throw new Error("持久化密钥需要桌面客户端");
      const status = await cmdSetModelProviderSecret(operation.credential_alias, secret);
      if (!status.configured) throw new Error("系统凭据库未确认保存");
      completed = "配置草案和新密钥已保存，原配置尚未替换。";
    }
    if (secret || !operation.credential_ready) {
      check();
      if (!isTauri()) throw new Error("恢复系统凭据需要桌面客户端");
      await requestJson(`/model-save-operations/${operation.id}/credential`, {
        method: "PUT", headers, body: JSON.stringify({ stored_alias: operation.credential_alias }),
      });
    }
    check();
    return await requestJson(`/model-save-operations/${operation.id}/commit`, { method: "POST", headers });
  } catch (cause) {
    throw new Error(completed + (cause instanceof Error ? cause.message : "保存未完成") + " 可在模型设置中查看并继续未完成的保存。");
  }
}
export async function resumeModelSave(operation: ModelSaveOperation): Promise<void> {
  const { check, headers } = session();
  if (operation.credential_action === "replace" || !operation.credential_ready) {
    if (!isTauri()) throw new Error("恢复系统凭据需要桌面客户端");
    await requestJson(`/model-save-operations/${operation.id}/credential`, {
      method: "PUT", headers, body: JSON.stringify({ stored_alias: operation.credential_alias }),
    });
  }
  check();
  await requestJson(`/model-save-operations/${operation.id}/commit`, { method: "POST", headers });
}
export async function discardModelSave(id: string): Promise<void> {
  const { headers } = session();
  await requestJson(`/model-save-operations/${id}`, { method: "DELETE", headers });
}
export async function unusedModelCredentials(): Promise<string[]> {
  return (await requestJson<{ aliases: string[] }>("/model-save-operations/credentials/unused")).aliases;
}
export async function removeUnusedModelCredentials(reviewed: string[]): Promise<number> {
  const { check, headers } = session();
  const reserved = await requestJson<{ aliases: string[] }>("/model-save-operations/credentials/cleanup", {
    method: "POST", headers, body: JSON.stringify({ aliases: reviewed }),
  });
  let removed = 0;
  try {
    for (const alias of reserved.aliases) {
      check();
      await cmdClearModelProviderSecret(alias);
      check();
      await requestJson(`/model-save-operations/credentials/${alias}/cleared`, { method: "POST", headers });
      removed += 1;
    }
  } catch (cause) {
    throw new Error(`已确认清理 ${removed} 项，其余凭据清理尚未完成，请重新核对。` + (cause instanceof Error ? cause.message : ""));
  }
  return removed;
}
