import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ensureApiBase } from "./http";
import { cmdClearModelProviderSecret, cmdSetModelProviderSecret } from "./tauri";
import { getWorkspaceAccessToken } from "../auth/session";
import { removeUnusedModelCredentials, resumeModelSave, saveModelProviderRecoverably, type ModelSaveOperation } from "./modelSaves";
import type { ModelProviderSaveInput } from "./modelProviders";
vi.mock("./http", () => ({ apiFetch: vi.fn(), ensureApiBase: vi.fn() }));
vi.mock("./tauri", () => ({ cmdClearModelProviderSecret: vi.fn(), cmdSetModelProviderSecret: vi.fn() }));
vi.mock("../auth/session", () => ({ getWorkspaceAccessToken: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));
const operation: ModelSaveOperation = { id: "a".repeat(32), provider_id: "sample", configuration: { name: "测试", base_url: "https://provider.example.test/v1", protocol: "openai" }, parameters: null,
  credential_action: "replace", credential_alias: "b".repeat(64), credential_ready: false, status: "prepared", updated_at: "saved" };
const configuration: ModelProviderSaveInput = { name: "测试", baseUrl: operation.configuration.base_url, protocol: "openai", apiFormat: "chat_completions", enabled: true,
  models: [{ modelId: "test-model", contextTokens: 32000, maxOutputTokens: null, metadataSource: "user_override" }] };
let order: string[];
beforeEach(() => {
  vi.clearAllMocks();
  order = [];
  vi.mocked(getWorkspaceAccessToken).mockReturnValue("synthetic-local-session");
  vi.mocked(ensureApiBase).mockResolvedValue("http://localhost");
  vi.mocked(cmdSetModelProviderSecret).mockImplementation(async () => { order.push("vault"); return { configured: true, reference: "synthetic-reference" }; });
  vi.mocked(cmdClearModelProviderSecret).mockResolvedValue({ configured: false, reference: "synthetic-reference" });
  vi.mocked(apiFetch).mockImplementation(async (path, init) => {
    const text = String(path);
    if (text.endsWith("/credential")) { order.push("hydrate"); return Response.json(operation); }
    if (text.endsWith("/commit")) { order.push("commit"); return Response.json({ ...operation, status: "completed" }); }
    if (text.endsWith("/cleanup")) return Response.json({ aliases: [operation.credential_alias] });
    if (text.endsWith("/cleared")) return Response.json({ cleared: true });
    if (init?.method === "POST") order.push("prepare");
    return Response.json(operation);
  });
});
describe("可恢复的模型配置保存", () => {
  it("先准备配置再保存凭据，固定恢复接口只发送别名，最后启用", async () => {
    await saveModelProviderRecoverably("sample", configuration, "synthetic-new-value", operation.id, null);
    expect(order).toEqual(["prepare", "vault", "hydrate", "commit"]);
    expect(cmdSetModelProviderSecret).toHaveBeenCalledWith(operation.credential_alias, "synthetic-new-value");
    expect(JSON.stringify(vi.mocked(apiFetch).mock.calls)).not.toContain("synthetic-new-value");
    const credential = vi.mocked(apiFetch).mock.calls.find(([path]) => String(path).endsWith("/credential"))!;
    expect(JSON.parse(credential[1]!.body as string)).toEqual({ stored_alias: operation.credential_alias });
  });
  it("凭据保存失败不会启用草案，提示原配置保留", async () => {
    vi.mocked(cmdSetModelProviderSecret).mockRejectedValueOnce(new Error("vault unavailable"));
    await expect(saveModelProviderRecoverably("sample", configuration, "synthetic-new-value", operation.id, null)).rejects.toThrow("原配置尚未替换");
    expect(order).toEqual(["prepare"]);
  });
  it("恢复待提交凭据由原生层读取，不要求浏览器持有密钥", async () => {
    await resumeModelSave(operation);
    expect(order).toEqual(["hydrate", "commit"]);
    expect(cmdSetModelProviderSecret).not.toHaveBeenCalled();
  });
  it("本机会话变化后不向新会话继续提交", async () => {
    vi.mocked(cmdSetModelProviderSecret).mockImplementationOnce(async () => {
      vi.mocked(getWorkspaceAccessToken).mockReturnValue("changed-session");
      return { configured: true, reference: "synthetic-reference" };
    });
    await expect(saveModelProviderRecoverably("sample", configuration, "synthetic-new-value", operation.id, null)).rejects.toThrow("本机会话已变化");
    expect(order).toEqual(["prepare"]);
  });
  it("清理先保留已核对的范围，删除成功后才标记完成", async () => {
    expect(await removeUnusedModelCredentials([operation.credential_alias])).toBe(1);
    expect(cmdClearModelProviderSecret).toHaveBeenCalledWith(operation.credential_alias);
    const calls = vi.mocked(apiFetch).mock.calls;
    expect(String(calls[0][0])).toContain("/cleanup");
    expect(String(calls[1][0])).toContain("/cleared");
  });
});
